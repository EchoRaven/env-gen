"""Memory-redesign #3: ``retrieve_context`` should bypass the LLM
"do I need retrieval?" round-trip whenever the agent has knowledge
worth fetching. Without this, ``query_knowledge`` /
``read_memory_bank`` see far fewer calls than the data justifies —
LLM defaults to "no need" to save tokens, and the knowledge base
becomes write-only.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class AgentHasKnowledgeHelper(unittest.TestCase):
    """Direct tests on the helper that drives the auto-fetch."""

    def _agent(self, **attrs):
        from multi_agent.agents.runtime.step_pipeline.stages import AgentStepStageMixin

        class A(AgentStepStageMixin):
            pass

        a = A()
        for k, v in attrs.items():
            setattr(a, k, v)
        return a

    def test_no_memory_no_bank_returns_false(self):
        agent = self._agent(memory=None, memory_bank=None)
        self.assertFalse(agent._agent_has_knowledge_to_fetch())

    def test_memory_with_in_memory_knowledge_returns_true(self):
        mem = MagicMock()
        mem._knowledge = [{"text": "a"}, {"text": "b"}]
        mem._persistence_path = None
        agent = self._agent(memory=mem, memory_bank=None)
        self.assertTrue(agent._agent_has_knowledge_to_fetch())

    def test_memory_with_persisted_jsonl_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "kb.jsonl"
            jsonl.write_text('{"k":"v"}\n')
            mem = MagicMock()
            mem._knowledge = []
            mem._persistence_path = str(jsonl)
            agent = self._agent(memory=mem, memory_bank=None)
            self.assertTrue(agent._agent_has_knowledge_to_fetch())

    def test_empty_persisted_jsonl_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "kb.jsonl"
            jsonl.write_text("")
            mem = MagicMock()
            mem._knowledge = []
            mem._persistence_path = str(jsonl)
            agent = self._agent(memory=mem, memory_bank=None)
            self.assertFalse(agent._agent_has_knowledge_to_fetch())

    def test_memory_bank_with_files_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = Path(tmp) / "bank"
            bank.mkdir()
            (bank / "progress.md").write_text("# Progress\n\n- done")
            mb = MagicMock()
            mb.memory_dir = str(bank)
            mb.base_dir = None
            mem = MagicMock()
            mem._knowledge = []
            mem._persistence_path = None
            agent = self._agent(memory=mem, memory_bank=mb)
            self.assertTrue(agent._agent_has_knowledge_to_fetch())

    def test_memory_bank_with_empty_files_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = Path(tmp) / "bank"
            bank.mkdir()
            (bank / "progress.md").write_text("")  # empty
            mb = MagicMock()
            mb.memory_dir = str(bank)
            mb.base_dir = None
            mem = MagicMock()
            mem._knowledge = []
            mem._persistence_path = None
            agent = self._agent(memory=mem, memory_bank=mb)
            self.assertFalse(agent._agent_has_knowledge_to_fetch())

    def test_exceptions_in_introspection_dont_crash_the_stage(self):
        """The helper must be defensive — any failure returns False
        rather than blowing up the step pipeline."""
        class Boom:
            @property
            def _knowledge(self):
                raise RuntimeError("boom")

            @property
            def _persistence_path(self):
                raise RuntimeError("boom")
        agent = self._agent(memory=Boom(), memory_bank=None)
        self.assertFalse(agent._agent_has_knowledge_to_fetch())


class AutoRetrieveThrottle(unittest.TestCase):
    """Reviewer's follow-up note: auto-fetch on every step is fine for
    the first deploy but a tight throttle (skip the next N steps after
    an auto-retrieve fires) keeps baseline token/latency from creeping
    up if the knowledge bank never meaningfully changes."""

    def test_throttle_constant_is_a_small_positive_integer(self):
        """If a future tweak sets this to 0 (no throttle) or negative
        the throttle silently disappears — pin a baseline."""
        from multi_agent.agents.runtime.step_pipeline.stages import (
            AgentStepStageMixin,
        )
        self.assertGreaterEqual(
            AgentStepStageMixin._RETRIEVE_AUTO_THROTTLE_STEPS, 1,
            "throttle must skip at least one step between auto-retrieves",
        )
        self.assertLessEqual(
            AgentStepStageMixin._RETRIEVE_AUTO_THROTTLE_STEPS, 10,
            "throttle > 10 risks the agent going stale between fetches",
        )


if __name__ == "__main__":
    unittest.main()
