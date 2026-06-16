"""Tests that orchestrator prompt teaches coverage discipline (Cutover 19)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorCoveragePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_prompt_mentions_coverage_audit_check(self) -> None:
        self.assertIn("COVERAGE_AUDIT_CHECK", self.system.upper())

    def test_prompt_mentions_mark_intentionally_dead(self) -> None:
        self.assertIn("MARK_INTENTIONALLY_DEAD", self.system.upper())

    def test_prompt_says_dead_code_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("DEAD", upper)
        self.assertIn("DELIVER", upper)

    def test_prompt_mentions_force_deliver_bypass(self) -> None:
        self.assertIn("FORCE_DELIVER", self.system.upper())


if __name__ == "__main__":
    unittest.main()
