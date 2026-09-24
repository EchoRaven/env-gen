r"""#1202ra: a walk is not discarded for a teardown that happened after it finished.

#1202ne compares the stack's containers before and after the walk and throws the verdict away
when they differ -- right, when the recycle happened UNDER the walk. The "after" sample was
taken outside the lease `_walk()` holds, so a teardown in the gap between the walk returning and
the sample being read discards a walk that ran start to finish on a live stack.

tiktok-r129, 20:52: the walk completed, `validation_runner` ran `down -v` at 20:52:29, and the
sample at 20:52:32 read `3 -> 0 running`. The framework logged "this walk's verdict is
discarded, not dispatched" about a walk nothing had interfered with, and the release waited
another pass.

The lease (#1202nx) is a token set rather than a mutex, so nesting one around the whole
before/walk/after sequence costs nothing and closes the gap.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import compose_mutex as CM  # noqa: E402

HP_SRC = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
          / "heal_pipeline.py").read_text(encoding="utf-8")


def _verdict_block() -> str:
    i = HP_SRC.index("#1202ra: hold the lease ACROSS")
    return HP_SRC[i:HP_SRC.index("if not report.get(\"ran\"):", i)]


def test_the_lease_is_nestable():
    """The premise: two holders on the same project coexist, so wrapping the walk is free."""
    proj = "/tmp/_1202ra_project"
    with CM.stack_lease_1202nx(proj, "outer"):
        with CM.stack_lease_1202nx(proj, "inner"):
            assert sorted(CM.active_stack_leases_1202nx(proj)) == ["inner", "outer"]
        assert CM.active_stack_leases_1202nx(proj) == ["outer"]
    assert CM.active_stack_leases_1202nx(proj) == []


def test_both_samples_sit_inside_the_lease():
    """Parse it: a `with` whose body holds the before-sample, the walk and the after-sample."""
    block = _verdict_block()
    tree = ast.parse("if True:\n" + "\n".join("    " + ln for ln in block.splitlines()))
    withs = [n for n in ast.walk(tree) if isinstance(n, ast.With)]
    assert withs, "the verdict sequence is not under a lease at all"
    guarded = []
    for w in withs:
        body = ast.unparse(w)
        if body.count("stack_identity_1202ne(compose)") == 2 and "_walk()" in body:
            guarded.append(w)
    assert guarded, "before-sample, walk and after-sample must share one lease block"


def test_the_re_walk_is_guarded_too():
    """The second walk has the same gap; #1202ne walks twice before giving up."""
    block = _verdict_block()
    assert block.count("_lease_1202ra(proj,") == 2


def test_no_sample_is_taken_outside_a_lease():
    block = _verdict_block()
    tree = ast.parse("if True:\n" + "\n".join("    " + ln for ln in block.splitlines()))

    inside = set()
    for w in (n for n in ast.walk(tree) if isinstance(n, ast.With)):
        for n in ast.walk(w):
            inside.add(id(n))
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        if getattr(call.func, "id", "") != "stack_identity_1202ne":
            continue
        assert id(call) in inside, "a stack sample outside the lease reopens the r129 gap"
