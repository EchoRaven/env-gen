"""Tests that knowledge_agent prompt teaches structured outputs."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class KnowledgeAgentStructuredPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("knowledge_agent.j2")
        mod = tpl.make_module()
        for name in ("knowledge_specifics", "knowledge_system_prompt"):
            if hasattr(mod, name):
                try:
                    cls.system = getattr(mod, name)()
                except TypeError:
                    cls.system = getattr(mod, name)(".", "")
                break
        else:
            raise RuntimeError("no knowledge specifics/system macro")

    def test_prompt_mentions_submit_adr(self) -> None:
        self.assertIn("SUBMIT_ADR", self.system.upper())

    def test_prompt_mentions_submit_runbook(self) -> None:
        self.assertIn("SUBMIT_RUNBOOK", self.system.upper())

    def test_prompt_mentions_submit_postmortem(self) -> None:
        self.assertIn("SUBMIT_POSTMORTEM", self.system.upper())

    def test_prompt_explains_when_to_use_each_type(self) -> None:
        upper = self.system.upper()
        # Heuristic: prompt should describe the trigger condition for each type
        self.assertIn("DECISION", upper)
        self.assertIn("INCIDENT", upper)
        self.assertTrue("OPERATIONAL" in upper or "PROCEDURE" in upper or "DEPLOY" in upper)


if __name__ == "__main__":
    unittest.main()
