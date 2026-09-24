"""Step B activation: the lane_idle_circuit_breaker policy must be
wired into every lane that ships, and the orchestrator prompt must
teach how to handle each escalation tier. Otherwise the policy
exists as code but never fires in production runs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _load_profile_breaker(profile_name: str) -> dict:
    """Return the lane_idle_circuit_breaker entry from a profile, or
    raise AssertionError if the profile doesn't have one."""
    import yaml
    cfg_path = LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    prof = (cfg.get("profiles") or {}).get(profile_name) or {}
    for entry in prof.get("workflow_policies") or []:
        if entry.get("kind") == "lane_idle_circuit_breaker":
            return entry
    raise AssertionError(
        f"profile {profile_name!r} has no lane_idle_circuit_breaker policy"
    )


class CircuitBreakerEnabledForShippingLanes(unittest.TestCase):
    """Four lanes get the breaker: design, backend, frontend, verifier.
    orchestrator + debugger + knowledge don't (they coordinate or are
    event-driven; a breaker on the coordinator would self-trigger
    feedback loops)."""

    def test_backend_frontend_share_thresholds(self):
        for name in ("backend", "frontend"):
            b = _load_profile_breaker(name)
            self.assertEqual(b["warn_after_idle_steps"], 3, f"{name}: warn")
            self.assertEqual(b["failforward_after_idle_steps"], 6, f"{name}: ff")
            self.assertEqual(b["halt_after_idle_steps"], 10, f"{name}: halt")

    def test_verifier_has_looser_thresholds(self):
        """Verifier naturally idles waiting for implementations to
        ship — looser thresholds avoid noisy escalations."""
        b = _load_profile_breaker("verifier")
        self.assertGreater(
            b["warn_after_idle_steps"], 3,
            "Verifier idle thresholds must be looser than implementation lanes",
        )
        self.assertGreater(b["failforward_after_idle_steps"], 6)
        self.assertGreater(b["halt_after_idle_steps"], 10)


class OrchestratorPromptTeachesEscalationResponse(unittest.TestCase):
    """The orchestrator prompt must teach how to act on each tier's
    event. Otherwise the LLM sees the event and doesn't know it's
    actionable."""

    PROMPT = LLM_DIR / "multi_agent" / "prompts" / "v3" / "orchestrator_agent.j2"

    def _text(self) -> str:
        return self.PROMPT.read_text()

    def test_warning_tier_handler_present(self):
        text = self._text()
        self.assertIn("lane_idle_warning", text,
                      "orchestrator prompt must teach how to handle tier-1 warning")
        # Concrete action mentioned, not just a description.
        self.assertIn("send_message", text)

    def test_failforward_tier_handler_present(self):
        text = self._text()
        self.assertIn("lane_stuck_failforward", text)
        self.assertIn("workhub_fail_task", text,
                      "fail-forward tier must mention workhub_fail_task")

    def test_halt_tier_handler_present(self):
        text = self._text()
        self.assertIn("lane_halted_human", text)
        # Must explicitly say "stop re-pinging" or equivalent — the
        # whole point of tier 3 is to break the noisy retry loop.
        self.assertTrue(
            "stop" in text.lower() and "halted" in text.lower(),
            "halted tier must tell orchestrator to stop nudging the lane",
        )

    def test_prompt_explains_deterministic_tier3_action(self):
        """After the tier-3 hardening, the prompt must teach
        orchestrator about BOTH branches of the deterministic action
        — failed (claimed task) AND cancelled (assigned but never
        claimed). The latter is what actually fires in the observed
        deadlock pattern, so the prompt MUST mention it explicitly
        or the orchestrator won't know to act on it."""
        text = self._text()
        self.assertIn("lane_task_auto_failed", text,
                       "orchestrator prompt must mention the deterministic event")
        # Both payload field names — orchestrator should read both lists.
        self.assertIn("failed_task_ids", text,
                       "prompt must name the failed_task_ids payload field")
        self.assertIn("cancelled_task_ids", text,
                       "prompt must name the cancelled_task_ids payload field "
                       "— this is the observed-deadlock branch and must not "
                       "be left implicit")
        # Both action verbs the breaker uses.
        self.assertIn("workhub_fail_task", text)
        self.assertIn("workhub_cancel_task", text,
                       "prompt must mention cancel — agents that never claim "
                       "have their tasks cancelled, not failed")
        self.assertIn("depends_on", text,
                       "prompt must teach re-evaluating downstream deps "
                       "after a deterministic fail-forward")


if __name__ == "__main__":
    unittest.main()
