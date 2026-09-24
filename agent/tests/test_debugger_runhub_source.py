"""Tests that debugger prompt mentions runhub as a source (Cutover 12)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class DebuggerRunHubSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("debugger_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.debugger_system_prompt()

    def test_prompt_mentions_runhub_run_failed(self) -> None:
        self.assertIn("RUN_FAILED", self.system.upper())

    def test_prompt_mentions_runhub_as_source(self) -> None:
        self.assertIn("RUNHUB", self.system.upper())

    def test_prompt_describes_runhub_artifact_shape(self) -> None:
        upper = self.system.upper()
        self.assertIn("AFFECTED_ENDPOINT", upper)


if __name__ == "__main__":
    unittest.main()
