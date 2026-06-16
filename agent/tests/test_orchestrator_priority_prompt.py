"""Tests that orchestrator prompt teaches task priority + dependency discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorPriorityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_mentions_priority_levels(self) -> None:
        upper = self.system.upper()
        for p in ("P0", "P1", "P2", "P3"):
            self.assertIn(p, upper)

    def test_mentions_depends_on_enforcement(self) -> None:
        upper = self.system.upper()
        self.assertIn("DEPENDS_ON", upper)

    def test_mentions_list_ready_and_blocked(self) -> None:
        upper = self.system.upper()
        self.assertIn("WORKHUB_LIST_READY", upper)
        self.assertIn("WORKHUB_LIST_BLOCKED", upper)


if __name__ == "__main__":
    unittest.main()
