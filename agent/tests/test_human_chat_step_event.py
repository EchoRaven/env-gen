"""_emit_chat_step publishes an agent_chat_step event onto the chat thread (Task 5)."""
from __future__ import annotations

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


class _Stub:
    agent_id = "design"
    _agent_id = "design"

    def __init__(self, reg: HubRegistry):
        self._hubs = reg
        self._logger = MagicMock()


def _emit(stub, **kwargs):
    from multi_agent.agents.base import EnvGenAgent
    return EnvGenAgent._emit_chat_step(stub, **kwargs)


class TestEmitChatStep(unittest.TestCase):
    def test_success_call_emits_done_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            _emit(
                _Stub(reg),
                thread_id=tid,
                tool_name="workhub_list_tasks",
                tool_args={"assignee": "design"},
                result_data={"tasks": [{"id": "T-3"}]},
                success=True,
            )

            events = reg.eventhub.get_thread(tid)
            steps = [e for e in events if e.get("event_type") == "agent_chat_step"]
            self.assertEqual(len(steps), 1)
            p = steps[0]["payload"]
            self.assertEqual(p["tool"], "workhub_list_tasks")
            self.assertEqual(p["status"], "done")
            self.assertEqual(p["agent"], "design")
            self.assertIn("assignee", p["args_preview"])
            self.assertIn("T-3", p["result_preview"])

    def test_failed_call_emits_error_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p2", project_name="P2")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            _emit(
                _Stub(reg),
                thread_id=tid,
                tool_name="bad_tool",
                tool_args={"x": 1},
                result_data="permission denied",
                success=False,
            )

            events = reg.eventhub.get_thread(tid)
            steps = [e for e in events if e.get("event_type") == "agent_chat_step"]
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0]["payload"]["status"], "error")
            self.assertIn("permission denied", steps[0]["payload"]["result_preview"])

    def test_truncates_long_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p3", project_name="P3")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            big = "x" * 5000
            _emit(
                _Stub(reg),
                thread_id=tid,
                tool_name="read",
                tool_args={"file_path": "/a"},
                result_data=big,
                success=True,
            )
            events = reg.eventhub.get_thread(tid)
            preview = events[-1]["payload"]["result_preview"]
            self.assertLess(len(preview), 260)
            self.assertTrue(preview.endswith("…"))

    def test_does_not_write_to_human_user_inbox(self):
        """Chat steps are live-SSE breadcrumbs, not persisted messages —
        they must NOT land in any inbox. Recipients=[] keeps them SSE-only."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]
            # Inbox starts with the human_message itself routed to "design".
            inboxes_before = reg.eventhub.list_inbox("human_user", unread_only=False)
            initial = len(inboxes_before)
            # Emit several chat_step events.
            for _ in range(3):
                _emit(
                    _Stub(reg),
                    thread_id=tid,
                    tool_name="check_inbox", tool_args={}, result_data="ok", success=True,
                )
            inboxes_after = reg.eventhub.list_inbox("human_user", unread_only=False)
            self.assertEqual(
                len(inboxes_after), initial,
                "agent_chat_step events must NOT add inbox entries to human_user",
            )

    def test_missing_hubs_does_not_crash(self):
        """_emit_chat_step must be silent when _hubs is None — used in unit tests."""
        from multi_agent.agents.base import EnvGenAgent
        class StubNoHubs:
            agent_id = "design"
            _hubs = None
            _logger = MagicMock()
        # Should NOT raise.
        EnvGenAgent._emit_chat_step(
            StubNoHubs(),
            thread_id="t1",
            tool_name="x", tool_args={}, result_data="y", success=True,
        )


if __name__ == "__main__":
    unittest.main()
