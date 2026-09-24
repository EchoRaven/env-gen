"""Tests for EventHub catch-up inbox semantics under offline-then-online pattern.

These tests verify the existing contract: events published while an agent is
"offline" (not registered to MessageBus) are durable in EventHub and can be
retrieved via list_inbox after the agent comes online.

Tests are expected to PASS against the current EventHub implementation.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


def _hub() -> EventHub:
    tmp = tempfile.mkdtemp()
    return EventHub(Path(tmp))


class TestEventHubSpawnCatchup(unittest.TestCase):
    """Verify EventHub durable inbox semantics for offline agents."""

    def test_offline_events_visible_in_inbox(self):
        """Events published with recipients=[agent_id] while agent is offline
        must appear in list_inbox(agent, unread_only=True) after agent comes online.
        """
        hub = _hub()
        agent_id = "backend-agent-1"

        # Agent is "offline" — no MessageBus registration, no bridge attached.
        # Publish two events addressed to the agent.
        evt1 = hub.publish_event(
            "registryhub",
            "breaking_change_detected",
            {"api": "GET /users"},
            recipients=[agent_id],
        )
        evt2 = hub.publish_event(
            "workhub",
            "task_assigned",
            {"task_id": "t-42"},
            recipients=[agent_id],
        )

        # Agent "comes online" — reads its inbox.
        inbox = hub.list_inbox(agent_id, unread_only=True)
        inbox_ids = {e["id"] for e in inbox}

        self.assertIn(evt1["id"], inbox_ids, "First offline event must be in unread inbox")
        self.assertIn(evt2["id"], inbox_ids, "Second offline event must be in unread inbox")

    def test_mark_read_excludes_from_unread_inbox(self):
        """After mark_read, the read event must not appear in unread inbox."""
        hub = _hub()
        agent_id = "frontend-agent-2"

        evt1 = hub.publish_event(
            "registryhub",
            "spec_changed",
            {"version": "v2"},
            recipients=[agent_id],
        )
        evt2 = hub.publish_event(
            "workhub",
            "comment_added",
            {"thread": "t-7"},
            recipients=[agent_id],
        )

        # Mark first event as read.
        hub.mark_read(agent_id, evt1["id"])

        unread = hub.list_inbox(agent_id, unread_only=True)
        unread_ids = {e["id"] for e in unread}

        self.assertNotIn(evt1["id"], unread_ids, "Read event must not appear in unread inbox")
        self.assertIn(evt2["id"], unread_ids, "Unread event must still appear in unread inbox")

        # Verify it does appear when unread_only=False.
        all_items = hub.list_inbox(agent_id, unread_only=False)
        all_ids = {e["id"] for e in all_items}
        self.assertIn(evt1["id"], all_ids, "Read event must still appear in full inbox")

    def test_inbox_newest_first_ordering(self):
        """list_inbox returns events newest-first (sorted by created_at descending)."""
        hub = _hub()
        agent_id = "scheduler-agent-3"

        # Publish three events in sequence.
        evt1 = hub.publish_event("workhub", "task_created", {"n": 1}, recipients=[agent_id])
        evt2 = hub.publish_event("workhub", "task_created", {"n": 2}, recipients=[agent_id])
        evt3 = hub.publish_event("workhub", "task_created", {"n": 3}, recipients=[agent_id])

        inbox = hub.list_inbox(agent_id, unread_only=True)
        self.assertEqual(len(inbox), 3, "All three events must appear in inbox")

        timestamps = [e.get("created_at", 0) for e in inbox]
        self.assertEqual(
            timestamps,
            sorted(timestamps, reverse=True),
            "Inbox must be sorted newest-first by created_at",
        )

        # The most recent event should be first.
        self.assertEqual(inbox[0]["id"], evt3["id"], "Newest event must be first in inbox")


if __name__ == "__main__":
    unittest.main()
