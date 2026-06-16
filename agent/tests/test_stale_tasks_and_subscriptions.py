"""Stale-task detection (orchestrator nudges stuck assignees) and the
expanded DEFAULT_SUBSCRIPTIONS that wake backend/frontend/etc. on
hub events without requiring an explicit recipient list.

Two structural fixes surfaced by the end-to-end thought-experiment:
"orchestrator → design → backend wakeup chain", where:
  * design used to never get its task nudged when stuck
  * backend / frontend / verifier never received endpoint events
    unless someone happened to include them as a recipient.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS, ensure_default_subscriptions,
)
from multi_agent.agents.runtime.hub_pulse import (  # noqa: E402
    collect_hub_pulse, build_hub_pulse_prompt,
)


class StaleTaskDetection(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="stale_"))
        self.hubs = HubRegistry(self.tmp)

    def test_no_stale_when_just_created(self) -> None:
        self.hubs.workhub.create_task(
            title="design API", assignee="design", agent="orchestrator")
        self.assertEqual(self.hubs.workhub.list_stale_tasks(), [])

    def test_pending_task_unclaimed_past_threshold_is_stale(self) -> None:
        t = self.hubs.workhub.create_task(
            title="design API", assignee="design", agent="orchestrator")
        # Simulate "15 min ago"
        future = float(t["created_at"]) + 1000.0
        stale = self.hubs.workhub.list_stale_tasks(
            stale_seconds_pending=900.0, now_ts=future,
        )
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["stale_reason"], "unclaimed")
        self.assertEqual(stale[0]["assignee"], "design")

    def test_in_progress_task_idle_past_threshold_is_stale(self) -> None:
        t = self.hubs.workhub.create_task(
            title="design API", assignee="design", agent="orchestrator")
        self.hubs.workhub.claim_task(t["id"], "design")
        future = time.time() + 2000.0
        stale = self.hubs.workhub.list_stale_tasks(
            stale_seconds_in_progress=1800.0, now_ts=future,
        )
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["stale_reason"], "no_progress")

    def test_completed_task_is_never_stale(self) -> None:
        t = self.hubs.workhub.create_task(
            title="x", assignee="design", agent="orchestrator")
        self.hubs.workhub.claim_task(t["id"], "design")
        self.hubs.workhub.complete_task(t["id"], "design", result={"ok": True})
        future = time.time() + 10000.0
        self.assertEqual(self.hubs.workhub.list_stale_tasks(now_ts=future), [])

    def test_unassigned_task_is_not_flagged_as_stale(self) -> None:
        """Unassigned pending tasks belong to orchestrator routing, not
        agent slowness — they're a different problem."""
        self.hubs.workhub.create_task(
            title="floating", assignee=None, agent="orchestrator")
        future = time.time() + 100000.0
        self.assertEqual(self.hubs.workhub.list_stale_tasks(now_ts=future), [])


class OrchestratorPulseSurfacesStaleTasks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="stale_pulse_"))
        self.hubs = HubRegistry(self.tmp)
        t = self.hubs.workhub.create_task(
            title="design the API spec", assignee="design",
            agent="orchestrator",
        )
        # Force the created_at into the past so list_stale_tasks fires
        # without us having to wait or inject now_ts (collect_hub_pulse
        # calls list_stale_tasks with no now_ts override).
        tasks = self.hubs.workhub.stores.tasks.value()
        tasks[t["id"]]["created_at"] = time.time() - 99999.0
        self.hubs.workhub.stores.tasks.update(
            lambda m: m.set(t["id"], tasks[t["id"]], "test"),
            change_info={"agent": "test"},
        )

    def test_orchestrator_sees_stale_tasks_in_pulse(self) -> None:
        pulse = collect_hub_pulse(self.hubs, agent_id="orchestrator", step_num=1)
        self.assertIn("stale_tasks", pulse)
        self.assertGreaterEqual(len(pulse["stale_tasks"]), 1)
        prompt = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(prompt)
        self.assertIn("STALE TASKS", prompt)
        self.assertIn("design", prompt)

    def test_non_orchestrator_does_not_see_global_stale_list(self) -> None:
        pulse = collect_hub_pulse(self.hubs, agent_id="backend", step_num=1)
        self.assertEqual(pulse["stale_tasks"], [])


class DefaultSubscriptionsWakeAgents(unittest.TestCase):
    """The expanded DEFAULT_SUBSCRIPTIONS wire backend/frontend/orchestrator
    to push-events they previously had to poll for."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="subs_"))
        self.hubs = HubRegistry(self.tmp)

    def test_backend_subscribes_to_endpoint_defined(self) -> None:
        self.assertIn("backend", DEFAULT_SUBSCRIPTIONS)
        types = {(s[0], s[1]) for s in DEFAULT_SUBSCRIPTIONS["backend"]}
        self.assertIn(("registryhub", "endpoint_defined"), types)

    def test_design_does_not_subscribe_to_raw_bug_found(self) -> None:
        """Design profile was removed in the kickoff-refactor (2026-06-02);
        ensure it stays absent from DEFAULT_SUBSCRIPTIONS so we don't
        accidentally re-introduce a dangling subscription that wakes a
        non-existent agent."""
        self.assertNotIn(
            "design", DEFAULT_SUBSCRIPTIONS,
            "design profile is gone; DEFAULT_SUBSCRIPTIONS should not "
            "carry an entry for it.",
        )

    def test_orchestrator_subscribes_to_merge_conflict(self) -> None:
        types = {(s[0], s[1]) for s in DEFAULT_SUBSCRIPTIONS["orchestrator"]}
        self.assertIn(("codehub", "merge_conflict"), types)
        self.assertIn(("workhub", "task_failed"), types)
        self.assertIn(("workhub", "task_stale"), types)

    def test_ensure_default_subscriptions_installs_them_idempotently(self) -> None:
        ensure_default_subscriptions(self.hubs, "backend")
        ensure_default_subscriptions(self.hubs, "backend")  # again
        subs = self.hubs.eventhub.get_subscriptions(agent="backend")
        # Should match the catalogue size — no duplicates from the second call.
        expected_count = len(DEFAULT_SUBSCRIPTIONS["backend"])
        self.assertEqual(len(subs), expected_count)

    def test_endpoint_defined_reaches_subscribed_backend(self) -> None:
        """Design registers an endpoint with no explicit recipient; backend
        should still receive it because of the default subscription."""
        ensure_default_subscriptions(self.hubs, "backend")
        # Design registers a fresh endpoint with no consumers yet.
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts", schema={"response": {"id": "string"}},
            provider="backend", agent="backend", status="defined",
        )
        inbox = self.hubs.eventhub.list_inbox("backend", unread_only=True)
        types = {e.get("event_type") for e in inbox}
        self.assertIn("endpoint_defined", types,
                      f"backend inbox missing endpoint_defined: {types}")


if __name__ == "__main__":
    unittest.main()
