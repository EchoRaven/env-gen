#!/usr/bin/env python3
"""Run one Netflix job with the oracle hidden: one Claude Code session, ITERS iterations, one evaluation each. Resumable.

An iteration is one submission. The agent works in the same session (--resume) and workspace, tests with what the
sandbox offers, and submits by ending its turn. The harness then:
1. snapshots /workspace;
2. runs the DEV evaluation (env-gen's api_smoke, scripts/dev_validator.py), whose report opens the next iteration;
3. starts the HIDDEN evaluation (scripts/hidden_eval.py: API suite, UI walk, static audit, visual judge) in the
   background. Its results are written outside the sandbox and never reach the agent.
The last submission is evaluated the same way.

Sandbox: the baseline's bwrap sandbox (0_baxbench_nl2_tests/scripts/sandbox.py, unmodified), workspace at /workspace,
plus read-only Node (/opt/node) and the task materials (/workspace/design). It has no evaluator, no env-gen source
and no docker.

usage: run_hidden_job.py <run>
"""
import fcntl, json, os, shlex, signal, subprocess, sys, time, uuid
from datetime import datetime

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
BASE = os.path.join(os.path.dirname(EXP), X["base_experiment"])
sys.path.insert(0, os.path.join(BASE, "scripts"))
import sandbox  # noqa: E402
from common import CFG, ENVS, SF, read_json, write_json  # noqa: E402  (agent settings come from the baseline config)
from run_job import LIMIT_RX, log, session_exists, snapshot, wait_for_limit  # noqa: E402

DESIGN = f"{SF}/benchmarks/env-gen/design_inputs/netflix"
PY = f"{ENVS}/venvs/thb-validator/bin/python"
EVALS = os.path.join(EXP, "evals")
PROMPTS = os.path.join(EXP, "prompts")
CLEAN_ENV = (f"env -i PATH=/usr/local/bin:/usr/bin:/bin HOME={os.path.expanduser('~')} LANG=C.UTF-8 "
             f"PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH={ENVS}/cache/ms-playwright")  # no API keys, no CLAUDECODE


def sandbox_argv(rd, claude_args):
    argv = sandbox.command("nl2", rd, claude_args)
    b = argv.index("bwrap")
    env = [e for e in argv[2:b] if not e.startswith(("PATH=", "PIP_CACHE_DIR="))]
    env += [f"PATH=/opt/node/bin:{sandbox.SANDBOX_BIN}:/usr/local/bin:/usr/bin:/bin",
            "PIP_CACHE_DIR=/home/agent/.cache/pip", "NPM_CONFIG_CACHE=/home/agent/.npm", "NPM_CONFIG_UPDATE_NOTIFIER=false",
            f"BASH_DEFAULT_TIMEOUT_MS={X['bash_timeout_ms']['default']}", f"BASH_MAX_TIMEOUT_MS={X['bash_timeout_ms']['max']}"]
    argv = argv[:2] + env + argv[b:]
    c = argv.index("--chdir")
    return argv[:c] + ["--ro-bind", X["node_dir"], "/opt/node", "--ro-bind", DESIGN, "/workspace/design"] + argv[c:]


def run_claude(rd, args, timeout, tag):
    out_p, err_p = os.path.join(rd, f"{tag}.json"), os.path.join(rd, f"{tag}.stderr")
    t0 = time.time()
    with open(out_p, "w") as fo, open(err_p, "w") as fe:
        p = subprocess.Popen(sandbox_argv(rd, args), stdout=fo, stderr=fe, start_new_session=True)
        try:
            rc, timed_out = p.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            rc, timed_out = -9, True
    try:
        res = json.loads(open(out_p).read())
    except Exception:
        res = {"is_error": True, "result": open(out_p).read()[-2000:] or open(err_p).read()[-2000:], "parse_error": True}
    res.update({"_rc": rc, "_timed_out": timed_out, "_wall_s": round(time.time() - t0, 1)})
    write_json(out_p, res)
    return res


def dev_eval(rd, run, k):
    """The dev evaluation of snapshots/iter<k> (retried once on a validator or docker hiccup). Returns its report."""
    out = os.path.join(EVALS, "dev", f"r{run}-it{k}")
    rp = os.path.join(out, "report.txt")
    src = os.path.join(rd, "snapshots", f"iter{k}", "workspace")
    rep = {}
    for attempt in range(2):
        if not os.path.exists(rp):
            os.makedirs(out, exist_ok=True)
            cmd = f"{CLEAN_ENV} {PY} -I -B {EXP}/scripts/dev_validator.py {shlex.quote(src)} {shlex.quote(out)}"
            with open(os.path.join(EVALS, ".dev.lock"), "w") as lk, open(os.path.join(rd, "dev_validator.log"), "a") as lg:
                fcntl.flock(lk, fcntl.LOCK_EX)
                try:
                    subprocess.run(["sg", "docker", "-c", cmd], stdout=lg, stderr=subprocess.STDOUT, timeout=3600)
                except subprocess.TimeoutExpired:
                    pass
        rep = read_json(os.path.join(out, "report.json"), {}) or {}
        infra = any(c.get("name") in ("validator_error", "runner_error") for c in rep.get("checks", []))
        if os.path.exists(rp) and not infra:
            break
        if attempt == 0 and os.path.exists(rp):
            os.remove(rp)
    m = rep.get("_wrapper", {}).get("metrics")
    with open(os.path.join(EVALS, "dev", f"r{run}_scores.jsonl"), "a") as o:
        o.write(json.dumps({"iter": k, "passed": rep.get("passed"), "metrics": m, "summary": rep.get("summary"),
                            "at": datetime.now().isoformat(timespec="seconds")}) + "\n")
    log(rd, f"dev evaluation of iter {k}: passed={rep.get('passed')} {m}")
    return open(rp).read() if os.path.exists(rp) else "The evaluator produced no report.\n"


def hidden_eval(rd, run, k):
    """Start the hidden evaluation of snapshots/iter<k> in the background; returns the process."""
    src = os.path.join(rd, "snapshots", f"iter{k}", "workspace")
    cmd = f"{CLEAN_ENV} {PY} -I -B {EXP}/scripts/hidden_eval.py {shlex.quote(src)} r{run}-it{k}"
    lg = open(os.path.join(EXP, "logs", f"hidden_r{run}-it{k}.log"), "a")
    log(rd, f"hidden evaluation of iter {k} started (results stay outside the sandbox)")
    return subprocess.Popen(["sg", "docker", "-c", cmd], stdout=lg, stderr=subprocess.STDOUT, start_new_session=True)


def main(run):
    run = int(run)
    rd = os.path.join(EXP, "runs", f"{X['task']}__r{run}")
    for d in ("workspace/design", "snapshots"):
        os.makedirs(os.path.join(rd, d), exist_ok=True)
    os.makedirs(os.path.join(EVALS, "dev"), exist_ok=True)
    lock = open(os.path.join(rd, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"r{run} is already being run by another process; exiting", flush=True)
        return 0
    st_p = os.path.join(rd, "status.json")
    st = read_json(st_p, {}) or {}
    if not st:
        st = {"task": X["task"], "run": run, "arm": "oracle_hidden", "session_id": str(uuid.uuid4()), "iters_done": 0,
              "state": "running", "model": CFG["model"], "effort": CFG["effort"], "iters": []}
    if st.get("state") == "done" and st["iters_done"] >= X["iters"]:
        log(rd, "already done")
        return 0
    st["state"], st["pid"] = "running", os.getpid()
    write_json(st_p, st)
    loop = open(os.path.join(PROMPTS, "loop.txt")).read()
    first = open(os.path.join(PROMPTS, "iter1.txt")).read().format(
        iters=X["iters"], description=open(os.path.join(DESIGN, "DESCRIPTION.txt")).read().strip(), loop=loop)
    sid, hidden = st["session_id"], []

    for k in range(st["iters_done"] + 1, X["iters"] + 1):
        if k == 1:
            prompt = first
        else:
            prompt = open(os.path.join(PROMPTS, "next_iter.txt")).read().format(
                k=k, iters=X["iters"], prev=k - 1, report=dev_eval(rd, run, k - 1), loop=loop)
            if not os.path.exists(os.path.join(EVALS, "hidden", f"r{run}-it{k - 1}", "summary.json")):
                hidden.append(hidden_eval(rd, run, k - 1))
        for attempt in range(CFG["max_attempts_per_iter"]):
            have = session_exists(rd, sid)
            if have and k == 1:
                prompt = f"This is still iteration 1 of {X['iters']}; your previous turn was interrupted.\n\n{loop}"
            open(os.path.join(rd, f"prompt_iter{k}.txt"), "w").write(prompt)
            args = ["-p", prompt, "--model", CFG["model"], "--effort", CFG["effort"], "--output-format", "json",
                    "--dangerously-skip-permissions", "--strict-mcp-config", "--disallowedTools", *CFG["disallowed_tools"]]
            args += ["--resume", sid] if have else ["--session-id", sid]
            log(rd, f"iter {k} attempt {attempt} ({'resume' if have else 'new session'})")
            res = run_claude(rd, args, X["iter_timeout_s"], f"iter{k}_a{attempt}")
            text = str(res.get("result", ""))
            if res.get("_timed_out"):
                log(rd, f"iter {k} timed out after {X['iter_timeout_s']}s; keeping its work")
                break
            if not res.get("is_error") and res.get("_rc") == 0:
                break
            if LIMIT_RX.search(text) or LIMIT_RX.search(open(os.path.join(rd, f"iter{k}_a{attempt}.stderr")).read()):
                wait_for_limit(rd, res, attempt)
            else:
                log(rd, f"iter {k} error (rc={res.get('_rc')}): {text[:300]!r}; retrying in 300s")
                time.sleep(300)
        else:
            st = read_json(st_p, st)
            st["state"] = "failed"
            write_json(st_p, st)
            log(rd, f"iter {k} failed after {CFG['max_attempts_per_iter']} attempts; stopping job")
            return 1
        snapshot(os.path.join(rd, "workspace"), os.path.join(rd, "snapshots", f"iter{k}", "workspace"))
        st = read_json(st_p, st)
        st["iters"].append({"iter": k, "attempts": attempt + 1, "timed_out": res.get("_timed_out"),
                            "wall_s": res.get("_wall_s"), "num_turns": res.get("num_turns"),
                            "list_cost_usd": res.get("total_cost_usd"), "is_error": res.get("is_error"),
                            "usage": res.get("usage"), "finished": datetime.now().isoformat(timespec="seconds")})
        st["iters_done"] = k
        write_json(st_p, st)
        log(rd, f"iter {k} submitted: turns={res.get('num_turns')} wall={res.get('_wall_s')}s list_cost=${res.get('total_cost_usd')}")
    dev_eval(rd, run, X["iters"])  # the last submission gets the same two evaluations; no agent sees them
    if not os.path.exists(os.path.join(EVALS, "hidden", f"r{run}-it{X['iters']}", "summary.json")):
        hidden.append(hidden_eval(rd, run, X["iters"]))
    for p in hidden:
        p.wait()
    st = read_json(st_p, st)
    st["state"] = "done"
    write_json(st_p, st)
    log(rd, "job done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 0))
