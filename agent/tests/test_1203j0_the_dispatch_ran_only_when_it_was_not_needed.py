r"""#1203j0: two non-blocking findings were dispatched only when some OTHER check was red.

#1139 detects a filter no seeded row can satisfy and #1203ie publishes the endpoints whose
`total` their own cursor contradicts. Both deliberately REPORT rather than block, so each can
be present while every check is green — which is exactly when a run delivers. #1148's own
comment says so: netflix-local-r8 DELIVERED with one, "so it has to reach the backend EVEN
WHEN EVERY CHECK IS GREEN". Both dispatches were then written inside

    if gate.get("failed_checks"):

which runs only when some check is red.

Measured over the 12633 gate records on this machine:

    never_matching_filters     non-empty with a GREEN gate:  67 records across 7 runs
    list_totals_unreachable    non-empty with a GREEN gate:  67 records across 3 runs

tiktok-web-r183 is in the first group and DELIVERED carrying `media_url IS NOT NULL` with no
seeded row; its workhub holds 501 tasks and none of them is "Seed a column the queries filter
on", because that line never ran. The second group is r185/r186/r187 — #1203ii inherited the
bug it was written to avoid, because I copied the call site together with its gate.

Hoisting is safe by the delivery gate's own rule, and `test_an_adhoc_task_does_not_block_
delivery` holds that rule rather than quoting it: `incomplete_required_tasks` counts only
"structural kickoff kinds" and says ad-hoc remediation tasks "are deliberately excluded here
so this gate never double-blocks them".
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch_mod
from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

SRC = inspect.getsource(orch_mod)
CALLS = ("dispatch_never_matching_filters_1148", "dispatch_list_totals_unreachable_1203ii")


def _deliver_fn():
    for n in ast.walk(ast.parse(SRC)):
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "_maybe_framework_deliver"):
            return n
    raise AssertionError("_maybe_framework_deliver is gone")


def _call_nodes(name):
    out = []
    for n in ast.walk(_deliver_fn()):
        if isinstance(n, ast.Call) and name in ast.unparse(n):
            out.append(n)
    return out


def _enclosing_ifs(target_lineno):
    chain = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            lo = getattr(child, "lineno", None)
            hi = getattr(child, "end_lineno", None)
            if lo and hi and lo <= target_lineno <= hi:
                chain.append(child)
                walk(child)

    walk(_deliver_fn())
    return [ast.unparse(c.test) for c in chain if isinstance(c, ast.If)]


# --- the property this ticket is ---------------------------------------------------------------

@pytest.mark.parametrize("name", CALLS)
def test_the_dispatch_is_still_made(name):
    """Non-vacuity: everything below is empty if the call is gone."""
    assert _call_nodes(name), name


@pytest.mark.parametrize("name", CALLS)
def test_no_failed_check_gate_stands_between_the_finding_and_its_task(name):
    """The whole ticket. A green gate is when these findings matter most."""
    for call in _call_nodes(name):
        for cond in _enclosing_ifs(call.lineno):
            assert "failed_checks" not in cond, (name, cond)


@pytest.mark.parametrize("name", CALLS)
def test_the_dispatch_is_unconditional_in_the_deliver_path(name):
    """Not merely free of THAT condition — free of any condition, so a future branch cannot
    re-acquire one by accident."""
    for call in _call_nodes(name):
        assert _enclosing_ifs(call.lineno) == [], (name, _enclosing_ifs(call.lineno))


@pytest.mark.parametrize("name", CALLS)
def test_each_dispatch_keeps_its_own_try(name):
    """#1201: one dispatch failing must not swallow the other.

    The INNERMOST try, not any enclosing one. A first version walked every `Try` containing
    the call and so picked up the function-wide try that wraps the whole deliver path — which
    contains both dispatches by construction, and reported them as sharing one.
    """
    call = _call_nodes(name)[0]
    enclosing = [n for n in ast.walk(_deliver_fn())
                 if isinstance(n, ast.Try)
                 and n.lineno <= call.lineno <= (n.end_lineno or n.lineno)]
    assert enclosing, name
    innermost = min(enclosing, key=lambda n: (n.end_lineno or n.lineno) - n.lineno)
    other = [c for c in CALLS if c != name][0]
    body = ast.unparse(ast.Module(body=list(innermost.body), type_ignores=[]))
    assert name in body, (name, body[:120])
    assert other not in body, "both dispatches share one try"


# --- the guarantee this fix rests on ------------------------------------------------------------

def test_an_adhoc_task_does_not_block_delivery():
    """★ MY SAFETY ARGUMENT, HELD RATHER THAN QUOTED.

    Filing a P0 at a green gate is only safe because `incomplete_required_tasks` counts
    "structural kickoff kinds" and excludes ad-hoc remediation. If that ever changes, this
    ticket turns a report into a block — so the rule is exercised here, not cited.
    """
    class _WorkHub:
        def list_tasks(self):
            return [{"id": "task_deadbeef", "title": "Seed a column the queries filter on",
                     "status": "pending", "assignee": "backend", "priority": "P0"}]

    class _Hubs:
        workhub = _WorkHub()
        registryhub = None
        schema_hub = None

    assert dg.incomplete_required_tasks(_Hubs()) == []


def test_the_structural_kinds_are_still_the_ones_it_counts():
    """The same rule from the other side: a kickoff kind with no evidence still blocks, so
    the test above is not passing because the function returns [] for everything."""
    doc = inspect.getdoc(dg.incomplete_required_tasks) or ""
    for kind in ("implement_endpoint", "implement_table", "validate_api_smoke"):
        assert kind in doc, kind


# --- the re-fire guards that make "every tick" safe ----------------------------------------------

@pytest.mark.parametrize("attr", ["_nmf1148_dispatched", "_ltu1203ii_dispatched"])
def test_the_per_milestone_refire_guard_survives(attr):
    """Running on every tick is only safe while each dispatcher refuses to re-file within a
    milestone."""
    src = inspect.getsource(rd)
    assert ("getattr(orch, \"%s\"" % attr) in src or ("getattr(orch, '%s'" % attr) in src, attr
    assert ("orch.%s = milestone" % attr) in src, attr


# --- provenance -----------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "67 records, 7 runs" in flat
    assert "67 records, 3 runs" in flat


def test_the_run_that_delivered_with_it_is_named():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "tiktok-web-r183" in flat
    assert "501 tasks" in flat


def test_my_own_ticket_is_named_as_having_inherited_it():
    """#1203ii copied the call site together with its gate; saying so is the point."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "inherited the bug it was written to avoid" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
