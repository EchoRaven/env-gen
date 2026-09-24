"""TDD tests for EventHub agent_status system-topic helpers (Phase E, Task 20)."""
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


class TestRecordAgentStatus(unittest.TestCase):
    def test_record_publishes_system_event_and_get_returns_payload(self):
        """record_agent_status publishes a system/agent_status event; get_agent_status returns payload."""
        hub = _hub()
        status = {"status": "working", "current_task": "build api"}
        hub.record_agent_status("agent_a", status)
        result = hub.get_agent_status("agent_a")
        self.assertIsNotNone(result)
        self.assertEqual(result["agent_id"], "agent_a")
        self.assertEqual(result["status"], "working")
        self.assertEqual(result["current_task"], "build api")

    def test_record_stores_on_system_topic(self):
        """Events are tagged source_hub='system', event_type='agent_status'."""
        hub = _hub()
        hub.record_agent_status("agent_b", {"status": "idle"})
        events = list(hub._events.value().values())
        sys_events = [
            e for e in events
            if e.get("source_hub") == "system" and e.get("event_type") == "agent_status"
        ]
        self.assertEqual(len(sys_events), 1)
        self.assertEqual(sys_events[0]["thread_id"], "thread:agent:agent_b")

    def test_record_returns_event_dict(self):
        """record_agent_status returns the published event dict."""
        hub = _hub()
        evt = hub.record_agent_status("agent_c", {"status": "completed"})
        self.assertIn("id", evt)
        self.assertEqual(evt["source_hub"], "system")
        self.assertEqual(evt["event_type"], "agent_status")


class TestGetAgentStatus(unittest.TestCase):
    def test_returns_latest_by_created_at(self):
        """get_agent_status returns the most recently created event payload for the agent."""
        hub = _hub()
        hub.record_agent_status("agent_d", {"status": "idle"})
        time.sleep(0.01)
        hub.record_agent_status("agent_d", {"status": "working", "current_task": "step 2"})
        result = hub.get_agent_status("agent_d")
        self.assertEqual(result["status"], "working")
        self.assertEqual(result["current_task"], "step 2")

    def test_returns_none_for_unknown_agent(self):
        """get_agent_status returns None when no status has been recorded."""
        hub = _hub()
        self.assertIsNone(hub.get_agent_status("no_such_agent"))

    def test_does_not_cross_agents(self):
        """get_agent_status for one agent is not affected by another agent's status."""
        hub = _hub()
        hub.record_agent_status("agent_e", {"status": "idle"})
        hub.record_agent_status("agent_f", {"status": "error"})
        self.assertEqual(hub.get_agent_status("agent_e")["status"], "idle")
        self.assertEqual(hub.get_agent_status("agent_f")["status"], "error")


class TestGetAllAgentStatuses(unittest.TestCase):
    def test_returns_dict_keyed_by_agent_id(self):
        """get_all_agent_statuses returns a dict keyed by agent_id with latest payload."""
        hub = _hub()
        hub.record_agent_status("agent_g", {"status": "working"})
        hub.record_agent_status("agent_h", {"status": "idle"})
        all_statuses = hub.get_all_agent_statuses()
        self.assertIn("agent_g", all_statuses)
        self.assertIn("agent_h", all_statuses)
        self.assertEqual(all_statuses["agent_g"]["status"], "working")
        self.assertEqual(all_statuses["agent_h"]["status"], "idle")

    def test_returns_latest_per_agent(self):
        """get_all_agent_statuses returns the latest status per agent."""
        hub = _hub()
        hub.record_agent_status("agent_i", {"status": "idle"})
        time.sleep(0.01)
        hub.record_agent_status("agent_i", {"status": "completed"})
        all_statuses = hub.get_all_agent_statuses()
        self.assertEqual(all_statuses["agent_i"]["status"], "completed")

    def test_empty_when_no_statuses(self):
        """get_all_agent_statuses returns empty dict when nothing recorded."""
        hub = _hub()
        self.assertEqual(hub.get_all_agent_statuses(), {})

    def test_includes_event_created_at_metadata(self):
        """get_all_agent_statuses values include _event_created_at for tracking."""
        hub = _hub()
        hub.record_agent_status("agent_j", {"status": "working"})
        all_statuses = hub.get_all_agent_statuses()
        self.assertIn("_event_created_at", all_statuses["agent_j"])
        self.assertGreater(all_statuses["agent_j"]["_event_created_at"], 0)


if __name__ == "__main__":
    unittest.main()
