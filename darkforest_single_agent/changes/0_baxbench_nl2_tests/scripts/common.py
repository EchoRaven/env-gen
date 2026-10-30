"""Shared paths and config for changes/0_baxbench_nl2_tests. Standard library only."""
import json, os

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SF = "/home/user/project/shabi_forest"
ENVS = f"{SF}/.envs"
BENCH = f"{SF}/benchmarks"
BAX = f"{BENCH}/baxbench"
NL2 = f"{BENCH}/NL2RepoBench"
CFG = json.load(open(os.path.join(EXP, "config.json")))
RUNS = os.path.join(EXP, "runs")
DATA = os.path.join(EXP, "data")
PROMPTS = os.path.join(EXP, "prompts")
EVAL = os.path.join(EXP, "eval")
LOGS = os.path.join(EXP, "logs")
REAL_CLAUDE_DIR = os.path.expanduser("~/.claude")
REAL_CLAUDE_JSON = os.path.expanduser("~/.claude.json")


def jobs():
    """All (bench, task, run) jobs, interleaved so both benchmarks make progress early."""
    out = []
    for r in range(CFG["runs"]):
        for i in range(max(len(CFG["nl2"]["tasks"]), len(CFG["bax"]["scenarios"]))):
            if i < len(CFG["nl2"]["tasks"]):
                out.append(("nl2", CFG["nl2"]["tasks"][i], r))
            if i < len(CFG["bax"]["scenarios"]):
                out.append(("bax", CFG["bax"]["scenarios"][i], r))
    return out


def target_iters(bench, task):
    """Iterations for this task: CFG["iters"], unless config.json extends it (extend_iters: {"bench/task": n})."""
    return CFG.get("extend_iters", {}).get(f"{bench}/{task}", CFG["iters"])


def run_dir(bench, task, run):
    return os.path.join(RUNS, f"{bench}__{task}__r{run}")


def read_json(path, default=None):
    try:
        return json.load(open(path))
    except Exception:
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as o:
        json.dump(obj, o, indent=1, default=str)
    os.replace(tmp, path)
