"""Active human directives block gets appended to system prompt each step (Task 3)."""
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


class _StubAgent:
    """Minimal stand-in that we drive through EnvGenAgent._compose_system_prompt."""

    def __init__(self, agent_id: str, reg: HubRegistry, base_prompt: str = "BASE PROMPT"):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self._hubs = reg
        self._logger = MagicMock()
        self._base = base_prompt

    def _get_system_prompt(self) -> str:
        return self._base


def _compose(stub: _StubAgent) -> str:
    """Call the unbound method on the stub, mirroring the existing test pattern."""
    from multi_agent.agents.base import EnvGenAgent
    return EnvGenAgent._compose_system_prompt(stub)


class TestDirectiveInjection(unittest.TestCase):
    def test_no_human_thread_returns_base_prompt_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p_a", project_name="A")
            stub = _StubAgent("design", reg, base_prompt="BASE PROMPT")
            composed = _compose(stub)
            self.assertEqual(composed, "BASE PROMPT")
            self.assertNotIn("Active human directives", composed)

    def test_human_message_appears_in_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p_b", project_name="B")
            reg.eventhub.publish_human_message(
                text="please continue working", target_agents=["design"], from_user="test_user"
            )
            stub = _StubAgent("design", reg, base_prompt="BASE PROMPT")
            composed = _compose(stub)
            self.assertIn("BASE PROMPT", composed)
            self.assertIn("Active human directives", composed)
            self.assertIn("please continue working", composed)

    def test_only_threads_this_agent_participates_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p_c", project_name="C")
            # Message for backend, not design
            reg.eventhub.publish_human_message(
                text="backend-only message", target_agents=["backend"], from_user="test_user"
            )
            stub = _StubAgent("design", reg, base_prompt="BASE PROMPT")
            composed = _compose(stub)
            self.assertNotIn("backend-only message", composed)

    def test_most_recent_thread_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp, human_user_id="test_user"), project_id="p_d", project_name="D")
            # Two threads; second one is the most recent.
            reg.eventhub.publish_human_message(
                text="older directive", target_agents=["design"], from_user="test_user"
            )
            reg.eventhub.publish_human_message(
                text="newer directive", target_agents=["design"], from_user="test_user"
            )
            stub = _StubAgent("design", reg, base_prompt="BASE PROMPT")
            composed = _compose(stub)
            # The newer directive is required; we don't strictly forbid the
            # older one (depends on max_raw_turns and the threads-window).
            self.assertIn("newer directive", composed)


if __name__ == "__main__":
    unittest.main()
