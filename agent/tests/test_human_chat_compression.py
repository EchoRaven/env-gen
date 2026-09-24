"""Transcript compression at threshold (Task 8)."""
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class _AgentStub:
    """Minimal stand-in: provides _hubs and a fake _generate_text."""
    def __init__(self, reg, summary_text="user wants X done; agent confirmed."):
        self.agent_id = "design"
        self._hubs = reg
        self._logger = MagicMock()
        self._summary_text = summary_text
        self.last_compress_input = None

    async def _generate_text(self, system: str, user: str) -> str:
        self.last_compress_input = user
        return self._summary_text


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestCompressThreadIfNeeded(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_short_thread_does_nothing(self):
        from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p", project_name="P")
            ev = reg.eventhub.publish_human_message(text="hi", target_agents=["design"], from_user="test_user")
            tid = ev["thread_id"]

            agent = _AgentStub(reg)
            ran = asyncio.run(compress_thread_if_needed(
                agent=agent, thread_id=tid,
                token_limit=4000, keep_last_n=10,
            ))
            self.assertFalse(ran)
            self.assertIsNone(reg.eventhub._threads.get(tid).get("summary"))

    def test_long_thread_summarizes_older_turns(self):
        from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p2", project_name="P2")
            # Big first turn pushes the token estimate past the threshold.
            ev = reg.eventhub.publish_human_message(
                text="x" * 20000, target_agents=["design"], from_user="test_user"
            )
            tid = ev["thread_id"]
            # Add enough small follow-ups so there's something to keep verbatim.
            for i in range(12):
                reg.eventhub.publish_agent_reply(
                    thread_id=tid, agent="design", text=f"reply {i}",
                )

            agent = _AgentStub(reg, summary_text="user requested a big thing; design replied many times.")
            ran = asyncio.run(compress_thread_if_needed(
                agent=agent, thread_id=tid,
                token_limit=4000, keep_last_n=10,
            ))
            self.assertTrue(ran)

            thread = reg.eventhub._threads.get(tid)
            self.assertEqual(thread["summary"], "user requested a big thing; design replied many times.")
            self.assertGreater(thread["summary_until_ts"], 0)

            # Confirm the summarizer received the OLDER turns (the big first
            # human turn is "old" given keep_last_n=10 ≤ 13 total entries).
            self.assertIsNotNone(agent.last_compress_input)
            self.assertIn("x" * 100, agent.last_compress_input)

    def test_too_few_turns_skips_even_if_token_limit_crossed(self):
        from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p3", project_name="P3")
            # One mega turn — over budget but only one entry to split.
            reg.eventhub.publish_human_message(
                text="x" * 20000, target_agents=["design"], from_user="test_user"
            )
            tid = reg.eventhub.list_conversations()[0]["thread_id"]

            agent = _AgentStub(reg)
            ran = asyncio.run(compress_thread_if_needed(
                agent=agent, thread_id=tid,
                token_limit=4000, keep_last_n=10,
            ))
            self.assertFalse(ran)


if __name__ == "__main__":
    unittest.main()
