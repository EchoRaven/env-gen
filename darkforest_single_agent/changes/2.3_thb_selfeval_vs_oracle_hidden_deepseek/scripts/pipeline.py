#!/usr/bin/env python3
"""2.3 supervisor: runs what 2.2's auto-agent proctor ran, in the same order, without a Claude agent.

1. Job 1 (job_selfval, oracle observable), 20 iterations, via its scripts/launch.sh.
2. When job 1 is done: the hidden evaluation of a sample of job 1's snapshots (scripts/hidden_selfval.sh, the sample
   2.2 planned: iterations 1 4 8 12 16 20; tags selfval-it<k>), in the background. 2.2 started it while job 1 was still
   running; 2.3 starts it after job 1, so its docker stack never runs next to the agent's `validate` stacks (2.2 saw
   a container-name clash between concurrent stacks in job 2 and an unexplained host-port clash in job 1).
3. Job 2 (job_oracle_hidden), 20 iterations, via its scripts/launch.sh (it runs the hidden evaluations itself).
4. scripts/rejudge_loop.sh, started with step 2: re-judges any hidden tag whose visual judge hit the Claude usage limit
   (2.2 added it after job 2's judge ran out of quota); it exits once job 2 is done and no tag is left.
5. scripts/collect.py (tables, results/summary.json), then logs/PIPELINE_DONE.

A job that stops in state "failed" or whose process dies (e.g. a long upstream outage: each iteration gives up after
8 failed attempts) is relaunched after `retry_wait_s`; jobs resume from status.json. After `max_restarts` relaunches
of one job the pipeline stops and writes logs/PIPELINE_FAILED. It never starts a job while the disk has less than
50 GB free. `touch STOP` ends the pipeline at the next check (running jobs continue; stop them by PID).

usage: setsid nohup python3 -I scripts/pipeline.py >> logs/pipeline.out 2>&1 &   (scripts/start.sh does this)
"""
import json, os, shutil, subprocess, sys, time
from datetime import datetime

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(EXP, "logs")
RETRY_WAIT_S, MAX_RESTARTS, POLL_S, MIN_FREE_GB = 1800, 12, 60, 50


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(os.path.join(LOGS, "pipeline.log"), "a") as o:
        o.write(line + "\n")


def running(pid):
    """True if pid exists and is not a zombie. A finished child that nobody has reaped yet still answers kill(pid, 0),
    so a zombie is reaped here (if it is ours) and counted as ended."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        if open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0] == "Z":
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            return False
    except (OSError, IndexError):
        return False
    return True


def stopped():
    return os.path.exists(os.path.join(EXP, "STOP"))


def state(job):
    try:
        return json.load(open(os.path.join(EXP, job, "runs", "netflix__r0", "status.json")))
    except (OSError, ValueError):
        return {}


def alive(job):
    try:
        return running(int(open(os.path.join(EXP, job, "logs", "job_r0.pid")).read()))
    except (OSError, ValueError):
        return False


def done(job):
    st = state(job)
    return st.get("state") == "done" and st.get("iters_done", 0) >= json.load(open(os.path.join(EXP, job, "config.json")))["iters"]


def run_job(job):
    restarts = 0
    while not done(job):
        if stopped():
            return False
        if not alive(job):
            if restarts > MAX_RESTARTS:
                log(f"{job}: gave up after {MAX_RESTARTS} relaunches")
                return False
            while shutil.disk_usage("/").free < MIN_FREE_GB * 2**30 and not stopped():
                log(f"{job}: less than {MIN_FREE_GB} GB free on /; waiting")
                time.sleep(RETRY_WAIT_S)
            if restarts:
                log(f"{job}: not running (state={state(job).get('state')}, iters_done={state(job).get('iters_done')}); "
                    f"relaunch {restarts}/{MAX_RESTARTS}")
            r = subprocess.run(["bash", os.path.join(EXP, job, "scripts", "launch.sh"), "0"], capture_output=True, text=True)
            log(f"{job}: launch.sh rc={r.returncode}: {(r.stdout + r.stderr).strip()[-400:]}")
            restarts += 1
            if r.returncode != 0:
                time.sleep(RETRY_WAIT_S)
                continue
            time.sleep(POLL_S)
        while alive(job) and not stopped():
            time.sleep(POLL_S)
        if not done(job) and not stopped():
            log(f"{job}: process ended with state={state(job).get('state')} iters_done={state(job).get('iters_done')}; "
                f"waiting {RETRY_WAIT_S}s before relaunching")
            time.sleep(RETRY_WAIT_S)
    log(f"{job}: done ({state(job).get('iters_done')} iterations)")
    return True


def background(name, argv):
    pidf = os.path.join(LOGS, f"{name}.pid")
    try:
        if running(int(open(pidf).read())):
            log(f"{name} already running")
            return None
    except (OSError, ValueError):
        pass
    p = subprocess.Popen(argv, stdout=open(os.path.join(LOGS, f"{name}.txt"), "a"), stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, cwd=EXP)
    open(pidf, "w").write(str(p.pid))
    log(f"{name} started: pid {p.pid}")
    return p


def wait_pidfile(name):
    try:
        pid = int(open(os.path.join(LOGS, f"{name}.pid")).read())
    except (OSError, ValueError):
        return
    while not stopped() and running(pid):
        time.sleep(POLL_S)


def main():
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(os.path.join(EXP, "results"), exist_ok=True)
    log(f"pipeline started (pid {os.getpid()})")
    if not run_job("job_selfval"):
        open(os.path.join(LOGS, "PIPELINE_FAILED"), "w").write("job_selfval\n")
        return 1
    background("hidden_selfval", ["bash", os.path.join(EXP, "scripts", "hidden_selfval.sh")])
    background("rejudge_loop", ["bash", os.path.join(EXP, "scripts", "rejudge_loop.sh")])
    if not run_job("job_oracle_hidden"):
        open(os.path.join(LOGS, "PIPELINE_FAILED"), "w").write("job_oracle_hidden\n")
        return 1
    wait_pidfile("hidden_selfval")
    wait_pidfile("rejudge_loop")
    if stopped():
        log("STOP file present; exiting")
        return 0
    r = subprocess.run([sys.executable, "-I", os.path.join(EXP, "scripts", "collect.py")], capture_output=True, text=True)
    open(os.path.join(EXP, "results", "tables.md"), "w").write(r.stdout)
    log(f"collect.py rc={r.returncode}; tables in results/tables.md")
    r = subprocess.run(["python3", "-I", "/home/user/project/shabi_forest/tools/benchmark_freeze.py", "verify"],
                       capture_output=True, text=True)
    log(f"benchmark_freeze verify rc={r.returncode}")
    open(os.path.join(LOGS, "PIPELINE_DONE"), "w").write(datetime.now().isoformat(timespec="seconds") + "\n")
    log("pipeline done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
