"""Tests that orchestrator prompt teaches retro discipline (Cutover 16)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorRetroPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break

    def test_prompt_mentions_submit_retro(self) -> None:
        self.assertIn("SUBMIT_RETRO", self.system.upper())

    def test_prompt_warns_deliver_blocked_without_retro(self) -> None:
        upper = self.system.upper()
        self.assertIn("RETRO", upper)
        self.assertTrue(
            any(p in upper for p in ("BEFORE DELIVER", "BEFORE CALLING DELIVER",
                                       "PREREQUISITE", "GATE")),
            "prompt must indicate retro is a prerequisite for deliver_project",
        )

    def test_prompt_mentions_required_retro_fields(self) -> None:
        upper = self.system.upper()
        self.assertIn("PLAN_VS_REALITY", upper)
        self.assertIn("LESSONS", upper)
        self.assertIn("PROPOSED_PROMPT_CHANGES", upper)


if __name__ == "__main__":
    unittest.main()
