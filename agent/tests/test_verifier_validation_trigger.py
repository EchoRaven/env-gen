"""Guard: the orchestrator-driven verifier validation trigger (Design A).

PROPOSAL #2 (reviewed_version:2 PASS). The verifier perpetually idled
`awaiting ['frontend']` and never ran its validation pass when the canonical
`validation_ready` signal didn't fire (run #15: not all endpoints implemented +
frontend finished `notify=[]`). Fix: the deterministic driver
(`_maybe_run_framework_validation`) sends the verifier an explicit
`validation_phase=True` `task_ready` once api_smoke is attempted (past the
route-code floor), re-armable per impl epoch.

These tests pin the two load-bearing pieces:
  1. the re-armable guard (`_verifier_trigger_due`) — one trigger per impl epoch,
     re-arms on progress, never a permanent boolean;
  2. the trigger MESSAGE must carry `metadata["validation_phase"] = True`
     (injected post-construction — `_create_message` has no metadata kwarg) so it
     satisfies VerifierValidationTriggerPolicy.explicit_trigger with ZERO
     dependence on env-configured tags/phases, AND it must wake an IDLE verifier
     (couples commit a3aea89: revert that and this test fails).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.orchestrator import Orchestrator  # noqa: E402
from multi_agent.workflow_policies import VerifierValidationTriggerPolicy  # noqa: E402
from tools.communication_tools import _create_message  # noqa: E402

_due = Orchestrator._verifier_trigger_due


class VerifierTriggerGuardTests(unittest.TestCase):
    """Re-armable guard: fire once per impl epoch, re-arm on progress."""

    def test_first_fire_when_never_triggered(self):
        self.assertTrue(_due(0, -1))    # epoch 0, never triggered (init -1) → fire
        self.assertTrue(_due(5, -1))

    def test_no_refire_on_stable_epoch(self):
        self.assertFalse(_due(0, 0))    # already triggered this epoch → don't re-fire
        self.assertFalse(_due(5, 5))

    def test_rearm_on_impl_progress(self):
        # impl lanes implemented more endpoints since last trigger → re-validate
        self.assertTrue(_due(7, 3))

    def test_not_a_permanent_boolean(self):
        # the trap we avoid: triggered at epoch 2, then progress to 4 must re-fire
        last = -1
        self.assertTrue(_due(2, last)); last = 2
        self.assertFalse(_due(2, last))          # same epoch, no spam
        self.assertTrue(_due(4, last))           # progress → re-fire
        last = 4
        self.assertFalse(_due(4, last))


class VerifierTriggerMessageTests(unittest.TestCase):
    """The trigger message must wake an IDLE verifier via the validation_phase
    explicit-trigger path — independent of tag/phase config."""

    def _policy(self):
        # accepted_tags/phases/keywords intentionally EMPTY → prove validation_phase
        # alone admits (no per-env wiring), exactly the orchestrator's general path.
        return VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator", accepted_tags=[],
            accepted_phases=[], payload_keywords=[],
        )

    def _verifier(self):
        agent = MagicMock()
        agent.agent_id = "verifier"
        return agent

    def _build_trigger(self, with_validation_phase: bool):
        msg = _create_message(
            source_agent_id="orchestrator", target_agent_id="verifier",
            content="run your validation pass now",
            msg_type="task_ready", priority="urgent", persist=True,
        )
        if with_validation_phase:
            msg.metadata["validation_phase"] = True  # the binding correction
        return msg

    def test_validation_phase_message_admits_idle_verifier(self):
        # allow_resident_wakeup (the IDLE-lane path, delegates to allow_task_ready)
        # must ADMIT (None = no objection) on validation_phase=True from orchestrator.
        policy = self._policy()
        msg = self._build_trigger(with_validation_phase=True)
        inbox_msg = {"from": "orchestrator", "type": "task_ready"}
        self.assertIsNone(
            policy.allow_resident_wakeup(self._verifier(), msg, inbox_msg),
            "a validation_phase=True task_ready from orchestrator MUST wake the "
            "idle verifier (the whole point of Design A); couples a3aea89.",
        )
        # and the same via allow_task_ready directly
        self.assertIsNone(policy.allow_task_ready(self._verifier(), msg))

    def test_missing_validation_phase_is_NOT_admitted(self):
        # The broken kwarg form (metadata={...} silently dropped, or forgetting the
        # injection) leaves validation_phase absent → policy must NOT admit, so the
        # bug surfaces in test rather than as a silent prod no-op.
        policy = self._policy()
        msg = self._build_trigger(with_validation_phase=False)
        decision = policy.allow_task_ready(self._verifier(), msg)
        self.assertIsNotNone(
            decision,
            "without validation_phase the trigger must be REJECTED (else the fix "
            "silently no-ops) — this catches the metadata= kwarg mistake.",
        )
        allowed, _reason = decision
        self.assertFalse(allowed)

    def test_create_message_has_no_metadata_kwarg(self):
        # Documents the binding correction: passing metadata= raises TypeError, so
        # the injection form is mandatory.
        with self.assertRaises(TypeError):
            _create_message(
                source_agent_id="orchestrator", target_agent_id="verifier",
                content="x", msg_type="task_ready",
                metadata={"validation_phase": True},  # type: ignore[call-arg]
            )


if __name__ == "__main__":
    unittest.main()
