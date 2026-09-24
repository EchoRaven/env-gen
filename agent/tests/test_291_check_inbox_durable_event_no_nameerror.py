"""#291 — check_inbox must not crash on a durable eventhub message.

r75 live (184×): every agent that had a durable cross-process eventhub message
in its inbox hit

    ❌ check_inbox FAILED: name 'summarize_inbox_message_body' is not defined

#274 wrapped the durable-event content in ``summarize_inbox_message_body(...)``
(communication_tools.py:773) — a function that is DEFINED NOWHERE (pure
NameError). The exception fires in the durable-event append loop, which is
OUTSIDE the surrounding try/except, so it aborts the WHOLE execute(): the agent
can read NONE of its inbox (durable AND in-memory), breaking coordination
(task_ready / nudges / merges silently lost).

The wrapper also VIOLATES the file's own tested invariant (lines 824-830 /
881-887): inbox bodies are deliberately NOT truncated/summarized per the
2026-06-01 user directive "不要截断，这个肯定要完整信息的". The non-durable
formatting path (line 888) keeps the raw ``msg.get("content", "")``.

Fix: the durable path must carry the raw, untruncated payload content, exactly
like the non-durable path — no summarizer.

The existing test_inbox_no_content_truncation E2E stub uses ``_hubs = None`` and
so only exercises the in-memory path; this test drives the DURABLE branch.
"""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from tools.communication_tools import CheckInboxTool  # noqa: E402


class _StubEventhub:
    def __init__(self, events):
        self._events = events

    def list_inbox(self, agent_id, unread_only=False):
        return list(self._events)

    def mark_read(self, *a, **k):
        pass


class _StubHubs:
    def __init__(self, events):
        self.eventhub = _StubEventhub(events)


class _StubAgent:
    agent_id = "backend"

    def __init__(self, events):
        self._subscription_inbox = []
        self._hubs = _StubHubs(events)

    def get_inbox_messages(self, limit=999, clear=False):
        return []


class CheckInboxDurableEventTests(unittest.TestCase):
    def _make(self, content):
        event = {
            "id": "evt_1",
            "event_type": "task_ready",
            "priority": "high",
            "source_hub": "workhub",
            "created_at": "2026-07-25T01:00:00",
            "payload": {"from": "orchestrator", "content": content,
                        "tags": ["task_ready"]},
        }
        return CheckInboxTool(agent=_StubAgent([event]))

    def test_durable_event_does_not_raise_nameerror(self) -> None:
        tool = self._make("hello from a durable cross-process event")
        # On the unfixed code this raises NameError before returning.
        result = tool.execute(limit=10, clear=False)
        self.assertTrue(result.success)
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["messages"][0]["from"], "orchestrator")

    def test_durable_event_content_is_not_truncated(self) -> None:
        long_content = "C" * 4000  # 8x the old 500-char cap
        tool = self._make(long_content)
        result = tool.execute(limit=10, clear=False)
        self.assertTrue(result.success)
        returned = result.data["messages"][0]["content"]
        self.assertEqual(
            returned, long_content,
            msg="durable-event inbox content must round-trip raw + untruncated "
                "(no summarizer), per the no-truncation invariant")


if __name__ == "__main__":
    unittest.main()
