"""EventHub transcript reader + thread summary fields (human chat mini-loop, Task 1)."""
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
    return EventHub(Path(tempfile.mkdtemp()))


class TestGetThreadTranscript(unittest.TestCase):
    def test_shapes_human_and_agent_events_into_llm_entries(self):
        hub = _hub()
        ev = hub.publish_human_message(text="Hi there", target_agents=["design"], from_user="haibotong")
        tid = ev["thread_id"]
        hub.publish_agent_reply(thread_id=tid, agent="design", text="On it.")

        transcript = hub.get_thread_transcript(tid)
        self.assertEqual(len(transcript), 2)

        first, second = transcript
        self.assertEqual(first["role"], "user")
        # Phase 4.7-slim Path A: speaker reflects the propagated
        # human user id (the project's 甲方), not the legacy
        # "human_user" placeholder.
        self.assertEqual(first["speaker"], "haibotong")
        self.assertEqual(first["text"], "Hi there")
        self.assertGreater(first["ts"], 0)

        self.assertEqual(second["role"], "assistant")
        self.assertEqual(second["speaker"], "design")
        self.assertEqual(second["text"], "On it.")
        self.assertGreaterEqual(second["ts"], first["ts"])

    def test_skips_empty_text_events(self):
        hub = _hub()
        ev = hub.publish_human_message(text="real text", target_agents=["design"], from_user="haibotong")
        tid = ev["thread_id"]
        # Publish a non-message event into the thread to confirm it's ignored.
        hub.publish_event(
            source_hub="design",
            event_type="agent_status",
            payload={"agent_id": "design", "status": "thinking"},
            recipients=[],
            thread_id=tid,
        )

        transcript = hub.get_thread_transcript(tid)
        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0]["text"], "real text")

    def test_unknown_thread_returns_empty(self):
        hub = _hub()
        self.assertEqual(hub.get_thread_transcript("does_not_exist"), [])


class TestUpdateThreadSummary(unittest.TestCase):
    def test_persists_summary_fields(self):
        hub = _hub()
        ev = hub.publish_human_message(text="hi", target_agents=["design"], from_user="haibotong")
        tid = ev["thread_id"]
        cutoff = ev["created_at"]

        result = hub.update_thread_summary(
            thread_id=tid,
            summary="user wants X done",
            summary_until_ts=cutoff,
        )

        self.assertEqual(result["summary"], "user wants X done")
        self.assertEqual(result["summary_until_ts"], cutoff)
        self.assertGreater(result["summary_updated_at"], 0)

        stored = hub._threads.get(tid)
        self.assertEqual(stored["summary"], "user wants X done")
        self.assertEqual(stored["summary_until_ts"], cutoff)
        self.assertGreater(stored["summary_updated_at"], 0)

    def test_unknown_thread_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.update_thread_summary(
                thread_id="nope",
                summary="x",
                summary_until_ts=1.0,
            )


class TestEstimateThreadTokens(unittest.TestCase):
    def test_grows_with_text(self):
        hub = _hub()
        ev = hub.publish_human_message(text="short", target_agents=["design"], from_user="haibotong")
        tid = ev["thread_id"]
        baseline = hub.estimate_thread_tokens(tid)

        hub.publish_agent_reply(thread_id=tid, agent="design", text="x " * 500)
        big = hub.estimate_thread_tokens(tid)

        self.assertGreater(big, baseline * 5)

    def test_empty_thread_estimate_is_one(self):
        hub = _hub()
        # Unknown thread: transcript empty → max(1, 0) == 1
        self.assertEqual(hub.estimate_thread_tokens("missing"), 1)


if __name__ == "__main__":
    unittest.main()
