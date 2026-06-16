"""Reviewer re-audit (2026-05-29) HIGH #4:
``_should_start_from_task_ready`` consults every policy's
``allow_task_ready`` before letting a ``task_ready`` message kick the
lane. But resident lanes are ALSO woken by ordinary inbox messages
via ``_maybe_schedule_resident_message_wakeup`` (messaging.py:87) —
that path did NOT consult any policy, so:

  * ``DependsOnPolicy`` ("waiting on upstream X") could be bypassed:
    a random inbox notification woke the lane even though its
    upstream had never reached task_ready.
  * ``VerifierValidationTriggerPolicy`` ("verifier only acts on
    explicit validation triggers") could be bypassed: any inbox
    message kicked the verifier into a full agentic loop, even
    when it wasn't a validation trigger.

Fix: a new ``allow_resident_wakeup`` hook on ``BaseWorkflowPolicy``
(default None). ``DependsOnPolicy`` and
``VerifierValidationTriggerPolicy`` override it to delegate to
``allow_task_ready`` so the same denial reasons apply on both
paths. The wakeup scheduler consults the hook before enqueueing
the wakeup TaskMessage.

These tests pin both directions:
  * policy says "deny" → scheduler must NOT enqueue.
  * policy says None (no opinion) → scheduler proceeds as before.
  * Round 8h Stage 1: ``KickoffBootstrapGate`` (which replaces the
    retired ``ImplementationBootstrapPolicy``) deliberately does NOT
    override → its own inline bootstrap-gate (which has side-effect
    flag-flipping semantics on ``_kickoff_bootstrapped``) keeps
    handling its case.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


# --- policy-side: allow_resident_wakeup contract ---------------------

class BaseHookDefaultIsNoOpinion(unittest.TestCase):
    def test_base_class_returns_none_unconditionally(self):
        from multi_agent.workflow_policies import BaseWorkflowPolicy
        b = BaseWorkflowPolicy()
        # Doesn't even look at the args — must be a safe default.
        self.assertIsNone(
            b.allow_resident_wakeup(MagicMock(), MagicMock(), {}),
            "default allow_resident_wakeup must return None — "
            "policies that don't care about wakeups shouldn't have "
            "to override it.",
        )


class DependsOnPolicyDelegatesToTaskReady(unittest.TestCase):
    def test_blocks_wakeup_when_upstream_not_ready(self):
        from multi_agent.workflow_policies import DependsOnPolicy
        agent = MagicMock()
        agent._upstream_ready_agents = set()  # nothing ready
        msg = MagicMock()
        p = DependsOnPolicy(depends_on=["backend"])
        decision = p.allow_resident_wakeup(agent, msg, {"from": "frontend"})
        self.assertIsNotNone(
            decision,
            "DependsOnPolicy must reject a resident wakeup when its "
            "upstream hasn't reached task_ready — otherwise a Slack-"
            "shaped inbox message bypasses the dependency gate.",
        )
        allowed, reason = decision
        self.assertFalse(allowed)
        self.assertIn("waiting on depends_on", reason)
        self.assertIn("backend", reason)

    def test_passes_wakeup_when_upstream_ready(self):
        from multi_agent.workflow_policies import DependsOnPolicy
        agent = MagicMock()
        agent._upstream_ready_agents = {"backend"}
        msg = MagicMock()
        p = DependsOnPolicy(depends_on=["backend"])
        self.assertIsNone(
            p.allow_resident_wakeup(agent, msg, {"from": "frontend"})
        )

    def test_passes_wakeup_when_no_dependencies(self):
        from multi_agent.workflow_policies import DependsOnPolicy
        agent = MagicMock()
        msg = MagicMock()
        p = DependsOnPolicy(depends_on=[])
        self.assertIsNone(p.allow_resident_wakeup(agent, msg, {}))

    def test_validation_ready_signal_bypasses_depends_on(self):
        # §6 C1: the hub's validation_ready signal is authoritative readiness — it
        # bypasses the lane-completion depends_on gate (lanes may be mid-cleanup).
        from multi_agent.workflow_policies import DependsOnPolicy
        agent = MagicMock()
        agent._upstream_ready_agents = set()   # lanes NOT marked ready
        msg = MagicMock()
        msg.metadata = {"tags": ["validation_ready"]}
        msg.payload = "validation_ready: all_business_endpoints_implemented"
        p = DependsOnPolicy(depends_on=["backend", "frontend"])
        self.assertIsNone(p.allow_resident_wakeup(agent, msg, {}))


class VerifierValidationTriggerPolicyDelegatesToTaskReady(unittest.TestCase):
    def _build_message(self, source: str, tags=None, phase=None, payload=""):
        m = MagicMock()
        m.header.source_agent_id = source
        m.metadata = {
            "tags": tags or [],
            "phase": phase or "",
            "validation_phase": False,
        }
        m.payload = payload
        return m

    def test_blocks_wakeup_from_non_orchestrator_message(self):
        from multi_agent.workflow_policies import (
            VerifierValidationTriggerPolicy,
        )
        agent = MagicMock()
        agent.agent_id = "verifier"
        msg = self._build_message(source="knowledge")  # not orchestrator, not impl
        p = VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator",
            accepted_tags=["validate"],
            accepted_phases=["validation"],
            payload_keywords=["validate"],
        )
        decision = p.allow_resident_wakeup(agent, msg, {"from": "knowledge"})
        self.assertIsNotNone(
            decision,
            "verifier must not wake on a non-trigger inbox message — "
            "the entire point of this policy is to gate verifier on "
            "explicit validation-phase signal from orchestrator.",
        )
        allowed, reason = decision
        self.assertFalse(allowed)
        self.assertIn("validation-phase trigger", reason)

    def test_impl_completion_self_triggers_only_when_all_lanes_done(self):
        # ⚠2 (Theme C): the FIRST impl completion is recorded but does NOT wake
        # the verifier (half-built tree); once EVERY impl lane has finished, the
        # verifier self-triggers — no orchestrator trigger needed.
        from multi_agent.workflow_policies import VerifierValidationTriggerPolicy
        agent = MagicMock(); agent.agent_id = "verifier"
        p = VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator", accepted_tags=[], accepted_phases=[],
            payload_keywords=[], impl_completion_senders=["backend", "frontend"],
        )
        # backend finishes first → recorded, still blocked (frontend pending)
        d1 = p.allow_resident_wakeup(agent, self._build_message(source="backend"), {})
        self.assertIsNotNone(d1)
        self.assertFalse(d1[0])
        self.assertIn("awaiting", d1[1])
        self.assertIn("frontend", d1[1])
        # frontend finishes → both done → ADMIT (None == no objection)
        d2 = p.allow_resident_wakeup(agent, self._build_message(source="frontend"), {})
        self.assertIsNone(d2)

    def test_hub_validation_ready_signal_admitted_regardless_of_sender(self):
        # §6 C1: RegistryHub emits validation_ready (from a hub, NOT the orchestrator)
        # when all business endpoints are implemented. The verifier must admit it.
        from multi_agent.workflow_policies import VerifierValidationTriggerPolicy
        agent = MagicMock(); agent.agent_id = "verifier"
        p = VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator", accepted_tags=[], accepted_phases=[],
            payload_keywords=[],
        )
        msg = self._build_message(
            source="registryhub",
            payload="validation_ready: all_business_endpoints_implemented",
        )
        self.assertIsNone(p.allow_resident_wakeup(agent, msg, {}))

    def test_explicit_orchestrator_trigger_still_works_before_impl_done(self):
        from multi_agent.workflow_policies import VerifierValidationTriggerPolicy
        agent = MagicMock(); agent.agent_id = "verifier"
        p = VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator", accepted_tags=["validate"],
            accepted_phases=[], payload_keywords=[],
        )
        msg = self._build_message(source="orchestrator", tags=["validate"])
        self.assertIsNone(p.allow_resident_wakeup(agent, msg, {}))

    def test_passes_wakeup_for_explicit_validation_trigger(self):
        from multi_agent.workflow_policies import (
            VerifierValidationTriggerPolicy,
        )
        agent = MagicMock()
        agent.agent_id = "verifier"
        msg = self._build_message(
            source="orchestrator",
            tags=["validate"],
        )
        p = VerifierValidationTriggerPolicy(
            allowed_sender="orchestrator",
            accepted_tags=["validate"],
            accepted_phases=[],
            payload_keywords=[],
        )
        self.assertIsNone(
            p.allow_resident_wakeup(agent, msg, {"from": "orchestrator"}),
            "explicit validation trigger must pass — otherwise the "
            "verifier is unreachable",
        )


class KickoffBootstrapGateDoesNotOverrideHook(unittest.TestCase):
    """Round 8h Stage 1: ``KickoffBootstrapGate`` replaces the retired
    ``ImplementationBootstrapPolicy``. Same invariant: the gate's
    task_ready logic has a side effect (flipping
    ``_kickoff_bootstrapped``) and must NOT fire on arbitrary inbox
    wakeups — the inline gate in messaging.py
    (``_has_kickoff_bootstrap_gate`` + ``_kickoff_bootstrapped``)
    handles bootstrap-vs-wakeup interaction. Pin that the override
    was deliberately NOT added."""

    def test_kickoff_bootstrap_gate_uses_default_no_opinion(self):
        from multi_agent.workflow_policies import (
            BaseWorkflowPolicy, KickoffBootstrapGate,
        )
        # The override on this class is intentionally absent — so it
        # resolves to BaseWorkflowPolicy.allow_resident_wakeup.
        # (Compare unbound functions — if the policy overrides, the
        # function object on the class differs.)
        self.assertIs(
            KickoffBootstrapGate.allow_resident_wakeup,
            BaseWorkflowPolicy.allow_resident_wakeup,
            "KickoffBootstrapGate must NOT override "
            "allow_resident_wakeup — its task_ready logic flips "
            "_kickoff_bootstrapped as a side effect, and "
            "firing it on every inbox message would corrupt the "
            "bootstrap state. The inline gate in messaging.py "
            "already handles bootstrap-vs-wakeup interaction.",
        )


# --- scheduler-side: messaging.py consults the hook ------------------

class SchedulerConsultsHookBeforeEnqueueing(unittest.TestCase):
    """End-to-end through ``_maybe_schedule_resident_message_wakeup``:
    a denying policy must SUPPRESS the wakeup; a no-opinion policy
    must let it through."""

    def tearDown(self):
        _reset_event_loop()

    def _build_messaging_stub(self, policies):
        """Build a minimal agent-like object exposing every attribute
        ``_maybe_schedule_resident_message_wakeup`` reads. Importing
        the bound method off the messaging module's mixin class is
        less brittle than constructing a full ConfigurableAgent."""
        from multi_agent.agents.runtime.messaging import (
            AgentMessaging,
        )
        from utils.message import (
            BaseMessage, MessageHeader, MessagePriority,
        )

        class _Stub(AgentMessaging):
            pass

        stub = _Stub()
        stub.agent_id = "frontend"
        stub._is_resident_lane = True
        stub._workflow_policies = policies
        stub._logger = MagicMock()
        stub._resident_wakeup_task_pending = False
        stub._kickoff_bootstrapped = True
        stub._message_queue = MagicMock()
        stub._message_queue.put = MagicMock(side_effect=
                                            lambda m: asyncio.sleep(0))
        return stub, BaseMessage, MessageHeader, MessagePriority

    def test_denying_policy_suppresses_wakeup(self):
        from multi_agent.workflow_policies import DependsOnPolicy
        # frontend depends on backend; backend hasn't reached
        # task_ready yet. Inbox message arrives anyway.
        stub, BaseMessage, MessageHeader, MessagePriority = (
            self._build_messaging_stub([DependsOnPolicy(depends_on=["backend"])])
        )
        stub._upstream_ready_agents = set()
        header = MessageHeader(
            source_agent_id="someone_else",
            target_agent_id="frontend",
            priority=MessagePriority.LOW,
        )
        msg = BaseMessage(header=header, payload="hi")
        inbox_msg = {"from": "someone_else", "type": "notify",
                      "id": "m1", "tags": []}
        asyncio.run(stub._maybe_schedule_resident_message_wakeup(msg, inbox_msg))
        # No wakeup TaskMessage enqueued because the policy denied.
        stub._message_queue.put.assert_not_called()
        # Suppression was logged so an operator can see it.
        joined = " ".join(
            str(a) for call in stub._logger.info.call_args_list for a in call.args
        )
        self.assertIn("suppressing resident wakeup", joined)
        self.assertIn("waiting on depends_on", joined)

    def test_no_opinion_policy_allows_wakeup(self):
        """A policy returning None (no opinion) on the hook must let
        the wakeup proceed — the regression must not over-correct
        the bug by suppressing everything."""
        from multi_agent.workflow_policies import BaseWorkflowPolicy

        class _NoOpinion(BaseWorkflowPolicy):
            pass

        stub, BaseMessage, MessageHeader, MessagePriority = (
            self._build_messaging_stub([_NoOpinion()])
        )
        header = MessageHeader(
            source_agent_id="some_agent",
            target_agent_id="frontend",
            priority=MessagePriority.LOW,
        )
        msg = BaseMessage(header=header, payload="hi")
        inbox_msg = {"from": "some_agent", "type": "notify",
                      "id": "m1", "tags": []}
        asyncio.run(stub._maybe_schedule_resident_message_wakeup(msg, inbox_msg))
        # The wakeup is created as a fire-and-forget asyncio.create_task,
        # so we observe the side effect: _resident_wakeup_task_pending
        # was flipped to True by the wakeup path.
        self.assertTrue(
            stub._resident_wakeup_task_pending,
            "no-opinion policy must let the wakeup proceed — the "
            "scheduler should have flipped _resident_wakeup_task_pending",
        )

    def test_buggy_policy_does_not_block_wakeups(self):
        """Defensive: if a policy's allow_resident_wakeup raises, the
        scheduler must continue and not block legitimate wakeups."""
        from multi_agent.workflow_policies import BaseWorkflowPolicy

        class _BuggyPolicy(BaseWorkflowPolicy):
            def allow_resident_wakeup(self, agent, message, inbox_msg):
                raise RuntimeError("synthetic")

        stub, BaseMessage, MessageHeader, MessagePriority = (
            self._build_messaging_stub([_BuggyPolicy()])
        )
        header = MessageHeader(
            source_agent_id="some_agent",
            target_agent_id="frontend",
            priority=MessagePriority.LOW,
        )
        msg = BaseMessage(header=header, payload="hi")
        inbox_msg = {"from": "some_agent", "type": "notify",
                      "id": "m1", "tags": []}
        asyncio.run(stub._maybe_schedule_resident_message_wakeup(msg, inbox_msg))
        self.assertTrue(
            stub._resident_wakeup_task_pending,
            "buggy policy must not block legitimate wakeups — the "
            "scheduler should swallow the exception and continue.",
        )
        # And the exception was logged so the operator can fix the
        # policy.
        joined = " ".join(
            str(a) for call in stub._logger.warning.call_args_list for a in call.args
        )
        self.assertIn("synthetic", joined)

    def test_kickoff_participation_event_bypasses_denying_policy(self):
        """A kickoff PARTICIPATION event (reply/comment/revision/request) is MANDATORY
        work for an attendee — it must bypass a denying policy and wake the lane, or
        the kickoff hangs to its timeout waiting on the suppressed attendee (the exact
        instagram M1/M2 death: verifier+frontend suppressed kickoff_reply_phase_request
        42×)."""
        from multi_agent.workflow_policies import DependsOnPolicy
        for ev in ("kickoff_request", "kickoff_comment_phase_request",
                   "kickoff_reply_phase_request", "kickoff_revision_request"):
            stub, BaseMessage, MessageHeader, MessagePriority = (
                self._build_messaging_stub([DependsOnPolicy(depends_on=["backend"])])
            )
            stub._upstream_ready_agents = set()  # policy WOULD deny a normal message
            header = MessageHeader(source_agent_id="orchestrator",
                                   target_agent_id="frontend",
                                   priority=MessagePriority.LOW)
            msg = BaseMessage(header=header, payload="kickoff phase")
            inbox_msg = {"from": "orchestrator", "type": ev, "id": "m1", "tags": []}
            asyncio.run(stub._maybe_schedule_resident_message_wakeup(msg, inbox_msg))
            self.assertTrue(
                stub._resident_wakeup_task_pending,
                f"{ev} must bypass policy suppression so the attendee wakes to "
                "author/ack — else the kickoff hangs to timeout.")
            _reset_event_loop()

    def test_kickoff_notification_still_policy_gated(self):
        """kickoff_failed / kickoff_complete are NOT participation — they stay
        policy-gated (a denying policy suppresses them, like any notification)."""
        from multi_agent.workflow_policies import DependsOnPolicy
        stub, BaseMessage, MessageHeader, MessagePriority = (
            self._build_messaging_stub([DependsOnPolicy(depends_on=["backend"])])
        )
        stub._upstream_ready_agents = set()
        header = MessageHeader(source_agent_id="orchestrator",
                               target_agent_id="frontend",
                               priority=MessagePriority.LOW)
        msg = BaseMessage(header=header, payload="failed")
        inbox_msg = {"from": "orchestrator", "type": "kickoff_failed",
                     "id": "m1", "tags": []}
        asyncio.run(stub._maybe_schedule_resident_message_wakeup(msg, inbox_msg))
        stub._message_queue.put.assert_not_called()
        joined = " ".join(
            str(a) for call in stub._logger.info.call_args_list for a in call.args)
        self.assertIn("suppressing resident wakeup", joined)


if __name__ == "__main__":
    unittest.main()
