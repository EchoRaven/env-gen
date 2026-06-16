"""TDD tests for EventHub subscription-driven fan-out in publish_event (Task 5)."""
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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


def _hub() -> EventHub:
    tmp = tempfile.mkdtemp()
    return EventHub(Path(tmp))


class TestSubscriptionFanOut(unittest.TestCase):

    def test_subscription_adds_recipient(self):
        """publish_event fans out to agents whose subscriptions match source_hub + event_type."""
        hub = _hub()
        hub.subscribe("watcher", source_hub="registryhub", event_type="spec_changed")
        event = hub.publish_event("registryhub", "spec_changed", {})
        self.assertIn("watcher", event["recipients"])

    def test_subscription_source_hub_filter(self):
        """Subscriptions for a different source_hub are not fanned out."""
        hub = _hub()
        hub.subscribe("watcher", source_hub="workhub", event_type="spec_changed")
        event = hub.publish_event("registryhub", "spec_changed", {})
        self.assertNotIn("watcher", event["recipients"])

    def test_subscription_event_type_filter(self):
        """Subscriptions for a different event_type are not fanned out."""
        hub = _hub()
        hub.subscribe("watcher", source_hub="registryhub", event_type="other_event")
        event = hub.publish_event("registryhub", "spec_changed", {})
        self.assertNotIn("watcher", event["recipients"])

    def test_subscription_priority_floor_honored(self):
        """Subscriptions with priority_floor='high' are skipped for 'normal' priority events."""
        hub = _hub()
        hub.subscribe("strict_watcher", source_hub="registryhub", event_type="spec_changed", priority_floor="high")
        hub.subscribe("normal_watcher", source_hub="registryhub", event_type="spec_changed", priority_floor="normal")
        event = hub.publish_event("registryhub", "spec_changed", {}, priority="normal")
        self.assertIn("normal_watcher", event["recipients"])
        self.assertNotIn("strict_watcher", event["recipients"])

    def test_explicit_recipients_preserved(self):
        """Explicit recipients are kept even when no matching subscription exists."""
        hub = _hub()
        event = hub.publish_event("registryhub", "spec_changed", {}, recipients=["explicit_agent"])
        self.assertIn("explicit_agent", event["recipients"])

    def test_inbox_only_delivery_preserved_in_subscription(self):
        """Subscriptions with delivery='inbox_only' still land in recipients (bridge handles exclusion)."""
        hub = _hub()
        hub.subscribe("inbox_watcher", source_hub="registryhub", event_type="spec_changed", delivery="inbox_only")
        event = hub.publish_event("registryhub", "spec_changed", {})
        self.assertIn("inbox_watcher", event["recipients"])
        inbox = hub.list_inbox("inbox_watcher", unread_only=True)
        self.assertTrue(any(e["id"] == event["id"] for e in inbox))

    def test_bridge_deliver_called_after_publish(self):
        """add_bridge: bridge.deliver is called with the event after inboxes are written."""
        hub = _hub()
        bridge = MagicMock()
        bridge.deliver = MagicMock()
        hub.add_bridge(bridge)
        event = hub.publish_event("registryhub", "spec_changed", {}, recipients=["alpha"])
        bridge.deliver.assert_called_once_with(event)


class TestWildcardSubscriptions(unittest.TestCase):

    def test_wildcard_source_hub_matches_any(self):
        """source_hub='*' subscription matches any source_hub."""
        hub = _hub()
        hub.subscribe("watcher", source_hub="*", event_type="spec_changed")
        event = hub.publish_event("workhub", "spec_changed", {})
        self.assertIn("watcher", event["recipients"])

    def test_wildcard_event_type_matches_any(self):
        """event_type='*' subscription matches any event_type."""
        hub = _hub()
        hub.subscribe("watcher", source_hub="registryhub", event_type="*")
        event = hub.publish_event("registryhub", "anything_at_all", {})
        self.assertIn("watcher", event["recipients"])
