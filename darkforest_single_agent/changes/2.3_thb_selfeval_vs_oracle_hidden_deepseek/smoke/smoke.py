"""2.3 smoke (2.2's smoke.py with the run dir as an argument): drive one Codex session in the worker sandbox, one prompt
per argument; each later prompt resumes the session. Prints parse_stream's result and the harness state.
usage: python3 -I smoke/smoke.py <run dir name under smoke/> <prompt> [<prompt> ...]"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import codex_worker as W
rd = os.path.join(HERE, sys.argv[1])
st = {}
log = lambda m: print(m, flush=True)
first = sys.argv[2]
for i, p in enumerate(sys.argv[2:]):
    res, n = W.drive(rd, st, lambda: None, p, first, 900, f"t{i + 1}", log)
    print(json.dumps({k: v for k, v in (res or {}).items() if k != "_stderr"}, indent=1), flush=True)
    print(st, flush=True)
