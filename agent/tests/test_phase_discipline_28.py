"""PROPOSAL #28 — phase discipline (reviewer-corrected set: F0+F1, F2, C-recovery; F3 dropped).

F0/F1: a GATE-SAFE hub-derived kickoff_finalized_signal (endpoints OR tasks OR flag), and
       kickoff_finalized uses it — so the ORCHESTRATOR (which has no KickoffBootstrapGate, so
       its _kickoff_bootstrapped is never set) is no longer PERMANENTLY classified as "in
       KICKOFF" → its deliverability_check/run_validation unblock once the contract exists.
       (The #24 flag-only check was a latent over-block; delivery itself is deterministic, so
       this was wasted-rounds/noise, not a delivery breaker.)
F2:    EnvGenAgent._KICKOFF_DEFER_TOOLS (the validation/delivery force-offers) are subtracted
       from the action-stage always-include while NOT kickoff_finalized_signal — so the
       orchestrator stops attempting run_validation/deliverability_check during kickoff.
       Monotonic signal → strict no-op post-kickoff (no smoke #9 retro-gate regression).
C:     a fast stall escape — the kickoff driver finalizes via the existing
       _kickoff_fallback_or_reconcile when phase=initial shows no substantive-section progress
       for KICKOFF_INITIAL_STALL_POLLS past the grace window (instead of the full 1200s).

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
    kickoff_finalized_signal, kickoff_finalized)


def _hubs(endpoints=None, tasks=None):
    rh = SimpleNamespace(
        _endpoints=SimpleNamespace(value=lambda: (endpoints or {})),
        get_endpoints=lambda: (endpoints or {}),
    )
    wh = SimpleNamespace(list_tasks=lambda: (tasks or []))
    return SimpleNamespace(registryhub=rh, workhub=wh)


def _agent(hubs, bootstrapped=False):
    return SimpleNamespace(_hubs=hubs, _kickoff_bootstrapped=bootstrapped, agent_id="orchestrator")


class F0Signal(unittest.TestCase):
    def test_false_when_nothing(self):
        self.assertFalse(kickoff_finalized_signal(_hubs()))

    def test_true_on_endpoints(self):
        self.assertTrue(kickoff_finalized_signal(_hubs(endpoints={"e1": {"path": "/x"}})))

    def test_true_on_tasks(self):
        self.assertTrue(kickoff_finalized_signal(_hubs(tasks=[{"id": "t1"}])))

    def test_true_on_flag_even_without_hubs(self):
        self.assertTrue(kickoff_finalized_signal(None, SimpleNamespace(_kickoff_bootstrapped=True)))

    def test_never_raises(self):
        self.assertFalse(kickoff_finalized_signal(SimpleNamespace()))


class F1RegressionFix(unittest.TestCase):
    def test_orchestrator_blocked_during_kickoff(self):
        # no endpoints/tasks, flag never set (orchestrator has no gate) → KICKOFF → blocked
        a = _agent(_hubs(), bootstrapped=False)
        msg = kickoff_finalized(a, "deliverability_check", {})
        self.assertIsNotNone(msg)
        self.assertIn("KICKOFF", msg)

    def test_orchestrator_UNBLOCKED_post_kickoff_via_hub(self):
        # THE REGRESSION FIX: flag still False (orchestrator never gets it), but endpoints
        # exist → hub-derived signal True → tools UNBLOCK (the #24 flag-only check wrongly
        # blocked these forever).
        a = _agent(_hubs(endpoints={"e1": {"path": "/api/notes"}}), bootstrapped=False)
        for tool in ("deliverability_check", "run_validation", "run_start"):
            self.assertIsNone(kickoff_finalized(a, tool, {}),
                              f"{tool} must unblock once the contract exists (hub signal)")

    def test_uses_hub_signal_not_flag_only(self):
        src = inspect.getsource(kickoff_finalized)
        self.assertIn("kickoff_finalized_signal", src)


class F2DeferSet(unittest.TestCase):
    def test_defer_set_membership(self):
        from multi_agent.agents.base import EnvGenAgent
        defer = EnvGenAgent._KICKOFF_DEFER_TOOLS
        for t in ("run_validation", "deliverability_check", "deliver_project",
                  "report_completion", "submit_retro"):
            self.assertIn(t, defer, f"{t} must be deferred during kickoff")
        # finish / read must NOT be deferred (the agent still needs them in kickoff)
        self.assertNotIn("finish", defer)

    def test_tooling_gates_defer_on_signal(self):
        from multi_agent.agents.runtime.step_pipeline import tooling
        src = inspect.getsource(tooling)
        self.assertIn("_KICKOFF_DEFER_TOOLS", src)
        # PRE-LAUNCH AUDIT F1 (re-review scoped): the ORCHESTRATOR defers
        # validation/delivery tools through kickoff AND implementation (validation-ready
        # signal); EVERY OTHER lane keeps the kickoff-only defer (so the verifier's
        # _VALIDATION_FLOW force-offer survives — a validation-ready defer there could
        # strip run_validation/register_verification_chain).
        self.assertIn("validation_ready_signal", src)
        self.assertIn("kickoff_finalized_signal", src)
        self.assertIn('agent_id", None) == "orchestrator"', src)


class CRecovery(unittest.TestCase):
    def test_constants_sane(self):
        from multi_agent.runtime.kickoff import run_kickoff as rk
        self.assertLess(rk.KICKOFF_INITIAL_STALL_MIN_SEC, rk.KICKOFF_TIMEOUT_SEC,
                        "stall escape must fire BEFORE the full timeout")
        self.assertGreater(rk.KICKOFF_INITIAL_STALL_POLLS, 0)

    def test_driver_finalizes_on_initial_stall(self):
        # the phase=initial branch must early-finalize via the existing fallback
        from multi_agent.runtime import kickoff_driver
        src = inspect.getsource(kickoff_driver)
        self.assertIn("KICKOFF_INITIAL_STALL_POLLS", src)
        self.assertIn("KICKOFF_INITIAL_STALL_MIN_SEC", src)
        self.assertIn('"initial_stall"', src)
        self.assertIn("_kickoff_fallback_or_reconcile", src)
        # progress measured via try_synthesize's missing set (shrinking = progress)
        self.assertIn("try_synthesize", src)
        self.assertIn("missing", src)


if __name__ == "__main__":
    unittest.main()
