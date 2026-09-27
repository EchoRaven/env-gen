"""#1202vx: the framework's explanation must not spend the lane's budget for evidence.

`dispatch_failing_checks` classified a failing endpoint check and PREPENDED its conclusion to
`detail` -- #1006's "FRAMEWORK DEFECT — main.py ALREADY MOUNTS these routes..." and #1202vq's
"THE APP DID NOT ANSWER these..." -- and only afterwards ran

    detail = _salient_error(detail, cap=600) or detail

So the framework's own prose competed with the real failures for 600 characters, from the
front, and won. Measured on a realistic detail (6 endpoints, each with its `custom_routes.py`
traceback, 520 chars):

    prepend-then-trim, #1006 prose only     4 of 6 fragments survive
    prepend-then-trim, both notices         1 of 6
    trim-then-prepend                       6 of 6

#978 is the reason this is a defect and not a trade-off: that trim exists to "hand the LANE
the salient line, not a blind prefix". Spending the salient line on a lecture is the defect
it was written to end.

The classification still reads the WHOLE detail -- a fragment trimmed away could not be
classified -- and only its prose waits.
"""
import ast
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import remediation_dispatcher as RD          # noqa: E402
from multi_agent.runtime.framework_validation import _salient_error   # noqa: E402


def _dispatch_fn():
    tree = ast.parse(inspect.getsource(RD))
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "unreachable_but_mounted" in ast.unparse(n))


def _lines_of(fn, predicate):
    return sorted(n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and predicate(ast.unparse(n)))


def test_the_notices_are_collected_before_the_trim_and_applied_after():
    """Order by AST line numbers, not a source window (#943)."""
    fn = _dispatch_fn()
    appends = _lines_of(fn, lambda s: s.startswith("_notices_1202vx.append"))
    trims = _lines_of(fn, lambda s: "_salient_978(" in s)
    joins = _lines_of(fn, lambda s: "join(_notices_1202vx" in s)

    assert appends, "no notice is collected — the classification prose went somewhere else"
    assert len(trims) == 1, f"expected one salient trim, found {len(trims)}"
    assert len(joins) == 1, "the collected notices must be applied exactly once"
    assert max(appends) < trims[0], (
        "the classification must read the WHOLE detail, so it stays before the trim")
    assert joins[0] > trims[0], (
        "the prose must be applied AFTER the trim, or it spends the evidence's budget")


def test_no_notice_prose_is_assigned_into_detail_before_the_trim():
    """The actual regression guard: an assignment to `detail` that carries the prose, sitting
    before the trim, is the old bug whatever it is named."""
    fn = _dispatch_fn()
    trim_line = _lines_of(fn, lambda s: "_salient_978(" in s)[0]
    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or node.lineno >= trim_line:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "detail" for t in node.targets):
            continue
        src = ast.unparse(node.value)
        if "FRAMEWORK DEFECT" in src or "DID NOT ANSWER" in src:
            offenders.append(node.lineno)
    assert not offenders, (
        f"prose is prepended to `detail` at line(s) {offenders}, before the cap at "
        f"{trim_line} — it will outbid the failures for the budget")


def test_the_lane_still_receives_both_the_prose_and_the_failures():
    """The prose must not be dropped either — #1006/#1202vq exist because a lane that does
    not know WHY it is being refused builds the wrong thing."""
    fn = _dispatch_fn()
    body = ast.unparse(fn)
    assert "FRAMEWORK DEFECT" in body and "DID NOT ANSWER" in body
    assert "writes to it are denied" in body
    assert "Do NOT edit a handler for these" in body


def test_the_ordering_is_what_saves_the_evidence():
    """The measurement, as a test: same trimmer, same strings, both orders."""
    frags = [f"GET /api/r{i} → 500 | backend traceback: custom_routes.py:{100+i} "
             f"in h{i} — KeyError: 'col_{i}'" for i in range(6)]
    raw = "; ".join(frags)
    prose = ("THE APP DID NOT ANSWER these — the request raised at the socket, so none of "
             "them is evidence about your code: GET /api/x → ConnectionResetError: "
             "[Errno 104]. Do NOT edit a handler for these. Check the stack is up and re-run "
             "the validation.")

    old = _salient_error(prose + " || " + raw, cap=600) or raw
    new = " || ".join([prose, _salient_error(raw, cap=600) or raw])

    assert old.count("custom_routes.py") < 6, (
        "the control is supposed to LOSE fragments; if it does not, this fix is unmotivated")
    assert new.count("custom_routes.py") == 6, "every failure must survive the new order"
    assert prose[:30] in new, "and the explanation must still be there"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
