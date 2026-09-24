"""Design Analyst prompt renders + encodes the field manual's methodology (measure-don't-guess,
lever order, translucency trap, 塌缩点 checklist, brand boundary, design_system.json output).
LOCAL-ONLY (agent/tests/ gitignored).
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent
TEMPLATE = "design_analyst.j2"


class DesignAnalystPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        mod = env.get_template(TEMPLATE).make_module()
        cls.system = mod.design_analyst_system_prompt()
        cls.task = mod.design_analyst_task_prompt(task_description="Analyze the instagram references.")

    def test_renders_nonempty(self) -> None:
        self.assertGreater(len(self.system.strip()), 800)
        self.assertIn("Analyze the instagram references", self.task)

    def test_measure_dont_guess_is_the_law(self) -> None:
        up = self.system.upper()
        self.assertIn("MEASURE", up)
        self.assertTrue("GUESS" in up and ("NEVER" in up or "DON'T" in up or "别猜" in self.system))

    def test_per_component_tool_chain_present(self) -> None:
        for tool in ("decompose_reference", "crop_reference", "sample_color",
                     "measure_layout", "extract_palette"):
            self.assertIn(tool, self.system, tool)

    def test_translucency_trap_and_lever_order(self) -> None:
        self.assertIn("row-mode", self.system)
        self.assertTrue("translucent" in self.system.lower() or "wallpaper" in self.system.lower())
        self.assertTrue("LEVER" in self.system.upper() or "background" in self.system.lower())

    def test_collapse_checklist_and_semantic_color(self) -> None:
        # the single most important critic item: dropped semantic color / all-gray collapse
        self.assertTrue("semantic" in self.system.lower())
        self.assertTrue("all-gray" in self.system.lower() or "all gray" in self.system.lower())

    def test_brand_boundary_and_assets(self) -> None:
        self.assertTrue("brand" in self.system.lower())
        self.assertIn("asset", self.system.lower())

    def test_output_is_design_system_json(self) -> None:
        self.assertIn("design_system.json", self.system)
        self.assertIn("screens", self.system)
        self.assertIn("components", self.system)

    def test_finishes_when_done(self) -> None:
        self.assertIn("finish()", self.system)


if __name__ == "__main__":
    unittest.main()
