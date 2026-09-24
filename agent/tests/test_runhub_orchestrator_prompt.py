"""Tests that orchestrator prompt now includes RunHub discipline (Cutover 11)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorRunDisciplineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        # Macro name was `lead_specifics` per Cutover 8.
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_mentions_run_start(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUN_START", upper)

    def test_prompt_requires_run_after_backend_merge(self) -> None:
        upper = self.system.upper()
        # Some phrasing of "after PR merge, call run_start"
        self.assertIn("AFTER", upper)
        self.assertTrue("MERGE" in upper or "PR" in upper)

    def test_prompt_references_runhub(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUNHUB", upper)


if __name__ == "__main__":
    unittest.main()
