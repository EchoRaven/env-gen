"""list_messages must exclude agent_chat_step events from the chat transcript.

Bug: I introduced ``agent_chat_step`` events for live tool-call viz under the
typing dots. They live on the same thread as the human/agent messages and
were being returned by ``list_messages`` with empty ``text``, surfacing as
blank chat bubbles in the UI.

Fix: only ``human_message`` and ``agent_reply`` events are real chat
messages. Everything else (tool-call progress, status pings, etc.) stays
out of the transcript.
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


class TestListMessagesFiltersChatSteps(unittest.TestCase):
    def test_chat_step_events_excluded_from_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            ev = reg.eventhub.publish_human_message(
                text="design alive?", target_agents=["orchestrator"],
                from_user="alice@test",
            )
            tid = ev["thread_id"]
            # Emit several chat_step events that the mini-loop would publish.
            for tool in ["check_inbox", "send_message", "set_step_reminder"]:
                reg.eventhub.publish_event(
                    source_hub="orchestrator",
                    event_type="agent_chat_step",
                    payload={
                        "agent": "orchestrator",
                        "tool": tool,
                        "args_preview": "{}",
                        "status": "done",
                        "result_preview": "ok",
                    },
                    recipients=["human_user"],
                    priority="normal",
                    thread_id=tid,
                )
            # Finally a real reply.
            reg.eventhub.publish_agent_reply(thread_id=tid, agent="orchestrator", text="Design is alive but slow.")

            msgs = reg.human_console.list_messages(tid)
            # Must contain exactly the human msg + 1 reply — no chat_step rows.
            self.assertEqual(len(msgs), 2, f"unexpected messages: {msgs}")
            self.assertEqual(msgs[0]["event_type"], "human_message")
            self.assertEqual(msgs[0]["text"], "design alive?")
            self.assertEqual(msgs[1]["event_type"], "agent_reply")
            self.assertEqual(msgs[1]["text"], "Design is alive but slow.")
            # And specifically no blank-text rows
            self.assertFalse(any(m["text"] == "" for m in msgs),
                             f"empty-text message leaked into transcript: {msgs}")

    def test_other_unknown_event_types_also_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p2", project_name="P2")
            ev = reg.eventhub.publish_human_message(
                text="hi", target_agents=["orchestrator"],
                from_user="alice@test",
            )
            tid = ev["thread_id"]
            # Random non-conversational event on the same thread.
            reg.eventhub.publish_event(
                source_hub="system",
                event_type="agent_status",
                payload={"agent_id": "orchestrator", "status": "thinking"},
                recipients=[],
                priority="normal",
                thread_id=tid,
            )
            msgs = reg.human_console.list_messages(tid)
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]["event_type"], "human_message")


if __name__ == "__main__":
    unittest.main()
