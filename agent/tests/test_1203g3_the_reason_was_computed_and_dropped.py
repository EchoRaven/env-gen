"""#1203g3 — the re-wake named the task ids and dropped the reason the gate had computed.

`incomplete_required_tasks` returns, per open task, one of exactly three reasons from its three
branches:

    implement_endpoint   -> "endpoint not implemented in registry and no passing contract-test
                             record"
    implement_table      -> "table not implemented in registry"
    validate_api_smoke   -> "endpoint has no passing contract-test record"

The bespoke re-wake read `id` and `assignee` only, and offered one parenthetical instead:
"(verifier: re-run run_validation to record the missing per-endpoint contract tests)" -- right
for ONE of the three kinds, and sent to every assignee.

Replayed over every run directory with the real function: 9 runs end with required tasks still
open, 123 of them. 66 are `implement_endpoint` and 15 are `implement_table`, both assigned to
BACKEND -- 81 of 123, 66% -- and re-running run_validation clears neither. The 42
`validate_api_smoke` tasks go to the verifier, and for those the old hint was correct.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    incomplete_task_reasons_1203g3 as reasons)

_EP = {"id": "impl.endpoint.post._api_videos", "kind": "implement_endpoint",
       "assignee": "backend", "status": "pending",
       "reason": "endpoint not implemented in registry and no passing contract-test record"}
_TBL = {"id": "impl.table.videos", "kind": "implement_table", "assignee": "backend",
        "status": "pending", "reason": "table not implemented in registry"}
_SMOKE = {"id": "validate.api_smoke.get._api_feed", "kind": "validate_api_smoke",
          "assignee": "verifier", "status": "in_progress",
          "reason": "endpoint has no passing contract-test record"}


def test_each_task_carries_its_own_reason():
    out = reasons([_EP, _TBL, _SMOKE])
    assert "WHY EACH IS STILL OPEN" in out
    for t in (_EP, _TBL, _SMOKE):
        assert t["id"] in out
        assert t["reason"] in out


def test_the_action_matches_the_kind_not_the_verifier_default():
    """The whole defect: a backend task used to be handed the verifier's instruction."""
    out = reasons([_EP, _TBL])
    assert "registryhub_register_endpoint" in out
    assert "registryhub_register_table" in out
    assert "run_validation" not in out, out


def test_the_verifier_kind_still_gets_run_validation():
    out = reasons([_SMOKE])
    assert "re-run run_validation" in out
    assert "registryhub_register_endpoint" not in out


def test_each_kind_is_explained_once_even_with_many_tasks():
    out = reasons([dict(_EP, id="impl.endpoint.%d" % i) for i in range(5)])
    assert out.count("write the route handler") == 1


def test_a_long_list_is_cut_and_says_so():
    """#1034: declare the cut. r104 ends with 51 open required tasks."""
    out = reasons([dict(_EP, id="impl.endpoint.%d" % i) for i in range(12)])
    assert out.count("\n- impl.endpoint.") == 8
    assert "(+4 more with the same shape)" in out


@pytest.mark.parametrize("tasks", [
    [], None, [{"id": "x"}], [{"id": "x", "reason": ""}], ["not a dict"], [None],
])
def test_it_is_silent_without_reasons(tasks):
    """An older payload with no `reason` keeps the previous text rather than printing a header
    over nothing."""
    assert reasons(tasks) == ""


def test_an_unknown_kind_still_gets_its_reason():
    """Forward-compatible: a future structural kind has no action line yet, but its reason is
    still the most useful sentence available."""
    out = reasons([{"id": "impl.widget.x", "kind": "implement_widget",
                    "reason": "widget not registered"}])
    assert "widget not registered" in out
    assert "WHAT CLEARS EACH KIND" not in out


def test_it_never_raises():
    """`... == "" or True` was the first version of this assertion, which is no assertion at
    all. What matters is that a hostile value cannot propagate out of the remediation path and
    that the return is always a string."""
    class _Bad:
        def __str__(self):
            raise ValueError("nope")
    out = reasons([{"id": _Bad(), "kind": "implement_table",
                    "reason": "table not implemented in registry"}])
    assert isinstance(out, str)


# --------------------------------------------------------------------- wiring, over the AST

def test_the_rewake_composes_the_reasons():
    """#1178 is the standing lesson that a perfect helper can be unreachable. Anchored on the
    re-wake's own message construction, over the AST."""
    import ast
    src = inspect.getsource(rd)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "incomplete_task_reasons_1203g3"]
    assert len(calls) == 1, "exactly one call site"
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(c is calls[0] for c in ast.walk(n))]
    assert assigns, "the result must be assigned"
    name = assigns[0].targets[0]
    assert isinstance(name, ast.Name)
    # ★ and the name must be READ inside the message's `content=`, not merely assigned nearby.
    # A first version asserted `name.id in block` over the source text, and deleting the USE
    # from the f-string left it GREEN because the assignment line still mentions it: a name
    # appearing is not a name being used.
    msgs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_create_message"]
    used = False
    for m in msgs:
        for kw in m.keywords:
            if kw.arg != "content":
                continue
            names = {x.id for x in ast.walk(kw.value) if isinstance(x, ast.Name)}
            if name.id in names and any(
                    isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and "unfinished required task(s)" in c.value
                    for c in ast.walk(kw.value)):
                used = True
    assert used, (
        "%s is assigned but never read inside the re-wake message's content" % name.id)


def test_the_old_blanket_verifier_hint_is_gone_from_that_block():
    src = inspect.getsource(rd)
    i = src.index('if "incomplete_required_tasks" in failed_checks:')
    j = src.index("# #1041:", i)
    block = src[i:j]
    assert "re-run run_validation to record the missing per-endpoint" not in block


# ------------------------------------------------------- replay against the real function

def test_the_three_reasons_are_the_ones_the_gate_produces():
    """The action table must key off the gate's OWN kinds. If a fourth branch is ever added,
    this goes red rather than silently omitting its action."""
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg.incomplete_required_tasks)
    import re
    kinds = set(re.findall(r'kind == "([a-z_]+)"', src))
    assert kinds == set(rd._INCOMPLETE_TASK_ACTION_1203G3), (
        kinds, set(rd._INCOMPLETE_TASK_ACTION_1203G3))
