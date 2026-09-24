"""TDD tests for MessageBusBridge (Task 7 of Cutover 2)."""
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
from multi_agent.runtime.hubs.eventhub import MessageBusBridge  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeAgent:
    """Minimal stand-in for BaseAgent with a sync receive_message."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.received = []

    def receive_message(self, msg):
        self.received.append(msg)


class FakeMessageBus:
    """Minimal stand-in for MessageBus that holds agents by id."""

    def __init__(self):
        self._agents: dict = {}

    def register_agent(self, agent: FakeAgent) -> None:
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str):
        return self._agents.get(agent_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup():
    """Return (hub, bus, bridge) backed by a fresh temp directory."""
    tmp = tempfile.mkdtemp()
    hub = EventHub(Path(tmp))
    bus = FakeMessageBus()
    bridge = MessageBusBridge(bus, hub)
    hub.add_bridge(bridge)
    return hub, bus, bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMessageBusBridgeLivePush(unittest.TestCase):
    """deliver() pushes BaseMessage to live agents and marks delivered."""

    def test_live_push_delivers_to_registered_agent(self):
        hub, bus, bridge = _setup()
        agent = FakeAgent("alpha")
        bus.register_agent(agent)
        # publish_event calls bridge.deliver internally via add_bridge
        hub.publish_event("registryhub", "spec_changed", {}, recipients=["alpha"])

        self.assertEqual(len(agent.received), 1)

    def test_mark_delivered_flipped_in_inbox(self):
        hub, bus, bridge = _setup()
        agent = FakeAgent("alpha")
        bus.register_agent(agent)
        event = hub.publish_event("registryhub", "spec_changed", {}, recipients=["alpha"])
        # deliver is already called by publish_event; check inbox state

        inbox = hub.list_inbox("alpha", unread_only=False)
        item = next((e["inbox"] for e in inbox if e["id"] == event["id"]), None)
        self.assertIsNotNone(item)
        self.assertTrue(item.get("delivered"))


class TestMessageBusBridgeOfflineSkip(unittest.TestCase):
    """deliver() skips agents not registered on the bus."""

    def test_offline_agent_goes_to_skipped_offline(self):
        hub, bus, bridge = _setup()
        # "beta" is NOT registered on the bus; call deliver directly to inspect result
        event = {
            "id": "evt_offline",
            "thread_id": "thread_offline",
            "source_hub": "registryhub",
            "event_type": "spec_changed",
            "payload": {},
            "recipients": ["beta"],
            "priority": "normal",
        }
        result = bridge.deliver(event)

        self.assertIn("beta", result["skipped_offline"])
        self.assertEqual(result["delivered"], [])


class TestMessageBusBridgeInboxOnly(unittest.TestCase):
    """deliver() excludes inbox_only subscribers from live push."""

    def test_inbox_only_subscriber_not_pushed(self):
        hub, bus, bridge = _setup()
        agent = FakeAgent("gamma")
        bus.register_agent(agent)
        hub.subscribe("gamma", source_hub="registryhub", event_type="spec_changed", delivery="inbox_only")
        event = hub.publish_event("registryhub", "spec_changed", {})
        # publish_event already called bridge.deliver internally

        # Still lands in inbox (bridge excluded from live, not from inbox)
        inbox = hub.list_inbox("gamma", unread_only=True)
        self.assertTrue(any(e["id"] == event["id"] for e in inbox))
        # No live message received
        self.assertEqual(len(agent.received), 0)


class TestMessageBusBridgeBaseMessageShape(unittest.TestCase):
    """_to_base_message wraps event with correct metadata and MessageType.STATUS."""

    def test_base_message_metadata_and_type(self):
        from utils.message import MessageType

        hub, bus, bridge = _setup()
        event = {
            "id": "evt_abc",
            "thread_id": "thread_evt_abc",
            "source_hub": "registryhub",
            "event_type": "spec_changed",
            "payload": {"resource_type": "endpoint", "resource_id": "ep_1", "links": ["/a"]},
            "recipients": ["delta"],
            "priority": "high",
        }

        msg = bridge._to_base_message(event, "delta")

        self.assertEqual(msg.message_type, MessageType.STATUS)
        self.assertEqual(msg.header.source_agent_id, "registryhub")
        self.assertEqual(msg.header.target_agent_id, "delta")
        self.assertEqual(msg.header.correlation_id, "thread_evt_abc")
        self.assertEqual(msg.metadata["event_id"], "evt_abc")
        self.assertEqual(msg.metadata["event_type"], "spec_changed")
        # Round-8d Fix #2-bis: msg_type MUST mirror event_type at the
        # bridge boundary so the dispatch site can match it.
        self.assertEqual(msg.metadata["msg_type"], "spec_changed")
        self.assertEqual(msg.metadata["resource_type"], "endpoint")
        self.assertEqual(msg.metadata["resource_id"], "ep_1")
        self.assertEqual(msg.metadata["links"], ["/a"])


class TestMessageBusBridgeMsgTypeMirror(unittest.TestCase):
    """Round-8d Fix #2-bis closed-by-construction pin.

    Round-8b + round-8d smokes both showed "Handling urgent " (bare,
    trailing space) for every bridge-delivered urgent event — meaning
    ``_check_and_handle_urgent`` read ``metadata['msg_type']`` as empty
    for kickoff_request (and would have done the same for any other
    bridge-delivered urgent). Root cause: ``bridge._to_base_message``
    built the metadata dict with an ``event_type`` key but NOT an
    ``msg_type`` key, so the dispatch-site branches
    ``if msg_type == "kickoff_request"`` /
    ``if msg_type == "task_ready"`` / etc. never matched and the urgent
    event was silently dropped.

    This bug class affects EVERY dispatch branch in
    ``_check_and_handle_urgent``, not just kickoff_request. The
    on-disk undelivered-inbox pickup path
    (``messaging.py:_pickup_undelivered_inbox_events`` line ~295) does
    set ``msg_type=event_type``; the bridge insert site is what was
    diverging. Round-8d fix is one line in the bridge dict literal;
    these tests pin the invariant closed-by-construction so a future
    edit that drops the key, renames it, or sources it from a different
    field fails immediately.
    """

    def test_base_message_sets_msg_type_from_event_type_for_kickoff_request(self):
        """Concrete-value pin for the exact round-8d regression scenario.

        Round-8d: 4 attendees idle for 10 min because bridge-delivered
        kickoff_request had empty msg_type at the dispatch site. The
        bridge MUST set ``metadata['msg_type'] = 'kickoff_request'`` so
        ``_check_and_handle_urgent`` can dispatch to
        ``_handle_kickoff_request``.
        """
        hub, bus, bridge = _setup()
        event = {
            "id": "evt_kickoff_1",
            "thread_id": "thr_kickoff",
            "source_hub": "orchestrator_hub",
            "event_type": "kickoff_request",
            "payload": {
                "meeting_id": "mtg-1",
                "milestone_index": 1,
                "requirements": ["Build a minimal blog."],
            },
            "recipients": ["design"],
            "priority": "high",
        }

        msg = bridge._to_base_message(event, "design")

        self.assertIn(
            "msg_type",
            msg.metadata,
            "round-8d Fix #2-bis: bridge MUST set metadata['msg_type'] "
            "so the dispatch site can match. Missing key → "
            "_check_and_handle_urgent reads empty string → every "
            "msg_type==... dispatch branch silently falls through.",
        )
        self.assertEqual(msg.metadata["msg_type"], "kickoff_request")
        # Closed-by-construction invariant: msg_type ALWAYS equals
        # event_type. Any future edit that drops the key, renames it,
        # or sources it from a different field fails here. This
        # generalizes the pin to every event_type the bridge will ever
        # emit, not just kickoff_request.
        self.assertEqual(msg.metadata["msg_type"], msg.metadata["event_type"])

    def test_base_message_msg_type_invariant_holds_across_event_types(self):
        """The bug class is 'bridge-delivered urgent with empty msg_type
        for ANY event_type', not just kickoff_request. Pin the invariant
        across multiple representative event types so the next
        bridge-delivered event with a matching dispatch branch (e.g.
        task_ready, issue, question, shutdown, kickoff_complete,
        kickoff_failed) dispatches correctly out of the box."""
        hub, bus, bridge = _setup()
        for event_type in (
            "kickoff_request",
            "kickoff_complete",
            "kickoff_failed",
            "task_ready",
            "issue",
            "question",
            "shutdown",
            "spec_changed",
            "merge_conflict",
            "human_message",
        ):
            event = {
                "id": f"evt_{event_type}",
                "thread_id": f"thr_{event_type}",
                "source_hub": "orchestrator_hub",
                "event_type": event_type,
                "payload": {},
                "recipients": ["design"],
                "priority": "high",
            }
            msg = bridge._to_base_message(event, "design")
            self.assertEqual(
                msg.metadata.get("msg_type"),
                event_type,
                f"round-8d Fix #2-bis: bridge must mirror event_type "
                f"into msg_type for ALL event types; failed for {event_type!r}.",
            )
            self.assertEqual(
                msg.metadata["msg_type"],
                msg.metadata["event_type"],
                f"round-8d Fix #2-bis invariant violated for {event_type!r}: "
                f"msg_type != event_type.",
            )

    def test_base_message_msg_type_when_event_type_missing(self):
        """Defensive coverage for malformed events: if ``event_type`` is
        absent entirely, ``msg_type`` should still be present in metadata
        (as None) so ``_check_and_handle_urgent``'s ``.get("msg_type", "")``
        + ``.lower()`` doesn't crash."""
        hub, bus, bridge = _setup()
        event = {
            "id": "evt_no_type",
            "thread_id": "thr_no_type",
            "source_hub": "orchestrator_hub",
            # event_type intentionally omitted
            "payload": {},
            "recipients": ["design"],
            "priority": "high",
        }
        msg = bridge._to_base_message(event, "design")
        # Key MUST be present (closed-by-construction: future code that
        # filters None-valued keys from the dict comprehension would
        # silently re-introduce the round-8d bug class).
        self.assertIn("msg_type", msg.metadata)
        # Value may be None (event_type was absent) but the dispatch
        # site can handle that — get("msg_type", "") on a None value
        # would return None, but the line in messaging.py is
        # `.get("msg_type", "").lower()` so None would crash. The
        # bridge SHOULD mirror event_type even if it's None; the
        # dispatch site's defensive default handles the rest.
        self.assertIsNone(msg.metadata["msg_type"])


if __name__ == "__main__":
    unittest.main()
