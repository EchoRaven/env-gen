"""human_chat module — directive block + transcript formatter (Task 2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class TestBuildDirectiveBlock(unittest.TestCase):
    def test_empty_threads_returns_empty_string(self):
        from multi_agent.agents.runtime import human_chat
        self.assertEqual(human_chat.build_directive_block([], {}, max_raw_turns=3), "")

    def test_summary_plus_last_n_turns(self):
        from multi_agent.agents.runtime import human_chat
        threads = [{
            "thread_id": "t1",
            "summary": "user wants X done by Friday",
            "summary_updated_at": 100.0,
            "last_message_at": 200.0,
        }]
        transcripts = {
            "t1": [
                {"role": "user", "speaker": "human_user", "text": "old 1", "ts": 50},
                {"role": "assistant", "speaker": "design", "text": "old 2", "ts": 60},
                {"role": "user", "speaker": "human_user", "text": "recent A", "ts": 180},
                {"role": "assistant", "speaker": "design", "text": "recent B", "ts": 190},
                {"role": "user", "speaker": "human_user", "text": "recent C", "ts": 200},
            ],
        }
        block = human_chat.build_directive_block(threads, transcripts, max_raw_turns=3)
        self.assertIn("Active human directives", block)
        self.assertIn("user wants X done by Friday", block)
        self.assertIn("recent A", block)
        self.assertIn("recent B", block)
        self.assertIn("recent C", block)
        self.assertNotIn("old 1", block)
        self.assertNotIn("old 2", block)

    def test_no_summary_still_shows_turns(self):
        from multi_agent.agents.runtime import human_chat
        threads = [{"thread_id": "t2", "summary": "", "last_message_at": 10.0}]
        transcripts = {
            "t2": [
                {"role": "user", "speaker": "human_user", "text": "hello", "ts": 10},
            ],
        }
        block = human_chat.build_directive_block(threads, transcripts, max_raw_turns=3)
        self.assertIn("Active human directives", block)
        self.assertIn("hello", block)
        self.assertNotIn("Summary:", block)

    def test_max_raw_turns_zero_suppresses_raw_section(self):
        """Regression: ``[-0:]`` returns the FULL list, not the empty
        list. Passing max_raw_turns=0 must yield no raw-turn section."""
        from multi_agent.agents.runtime import human_chat
        threads = [{
            "thread_id": "t1",
            "summary": "user wants X",
            "last_message_at": 200.0,
        }]
        transcripts = {
            "t1": [
                {"role": "user", "speaker": "human_user", "text": "one", "ts": 100},
                {"role": "user", "speaker": "human_user", "text": "two", "ts": 200},
            ],
        }
        block = human_chat.build_directive_block(threads, transcripts, max_raw_turns=0)
        # Summary still present.
        self.assertIn("user wants X", block)
        # NO raw turns leaked through the slice gotcha.
        self.assertNotIn("one", block)
        self.assertNotIn("two", block)
        self.assertNotIn("Recent turns:", block)

    def test_truncates_long_turns(self):
        from multi_agent.agents.runtime import human_chat
        threads = [{"thread_id": "t3", "last_message_at": 1.0}]
        long_text = "x" * 1000
        transcripts = {"t3": [
            {"role": "user", "speaker": "human_user", "text": long_text, "ts": 1},
        ]}
        block = human_chat.build_directive_block(threads, transcripts, max_raw_turns=3)
        # Should not contain the full 1000-char string verbatim
        self.assertNotIn("x" * 1000, block)
        # Should contain the ellipsis truncation marker
        self.assertIn("…", block)


class TestFormatTranscriptForCompression(unittest.TestCase):
    def test_orders_by_ts(self):
        from multi_agent.agents.runtime import human_chat
        entries = [
            {"role": "user", "speaker": "human_user", "text": "two", "ts": 200},
            {"role": "assistant", "speaker": "design", "text": "one-reply", "ts": 150},
            {"role": "user", "speaker": "human_user", "text": "one", "ts": 100},
        ]
        text = human_chat.format_transcript_for_compression(entries)
        self.assertLess(text.index("one"), text.index("one-reply"))
        self.assertLess(text.index("one-reply"), text.index("two"))

    def test_includes_speaker_labels(self):
        from multi_agent.agents.runtime import human_chat
        entries = [
            {"role": "user", "speaker": "haibotong", "text": "hi", "ts": 1},
            {"role": "assistant", "speaker": "design", "text": "yes", "ts": 2},
        ]
        text = human_chat.format_transcript_for_compression(entries)
        self.assertIn("[haibotong]", text)
        self.assertIn("[design]", text)


if __name__ == "__main__":
    unittest.main()
