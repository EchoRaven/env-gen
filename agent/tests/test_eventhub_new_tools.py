import asyncio
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_EVENTHUB_TOOLS = {
    "eventhub_subscribe",
    "eventhub_unsubscribe",
    "eventhub_list_subscriptions",
    "eventhub_get_thread",
    "eventhub_reply_in_thread",
    "eventhub_mark_all_read",
    "eventhub_get_agent_status",
}


def _run(coro):
    # Drift fix: the old helper drove coroutines through a current-loop handle,
    # which reuses the process-wide default loop. When these tests run inside the
    # full suite, an earlier async test in another file can close that shared loop,
    # making all 7 async tests here fail with "Event loop is closed" (only the one
    # synchronous export test survived). Run each coroutine on its own fresh,
    # isolated loop so ordering/pollution can't affect us.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class EventHubNewToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="backend", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_eventhub_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_EVENTHUB_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_eventhub_subscribe_persists_full_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["eventhub_subscribe"]
            result = _run(tool._run(source_hub="registryhub", event_type="breaking_change_detected",
                                     filter={"x": 1}, priority_floor="high"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["source_hub"], "registryhub")
            self.assertEqual(data["event_type"], "breaking_change_detected")
            self.assertEqual(data["priority_floor"], "high")

    def test_eventhub_unsubscribe_removes(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            sub = hubs.eventhub.subscribe(agent="backend", source_hub="registryhub")
            tool = tool_by_name["eventhub_unsubscribe"]
            result = _run(tool._run(subscription_id=sub["id"]))
            data = result.data if hasattr(result, "data") else result
            self.assertTrue(data.get("removed"))
            subs = hubs.eventhub.get_subscriptions(agent="backend")
            self.assertEqual(subs, [])

    def test_eventhub_list_subscriptions_returns_filter(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.subscribe(agent="backend", source_hub="registryhub")
            hubs.eventhub.subscribe(agent="backend", source_hub="codehub")
            tool = tool_by_name["eventhub_list_subscriptions"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(len(data["subscriptions"]), 2)


    def test_eventhub_get_thread_returns_chronological_events(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            e1 = hubs.eventhub.publish_event(source_hub="codehub", event_type="pr_opened",
                                               payload={}, recipients=[], thread_id="thread:pr:pr_x")
            e2 = hubs.eventhub.publish_event(source_hub="codehub", event_type="review_requested",
                                               payload={}, recipients=[], thread_id="thread:pr:pr_x")
            tool = tool_by_name["eventhub_get_thread"]
            result = _run(tool._run(thread_id="thread:pr:pr_x"))
            data = result.data if hasattr(result, "data") else result
            ids = [e["id"] for e in data["events"]]
            self.assertEqual(ids, [e1["id"], e2["id"]])

    def test_eventhub_reply_in_thread_creates_event(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.publish_event(source_hub="codehub", event_type="pr_opened",
                                          payload={}, recipients=[], thread_id="thread:pr:pr_y")
            tool = tool_by_name["eventhub_reply_in_thread"]
            result = _run(tool._run(thread_id="thread:pr:pr_y", body="Looks good"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["thread_id"], "thread:pr:pr_y")
            thread = hubs.eventhub.get_thread("thread:pr:pr_y")
            self.assertEqual(len(thread), 2)


    def test_eventhub_mark_all_read_returns_count(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.publish_event(source_hub="registryhub", event_type="x", payload={},
                                          recipients=["backend"])
            hubs.eventhub.publish_event(source_hub="registryhub", event_type="y", payload={},
                                          recipients=["backend"])
            tool = tool_by_name["eventhub_mark_all_read"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["marked"], 2)

    def test_eventhub_get_agent_status_returns_latest_payload(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.record_agent_status("frontend", {"state": "thinking"})
            hubs.eventhub.record_agent_status("frontend", {"state": "writing"})
            tool = tool_by_name["eventhub_get_agent_status"]
            result = _run(tool._run(agent_id="frontend"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["status"]["state"], "writing")


if __name__ == "__main__":
    unittest.main()
