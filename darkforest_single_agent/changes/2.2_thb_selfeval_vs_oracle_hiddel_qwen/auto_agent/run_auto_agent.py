#!/usr/bin/env python3
"""Auto-agent loop: run a Claude Code session on acct2's account (5h window, no weekly limit) as a long-running
background process. The session is given the JOB_SPEC.md as its prompt and works autonomously. On quota burnout
the loop sleeps until the reset and resumes the same session.

Usage: run_auto_agent.py [--resume]

The --resume flag skips session creation if status.json already has a session_id. Without it, a new session
is created on first launch. In both cases, the loop checks status.json and resumes from where it left off.

Patterns from:
  - 0.3/compose/scripts/common.py: quota detection (LIMIT_RX, reset_wait_s)
  - 0.3/compose/scripts/launch.sh: env stripping, setsid nohup
  - 0_baxbench_nl2_tests/scripts/run_job.py: session_exists, run_claude, wait_for_limit
  - 2_thb_netflix_selfval/scripts/run_selfval_job.py: Claude CLI invocation with sandbox
"""
import fcntl, hashlib, json, os, signal, subprocess, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
SF = "/home/user/project/shabi_forest"
ENVS = f"{SF}/.envs"

# Claude Code CLI path (same pinned version as other experiments)
CLAUDE_BIN = "/home/user/.local/bin/claude"

# acct2's oauth token
TOKEN_FILE = f"{ENVS}/secrets/claude_oauth_token_acct2"
ACCT2_HOME = os.path.join(HERE, "acct2_home")
ACCT2_CONFIG = os.path.join(HERE, "acct2_config")
TASK_ENVS = f"{ENVS}/experiments/2_2_acct2"

# Directories
LOGS_DIR = os.path.join(HERE, "logs")
STATUS_FILE = os.path.join(HERE, "status.json")
JOB_SPEC = os.path.join(HERE, "JOB_SPEC.md")

# Settings
MAX_SEGMENTS = 200          # safety: don't loop forever
SEGMENT_TIMEOUT_S = 18000   # 5 hours = 18000s; acct2's window
DISK_MIN_GB = 50            # pause if disk drops below this
ERROR_BACKOFF_S = 300       # backoff on non-quota errors
MAX_CONSECUTIVE_ERRORS = 10 # give up after this many consecutive non-quota errors

sys.path.insert(0, HERE)
from quota_utils import LIMIT_RX, classify_failure, fmt_s, limit_wait_s  # noqa: E402


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(os.path.join(LOGS_DIR, "agent.log"), "a") as o:
        o.write(line + "\n")


def read_json(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "w") as o:
        json.dump(obj, o, indent=2, default=str)
    os.replace(tmp, path)


def disk_free_gb():
    st = os.statvfs(EXP)
    return (st.f_bavail * st.f_frsize) / (1024 ** 3)


def token_fingerprint():
    """Detect a replacement token without recording its contents in status or logs."""
    try:
        with open(TOKEN_FILE, "rb") as f:
            data = f.read().strip()
    except OSError:
        data = b""
    return hashlib.sha256(data).hexdigest()


def goal_complete():
    """A normal Claude reply alone does not mean both 20-iteration jobs are done."""
    for arm in ("job_selfval", "job_oracle_hidden"):
        path = os.path.join(EXP, arm, "runs", "netflix__r0", "status.json")
        st = read_json(path) or {}
        if st.get("state") != "done" or st.get("iters_done", 0) < 20:
            return False
    return os.path.isfile(os.path.join(EXP, "REPORT.md"))


def session_dir():
    """Where Claude Code stores session transcripts for this agent."""
    return os.path.join(ACCT2_CONFIG, "projects")


def session_exists(sid):
    """Check if a Claude Code session file exists for the given session ID."""
    import glob
    return bool(glob.glob(os.path.join(session_dir(), "*", f"{sid}.jsonl")))


def prepare_home():
    """Use a fresh private HOME/config with no cached credentials from another account."""
    os.makedirs(ACCT2_HOME, mode=0o700, exist_ok=True)
    os.makedirs(ACCT2_CONFIG, mode=0o700, exist_ok=True)
    os.makedirs(session_dir(), mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(EXP, "tmp"), exist_ok=True)
    os.makedirs(os.path.join(TASK_ENVS, "cache"), exist_ok=True)
    cj = os.path.join(ACCT2_CONFIG, ".claude.json")
    if not os.path.exists(cj):
        with open(cj, "w") as f:
            json.dump({"hasCompletedOnboarding": True}, f)
        os.chmod(cj, 0o600)
    sp = os.path.join(ACCT2_CONFIG, "settings.json")
    with open(sp, "w") as f:
        json.dump({"cleanupPeriodDays": 3650, "autoMemoryEnabled": False}, f)
    return ACCT2_HOME


def claude_env():
    """Construct the same OAuth-token authentication method as the known acct2 CLI invocation."""
    prepare_home()
    with open(TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise RuntimeError("acct2 OAuth token file is empty")
    env = {
        "HOME": ACCT2_HOME,
        "CLAUDE_CONFIG_DIR": ACCT2_CONFIG,
        "CLAUDE_CODE_OAUTH_TOKEN": token,
        "PATH": f"{ENVS}/bin:/home/user/.nvm/versions/node/v22.22.1/bin:"
                "/home/user/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8", "TERM": "dumb",
        "TMPDIR": os.path.join(EXP, "tmp"),
        "XDG_CACHE_HOME": os.path.join(TASK_ENVS, "cache"),
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.getuid()}/bus",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return env


def verify_auth(env):
    """Reject fallback to a cached user/<user> login before paid work starts."""
    r = subprocess.run([CLAUDE_BIN, "auth", "status", "--json"], env=env, cwd=EXP,
                       capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    if (not d.get("loggedIn") or d.get("authMethod") != "oauth_token"
            or d.get("configDirectory") != ACCT2_CONFIG):
        raise RuntimeError("Claude did not select the isolated OAuth-token account")
    email = (d.get("email") or "").lower()
    if email in ("<emailAddress>", "<emailAddress>"):
        raise RuntimeError(f"Claude selected the wrong account: {email}")
    return email or None


def build_claude_args(prompt, session_id, have_session):
    """Build the claude CLI arguments."""
    with open(os.path.join(HERE, "SAFETY_RULES.md"), encoding="utf-8") as f:
        safety_prompt = f.read()
    args = [
        CLAUDE_BIN,
        "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--append-system-prompt", safety_prompt,
        "--model", "claude-opus-5-5",
        "--effort", "medium",
    ]
    if have_session:
        args += ["--resume", session_id]
    else:
        args += ["--session-id", session_id]
    return args


def run_segment(prompt, session_id, have_session, segment_idx):
    """Run one Claude Code segment. Returns (result_dict, stderr_text)."""
    env = claude_env()
    verify_auth(env)
    args = build_claude_args(prompt, session_id, have_session)

    out_p = os.path.join(LOGS_DIR, f"segment_{segment_idx}.json")
    err_p = os.path.join(LOGS_DIR, f"segment_{segment_idx}.stderr")

    t0 = time.time()
    log(f"segment {segment_idx}: launching claude ({'resume' if have_session else 'new'})")

    with open(out_p, "w") as fo, open(err_p, "w") as fe:
        p = subprocess.Popen(args, stdout=fo, stderr=fe, env=env,
                             cwd=EXP, start_new_session=True)
        try:
            rc = p.wait(timeout=SEGMENT_TIMEOUT_S)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            rc, timed_out = -9, True

    wall_s = round(time.time() - t0, 1)
    stderr_text = open(err_p, errors="replace").read()

    try:
        res = json.loads(open(out_p).read())
    except Exception:
        raw = open(out_p).read()
        res = {"is_error": True, "result": raw[-3000:] or stderr_text[-3000:], "parse_error": True}

    res.update({"_rc": rc, "_timed_out": timed_out, "_wall_s": wall_s, "_segment": segment_idx})
    write_json(out_p, res)

    log(f"segment {segment_idx}: rc={rc} timed_out={timed_out} wall={wall_s}s "
        f"turns={res.get('num_turns')} is_error={res.get('is_error')}")

    return res, stderr_text


def main():
    os.makedirs(LOGS_DIR, exist_ok=True)

    # Lock: only one auto-agent at a time
    lock = open(os.path.join(HERE, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another auto-agent is already running; exiting")
        return 0

    # Check prerequisites
    if not os.path.exists(TOKEN_FILE):
        log(f"ERROR: acct2's token file not found at {TOKEN_FILE}")
        return 1
    if not os.path.exists(JOB_SPEC):
        log(f"ERROR: JOB_SPEC.md not found at {JOB_SPEC}")
        return 1

    # Load or initialize status
    st = read_json(STATUS_FILE) or {}
    if not st:
        import uuid
        st = {
            "session_id": str(uuid.uuid4()),
            "state": "starting",
            "segments": [],
            "total_segments": 0,
            "consecutive_errors": 0,
            "started": datetime.now().isoformat(timespec="seconds"),
        }
        write_json(STATUS_FILE, st)
        log(f"initialized new auto-agent session: {st['session_id']}")

    if st.get("state") == "done":
        if goal_complete():
            log("auto-agent already completed; exiting")
            return 0
        st["state"] = "running"
        write_json(STATUS_FILE, st)

    session_id = st["session_id"]
    prompt = open(JOB_SPEC).read()

    consecutive_errors = st.get("consecutive_errors", 0)

    try:
        account_email = verify_auth(claude_env())
    except Exception as exc:
        st["state"] = "auth_failed"
        write_json(STATUS_FILE, st)
        log(f"authentication guard failed: {exc}")
        return 0
    st["auth_method"] = "oauth_token"
    st["auth_email"] = account_email
    write_json(STATUS_FILE, st)

    for seg_idx in range(st.get("total_segments", 0), MAX_SEGMENTS):
        if st.get("state") == "waiting_quota":
            deadline = float(st.get("next_retry_at") or 0)
            delay = max(0, deadline - time.time())
            if delay:
                log(f"quota wait persists across restart; sleeping {fmt_s(delay)}")
                time.sleep(delay)
            st.pop("next_retry_at", None)
            st["state"] = "running"
            write_json(STATUS_FILE, st)

        if st.get("state") == "waiting_token":
            old = st.get("token_fingerprint")
            log("OAuth token needs replacement; waiting for token file change")
            while token_fingerprint() == old:
                time.sleep(60)
            st.pop("token_fingerprint", None)
            st["state"] = "running"
            write_json(STATUS_FILE, st)

        # Disk check
        free = disk_free_gb()
        if free < DISK_MIN_GB:
            log(f"disk space low ({free:.1f} GB < {DISK_MIN_GB} GB); pausing for 30min")
            time.sleep(1800)
            continue

        # Check if session already exists (for resume)
        have = session_exists(session_id)

        # Build prompt: first segment gets full JOB_SPEC, resume segments get a continuation
        if not have:
            seg_prompt = prompt
        else:
            seg_prompt = (
                "You were interrupted by a quota limit or timeout. Resume your work from where you left off. "
                "Read the current auto_agent/JOB_SPEC.md and PROGRESS.md from disk first; their current content "
                "supersedes older copies in this conversation. Check progress and continue the next pending task."
            )

        try:
            res, stderr = run_segment(seg_prompt, session_id, have, seg_idx)
        except RuntimeError as exc:
            st["state"] = "auth_failed"
            write_json(STATUS_FILE, st)
            log(f"authentication guard failed: {exc}")
            return 0
        text = str(res.get("result", "")) + " " + stderr

        # Record segment
        st["total_segments"] = seg_idx + 1
        st["segments"].append({
            "idx": seg_idx,
            "wall_s": res.get("_wall_s"),
            "rc": res.get("_rc"),
            "timed_out": res.get("_timed_out"),
            "is_error": res.get("is_error"),
            "finished": datetime.now().isoformat(timespec="seconds"),
        })

        # Success: agent ended its turn normally
        if not res.get("is_error") and res.get("_rc") == 0:
            consecutive_errors = 0
            st["consecutive_errors"] = 0
            if goal_complete():
                st["state"] = "done"
                write_json(STATUS_FILE, st)
                log(f"auto-agent completed successfully after {seg_idx + 1} segments")
                return 0
            st["state"] = "running"
            write_json(STATUS_FILE, st)
            log("Claude turn ended; job artifacts are incomplete, continuing in the same session")
            time.sleep(30)
            continue

        # Timed out (5h quota window probably)
        if res.get("_timed_out"):
            consecutive_errors = 0
            st["state"] = "waiting_quota"
            st["consecutive_errors"] = 0
            write_json(STATUS_FILE, st)
            log(f"segment {seg_idx} timed out (likely 5h window); will resume")
            # Wait a bit then let the loop try again
            time.sleep(300)
            continue

        # Quota/rate limit
        failure_kind = classify_failure(text)
        if failure_kind == "limit":
            consecutive_errors = 0
            wait = limit_wait_s(text)
            st["state"] = "waiting_quota"
            st["consecutive_errors"] = 0
            st["next_retry_at"] = time.time() + wait
            write_json(STATUS_FILE, st)
            log(f"quota limit hit; sleeping {fmt_s(wait)} until reset")
            time.sleep(wait)
            st.pop("next_retry_at", None)
            st["state"] = "running"
            write_json(STATUS_FILE, st)
            continue

        if failure_kind == "auth":
            st["state"] = "waiting_token"
            st["token_fingerprint"] = token_fingerprint()
            write_json(STATUS_FILE, st)
            log("OAuth authentication failed; waiting for a replacement acct2 token")
            continue

        # Overload (transient)
        if failure_kind == "overload":
            wait = min(900, 60 * 2 ** min(consecutive_errors, 4))
            consecutive_errors += 1
            st["state"] = "retrying_overload"
            st["consecutive_errors"] = consecutive_errors
            write_json(STATUS_FILE, st)
            log(f"service overload; retrying in {wait}s (attempt {consecutive_errors})")
            time.sleep(wait)
            continue

        # Other error
        consecutive_errors += 1
        st["consecutive_errors"] = consecutive_errors
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            st["state"] = "failed"
            write_json(STATUS_FILE, st)
            log(f"giving up after {consecutive_errors} consecutive errors: {text[:500]}")
            return 1

        st["state"] = "retrying"
        write_json(STATUS_FILE, st)
        log(f"error (attempt {consecutive_errors}): {text[:300]}; retrying in {ERROR_BACKOFF_S}s")
        time.sleep(ERROR_BACKOFF_S)

    st["state"] = "max_segments"
    write_json(STATUS_FILE, st)
    log(f"reached maximum segments ({MAX_SEGMENTS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
