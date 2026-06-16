"""Tests that orchestrator + frontend prompts teach visual fidelity discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


def _render(tpl_name: str, macros: list) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    tpl = env.get_template(tpl_name)
    mod = tpl.make_module()
    for name in macros:
        if hasattr(mod, name):
            try:
                return getattr(mod, name)()
            except TypeError:
                return getattr(mod, name)(".", "")
    raise RuntimeError(f"no macro found in {tpl_name}")


class OrchestratorVisualPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("orchestrator_agent.j2", ["lead_system_prompt"])

    def test_mentions_visual_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("VISUAL", upper)
        self.assertIn("DELIVER", upper)

    def test_mentions_critical_routes(self) -> None:
        self.assertIn("CRITICAL", self.system.upper())


class FrontendVisualPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("frontend_agent.j2",
                              ["frontend_specifics", "frontend_system_prompt"])

    def test_mentions_register_visual_review_task(self) -> None:
        self.assertIn("REGISTER_VISUAL_REVIEW_TASK", self.system.upper())

    def test_mentions_reference_image(self) -> None:
        upper = self.system.upper()
        self.assertIn("REFERENCE", upper)

    def test_mentions_capture_screenshot(self) -> None:
        upper = self.system.upper()
        self.assertTrue(any(s in upper for s in ("SCREENSHOT", "CAPTURE", "CAPTUREWEBPAGE")))


if __name__ == "__main__":
    unittest.main()
