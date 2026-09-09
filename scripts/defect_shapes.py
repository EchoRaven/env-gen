"""Static detectors for the defect SHAPES this pipeline keeps producing.

Written because "why are these so hard to find?" has a concrete answer: read linearly and
every one of them looks correct, because each is a disagreement BETWEEN two places rather
than a mistake in either. Reading for the shape finds them; reading the code does not.

D1  "not measured" read as zero -- `float(x.get(<a measurement>) or 0.0)`.
    None means nobody measured; 0.0 means measured and terrible. Collapsing them makes an
    unphotographed screen indistinguishable from a blank page, and an unwritten ledger
    field from a run that spent nothing.

D3  a verdict recorded without its reason -- an `evidence=`/`metadata=` literal with no
    reason field while the producer had one.

EVERY HIT IS A CANDIDATE, NOT A DEFECT. Each needs its surrounding guard read: the first
run of D1 flagged visual_fidelity's blocking-average, whose line above already excludes
blank screens, so the `or 0.0` there can never fire. That triage is the point -- the
detector narrows 40k lines to a page.

Validate before trusting: `--self-test` asserts D1 still finds the known instance it was
built from (visual_fidelity's `_best_by_screen` update, which records an unphotographed
screen as 0.0). A detector that stops finding its own seed case has drifted.

    python scripts/defect_shapes.py [--self-test]
"""
import ast, pathlib, sys, re

ROOT = pathlib.Path('agent/env_generator')
MEASURED = re.compile(r'similarity|score|budget|left|elapsed|count|total|duration|'
                      r'rate|pct|percent|avg|median|size|bytes|judg|spent|usd|rows?$', re.I)

def d1(path, tree, src):
    """D1: 未测量被读成零 —— float/int(X.get(<度量名>) or 0)"""
    hits=[]
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and getattr(n.func,'id',None) in ('float','int')): continue
        if not n.args or not isinstance(n.args[0], ast.BoolOp) or not isinstance(n.args[0].op, ast.Or):
            continue
        vals=n.args[0].values
        if len(vals)!=2: continue
        tail=vals[1]
        if not (isinstance(tail, ast.Constant) and tail.value in (0,0.0,)): continue
        # 左侧是否取了一个"度量"名
        key=None
        for c in ast.walk(vals[0]):
            if isinstance(c, ast.Constant) and isinstance(c.value,str) and MEASURED.search(c.value):
                key=c.value
            if isinstance(c, ast.Attribute) and MEASURED.search(c.attr): key=c.attr
        if key: hits.append((n.lineno, key, src.splitlines()[n.lineno-1].strip()[:110]))
    return hits

def d3(path, tree, src):
    """D3: 记录失败却不带原因 —— evidence=/metadata= 字面量无 reason 字段, 而作用域里有原因变量"""
    REASON=re.compile(r'detail|reason|error|stderr|stdout|message|traceback|tail|summary',re.I)
    hits=[]
    for fn in [n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]:
        names={t.id for x in ast.walk(fn) if isinstance(x,ast.Name) for t in [x] if REASON.search(x.id)}
        names |= {c.value for c in ast.walk(fn) if isinstance(c,ast.Constant)
                  and isinstance(c.value,str) and REASON.fullmatch(c.value or '')}
        if not names: continue
        for call in [c for c in ast.walk(fn) if isinstance(c,ast.Call)]:
            for kw in call.keywords or []:
                if kw.arg not in ('evidence','metadata','details','payload'): continue
                if not isinstance(kw.value, ast.Dict): continue
                keys={k.value for k in kw.value.keys if isinstance(k,ast.Constant)}
                if any(REASON.search(str(k)) for k in keys): continue
                fname=getattr(call.func,'attr',None) or getattr(call.func,'id','?')
                hits.append((call.lineno, f"{fname}({kw.arg}=...)",
                             f"作用域内有 {sorted(names)[:3]}", sorted(keys)))
    return hits

SELFTEST = "--self-test" in sys.argv
_seed_seen = False

tot={'d1':0,'d3':0}
for p in sorted(ROOT.rglob('*.py')):
    try: src=p.read_text(errors='ignore'); tree=ast.parse(src)
    except Exception: continue
    for name,fn in (('d1',d1),('d3',d3)):
        for h in fn(p,tree,src):
            tot[name]+=1
            if name=='d1' and p.name=='visual_fidelity.py' and '_best_by_screen' in src \
                    and 'similarity' in str(h[1]) and '_sim' in h[2]:
                _seed_seen = True
            if SELFTEST: continue
            print(f"[{name.upper()}] {p.relative_to(ROOT)}:{h[0]}  {h[1]}")
            if name=='d1': print(f"        {h[2]}")
            else: print(f"        {h[2]}  keys={h[3]}")
if SELFTEST:
    assert _seed_seen, ("D1 no longer finds the instance it was built from "
                        "(visual_fidelity `_sim = float(_s.get(\"similarity\") or 0.0)`) — "
                        "the detector has drifted, fix it before trusting a clean run")
    print(f"self-test OK — D1 still finds its seed case; D1={tot['d1']} D3={tot['d3']} candidates")
else:
    print(f"\n合计 D1={tot['d1']}  D3={tot['d3']}  (候选, 每条都要读周边守卫)")
