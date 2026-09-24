"""The design_analyst profile is a valid, spawnable (one-shot, non-resident) configurable agent
with the material-prep measurement tool chain. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.configurable_agent import load_config, get_agent_config  # noqa: E402


class DesignAnalystProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()          # raises if any profile's tool surface is invalid
        cls.p = get_agent_config("design_analyst")

    def test_profile_present_and_valid(self) -> None:
        self.assertEqual(self.p["prompts"]["template"], "v3/design_analyst.j2")
        self.assertEqual(self.p["prompts"]["system_macro"], "design_analyst_system_prompt")
        self.assertEqual(self.p["prompts"]["task_macro"], "design_analyst_task_prompt")
        self.assertTrue(self.p.get("include_vision"))

    def test_is_spawnable_one_shot_not_a_resident_lane(self) -> None:
        self.assertIn("design_analyst", self.cfg["profiles"])
        self.assertNotIn("design_analyst", self.cfg.get("resident_lanes", {}))
        self.assertTrue(self.p.get("flags", {}).get("dynamic"))

    def test_has_the_measurement_tool_bundles(self) -> None:
        bundles = set(self.p.get("tool_bundles", []))
        self.assertIn("reference_images", bundles)   # sample_color/crop_reference/extract_palette/zoom_compare/measure_layout
        self.assertIn("vision_tools", bundles)       # decompose_reference


if __name__ == "__main__":
    unittest.main()
