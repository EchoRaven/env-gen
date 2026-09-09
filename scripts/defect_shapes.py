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
        # #self: the first draft matched CamelCase CLASS names (BaseMessage, MessageHeader)
        # as "reason variables" and buried the real hits under constructor calls. A reason
        # variable is lower_snake_case; a class is not.
        names={x.id for x in ast.walk(fn) if isinstance(x,ast.Name)
               and REASON.search(x.id) and x.id.islower()}
        names |= {c.value for c in ast.walk(fn) if isinstance(c,ast.Constant)
                  and isinstance(c.value,str) and REASON.fullmatch(c.value or '')}
        if not names: continue
        for call in [c for c in ast.walk(fn) if isinstance(c,ast.Call)]:
            for kw in call.keywords or []:
                if kw.arg not in ('evidence','metadata','details','payload'): continue
                if not isinstance(kw.value, ast.Dict): continue
                # #self: the reason may ride a SIBLING kwarg (`summary=`, `detail=`) rather
                # than the dict. heal_pipeline's record_validation_result passes both, and
                # flagging it read as a defect where the reason was one argument away.
                if any(REASON.search(k2.arg or "") for k2 in (call.keywords or [])
                       if k2.arg and k2.arg != kw.arg): continue
                keys={k.value for k in kw.value.keys if isinstance(k,ast.Constant)}
                if any(REASON.search(str(k)) for k in keys): continue
                fname=getattr(call.func,'attr',None) or getattr(call.func,'id','?')
                hits.append((call.lineno, f"{fname}({kw.arg}=...)",
                             f"作用域内有 {sorted(names)[:3]}", sorted(keys)))
    return hits

SELFTEST = "--self-test" in sys.argv
_seed_seen = False


_D4_SEED = """
codehub.record_check(pr_id="main", name=n,
                     status="success" if ok else "failure",
                     evidence={"source": "run_validation"}, agent="")
"""


# D5': the highest-yield shape in this tree — two consumers of ONE collection disagreeing
# about an EXCLUSION flag. Every side reads correctly on its own; the defect is the
# disagreement. #1202iq (two call sites of one FK resolver, one consulting the declared map
# and one not), #1202fn/#1202fp (two audits, two different roots), and visual_fidelity's
# `screens` (#619's average excludes `blank`, `_best_by_screen` does not) are all this.
#
# The FIRST version compared every field name two loops touched and produced 117 candidates:
# different loops legitimately read different fields, so field overlap carries no signal. It
# also missed its own seed, because #619 iterates `(screens or [])` — a BoolOp, not a Name.
# Both corrections are in here; a fixed vocabulary of exclusion words is what makes it sharp.
_EXCL_FLAGS_D5 = ('advisory', 'blank', 'deleted', 'skipped', 'stale', 'disabled', 'ignored',
                  'draft', 'archived', 'placeholder', 'transient', 'refunded', 'excluded',
                  'dead', 'pending')


def _excl_flags_d5(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'get' and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and a.value in _EXCL_FLAGS_D5:
                out.add(a.value)
        elif isinstance(n, ast.Subscript) and isinstance(getattr(n, 'slice', None), ast.Constant) \
                and n.slice.value in _EXCL_FLAGS_D5:
            out.add(n.slice.value)
    return out


def d5_groups(tree):
    """{iterated-name: [(lineno, {exclusion flags this loop honours})]}"""
    g = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.For):
            it, body = n.iter, n
        elif isinstance(n, (ast.ListComp, ast.GeneratorExp, ast.SetComp)) and n.generators:
            it, body = n.generators[0].iter, n
        else:
            continue
        it_ = it.values[0] if (isinstance(it, ast.BoolOp) and it.values) else it
        if not isinstance(it_, ast.Name):
            continue
        g.setdefault(it_.id, []).append((n.lineno, _excl_flags_d5(body)))
    return g


def d5(path, tree, src):
    hits = []
    for nm, lst in sorted(d5_groups(tree).items()):
        if len(lst) < 2:
            continue
        for flag in sorted(set().union(*[f for _, f in lst])):
            uses = sorted(ln for ln, f in lst if flag in f)
            miss = sorted(ln for ln, f in lst if flag not in f)
            if uses and miss:
                hits.append((uses[0], f"`{nm}` honours `{flag}` at {uses}",
                             f"and ignores it at {miss[:8]}"))
    return hits


_VERDICTISH = ('status', 'result', 'verdict', 'outcome', 'passed', 'ok')
_EVIDENCEISH = ('evidence', 'metadata', 'details', 'detail', 'payload', 'context')


def d4(path, tree, src):
    """D4: a FAILURE VERDICT recorded with almost no evidence.

    D3 could not find the case that inspired it (#1202iz): the reason was not a local
    variable, it was a field of the collection being read. D4 keys on a different signal --
    `status` DERIVED from a condition (so this call is a verdict, not a transcription) beside
    an evidence literal of at most two keys. A verdict always has a reason; that few keys says
    the reason was not carried.

    Seeded and self-tested: `#1202iz`'s pre-fix line was
    `record_check(status="success" if ok else "failure", evidence={"source": "run_validation"})`
    -- one key, and the failing check's own 1200-character container log one function away.
    """
    hits = []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        kws = {k.arg: k.value for k in (call.keywords or []) if k.arg}
        st = next((kws[k] for k in _VERDICTISH if k in kws), None)
        ev_name = next((k for k in _EVIDENCEISH if k in kws), None)
        if st is None or ev_name is None:
            continue
        if not (isinstance(st, (ast.IfExp, ast.Compare, ast.BoolOp))
                or (isinstance(st, ast.Call)
                    and getattr(st.func, 'id', None) in ('bool', 'str'))):
            continue                      # a literal status is a transcription, not a verdict
        ev = kws[ev_name]
        if not isinstance(ev, ast.Dict) or len(ev.keys) > 2:
            continue
        fname = getattr(call.func, 'attr', None) or getattr(call.func, 'id', '?')
        hits.append((call.lineno, f"{fname}({ev_name}={{{len(ev.keys)} keys}})",
                     [k.value for k in ev.keys if isinstance(k, ast.Constant)]))
    return hits


tot={'d1':0,'d3':0,'d4':0,'d5':0}
for p in sorted(ROOT.rglob('*.py')):
    try: src=p.read_text(errors='ignore'); tree=ast.parse(src)
    except Exception: continue
    for name,fn in (('d1',d1),('d3',d3),('d4',d4),('d5',d5)):
        for h in fn(p,tree,src):
            tot[name]+=1
            if name=='d1' and p.name=='visual_fidelity.py' and '_best_by_screen' in src \
                    and 'similarity' in str(h[1]) and '_sim' in h[2]:
                _seed_seen = True
            if SELFTEST: continue
            print(f"[{name.upper()}] {p.relative_to(ROOT)}:{h[0]}  {h[1]}")
            if name=='d1': print(f"        {h[2]}")
            elif name=='d4': print(f"        keys={h[2]}")
            elif name=='d5': print(f"        {h[2]}")
            else: print(f"        {h[2]}  keys={h[3]}")
if SELFTEST:
    # D4 has no live instance left in this tree (its one case is fixed), so it is seeded on a
    # snippet instead -- a detector with nothing to find must still prove it can find.
    _d4_seed_hits = d4(pathlib.Path("<seed>"), ast.parse(_D4_SEED), _D4_SEED)
    assert _d4_seed_hits, ("D4 no longer flags its own seed "
                           "(record_check with a derived status and a 1-key evidence dict)")
    _vf = ROOT / "llm_generator/multi_agent/runtime/visual_fidelity.py"
    _d5 = d5_groups(ast.parse(_vf.read_text(errors="ignore"))) if _vf.is_file() else {}
    _scr = _d5.get("screens") or []
    assert any("blank" in f for _, f in _scr) and any("blank" not in f for _, f in _scr), (
        "D5' no longer sees visual_fidelity's `screens` split on `blank` (#619's average "
        "excludes it, `_best_by_screen` does not) — its seed case")
    assert _seed_seen, ("D1 no longer finds the instance it was built from "
                        "(visual_fidelity `_sim = float(_s.get(\"similarity\") or 0.0)`) — "
                        "the detector has drifted, fix it before trusting a clean run")
    print(f"self-test OK — D1 finds its seed case, D4 finds its seed snippet; "
          f"D5' sees its screens/blank split; "
          f"D1={tot['d1']} D3={tot['d3']} D4={tot['d4']} D5={tot['d5']} candidates")
else:
    print(f"\n合计 D1={tot['d1']}  D3={tot['d3']}  D4={tot['d4']}  D5={tot['d5']}"
          f"  (候选, 每条都要读周边守卫)")
