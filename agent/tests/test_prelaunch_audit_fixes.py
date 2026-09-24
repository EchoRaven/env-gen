"""PRE-LAUNCH AUDIT fixes (B1 + F1/F5 + R1 + R2 + BUG-1).

B1: the coordination loop breaks on _project_delivered_event (which the LLM's
    deliver_project sets, flagging only the LANE — it does NOT cut a release); the sole
    create_release caller (_maybe_framework_deliver) is below the break. Fix: call
    _maybe_framework_deliver() on the break path (idempotent on the ORCHESTRATOR's flag).
F1/F5: orchestrator deliverability_check/run_start/run_validation gate on a STICKY
    validation-ready signal (not just kickoff-finalized) → no polling during impl; the
    sticky latch prevents mid-validation regression.
R1: _handle_task_ready pins _active_phase="implementation" so the validation allowlist binds.
R2: backend table_registered is inbox_only (no heal-loop wakeup amplification), not live.
BUG-1: the backend prompt no longer tells it to codehub_open_pr.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    validation_ready_signal, delivery_phase_reached)


def _hubs(endpoints):
    return SimpleNamespace(registryhub=SimpleNamespace(get_endpoints=lambda: endpoints))


def _biz(status):
    return {"path": "/notes", "status": status}


class F1F5ValidationReadyGate(unittest.TestCase):
    def test_false_during_implementation(self):
        # endpoints exist but not all implemented → NOT validation-ready
        h = _hubs({"e1": _biz("implemented"), "e2": _biz("defined")})
        self.assertFalse(validation_ready_signal(h, SimpleNamespace()))

    def test_true_when_all_implemented(self):
        h = _hubs({"e1": _biz("implemented"), "e2": _biz("implemented")})
        self.assertTrue(validation_ready_signal(h, SimpleNamespace()))

    def test_sticky_no_regression(self):
        # F5: once True, a later 'defined' endpoint must NOT regress the signal
        agent = SimpleNamespace()
        h_ok = _hubs({"e1": _biz("implemented")})
        self.assertTrue(validation_ready_signal(h_ok, agent))  # latches
        h_regress = _hubs({"e1": _biz("implemented"), "e2": _biz("defined")})
        self.assertTrue(validation_ready_signal(h_regress, agent),
                        "latched validation-ready must not regress mid-validation")

    def test_precondition_blocks_during_impl_allows_at_validation(self):
        a_impl = SimpleNamespace(_hubs=_hubs({"e1": _biz("defined")}))
        for tool in ("deliverability_check", "run_start", "run_validation"):
            self.assertIsNotNone(delivery_phase_reached(a_impl, tool, {}),
                                 f"{tool} must be blocked before validation-ready")
        a_val = SimpleNamespace(_hubs=_hubs({"e1": _biz("implemented")}))
        for tool in ("deliverability_check", "run_start", "run_validation"):
            self.assertIsNone(delivery_phase_reached(a_val, tool, {}),
                              f"{tool} must be allowed once validation-ready")

    def test_tooling_defer_uses_validation_ready(self):
        from multi_agent.agents.runtime.step_pipeline import tooling
        src = inspect.getsource(tooling)
        self.assertIn("validation_ready_signal", src)
        # re-review: validation-ready defer is ORCHESTRATOR-scoped; other lanes keep the
        # kickoff-only defer so the verifier's validation tools are never stripped.
        self.assertIn('agent_id", None) == "orchestrator"', src)


class B1DeliveryRace(unittest.TestCase):
    def test_break_path_calls_framework_deliver(self):
        # the only create_release caller must run on the event-set break path
        from multi_agent import orchestrator
        src = inspect.getsource(orchestrator)
        # the break-on-event path now ensures the deterministic deliver runs first
        self.assertIn("await self._maybe_framework_deliver()\n                            break", src)

    def test_framework_deliver_is_idempotent(self):
        from multi_agent import orchestrator
        src = inspect.getsource(orchestrator._maybe_framework_deliver if hasattr(orchestrator, "_maybe_framework_deliver") else orchestrator.Orchestrator._maybe_framework_deliver)
        self.assertIn('getattr(self, "_project_delivered", False)', src)  # early-return guard


class R1PhasePinned(unittest.TestCase):
    def test_handle_task_ready_pins_implementation(self):
        from multi_agent.agents.runtime import messaging
        src = inspect.getsource(messaging.MessagingMixin._handle_task_ready
                                if hasattr(messaging, "MessagingMixin")
                                else [o for _, o in inspect.getmembers(messaging) if hasattr(o, "_handle_task_ready")][0]._handle_task_ready)
        self.assertIn('self._active_phase = "implementation"', src)
        self.assertIn("_prev_active_phase", src)  # save/restore


class R2TableRegisteredInboxOnly(unittest.TestCase):
    def test_backend_table_registered_is_inbox_only_not_live(self):
        from multi_agent.runtime.agent_subscriptions import (
            DEFAULT_SUBSCRIPTIONS as D, INBOX_ONLY_SUBSCRIPTIONS as I)
        live = {e for (_h, e, _p) in D["backend"]}
        inbox = {e for (_h, e, _p) in I["backend"]}
        self.assertNotIn("table_registered", live, "must not LIVE-subscribe (wakeup amplification)")
        self.assertIn("table_registered", inbox, "must inbox_only-subscribe (informed, no wakeup)")
        self.assertIn("table_implemented", live)  # the status-gated one stays live


class BUG1NoOpenPrInstruction(unittest.TestCase):
    def test_backend_prompt_drops_open_pr(self):
        p = (LLM_DIR / "multi_agent" / "prompts" / "v3" / "backend_agent.j2").read_text()
        # the CodeHub row no longer instructs codehub_open_pr (not surfaced in-phase)
        self.assertNotIn("codehub_open_pr", p)


if __name__ == "__main__":
    unittest.main()
