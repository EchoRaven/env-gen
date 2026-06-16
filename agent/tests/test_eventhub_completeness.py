"""TDD tests for EventHub spec completeness (Tasks 2-4 of Cutover 2)."""
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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


def _hub() -> EventHub:
    tmp = tempfile.mkdtemp()
    return EventHub(Path(tmp))


# ---------------------------------------------------------------------------
# Task 2: Reshape subscribe to spec model
# ---------------------------------------------------------------------------

class TestSubscribeSpec(unittest.TestCase):
    def test_subscribe_6arg_signature_and_fields(self):
        """subscribe returns a Subscription with all spec fields."""
        hub = _hub()
        sub = hub.subscribe(
            agent="backend",
            source_hub="registryhub",
            event_type="breaking_change_detected",
            filter={"linked_apis_provider": "backend"},
            priority_floor="normal",
            delivery="live",
        )
        self.assertEqual(sub["agent"], "backend")
        self.assertEqual(sub["source_hub"], "registryhub")
        self.assertEqual(sub["event_type"], "breaking_change_detected")
        self.assertEqual(sub["filter"], {"linked_apis_provider": "backend"})
        self.assertEqual(sub["priority_floor"], "normal")
        self.assertEqual(sub["delivery"], "live")
        self.assertIn("id", sub)
        self.assertIn("created_at", sub)

    def test_subscribe_wildcard_defaults(self):
        """subscribe defaults: source_hub='*', event_type='*', priority_floor='low', delivery='live'."""
        hub = _hub()
        sub = hub.subscribe("frontend")
        self.assertEqual(sub["source_hub"], "*")
        self.assertEqual(sub["event_type"], "*")
        self.assertIsNone(sub["filter"])
        self.assertEqual(sub["priority_floor"], "low")
        self.assertEqual(sub["delivery"], "live")


# ---------------------------------------------------------------------------
# Task 3: unsubscribe + get_subscriptions
# ---------------------------------------------------------------------------

class TestUnsubscribeAndGetSubscriptions(unittest.TestCase):
    def test_unsubscribe_returns_true_and_soft_deletes(self):
        """unsubscribe marks the subscription _removed=True and returns True."""
        hub = _hub()
        sub = hub.subscribe("alpha", source_hub="registryhub")
        result = hub.unsubscribe(sub["id"])
        self.assertTrue(result)
        # get_subscriptions must not return removed entries
        subs = hub.get_subscriptions()
        self.assertFalse(any(s["id"] == sub["id"] for s in subs))

    def test_unsubscribe_nonexistent_returns_false(self):
        """unsubscribe on a missing id returns False (not an error)."""
        hub = _hub()
        result = hub.unsubscribe("no-such-id")
        self.assertFalse(result)

    def test_get_subscriptions_filters_by_agent(self):
        """get_subscriptions(agent=X) returns only X's active subscriptions."""
        hub = _hub()
        hub.subscribe("alpha", source_hub="registryhub")
        hub.subscribe("beta", source_hub="workhub")
        hub.subscribe("alpha", source_hub="codehub")
        alpha_subs = hub.get_subscriptions(agent="alpha")
        self.assertEqual(len(alpha_subs), 2)
        self.assertTrue(all(s["agent"] == "alpha" for s in alpha_subs))


# ---------------------------------------------------------------------------
# Task 4: mark_delivered / mark_all_read / get_event / get_thread
# ---------------------------------------------------------------------------

class TestMarkDeliveredAndRead(unittest.TestCase):
    def test_mark_delivered_flips_delivered_not_read(self):
        """mark_delivered sets delivered=True and delivered_at but leaves read=False."""
        hub = _hub()
        event = hub.publish_event("registryhub", "test_event", {}, recipients=["alpha"])
        result = hub.mark_delivered("alpha", event["id"])
        self.assertTrue(result.get("delivered"))
        self.assertIn("delivered_at", result)
        self.assertFalse(result.get("read", True))  # read must stay False

    def test_mark_delivered_nonexistent_event_returns_error(self):
        """mark_delivered on missing event_id returns dict with 'error' key."""
        hub = _hub()
        result = hub.mark_delivered("alpha", "evt_doesnotexist")
        self.assertIn("error", result)

    def test_mark_all_read_returns_count(self):
        """mark_all_read returns the number of items flipped to read."""
        hub = _hub()
        hub.publish_event("registryhub", "ev1", {}, recipients=["alpha"])
        hub.publish_event("registryhub", "ev2", {}, recipients=["alpha"])
        hub.publish_event("registryhub", "ev3", {}, recipients=["beta"])  # different agent
        count = hub.mark_all_read("alpha")
        self.assertEqual(count, 2)

    def test_mark_all_read_before_ts(self):
        """mark_all_read with before_ts only marks items received before that timestamp."""
        hub = _hub()
        hub.publish_event("registryhub", "early", {}, recipients=["alpha"])
        cutoff = time.time()
        time.sleep(0.01)
        hub.publish_event("registryhub", "late", {}, recipients=["alpha"])
        count = hub.mark_all_read("alpha", before_ts=cutoff)
        self.assertEqual(count, 1)

    def test_get_event_returns_event(self):
        """get_event returns the stored event dict."""
        hub = _hub()
        event = hub.publish_event("registryhub", "my_event", {"k": "v"}, recipients=["alpha"])
        fetched = hub.get_event(event["id"])
        self.assertEqual(fetched["id"], event["id"])
        self.assertEqual(fetched["payload"], {"k": "v"})

    def test_get_event_missing_returns_none(self):
        """get_event returns None for an unknown event_id."""
        hub = _hub()
        self.assertIsNone(hub.get_event("evt_unknown"))

    def test_get_thread_returns_chronological_events(self):
        """get_thread returns all events in the thread, in chronological order."""
        hub = _hub()
        thread_id = "thread_abc"
        ev1 = hub.publish_event("registryhub", "first", {}, recipients=[], thread_id=thread_id)
        ev2 = hub.publish_event("registryhub", "second", {}, recipients=[], thread_id=thread_id)
        ev3 = hub.publish_event("registryhub", "third", {}, recipients=[], thread_id=thread_id)
        events = hub.get_thread(thread_id)
        self.assertEqual(len(events), 3)
        ids = [e["id"] for e in events]
        self.assertEqual(ids, [ev1["id"], ev2["id"], ev3["id"]])


# ---------------------------------------------------------------------------
# Task 5: add_bridge
# ---------------------------------------------------------------------------

class TestAttachBridge(unittest.TestCase):
    def test_add_bridge_accepts_object(self):
        """add_bridge stores the bridge in self._bridges."""
        class StubBridge:
            pass

        hub = _hub()
        bridge = StubBridge()
        hub.add_bridge(bridge)
        self.assertIn(bridge, hub._bridges)


# ---------------------------------------------------------------------------
# Cutover 31: Multi-bridge support (list of bridges, not single slot)
# ---------------------------------------------------------------------------

class TestMultipleBridges(unittest.TestCase):
    def test_add_bridge_dispatches_to_all(self):
        """publish_event must call deliver() on every attached bridge."""
        calls_a, calls_b = [], []

        class BridgeA:
            def deliver(self, event):
                calls_a.append(event["id"])

        class BridgeB:
            def deliver(self, event):
                calls_b.append(event["id"])

        hub = _hub()
        hub.add_bridge(BridgeA())
        hub.add_bridge(BridgeB())
        evt = hub.publish_event("workhub", "test", {}, recipients=["alpha"])
        self.assertEqual(calls_a, [evt["id"]])
        self.assertEqual(calls_b, [evt["id"]])

    def test_add_bridge_is_backward_compatible(self):
        """add_bridge should now append rather than replace."""
        calls = []

        class Bridge:
            def __init__(self, tag):
                self.tag = tag

            def deliver(self, event):
                calls.append(self.tag)

        hub = _hub()
        hub.add_bridge(Bridge("first"))
        hub.add_bridge(Bridge("second"))
        hub.publish_event("workhub", "test", {}, recipients=["alpha"])
        self.assertEqual(sorted(calls), ["first", "second"])

    def test_bridge_exception_does_not_block_others(self):
        """A raising bridge must not prevent other bridges from receiving the event."""
        calls = []

        class GoodBridge:
            def deliver(self, event):
                calls.append("good")

        class BadBridge:
            def deliver(self, event):
                raise RuntimeError("boom")

        hub = _hub()
        hub.add_bridge(BadBridge())
        hub.add_bridge(GoodBridge())
        hub.publish_event("workhub", "test", {}, recipients=["alpha"])
        self.assertIn("good", calls)
