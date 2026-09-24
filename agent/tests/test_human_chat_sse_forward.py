"""agent_chat_step events ride the same EventHub bridge as agent_reply (Task 6).

The live monitor's _SSEHub.deliver() is an unfiltered broadcast — any new event
type flows through automatically. This test pins that contract: a bridge
attached to EventHub receives an ``agent_chat_step`` event without any
allowlist tweak.
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class _RecordingBridge:
    """Mimics _SSEHub.deliver — just records every event it sees."""
    def __init__(self):
        self.events: list = []

    def deliver(self, event: dict) -> None:
        self.events.append(event)


class TestAgentChatStepRidesBridge(unittest.TestCase):
    def test_chat_step_event_reaches_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            bridge = _RecordingBridge()
            reg.eventhub.add_bridge(bridge)

            # Spin a thread for a human chat first so there's a thread.
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            from multi_agent.agents.base import EnvGenAgent
            from unittest.mock import MagicMock
            class Stub:
                agent_id = "design"
                _agent_id = "design"
                _hubs = reg
                _logger = MagicMock()

            EnvGenAgent._emit_chat_step(
                Stub(),
                thread_id=tid,
                tool_name="workhub_list_tasks",
                tool_args={"assignee": "design"},
                result_data={"tasks": ["T-1", "T-2"]},
                success=True,
            )

            step_events = [
                e for e in bridge.events if e.get("event_type") == "agent_chat_step"
            ]
            self.assertEqual(len(step_events), 1)
            payload = step_events[0]["payload"]
            self.assertEqual(payload["tool"], "workhub_list_tasks")
            self.assertEqual(payload["status"], "done")


if __name__ == "__main__":
    unittest.main()
