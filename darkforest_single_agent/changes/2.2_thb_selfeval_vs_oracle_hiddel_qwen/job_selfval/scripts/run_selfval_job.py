#!/usr/bin/env python3
"""Run one Netflix job: one Codex CLI session (Qwen3.8-27B-INT4 on the local vLLM server) builds the env-gen Netflix
app over ITERS iterations. Resumable. Experiment 2.2: identical to ../../2_thb_netflix_selfval except for the worker
(Claude Code -> Codex + Qwen; see ../common/codex_worker.py) and ITERS (5 -> 20).

Per iteration the agent continues in the same session (`codex exec resume`) and workspace, may call `validate` (env-gen's
api_smoke, run outside the sandbox by the broker thread below) up to max_validate_calls_per_iter times, and submits
by ending its turn. The harness then snapshots /workspace and validates the snapshot independently (the official
score); that report opens the next iteration. The last iteration is scored too.

Sandbox: ../common/codex_worker.py's bwrap sandbox (the baseline's, minus ~/.claude, plus Codex at /opt/codex) plus read-only mounts
of Node, the `validate` command, the frozen contract, the frozen env-gen repo (/thb) and the task materials
(/workspace/design), and the request/response directory /validate_io. No docker inside the sandbox.

usage: run_selfval_job.py <run>
"""
import fcntl, json, os, shlex, signal, subprocess, sys, threading, time, uuid
from datetime import datetime

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = json.load(open(os.path.join(EXP, "config.json")))
BASE = os.path.join(os.path.dirname(EXP), X["base_experiment"])
sys.path.insert(0, os.path.join(BASE, "scripts"))
from common import ENVS, SF, read_json, write_json  # noqa: E402
from run_job import log, snapshot  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(EXP), "common"))
import codex_worker as W  # noqa: E402

THB = f"{SF}/benchmarks/env-gen"
DESIGN = f"{THB}/design_inputs/netflix"
VALIDATOR_PY = f"{ENVS}/venvs/thb-validator/bin/python"
EVALS = os.path.join(EXP, "evals")
VAL_LOCK = os.path.join(EVALS, ".validator.lock")
PROMPTS = os.path.join(EXP, "prompts")


def sandbox_kw(rd):
    """The job's additions to the worker sandbox: the same mounts and variables as experiment 2."""
    extra = ["--ro-bind", X["node_dir"], "/opt/node",
             "--ro-bind", os.path.join(EXP, "sandbox_tools"), "/opt/thbval",
             "--ro-bind", os.path.join(EXP, "contract", "netflix.json"), "/opt/thbval-contract.json",
             "--ro-bind", THB, "/thb",
             "--ro-bind", DESIGN, "/workspace/design",
             "--bind", os.path.join(rd, "validate_io"), "/validate_io"]
    return {"extra": extra, "path_prefix": ["/opt/node/bin", "/opt/thbval"],
            "env_extra": {"THBVAL_WAIT_S": str(X["validate_wait_s"])}}


def run_validator(src, out, logf):
    """Validate one snapshot (serialized: one docker stack at a time). Returns the report text."""
    os.makedirs(out, exist_ok=True)
    W.make_writable(os.path.join(out, "project"))  # a retry re-stages over the old copy
    cmd = (f"env -i PATH=/usr/local/bin:/usr/bin:/bin HOME={os.path.expanduser('~')} LANG=C.UTF-8 "
           f"PYTHONDONTWRITEBYTECODE=1 {VALIDATOR_PY} -I -B {EXP}/scripts/validator.py "
           f"{shlex.quote(src)} {shlex.quote(out)}")  # env -i: no API keys reach anything env-gen imports
    with open(VAL_LOCK, "w") as lk, open(logf, "a") as lg:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            subprocess.run(W.docker_argv(cmd), stdout=lg, stderr=subprocess.STDOUT, timeout=3600)
        except subprocess.TimeoutExpired:
            pass
    rp = os.path.join(out, "report.txt")
    return open(rp).read() if os.path.exists(rp) else f"The validator produced no report (timed out or crashed).\n"


class Broker(threading.Thread):
    """Serves the agent's `validate` requests from <rd>/validate_io (the sandbox's /validate_io)."""

    def __init__(self, rd, run):
        super().__init__(daemon=True)
        self.rd, self.run_no, self.k, self.stop = rd, run, 0, threading.Event()
        self.io = os.path.join(rd, "validate_io")
        self.log_p = os.path.join(EVALS, f"r{run}", "agent_calls.jsonl")
        self.calls = {}  # iteration -> calls made, rebuilt from the call log on resume
        for line in open(self.log_p) if os.path.exists(self.log_p) else []:
            it = json.loads(line)["iter"]
            self.calls[it] = self.calls.get(it, 0) + 1

    def run(self):
        req = os.path.join(self.io, "requests")
        while not self.stop.is_set():
            for f in sorted(os.listdir(req)):
                if f.startswith(".") or not f.endswith(".json"):
                    continue
                rid = f[:-5]
                try:
                    text = self.handle(rid)
                except Exception as e:
                    text = f"Validation infrastructure error (not your app): {type(e).__name__}: {e}\n"
                    log(self.rd, f"broker error on {rid}: {e!r}")
                tmp = os.path.join(self.io, "responses", f".{rid}.txt")
                open(tmp, "w").write(text)
                os.replace(tmp, os.path.join(self.io, "responses", f"{rid}.txt"))
                os.replace(os.path.join(req, f), os.path.join(self.io, "done", f))
            self.stop.wait(3)

    def handle(self, rid):
        k, cap = self.k, X["max_validate_calls_per_iter"]
        n = self.calls.get(k, 0)
        if n >= cap:
            return (f"Not run: all {cap} validation calls of iteration {k} are used. Submit when you are confident; "
                    f"the harness validates your submission independently.\n")
        self.calls[k] = n + 1
        out = os.path.join(EVALS, f"r{self.run_no}", f"it{k}-call{n + 1:02d}-{rid}")
        t0 = time.time()
        snapshot(os.path.join(self.rd, "workspace"), os.path.join(out, "src"))
        text = run_validator(os.path.join(out, "src"), out, os.path.join(self.rd, "validator.log"))
        m = (read_json(os.path.join(out, "report.json"), {}) or {}).get("_wrapper", {}).get("metrics")
        with open(self.log_p, "a") as o:
            o.write(json.dumps({"iter": k, "call": n + 1, "id": rid, "wall_s": round(time.time() - t0, 1),
                                "metrics": m, "at": datetime.now().isoformat(timespec="seconds")}) + "\n")
        log(self.rd, f"agent validate call {n + 1}/{cap} in iter {k}: {m}")
        return text + f"\n(Validation call {n + 1} of {cap} in this iteration.)\n"


def official(rd, run, k):
    """The harness's own validation of snapshots/iter<k>: the iteration's score and the next prompt's report."""
    out = os.path.join(EVALS, f"r{run}", f"official-it{k}")
    rp = os.path.join(out, "report.txt")
    for attempt in range(2):
        if not os.path.exists(rp):
            run_validator(os.path.join(rd, "snapshots", f"iter{k}", "workspace"), out,
                          os.path.join(rd, "validator.log"))
        rep = read_json(os.path.join(out, "report.json"), {}) or {}
        infra = any(c.get("name") in ("validator_error", "runner_error") for c in rep.get("checks", []))
        if os.path.exists(rp) and not infra:
            break
        if attempt == 0 and os.path.exists(rp):
            os.remove(rp)  # validator or docker hiccup: validate the same snapshot once more
    m = rep.get("_wrapper", {}).get("metrics")
    scores = os.path.join(EVALS, f"r{run}", "official_scores.jsonl")
    done = {json.loads(l)["iter"] for l in open(scores)} if os.path.exists(scores) else set()
    if k not in done:
        with open(scores, "a") as o:
            o.write(json.dumps({"iter": k, "passed": rep.get("passed"), "metrics": m,
                                "summary": rep.get("summary")}) + "\n")
    log(rd, f"official validation of iter {k}: passed={rep.get('passed')} {m}")
    return open(rp).read() if os.path.exists(rp) else "The validator produced no report.\n"


def main(run):
    run = int(run)
    rd = os.path.join(EXP, "runs", f"{X['task']}__r{run}")
    for d in ("workspace/design", "validate_io/requests", "validate_io/responses", "validate_io/done", "snapshots"):
        os.makedirs(os.path.join(rd, d), exist_ok=True)
    os.makedirs(os.path.join(EVALS, f"r{run}"), exist_ok=True)
    lock = open(os.path.join(rd, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one process per job, even if launched twice
    except BlockingIOError:
        print(f"r{run} is already being run by another process; exiting", flush=True)
        return 0
    st_p = os.path.join(rd, "status.json")
    st = read_json(st_p, {}) or {}
    if not st:
        st = {"task": X["task"], "run": run, "arm": "selfval", "codex_sid": None, "iters_done": 0,
              "state": "running", "worker": X["worker"], "codex": W.C, "iters": []}
    if st.get("state") == "done" and st["iters_done"] >= X["iters"]:
        log(rd, "already done")
        return 0
    st["state"], st["pid"] = "running", os.getpid()
    write_json(st_p, st)
    broker = Broker(rd, run)
    broker.start()
    loop = open(os.path.join(PROMPTS, "loop.txt")).read()
    first = open(os.path.join(PROMPTS, "iter1.txt")).read().format(
        iters=X["iters"], description=open(os.path.join(DESIGN, "DESCRIPTION.txt")).read().strip(),
        max_calls=X["max_validate_calls_per_iter"], loop=loop)
    save = lambda: write_json(st_p, st)  # noqa: E731
    kw = sandbox_kw(rd)

    for k in range(st["iters_done"] + 1, X["iters"] + 1):
        if k == 1:
            prompt = first
        else:
            prompt = open(os.path.join(PROMPTS, "next_iter.txt")).read().format(
                k=k, iters=X["iters"], prev=k - 1, report=official(rd, run, k - 1), loop=loop)
        if k == 1 and st.get("codex_sid"):
            prompt = f"This is still iteration 1 of {X['iters']}; your previous turn was interrupted.\n\n{loop}"
        broker.k = k
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
                            "commands": res.get("commands"), "is_error": res.get("is_error"),
                            "validate_calls": broker.calls.get(k, 0), "usage": res.get("usage"),
                            "session": st.get("codex_sid"), "result": str(res.get("result"))[:2000],
                            "finished": datetime.now().isoformat(timespec="seconds")})
        st["iters_done"] = k
        save()
        log(rd, f"iter {k} submitted: items={res.get('num_turns')} cmds={res.get('commands')} wall={res.get('_wall_s')}s "
                f"validate_calls={broker.calls.get(k, 0)} usage={res.get('usage')}")
    official(rd, run, X["iters"])  # score the last submission too (no agent sees it)
    broker.stop.set()
    st["state"] = "done"
    save()
    log(rd, "job done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 0))
