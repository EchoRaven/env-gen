"""FIX #117 — deliver_project defers while the FINAL milestone's visual gate is
actively deferring (run-32, 2026-07-08 17:22, archived SUCCESS artifact autopsy).

run-32's M3 (final) visual gate was mid-deferral — 1406s deferred / 7 judged, scores
0.1-0.4 vs the 0.65 threshold, escape at 3600s NOT yet due — when the orchestrator
LLM called deliver_project during a coordination tick (its objective gate report is
all-green: the visual gate is not one of its checks). deliver_project set
``_project_delivered_event`` → the coordination loop's while-condition broke → all
lanes were TERMINATED → the post-loop path ran the objective gate and cut v1.2.0.
The visual deferral (#112/#112b's whole point: give the lane time to converge) only
guarded the ``_maybe_framework_deliver`` path; the deliver_project tool was an
unguarded second exit that cut the window short at 1406s.

Fix: the orchestrator runtime stamps ``_visual_defer_check`` (a bound method) onto
the orchestrator agent alongside ``_is_final_milestone``; deliver_project consults it
after the existing guards and REJECTS (run keeps converging, same pattern as GUARD
1/2) while the check says the visual deferral is active. The check itself returns
False the moment the gate passes OR the bounded escape fires — deferral stays
bounded, nothing can deadlock. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.agent_interaction_tools import DeliverProjectTool  # noqa: E402


class _Agent:
    _is_final_milestone = True
    _hubs = None                      # GUARD 2 (live gate) short-circuits on None


def _call(agent):
    tool = DeliverProjectTool(agent=agent)
    return tool.execute(
        confirmation="CONFIRMED", delivery_summary="done",
        checklist={"no_bugs": True, "requirements_met": True,
                   "fully_functional": True, "docker_ok": True})


def test_deliver_rejected_while_visual_defer_active():
    a = _Agent()
    a._visual_defer_check = lambda: True
    res = _call(a)
    assert not res.success
    assert "visual" in (res.error_message or "").lower()


def test_deliver_allowed_when_defer_inactive_or_check_absent():
    a = _Agent()
    a._visual_defer_check = lambda: False
    assert _call(a).success
    b = _Agent()                       # no attribute at all → back-compat allow
    assert _call(b).success


def test_deliver_allowed_when_check_raises():
    a = _Agent()
    def _boom():
        raise RuntimeError("gate exploded")
    a._visual_defer_check = _boom
    assert _call(a).success            # never block delivery on a broken check


def test_orchestrator_defer_active_predicate():
    """the stamped predicate: True mid-deferral, False on pass / escape / no refs."""
    from multi_agent.orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)   # no __init__: predicate is getattr-pure
    gate = types.SimpleNamespace(passed=False, deferred_since=time.time() - 60,
                                 attempts=1, total_judgments=2)
    o._reference_images = ["ref.png"]
    o._is_final_milestone = True
    o.__dict__["_vf_gate_instance"] = gate   # _vf_gate is a lazy property
    assert o._visual_delivery_defer_active() is True
    gate.passed = True
    assert o._visual_delivery_defer_active() is False
    gate.passed = False
    gate.deferred_since = time.time() - 999_999      # far past any escape window
    assert o._visual_delivery_defer_active() is False
    o._reference_images = None                       # no refs → gate not in play
    gate.deferred_since = time.time() - 60
    assert o._visual_delivery_defer_active() is False
    o._reference_images = ["ref.png"]
    o._is_final_milestone = False                    # only the FINAL milestone blocks
    assert o._visual_delivery_defer_active() is False


def test_orchestrator_stamps_check_alongside_final_milestone_flag():
    import inspect
    from multi_agent import orchestrator as om
    src = inspect.getsource(om)
    # both milestone stamp sites carry the visual-defer check
    assert src.count("_visual_defer_check = self._visual_delivery_defer_active") >= 2


def test_fix123_stamp_helper_restamps_fresh_agent():
    """FIX #123 (run-42, live): _respawn_core_lanes creates FRESH agent instances at
    milestone 2+, losing every stamp — the new orchestrator agent defaulted to
    _is_final_milestone=True with NO _visual_defer_check, and deliver_project sailed
    through mid-visual-window (1397s/3600s: the exact bypass #117 closes). The stamp
    is now a helper called at the iteration top AND right after every respawn."""
    from multi_agent.orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o._is_final_milestone = True

    class _A:                                   # a fresh, unstamped agent instance
        pass
    o._agents = {"orchestrator": _A()}
    o._stamp_milestone_flags_on_orch_agent(3, 3)
    a = o._agents["orchestrator"]
    assert a._is_final_milestone is True
    assert a._milestone_progress == (3, 3)
    assert callable(a._visual_defer_check)
    # missing agent → no-op, never raises
    o._agents = {}
    o._stamp_milestone_flags_on_orch_agent(1, 3)


def test_fix123_restamp_wired_after_respawn():
    import re
    from multi_agent import orchestrator as om
    src = open(om.__file__, encoding="utf-8").read()
    # the re-stamp must appear AFTER the respawn call in source order
    respawn = src.index("await self._respawn_core_lanes()")
    restamp = src.index("_stamp_milestone_flags_on_orch_agent", respawn)
    assert restamp - respawn < 500              # immediately after, same block
