"""Build the bwrap sandbox in which one job's Claude Code agent runs.

The sandbox root is empty, with only an allow-list mounted:
- /usr, /etc and the DNS resolver dir are read-only system files; /proc, /dev and a private /tmp are provided.
- The pinned Claude Code binary is at /opt/claude/claude.
- The project Python interpreters are read-only. For BaxBench this is the Flask venv the benchmark prescribes.
- The job's workspace is the only project path that is writable: /app (BaxBench) or /workspace (NL2Repo).
- HOME=/home/agent is the job's own directory.

/home/user/project (benchmarks, hidden tests, lit review), ~/.ssh, and the user's other files are not visible.

Claude config: ~/.claude is bound from the real directory, because the OAuth credentials file has to be shared in
place. Claude Code replaces it by atomic rename on token refresh, and a bind of the single file would break that and
could log the user out. Every other entry of ~/.claude is replaced by a per-job overlay, so the agent sees none of the
user's sessions, memory, skills, plugins, settings, or history, and its own transcripts persist per job (needed for
--resume). ~/.claude.json is a per-job minimal copy (no tokens; account metadata only).
"""
import json, os

from common import CFG, ENVS, REAL_CLAUDE_DIR, REAL_CLAUDE_JSON

SHARED = {".credentials.json", ".device-keys.json"}       # must stay the real files
EXTRA_OVERLAY_DIRS = ["todos", "plans", "statsig"]        # created by Claude at runtime; keep them per-job too
AGENT_SETTINGS = {"cleanupPeriodDays": 3650}              # never prune this job's transcripts
WORKDIR = {"bax": "/app", "nl2": "/workspace"}
SANDBOX_BIN = f"{ENVS}/sandbox-bin"                       # python3 -> 3.11 etc. for NL2Repo agents


def prepare(bench, rd):
    """Create the job's home, overlays and workspace (idempotent)."""
    home, ovl = os.path.join(rd, "home"), os.path.join(rd, "claude_overlay")
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    os.makedirs(ovl, exist_ok=True)
    os.makedirs(os.path.join(rd, "app" if bench == "bax" else "workspace"), exist_ok=True)
    cj = os.path.join(home, ".claude.json")
    if not os.path.exists(cj):
        real = json.load(open(REAL_CLAUDE_JSON))
        json.dump({"hasCompletedOnboarding": True, "oauthAccount": real.get("oauthAccount", {})}, open(cj, "w"))
        os.chmod(cj, 0o600)
    entries = [e for e in os.listdir(REAL_CLAUDE_DIR) if e not in SHARED]
    for name in sorted(set(entries) | set(EXTRA_OVERLAY_DIRS)):
        real = os.path.join(REAL_CLAUDE_DIR, name)
        mine = os.path.join(ovl, name)
        is_dir = os.path.isdir(real) if os.path.exists(real) else True
        if not os.path.exists(real):
            os.makedirs(real, exist_ok=True)  # empty mount point; the agent writes into its overlay, not here
        if is_dir:
            os.makedirs(mine, exist_ok=True)
        elif not os.path.exists(mine):
            open(mine, "w").write(json.dumps(AGENT_SETTINGS) if name == "settings.json"
                                  else "{}" if name.endswith(".json") else "")
    return ovl


def command(bench, rd, claude_args):
    """Return argv for `env -i ... bwrap ... claude <claude_args>`."""
    ovl = prepare(bench, rd)
    wd = WORKDIR[bench]
    ws = os.path.join(rd, "app" if bench == "bax" else "workspace")
    if bench == "bax":
        path = f"{ENVS}/venvs/agent-flask/bin:/usr/local/bin:/usr/bin:/bin"
    else:
        path = f"{SANDBOX_BIN}:/usr/local/bin:/usr/bin:/bin"
    env = {
        "HOME": "/home/agent", "USER": "agent", "LOGNAME": "agent", "PATH": path, "SHELL": "/bin/bash",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "TMPDIR": "/tmp",
        "PIP_CACHE_DIR": "/tmp/pip-cache", "XDG_CACHE_HOME": "/tmp/xdg-cache",
        "DISABLE_AUTOUPDATER": "1",
    }
    argv = ["env", "-i"] + [f"{k}={v}" for k, v in env.items()] + [
        "bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--hostname", "sandbox",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc", "--ro-bind", "/run/systemd/resolve", "/run/systemd/resolve",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
        "--ro-bind", CFG["claude_bin"], "/opt/claude/claude",
        "--ro-bind", f"{ENVS}/python", f"{ENVS}/python",
        "--ro-bind", f"{ENVS}/bin", f"{ENVS}/bin",
    ]
    if bench == "bax":
        argv += ["--ro-bind", f"{ENVS}/venvs/agent-flask", f"{ENVS}/venvs/agent-flask"]
    else:
        argv += ["--ro-bind", SANDBOX_BIN, SANDBOX_BIN]
    argv += ["--bind", os.path.join(rd, "home"), "/home/agent",
             "--bind", REAL_CLAUDE_DIR, "/home/agent/.claude"]
    for name in sorted(os.listdir(ovl)):
        argv += ["--bind", os.path.join(ovl, name), f"/home/agent/.claude/{name}"]
    argv += ["--bind", ws, wd, "--chdir", wd, "/opt/claude/claude"] + claude_args
    return argv
