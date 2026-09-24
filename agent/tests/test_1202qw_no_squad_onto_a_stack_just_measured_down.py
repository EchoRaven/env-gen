r"""#1202qw: the squad is not launched onto a stack the framework just measured as down.

tiktok-r128, three log lines two seconds apart:

    17:25:34 [W] Framework validation attempt 1/6: api_smoke NOT passing - FAILED: backend_health
    17:25:36 [W] TEST-USER SQUAD launched in BACKGROUND (single-flight, 0s deferred) -
                 deferring this delivery tick
    17:26:39 [W] [test-user squad] env_unavailable: ui=...:8009 up, api=...:8008 DOWN

The delivery gate was GREEN at 17:25:36 -- `logs/delivery_gate.jsonl` records 0 failed checks
there, the third of only three green evaluations in the whole run. That window was spent on a
squad that could not reach the app, and the gate never came back: the run aborted at 17:55 with
"delivery never SUCCEEDED in 77min of lane time".

The gate's own comment asserts the premise that failed -- "the app is up (api_smoke booted it;
the visual gate just shot it)". Two seconds earlier the framework had measured the opposite and
written it down. This reads that measurement.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import framework_validation as FV  # noqa: E402
from multi_agent.runtime.test_user_squad import (  # noqa: E402
    STACK_VERDICT_TTL_1202QW, squad_launch_held_1202qw)

NOW = 1_000_000.0


def test_the_r128_case_holds_the_launch():
    """Two seconds after `api_smoke NOT passing - FAILED: backend_health`."""
    held = squad_launch_held_1202qw((NOW - 2, ("backend_health",)), NOW)
    assert held and "backend_health" in held


def test_a_serving_stack_launches():
    assert squad_launch_held_1202qw((NOW - 2, ()), NOW) == ""


def test_no_verdict_at_all_launches():
    """Before the first validation there is nothing to consult -- never a reason to hold."""
    assert squad_launch_held_1202qw(None, NOW) == ""


def test_a_stale_verdict_launches():
    """A stack that came back while nothing re-validated must not be held down by an old read."""
    old = NOW - STACK_VERDICT_TTL_1202QW - 1
    assert squad_launch_held_1202qw((old, ("backend_health",)), NOW) == ""


def test_a_verdict_from_the_future_launches():
    """Clock skew is not evidence of a dead stack."""
    assert squad_launch_held_1202qw((NOW + 60, ("docker_up",)), NOW) == ""


def test_an_app_level_failure_does_not_hold_the_launch():
    """business_chain failing is exactly what the squad is FOR. Only stack checks hold it."""
    class _Orch:
        pass
    o = _Orch()
    FV._note_stack_verdict_1202qw(o, ["business_chain", "deliverability_ui_flow_failed"])
    assert o._stack_verdict_1202qw[1] == ()
    assert squad_launch_held_1202qw(o._stack_verdict_1202qw, o._stack_verdict_1202qw[0]) == ""


def test_the_stamp_keeps_only_stack_checks():
    class _Orch:
        pass
    o = _Orch()
    FV._note_stack_verdict_1202qw(o, ["backend_health", "business_chain", "docker_up"])
    assert sorted(o._stack_verdict_1202qw[1]) == ["backend_health", "docker_up"]


def test_the_stamp_never_raises_on_a_hostile_orchestrator():
    class _NoSet:
        __slots__ = ()
    FV._note_stack_verdict_1202qw(_NoSet(), ["backend_health"])   # must not raise


def test_the_guard_is_reachable_from_the_delivery_tick():
    """#1202 ratchet: a guard nothing calls guards nothing. Anchor on the launch branch."""
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
           / "orchestrator.py").read_text(encoding="utf-8")
    launch = src.index('if _tu_action == "launch":')
    create = src.index("self._tu_squad_task = asyncio.create_task(", launch)
    between = src[launch:create]
    assert "squad_launch_held_1202qw(" in between
    assert "return" in between
