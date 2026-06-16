"""Tests that the debugger prompt renders and contains required discipline rules."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "prompts" / "v3"
)
PROMPTS_ROOT = PROMPTS_V3.parent
TEMPLATE = "debugger_agent.j2"


class DebuggerPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template(TEMPLATE)
        mod = tpl.make_module()
        cls.system = mod.debugger_system_prompt()
        cls.task = mod.debugger_task_prompt()

    def test_system_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.system.strip()), 200)

    def test_system_prompt_mentions_role_split(self) -> None:
        self.assertIn("VERIFIER", self.system.upper())
        self.assertIn("OWNING AGENT", self.system.upper())
        self.assertIn("FIX", self.system.upper())

    def test_system_prompt_forbids_code_edits(self) -> None:
        self.assertIn("NEVER", self.system.upper())
        self.assertTrue(
            "CODE" in self.system.upper() or "EDIT" in self.system.upper(),
            "prompt must explicitly forbid direct code edits",
        )

    def test_system_prompt_requires_root_cause_before_assignment(self) -> None:
        self.assertIn("ROOT CAUSE", self.system.upper())

    def test_system_prompt_describes_escalation_rule(self) -> None:
        self.assertIn("ESCALAT", self.system.upper())

    def test_system_prompt_lists_step_pipeline_stages(self) -> None:
        for stage in ("HUB PULSE", "INTEGRITY CHECK"):
            self.assertIn(stage, self.system.upper())

    def test_task_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.task.strip()), 100)


if __name__ == "__main__":
    unittest.main()
