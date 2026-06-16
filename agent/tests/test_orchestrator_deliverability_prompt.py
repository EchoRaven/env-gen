"""Tests that orchestrator prompt teaches deliverability discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorDeliverabilityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_mentions_deliverability_check(self) -> None:
        self.assertIn("DELIVERABILITY_CHECK", self.system.upper())

    def test_warns_runhub_required_this_session(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUN_START", upper)
        self.assertIn("SESSION", upper)

    def test_mentions_evidence_over_checklist(self) -> None:
        upper = self.system.upper()
        self.assertTrue("EVIDENCE" in upper or "CHECKLIST" in upper)


if __name__ == "__main__":
    unittest.main()
