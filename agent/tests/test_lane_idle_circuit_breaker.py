"""Step B: LaneIdleCircuitBreakerPolicy escalates a stuck agent
through three tiers (warn → fail-forward → halt) and resets on any
productive finish.

Without this, the live-run pattern observed in the Facebook smoke
was: design got stuck on a tool bug, orchestrator burned 48
``report_progress`` calls, verifier kept probing files that would
never appear. Nothing in the system told the orchestrator "this lane
is dead, decide what to do".
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class _StubAgent:
    def __init__(self, agent_id, hubs, tmp):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self._hubs = hubs
        self._logger = MagicMock()
        self.workspace = MagicMock()
        self.workspace.base_dir = Path(tmp)
        # The breaker is an IMPLEMENTATION-phase safety net — suppressed during
        # kickoff (smoke #4 guard). These tests exercise impl-phase behavior, so
        # the lane is bootstrapped past kickoff.
        self._kickoff_bootstrapped = True


def _make_policy(**kw):
    from multi_agent.workflow_policies import LaneIdleCircuitBreakerPolicy
    return LaneIdleCircuitBreakerPolicy(**kw)


def _run_finish(policy, agent, files_created=None, files_modified=None):
    """Invoke handle_finish with neutral inputs."""
    return asyncio.run(policy.handle_finish(
        agent,
        tool_name="finish",
        tool_args={"message": ""},
        tool_call=MagicMock(),
        tool_call_id="tc",
        messages=[],
        files_created=files_created or [],
        files_modified=files_modified or [],
    ))


def _events_for(hubs, agent):
    """Return events delivered to ``agent``'s inbox, oldest first."""
    events = hubs.eventhub.list_inbox(agent, unread_only=False)
    return sorted(events, key=lambda e: e.get("created_at", 0))


class FirstObservationDoesNotEscalate(unittest.TestCase):
    """The first finish() seeds the productivity baseline — it must
    not emit a warning even with zero output."""

    def test_first_idle_step_only_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            agent = _StubAgent("design", hubs, tmp)
            policy = _make_policy(warn_after_idle_steps=1)
            _run_finish(policy, agent)
            self.assertEqual(_events_for(hubs, "orchestrator"), [])
            # Counter starts at 0 after seed.
            self.assertEqual(getattr(agent, "_consecutive_idle_steps", -1), 0)


class EscalationTiers(unittest.TestCase):
    """The breaker fires three distinct events at three thresholds,
    each at a higher priority."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brkr_"))
        self.hubs = HubRegistry(self.tmp)
        self.agent = _StubAgent("design", self.hubs, self.tmp)
        self.policy = _make_policy(
            warn_after_idle_steps=2,
            failforward_after_idle_steps=4,
            halt_after_idle_steps=6,
        )
        # First call seeds, doesn't count.
        _run_finish(self.policy, self.agent)

    def _idle(self):
        _run_finish(self.policy, self.agent)

    def test_tier1_warn_at_threshold(self):
        for _ in range(2):
            self._idle()
        evts = _events_for(self.hubs, "orchestrator")
        types = [e.get("event_type") for e in evts]
        self.assertEqual(types, ["lane_idle_warning"])
        self.assertEqual(evts[0].get("priority"), "normal")

    def test_tier2_failforward(self):
        for _ in range(4):
            self._idle()
        types = [e.get("event_type") for e in _events_for(self.hubs, "orchestrator")]
        self.assertEqual(types, ["lane_idle_warning", "lane_stuck_failforward"])

    def test_tier3_halt(self):
        for _ in range(6):
            self._idle()
        types = [e.get("event_type") for e in _events_for(self.hubs, "orchestrator")]
        self.assertEqual(types,
                          ["lane_idle_warning", "lane_stuck_failforward",
                           "lane_halted_human"])
        urgent = [e for e in _events_for(self.hubs, "orchestrator")
                  if e.get("event_type") == "lane_halted_human"]
        self.assertEqual(urgent[0].get("priority"), "urgent")

    def test_does_not_re_fire_same_tier(self):
        """Crossing a tier must emit ONCE. Subsequent idle steps below
        the next threshold don't re-emit the same event."""
        for _ in range(3):
            self._idle()
        types = [e.get("event_type") for e in _events_for(self.hubs, "orchestrator")]
        self.assertEqual(types, ["lane_idle_warning"])


class ProductiveFinishResetsCounter(unittest.TestCase):
    """Any productive finish (files written OR owned hub items grew)
    resets the idle counter and the tier — so brief pauses don't
    accumulate into bogus escalations."""

    def test_writing_a_file_resets_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            agent = _StubAgent("design", hubs, tmp)
            policy = _make_policy(warn_after_idle_steps=2)
            _run_finish(policy, agent)        # seed
            _run_finish(policy, agent)        # idle 1
            _run_finish(policy, agent, files_created=["design/spec.api.json"])
            self.assertEqual(_events_for(hubs, "orchestrator"), [])
            self.assertEqual(agent._consecutive_idle_steps, 0)
            self.assertEqual(agent._last_idle_tier, 0)

    def test_registering_endpoint_resets_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            agent = _StubAgent("design", hubs, tmp)
            policy = _make_policy(warn_after_idle_steps=2)
            _run_finish(policy, agent)
            _run_finish(policy, agent)
            # design registers an endpoint between finishes.
            hubs.registryhub.register_endpoint(
                "POST", "/api/auth/login", schema={},
                provider="design", agent="backend",
            )
            _run_finish(policy, agent)
            self.assertEqual(_events_for(hubs, "orchestrator"), [])
            self.assertEqual(agent._consecutive_idle_steps, 0)

    def test_post_reset_can_re_escalate_through_warn_again(self):
        """After a reset, the agent that goes idle again should be
        able to climb back through warn, fail-forward, halt."""
        with tempfile.TemporaryDirectory() as tmp:
            hubs = HubRegistry(Path(tmp))
            agent = _StubAgent("design", hubs, tmp)
            policy = _make_policy(
                warn_after_idle_steps=2, failforward_after_idle_steps=4,
                halt_after_idle_steps=6,
            )
            # Trigger warn once.
            _run_finish(policy, agent)
            _run_finish(policy, agent)
            _run_finish(policy, agent)
            # Reset via file write.
            _run_finish(policy, agent, files_created=["design/spec.api.json"])
            # Idle again — should fire warn again, not stay silent.
            _run_finish(policy, agent)
            _run_finish(policy, agent)
            types = [e.get("event_type") for e in _events_for(hubs, "orchestrator")]
            # First warn from before-reset, second warn after-reset.
            self.assertEqual(types.count("lane_idle_warning"), 2)


class Tier3DeterministicAction(unittest.TestCase):
    """Reviewer follow-up: tier-3 should DO something deterministic,
    not just signal. By default the breaker now auto-fails the lane's
    in-progress claimed task on tier-3 so downstream depends_on can
    proceed independent of LLM behaviour."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brkr3_"))
        self.hubs = HubRegistry(self.tmp)
        # Seed: design has a task in_progress (assigned, claimed).
        task = self.hubs.workhub.create_task(
            title="Write spec.api.json", assignee="design",
            agent="orchestrator",
        )
        claim = self.hubs.workhub.claim_task(task["id"], "design")
        self.task_id = claim["id"] if "id" in claim else task["id"]
        self.agent = _StubAgent("design", self.hubs, self.tmp)

    def _drive_to_tier3(self, policy):
        # Seed step + halt_after_idle_steps idle steps.
        _run_finish(policy, self.agent)
        for _ in range(policy.halt_after_idle_steps):
            _run_finish(policy, self.agent)

    def test_default_halt_action_is_fail_task(self):
        policy = _make_policy()
        self.assertEqual(policy.halt_action, "fail_task")

    def test_tier3_auto_fails_claimed_task(self):
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        self._drive_to_tier3(policy)
        task = self.hubs.workhub.stores.tasks.value().get(self.task_id) or {}
        self.assertEqual(task.get("status"), "failed",
                          "tier-3 must auto-fail the lane's in-progress task")
        self.assertIn("tier-3", task.get("fail_reason", ""))

    def test_tier3_emits_lane_task_auto_failed_event(self):
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        self._drive_to_tier3(policy)
        types = [e.get("event_type")
                 for e in _events_for(self.hubs, "orchestrator")]
        self.assertIn("lane_task_auto_failed", types)
        evt = next(e for e in _events_for(self.hubs, "orchestrator")
                   if e.get("event_type") == "lane_task_auto_failed")
        self.assertEqual(evt.get("priority"), "urgent")
        self.assertIn(self.task_id,
                       (evt.get("payload") or {}).get("failed_task_ids") or [])

    def test_signal_only_mode_does_not_fail_task(self):
        """Operators who want strictly-passive behaviour can opt out."""
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3, halt_action="signal_only",
        )
        self._drive_to_tier3(policy)
        task = self.hubs.workhub.stores.tasks.value().get(self.task_id) or {}
        self.assertEqual(task.get("status"), "in_progress",
                          "signal_only must leave the task untouched")
        # The escalation event still fires.
        types = [e.get("event_type")
                 for e in _events_for(self.hubs, "orchestrator")]
        self.assertIn("lane_halted_human", types)
        self.assertNotIn("lane_task_auto_failed", types)

    def test_tier3_idempotent_does_not_double_fail(self):
        """Once tier-3 fires the deterministic action, subsequent idle
        steps within the same tier crossing must not re-attempt the
        fail (or attempt to fail an already-failed task again)."""
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        self._drive_to_tier3(policy)
        # Drive 5 more idle steps after tier-3 hit.
        for _ in range(5):
            _run_finish(policy, self.agent)
        types = [e.get("event_type")
                 for e in _events_for(self.hubs, "orchestrator")]
        # Exactly one auto-failed event.
        self.assertEqual(types.count("lane_task_auto_failed"), 1)

    def test_no_op_when_lane_has_no_tasks_at_all(self):
        """Lane with no assigned tasks (claimed OR pending) gets the
        event but nothing to act on. Must not crash."""
        # Wipe the seeded claim by failing the task ourselves first.
        self.hubs.workhub.fail_task(self.task_id, "design", "test-setup", force=True)
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        self._drive_to_tier3(policy)
        types = [e.get("event_type")
                 for e in _events_for(self.hubs, "orchestrator")]
        self.assertIn("lane_halted_human", types)
        self.assertNotIn("lane_task_auto_failed", types)

    def test_tier3_cancels_assigned_but_unclaimed_pending_tasks(self):
        """Reviewer's catch: the observed deadlock was tasks stuck at
        ``status=pending, claimed_by=None`` because agents respond to
        ``task_ready`` messages without ever calling claim_task. Tier-3
        must reach those tasks too — via ``cancel_task`` since
        ``fail_task`` requires a claimer."""
        # Wipe the seeded claimed task; replace with the deadlock shape.
        self.hubs.workhub.fail_task(self.task_id, "design", "test-setup", force=True)
        t_unclaimed = self.hubs.workhub.create_task(
            title="Write spec.api.json (assigned-not-claimed)",
            assignee="design", agent="orchestrator",
        )
        # Deliberately do NOT claim_task — this is the observed shape.
        self.assertIsNone(t_unclaimed.get("claimed_by"))
        self.assertEqual(t_unclaimed.get("status"), "pending")

        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        # Fresh agent so prev_owned counter doesn't pick up unrelated state.
        agent = _StubAgent("design", self.hubs, self.tmp)
        # seed + 3 idle = tier-3
        _run_finish(policy, agent)
        for _ in range(3):
            _run_finish(policy, agent)

        # The pending task is now cancelled.
        task = self.hubs.workhub.stores.tasks.value().get(t_unclaimed["id"]) or {}
        self.assertEqual(task.get("status"), "cancelled",
                          "Tier-3 must cancel assigned-but-unclaimed tasks "
                          "to break the actual observed deadlock.")
        self.assertIn("tier-3", task.get("cancel_reason", ""))

        # Event payload mentions the cancelled id.
        evt = next(
            e for e in _events_for(self.hubs, "orchestrator")
            if e.get("event_type") == "lane_task_auto_failed"
        )
        payload = evt.get("payload") or {}
        self.assertIn(t_unclaimed["id"], payload.get("cancelled_task_ids") or [])
        self.assertEqual(payload.get("failed_task_ids") or [], [],
                          "Pending task should be cancelled, not failed.")

    def test_tier3_handles_mixed_claimed_and_unclaimed(self):
        """Lane has BOTH a claimed in_progress task AND an assigned
        pending one — both get cleared in a single tier-3 crossing."""
        # Already have one claimed in_progress (self.task_id, "design").
        t_pending = self.hubs.workhub.create_task(
            title="Second batch", assignee="design", agent="orchestrator",
        )
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        self._drive_to_tier3(policy)

        tasks = self.hubs.workhub.stores.tasks.value()
        self.assertEqual(tasks[self.task_id].get("status"), "failed")
        self.assertEqual(tasks[t_pending["id"]].get("status"), "cancelled")

        evt = next(
            e for e in _events_for(self.hubs, "orchestrator")
            if e.get("event_type") == "lane_task_auto_failed"
        )
        p = evt.get("payload") or {}
        self.assertIn(self.task_id, p.get("failed_task_ids") or [])
        self.assertIn(t_pending["id"], p.get("cancelled_task_ids") or [])

    def test_recovered_then_restuck_lane_can_re_fail_on_new_tier3(self):
        """Productive step resets the sentinel; if the lane sticks
        again the breaker re-arms and fires another deterministic
        action on the next tier-3 crossing."""
        policy = _make_policy(
            warn_after_idle_steps=1, failforward_after_idle_steps=2,
            halt_after_idle_steps=3,
        )
        # First tier-3 (with the seeded task).
        self._drive_to_tier3(policy)
        # Lane recovers — productive finish.
        _run_finish(policy, self.agent, files_created=["app/design/notes.md"])
        # Orchestrator creates a fresh task for the lane.
        task2 = self.hubs.workhub.create_task(
            title="Round 2", assignee="design", agent="orchestrator",
        )
        self.hubs.workhub.claim_task(task2["id"], "design")
        # Now goes idle again.
        for _ in range(3):
            _run_finish(policy, self.agent)
        # Both tasks failed.
        states = {tid: t.get("status")
                  for tid, t in self.hubs.workhub.stores.tasks.value().items()
                  if isinstance(t, dict)}
        self.assertEqual(states.get(self.task_id), "failed")
        self.assertEqual(states.get(task2["id"]), "failed")


class HaltActionValidation(unittest.TestCase):
    def test_invalid_halt_action_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            _make_policy(halt_action="explode_run")


class FactoryWiring(unittest.TestCase):
    def test_factory_constructs_from_yaml(self):
        from multi_agent.workflow_policies import (
            create_workflow_policies, LaneIdleCircuitBreakerPolicy,
        )
        cfg = {"workflow_policies": [
            {"kind": "lane_idle_circuit_breaker",
             "warn_after_idle_steps": 3,
             "failforward_after_idle_steps": 5,
             "halt_after_idle_steps": 8,
             "halt_action": "signal_only"},
        ]}
        policies = create_workflow_policies(cfg)
        ms = [p for p in policies if isinstance(p, LaneIdleCircuitBreakerPolicy)]
        self.assertEqual(len(ms), 1)
        p = ms[0]
        self.assertEqual(p.warn_after_idle_steps, 3)
        self.assertEqual(p.failforward_after_idle_steps, 5)
        self.assertEqual(p.halt_after_idle_steps, 8)
        self.assertEqual(p.halt_action, "signal_only")

    def test_factory_default_halt_action_is_fail_task(self):
        from multi_agent.workflow_policies import (
            create_workflow_policies, LaneIdleCircuitBreakerPolicy,
        )
        cfg = {"workflow_policies": [{"kind": "lane_idle_circuit_breaker"}]}
        policies = create_workflow_policies(cfg)
        p = next(p for p in policies if isinstance(p, LaneIdleCircuitBreakerPolicy))
        self.assertEqual(p.halt_action, "fail_task")


class KickoffPhaseSuppression(unittest.TestCase):
    """smoke #4: the breaker must NOT count idle DURING kickoff — a lane doing
    bounded reply work finishes without files/owned-hub growth, and counting that
    as idle fails it forward mid-kickoff and stalls the meeting."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.hubs = HubRegistry(self.tmp)

    def _finish(self, agent, policy):
        return asyncio.run(policy.handle_finish(
            agent, tool_name="finish", tool_args={}, tool_call=None,
            tool_call_id="", messages=[], files_created=[], files_modified=[],
        ))

    def test_not_bootstrapped_lane_never_escalates_on_idle(self):
        policy = _make_policy(warn_after_idle_steps=1, failforward_after_idle_steps=2,
                              halt_after_idle_steps=3)
        agent = _StubAgent("frontend", self.hubs, self.tmp)
        agent._kickoff_bootstrapped = False   # still in kickoff
        # Many idle finishes — none should escalate while un-bootstrapped.
        for _ in range(6):
            self.assertIsNone(self._finish(agent, policy))
        # idle counter never advanced past the suppression guard
        self.assertEqual(getattr(agent, "_consecutive_idle_steps", 0), 0)
        self.assertEqual(getattr(agent, "_last_idle_tier", 0), 0)


if __name__ == "__main__":
    unittest.main()
