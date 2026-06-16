"""PR 2.5 of the hub-responsibility-split plan
(``docs/hub_responsibility_split_plan.md``, reviewer Q5).

Tier-3 of the lane-idle circuit breaker cancels unclaimed assigned
tasks reactively — but that's the *escalation*. The root cause is
that agents finish rounds while leaving pending tasks unclaimed in
their queue. This finish-gate makes it impossible: the agent
literally can't end the round while the queue has assigned-pending
tasks with ``claimed_by`` empty. They must either claim (and act)
or cancel (and explain).

Test shape mirrors ``test_hub_consistency_policy.py``: stub agent,
real ``HubRegistry`` rooted in a tempdir, exercise each branch.
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
from multi_agent.workflow_policies import ClaimAssignedTasksPolicy  # noqa: E402


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class _StubAgent:
    def __init__(self, agent_id, reg):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self.workspace = MagicMock()
        self._hubs = reg
        self._logger = MagicMock()


class _StubToolCall:
    """Mirrors what _apply_finish_policies passes for tool_call.
    The policy only needs it as an opaque value to attach to the
    rejection message."""
    def __init__(self):
        self.id = "call-1"
        self.function = MagicMock()
        self.function.name = "finish"
        self.function.arguments = "{}"


class TestPolicyShape(unittest.TestCase):
    """Shape parity with HubConsistencyPolicy: non-finish call → None,
    no hubs → None, no matching tasks → None."""

    def tearDown(self):
        _reset_event_loop()

    def _run(self, agent, tool_name="finish"):
        return asyncio.run(ClaimAssignedTasksPolicy().handle_finish(
            agent,
            tool_name=tool_name,
            tool_args={"message": "done"},
            tool_call=_StubToolCall(),
            tool_call_id="call-1",
            messages=[],
            files_created=[],
            files_modified=[],
        ))

    def test_non_finish_call_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            outcome = self._run(agent, tool_name="write")
            self.assertIsNone(outcome)

    def test_no_workhub_handle_returns_none(self):
        """If the agent has no _hubs (or hubs has no workhub), the
        policy must not block — same conservative posture as
        HubConsistencyPolicy when the registry isn't wired up yet."""
        agent = _StubAgent("backend", None)
        outcome = self._run(agent)
        self.assertIsNone(outcome)

    def test_empty_queue_returns_none(self):
        """No assigned tasks → no rejection."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            outcome = self._run(agent)
            self.assertIsNone(outcome)


class TestPolicyFiresOnUnclaimedAssigned(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def _build_agent(self, tmp, agent_id="backend"):
        reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
        return _StubAgent(agent_id, reg), reg

    def _run(self, agent):
        msgs = []
        outcome = asyncio.run(ClaimAssignedTasksPolicy().handle_finish(
            agent,
            tool_name="finish",
            tool_args={"message": "done"},
            tool_call=_StubToolCall(),
            tool_call_id="call-1",
            messages=msgs,
            files_created=[],
            files_modified=[],
        ))
        return outcome, msgs

    def test_unclaimed_pending_blocks_finish(self):
        """The canonical failure case the reviewer named: task is
        assigned to me, status='pending', claimed_by is empty.
        Finish must be blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp)
            reg.workhub.create_task(
                title="Implement /api/posts",
                description="add the routes",
                agent="orchestrator",
                assignee="backend",
            )
            outcome, msgs = self._run(agent)
            self.assertIsNotNone(outcome)
            self.assertEqual(outcome.get("action"), "continue")
            # 3 messages injected: assistant tool_call + tool rejection
            # + user-side prod to act. Same shape as HubConsistencyPolicy.
            self.assertEqual(len(msgs), 3)
            blob = " ".join(getattr(m, "content", "") or "" for m in msgs)
            self.assertIn("claim", blob.lower())
            self.assertIn("cancel", blob.lower())
            self.assertIn("/api/posts", blob)

    def test_claimed_in_progress_task_does_not_block(self):
        """If the agent has already claimed (and is working on) the
        task, that's the *desired* state — finish must not block.
        The whole point of the gate is to force claim/cancel."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp)
            task = reg.workhub.create_task(
                title="Implement /api/users",
                description="add the routes",
                agent="orchestrator",
                assignee="backend",
            )
            # Claim — status becomes in_progress, claimed_by=backend.
            reg.workhub.claim_task(task["id"], "backend")
            outcome, _ = self._run(agent)
            self.assertIsNone(outcome)

    def test_task_assigned_to_someone_else_does_not_block_me(self):
        """A task assigned to ``frontend`` must not block ``backend``
        from finishing. Per-agent scoping — the gate is about your
        own queue, not the global queue."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp, agent_id="backend")
            reg.workhub.create_task(
                title="Build the login form",
                description="...",
                agent="orchestrator",
                assignee="frontend",  # different agent
            )
            outcome, _ = self._run(agent)
            self.assertIsNone(outcome)

    def test_completed_task_does_not_block(self):
        """A finished task with status!='pending' must not block."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp)
            task = reg.workhub.create_task(
                title="ship the auth feature",
                description="...",
                agent="orchestrator",
                assignee="backend",
            )
            reg.workhub.claim_task(task["id"], "backend")
            reg.workhub.complete_task(task["id"], "backend")
            outcome, _ = self._run(agent)
            self.assertIsNone(outcome)

    def test_message_lists_task_id_and_title(self):
        """The rejection must name each blocking task by id and title
        so the agent has actionable info — not just a count."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp)
            t1 = reg.workhub.create_task(
                title="route X", description="...",
                agent="orchestrator", assignee="backend",
            )
            t2 = reg.workhub.create_task(
                title="route Y", description="...",
                agent="orchestrator", assignee="backend",
            )
            outcome, msgs = self._run(agent)
            self.assertIsNotNone(outcome)
            blob = " ".join(getattr(m, "content", "") or "" for m in msgs)
            self.assertIn(t1["id"], blob)
            self.assertIn(t2["id"], blob)
            self.assertIn("route X", blob)
            self.assertIn("route Y", blob)

    def test_truncates_long_lists_but_reports_remainder_count(self):
        """When the queue is huge, the message lists the first N and
        shows a (+M more) suffix so the rejection stays readable."""
        with tempfile.TemporaryDirectory() as tmp:
            agent, reg = self._build_agent(tmp)
            # 12 tasks > _MAX_LISTED (8)
            for i in range(12):
                reg.workhub.create_task(
                    title=f"task-{i}", description="...",
                    agent="orchestrator", assignee="backend",
                )
            outcome, msgs = self._run(agent)
            self.assertIsNotNone(outcome)
            blob = " ".join(getattr(m, "content", "") or "" for m in msgs)
            self.assertIn("12 task", blob)
            self.assertIn("more not shown", blob)


class TestPriorityOrdering(unittest.TestCase):
    """Pin the rejection ordering: P0 → P3 → created_at. Same shape
    as ``list_ready_tasks`` so the agent sees a queue in the order
    they'd naturally work it."""

    def tearDown(self):
        _reset_event_loop()

    def test_p0_tasks_listed_before_p2_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            # Create P2 first (older), then P0 (newer) — order in
            # rejection must still be P0 first.
            reg.workhub.create_task(
                title="cosmetic-typo", description="...",
                agent="orchestrator", assignee="backend",
                priority="P2",
            )
            reg.workhub.create_task(
                title="prod-outage-fix", description="...",
                agent="orchestrator", assignee="backend",
                priority="P0",
            )
            policy = ClaimAssignedTasksPolicy()
            tasks = policy._collect_unclaimed_assigned(reg.workhub, "backend")
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["title"], "prod-outage-fix")
            self.assertEqual(tasks[1]["title"], "cosmetic-typo")


class TestBuilderWiring(unittest.TestCase):
    """Per-profile YAML wiring: the kind→class builder must recognize
    ``claim_assigned_tasks`` so agents_config.yaml can opt agents in."""

    def test_kind_resolves_to_policy(self):
        from multi_agent.workflow_policies import create_workflow_policies
        policies = create_workflow_policies({
            "workflow_policies": [{"kind": "claim_assigned_tasks"}],
        })
        # exactly one of the returned policies must be ours.
        self.assertTrue(
            any(isinstance(p, ClaimAssignedTasksPolicy) for p in policies),
            f"claim_assigned_tasks kind didn't resolve. Got: {policies}",
        )


if __name__ == "__main__":
    unittest.main()
