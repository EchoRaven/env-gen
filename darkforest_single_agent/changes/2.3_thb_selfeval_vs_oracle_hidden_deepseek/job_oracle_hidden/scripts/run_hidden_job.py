#!/usr/bin/env python3
"""Run one Netflix job with the oracle hidden: one Codex CLI session (deepseek-v4.1-flash through the model gateway), ITERS
iterations, one evaluation each. Resumable. Experiment 2.3 = 2.2 with the model Qwen3.8-27B -> DeepSeek (this file is
2.2's). Experiment 2.2: identical to ../../2.1_thb_netflix_oracle_hidden except for
the worker (Claude Code -> Codex + Qwen; see ../common/codex_worker.py) and ITERS (5 -> 20).

An iteration is one submission. The agent works in the same session (--resume) and workspace, tests with what the
sandbox offers, and submits by ending its turn. The harness then:
1. snapshots /workspace;
2. runs the DEV evaluation (env-gen's api_smoke, scripts/dev_validator.py), whose report opens the next iteration;
3. starts the HIDDEN evaluation (scripts/hidden_eval.py: API suite, UI walk, static audit, visual judge) in the
   background. Its results are written outside the sandbox and never reach the agent.
The last submission is evaluated the same way.

Sandbox: ../common/codex_worker.py's bwrap sandbox (the baseline's, minus ~/.claude, plus Codex at /opt/codex), workspace at /workspace,
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
from common import ENVS, SF, read_json, write_json  # noqa: E402
from run_job import log, snapshot  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(EXP), "common"))
import codex_worker as W  # noqa: E402

DESIGN = f"{SF}/benchmarks/env-gen/design_inputs/netflix"
PY = f"{ENVS}/venvs/thb-validator/bin/python"
EVALS = os.path.join(EXP, "evals")
PROMPTS = os.path.join(EXP, "prompts")
CLEAN_ENV = (f"env -i PATH=/usr/local/bin:/usr/bin:/bin HOME={os.path.expanduser('~')} LANG=C.UTF-8 "
             f"PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH={ENVS}/cache/ms-playwright")  # no API keys, no CLAUDECODE


def sandbox_kw(rd):
    """The job's additions to the worker sandbox: the same mounts as experiment 2.1 (Node, task materials)."""
    return {"extra": ["--ro-bind", X["node_dir"], "/opt/node", "--ro-bind", DESIGN, "/workspace/design"],
            "path_prefix": ["/opt/node/bin"]}


def dev_eval(rd, run, k):
    """The dev evaluation of snapshots/iter<k> (retried once on a validator or docker hiccup). Returns its report."""
    out = os.path.join(EVALS, "dev", f"r{run}-it{k}")
    rp = os.path.join(out, "report.txt")
    src = os.path.join(rd, "snapshots", f"iter{k}", "workspace")
    rep = {}
    for attempt in range(2):
        if not os.path.exists(rp):
            os.makedirs(out, exist_ok=True)
            W.make_writable(os.path.join(out, "project"))  # a retry re-stages over the old copy
            cmd = f"{CLEAN_ENV} {PY} -I -B {EXP}/scripts/dev_validator.py {shlex.quote(src)} {shlex.quote(out)}"
            with open(os.path.join(EVALS, ".dev.lock"), "w") as lk, open(os.path.join(rd, "dev_validator.log"), "a") as lg, \
                    open(os.path.join(EVALS, ".hidden.lock"), "w") as hk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                # 2.2: Qwen's compose files hard-code container_name (netflix_database ...), so the dev stack and a
                # background hidden-eval stack cannot coexist; wait for the hidden eval's stack phase (it holds this
                # lock only while its stack is up). In 2.1 both ran concurrently.
                fcntl.flock(hk, fcntl.LOCK_EX)
                try:
                    subprocess.run(W.docker_argv(cmd), stdout=lg, stderr=subprocess.STDOUT, timeout=3600)
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
    return subprocess.Popen(W.docker_argv(cmd), stdout=lg, stderr=subprocess.STDOUT, start_new_session=True)


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
        st = {"task": X["task"], "run": run, "arm": "oracle_hidden", "codex_sid": None, "iters_done": 0,
              "state": "running", "worker": X["worker"], "codex": W.C, "iters": []}
    if st.get("state") == "done" and st["iters_done"] >= X["iters"]:
        log(rd, "already done")
        return 0
    st["state"], st["pid"] = "running", os.getpid()
    write_json(st_p, st)
    loop = open(os.path.join(PROMPTS, "loop.txt")).read()
    first = open(os.path.join(PROMPTS, "iter1.txt")).read().format(
        iters=X["iters"], description=open(os.path.join(DESIGN, "DESCRIPTION.txt")).read().strip(), loop=loop)
    hidden = []
    save = lambda: write_json(st_p, st)  # noqa: E731
    kw = sandbox_kw(rd)

    for k in range(st["iters_done"] + 1, X["iters"] + 1):
        if k == 1:
            prompt = first
        else:
            prompt = open(os.path.join(PROMPTS, "next_iter.txt")).read().format(
                k=k, iters=X["iters"], prev=k - 1, report=dev_eval(rd, run, k - 1), loop=loop)
            if not os.path.exists(os.path.join(EVALS, "hidden", f"r{run}-it{k - 1}", "summary.json")):
                hidden.append(hidden_eval(rd, run, k - 1))
        if k == 1 and st.get("codex_sid"):
            prompt = f"This is still iteration 1 of {X['iters']}; your previous turn was interrupted.\n\n{loop}"
        open(os.path.join(rd, f"prompt_iter{k}.txt"), "w").write(prompt)
        res, attempts = W.drive(rd, st, save, prompt, first, X["iter_timeout_s"], f"iter{k}",
                                lambda m: log(rd, m), **kw)
        if res is None:
            st["state"] = "failed"
            save()
            log(rd, f"iter {k} failed after {attempts} attempts; stopping job")
            return 1
        if res.get("_timed_out"):
            log(rd, f"iter {k} timed out after {X['iter_timeout_s']}s; keeping its work")
        snapshot(os.path.join(rd, "workspace"), os.path.join(rd, "snapshots", f"iter{k}", "workspace"))
        st["iters"].append({"iter": k, "attempts": attempts, "timed_out": res.get("_timed_out"),
                            "wall_s": res.get("_wall_s"), "num_turns": res.get("num_turns"),
                            "commands": res.get("commands"), "is_error": res.get("is_error"), "usage": res.get("usage"),
                            "session": st.get("codex_sid"), "result": str(res.get("result"))[:2000],
                            "finished": datetime.now().isoformat(timespec="seconds")})
        st["iters_done"] = k
        save()
        log(rd, f"iter {k} submitted: items={res.get('num_turns')} cmds={res.get('commands')} wall={res.get('_wall_s')}s "
                f"usage={res.get('usage')}")
    dev_eval(rd, run, X["iters"])  # the last submission gets the same two evaluations; no agent sees them
    if not os.path.exists(os.path.join(EVALS, "hidden", f"r{run}-it{X['iters']}", "summary.json")):
        hidden.append(hidden_eval(rd, run, X["iters"]))
    for p in hidden:
        p.wait()
    st["state"] = "done"
    save()
    log(rd, "job done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 0))
