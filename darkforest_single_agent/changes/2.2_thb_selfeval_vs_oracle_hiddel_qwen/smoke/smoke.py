import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import codex_worker as W
rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rd")
st = {}
log = lambda m: print(m, flush=True)
p = sys.argv[1]
res, n = W.drive(rd, st, lambda: None, p, p, 900, "t1", log)
print(json.dumps({k: v for k, v in res.items() if k != "_stderr"}, indent=1)); print(st)
if len(sys.argv) > 2:
    res, n = W.drive(rd, st, lambda: None, sys.argv[2], p, 900, "t2", log)
    print(json.dumps({k: v for k, v in res.items() if k != "_stderr"}, indent=1)); print(st)
