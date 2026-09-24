r"""#1202qx: a tick whose own repairs cleared the gate delivers in that tick -- if the stack is up.

tiktok-r128:

    17:20:29 [W] Framework deliver declined: delivery gate has 1 failed check(s):
                 ['verification_checklist_not_ready']
    17:20:29 [W] STALE BUILD-CHECKLIST record-the-truth (#511): a gate-passing api_smoke run
                 exists -> directly re-recorded 2 stale build/validation check(s) = success
    17:20:31      logs/delivery_gate.jsonl: 0 failed checks

The decline branch of `_maybe_framework_deliver` IS the repair branch: #511 re-records a stale
build checklist, #475 re-runs never-run chains, #240 authors ui_flow evidence, #74 re-emits the
schema SQL. Each can clear the very check that sent the tick there -- and the tick then returned
on the verdict it was handed before any of them ran.

r128's next delivery tick went to the test-user squad (#1202qw), the gate never came back, and
the run aborted at 17:55 with "delivery never SUCCEEDED in 77min of lane time".

A cleared gate is not permission to ship, though, and r128 is also the counter-example: that
17:20:31 green rested on an api_smoke pass from 17:01:05 -- the only one in the whole run -- and
the next measurement, 17:25:34, found `backend_health` failing. #511 re-records build truth from
a run that may be minutes old, which is the very evidence this branch just repaired. So the
fall-through also demands that a validation RECENTLY watched the stack answer.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SRC = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
       / "orchestrator.py").read_text(encoding="utf-8")


def _declined_branch() -> str:
    """The body of `if gate.get("failed_checks"):` inside _maybe_framework_deliver."""
    m = SRC.index("async def _maybe_framework_deliver(")
    start = SRC.index('if gate.get("failed_checks"):', m)
    end = SRC.index("# PAGE-BUILD BLOCKING", start)
    return SRC[start:end]


def test_the_branch_re_asks_the_gate_before_giving_up():
    body = _declined_branch()
    assert "_gate1202qx = self._validate_delivery_gate()" in body


def test_the_re_ask_comes_after_the_repairs():
    """Re-asking before the repairs would read the same verdict that sent the tick here."""
    body = _declined_branch()
    reask = body.index("_gate1202qx = self._validate_delivery_gate()")
    for repair in ("maybe_refresh_stale_build_checklist",   # #511's caller
                   "maybe_rerun_unrun_chains",              # #475
                   "maybe_author_ui_flow_evidence",         # #240
                   "maybe_emit_schema_sql"):                # #74
        assert body.index(repair) < reask, repair


def test_a_gate_that_is_still_red_still_returns():
    body = _declined_branch()
    reask = body.index("_gate1202qx = self._validate_delivery_gate()")
    tail = body[reask:]
    # #1202tk inserted a one-line hold-note between the test and its `return`, so the
    # anchor allows it. The property is unchanged: a still-red gate must RETURN, not fall
    # through to the release path.
    assert re.search(
        r'if _gate1202qx\.get\("failed_checks"\):'
        r'(?:\n[^\n]*_note_delivery_hold_1202tk[^\n]*)?\s*\n\s*return', tail)


def test_a_cleared_gate_falls_through_to_the_release_path():
    """Exactly two exits after the re-ask: still-red, and green-but-no-fresh-liveness."""
    body = _declined_branch()
    after_clear = body[body.index('if _gate1202qx.get("failed_checks"):'):]
    assert len(re.findall(r"^\s+return\b", after_clear, re.M)) == 2
    assert "gate = _gate1202qx" in after_clear


def test_the_declined_branch_is_the_repair_branch():
    """Pins the premise: if the repairs ever move out, this test fails rather than the fix
    silently becoming a no-op."""
    body = _declined_branch()
    assert body.count("self._validate_delivery_gate()") == 1


# --- the liveness precondition -----------------------------------------------------------

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _note_stack_verdict_1202qw, stack_known_serving_1202qx)

NOW = 1_000_000.0


def test_a_fresh_clean_verdict_is_serving():
    assert stack_known_serving_1202qx((NOW - 5, ()), NOW) is True


def test_the_r128_green_is_not_serving():
    """19 minutes since anything watched the stack answer."""
    assert stack_known_serving_1202qx((NOW - 19 * 60, ()), NOW, ttl=300.0) is False


def test_a_fresh_verdict_that_named_a_stack_check_is_not_serving():
    assert stack_known_serving_1202qx((NOW - 5, ("backend_health",)), NOW) is False


def test_no_verdict_is_not_serving():
    """Absence of evidence is not evidence -- the conservative direction here."""
    assert stack_known_serving_1202qx(None, NOW) is False


def test_the_two_readers_agree_on_the_stamp_shape():
    """#1202qw and #1202qx read the SAME tuple; a change to one must not silently skew it."""
    from multi_agent.runtime.test_user_squad import squad_launch_held_1202qw

    class _O:
        pass
    o = _O()
    _note_stack_verdict_1202qw(o, ["backend_health"])
    when = o._stack_verdict_1202qw[0]
    assert squad_launch_held_1202qw(o._stack_verdict_1202qw, when) != ""
    assert stack_known_serving_1202qx(o._stack_verdict_1202qw, when) is False
    _note_stack_verdict_1202qw(o, [])
    when = o._stack_verdict_1202qw[0]
    assert squad_launch_held_1202qw(o._stack_verdict_1202qw, when) == ""
    assert stack_known_serving_1202qx(o._stack_verdict_1202qw, when) is True


def test_the_fall_through_demands_the_liveness_check():
    body = _declined_branch()
    reask = body.index("_gate1202qx = self._validate_delivery_gate()")
    tail = body[reask:]
    assert "stack_known_serving_1202qx(" in tail
    assert tail.index("stack_known_serving_1202qx(") < tail.index("gate = _gate1202qx")
