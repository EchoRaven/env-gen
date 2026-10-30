#!/usr/bin/env python3
"""Run one Netflix job: one Claude Code session builds the env-gen Netflix app over ITERS iterations. Resumable.

Per iteration the agent continues in the same session (--resume) and workspace, may call `validate` (env-gen's
api_smoke, run outside the sandbox by the broker thread below) up to max_validate_calls_per_iter times, and submits
by ending its turn. The harness then snapshots /workspace and validates the snapshot independently (the official
score); that report opens the next iteration. The last iteration is scored too.

Sandbox: the baseline's bwrap sandbox (0_baxbench_nl2_tests/scripts/sandbox.py, unmodified) plus read-only mounts
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
import sandbox  # noqa: E402
from common import CFG, ENVS, SF, read_json, write_json  # noqa: E402  (agent settings come from the baseline config)
from run_job import LIMIT_RX, log, session_exists, snapshot, wait_for_limit  # noqa: E402

THB = f"{SF}/benchmarks/env-gen"
DESIGN = f"{THB}/design_inputs/netflix"
VALIDATOR_PY = f"{ENVS}/venvs/thb-validator/bin/python"
EVALS = os.path.join(EXP, "evals")
VAL_LOCK = os.path.join(EVALS, ".validator.lock")
PROMPTS = os.path.join(EXP, "prompts")


def sandbox_argv(rd, claude_args):
    argv = sandbox.command("nl2", rd, claude_args)  # workspace at /workspace, sandbox-bin pythons, per-job ~/.claude
    b = argv.index("bwrap")
    env = [e for e in argv[2:b] if not e.startswith(("PATH=", "PIP_CACHE_DIR="))]
    env += [f"PATH=/opt/node/bin:/opt/thbval:{sandbox.SANDBOX_BIN}:/usr/local/bin:/usr/bin:/bin",
            "PIP_CACHE_DIR=/home/agent/.cache/pip", "NPM_CONFIG_CACHE=/home/agent/.npm",
            "NPM_CONFIG_UPDATE_NOTIFIER=false", f"THBVAL_WAIT_S={X['validate_wait_s']}",
            f"BASH_DEFAULT_TIMEOUT_MS={X['bash_timeout_ms']['default']}",
            f"BASH_MAX_TIMEOUT_MS={X['bash_timeout_ms']['max']}"]
    argv = argv[:2] + env + argv[b:]
    c = argv.index("--chdir")
    extra = ["--ro-bind", X["node_dir"], "/opt/node",
             "--ro-bind", os.path.join(EXP, "sandbox_tools"), "/opt/thbval",
             "--ro-bind", os.path.join(EXP, "contract", "netflix.json"), "/opt/thbval-contract.json",
             "--ro-bind", THB, "/thb",
             "--ro-bind", DESIGN, "/workspace/design",
             "--bind", os.path.join(rd, "validate_io"), "/validate_io"]
    return argv[:c] + extra + argv[c:]


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


def run_validator(src, out, logf):
    """Validate one snapshot (serialized: one docker stack at a time). Returns the report text."""
    os.makedirs(out, exist_ok=True)
    cmd = (f"env -i PATH=/usr/local/bin:/usr/bin:/bin HOME={os.path.expanduser('~')} LANG=C.UTF-8 "
           f"PYTHONDONTWRITEBYTECODE=1 {VALIDATOR_PY} -I -B {EXP}/scripts/validator.py "
           f"{shlex.quote(src)} {shlex.quote(out)}")  # env -i: no API keys reach anything env-gen imports
    with open(VAL_LOCK, "w") as lk, open(logf, "a") as lg:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            subprocess.run(["sg", "docker", "-c", cmd], stdout=lg, stderr=subprocess.STDOUT, timeout=3600)
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
        st = {"task": X["task"], "run": run, "arm": "selfval", "session_id": str(uuid.uuid4()), "iters_done": 0,
              "state": "running", "model": CFG["model"], "effort": CFG["effort"], "iters": []}
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
    sid = st["session_id"]

    for k in range(st["iters_done"] + 1, X["iters"] + 1):
        if k == 1:
            prompt = first
        else:
            prompt = open(os.path.join(PROMPTS, "next_iter.txt")).read().format(
                k=k, iters=X["iters"], prev=k - 1, report=official(rd, run, k - 1), loop=loop)
        broker.k = k
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
                            "validate_calls": broker.calls.get(k, 0), "usage": res.get("usage"),
                            "finished": datetime.now().isoformat(timespec="seconds")})
        st["iters_done"] = k
        write_json(st_p, st)
        log(rd, f"iter {k} submitted: turns={res.get('num_turns')} wall={res.get('_wall_s')}s "
                f"validate_calls={broker.calls.get(k, 0)} list_cost=${res.get('total_cost_usd')}")
    official(rd, run, X["iters"])  # score the last submission too (no agent sees it)
    broker.stop.set()
    st = read_json(st_p, st)
    st["state"] = "done"
    write_json(st_p, st)
    log(rd, "job done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 0))
