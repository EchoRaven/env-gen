"""Regression: tools/task_tools.py must remain deleted (Cutover 18)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class TaskToolsRemovedTests(unittest.TestCase):
    def test_task_tools_module_no_longer_importable(self) -> None:
        with self.assertRaises(ImportError):
            import tools.task_tools  # noqa: F401

    def test_extract_action_space_tool_no_longer_exported_from_package(self) -> None:
        import tools
        self.assertFalse(hasattr(tools, "ExtractActionSpaceTool"))
        self.assertFalse(hasattr(tools, "GenerateTaskTool"))
        self.assertFalse(hasattr(tools, "GenerateTrajectoryTool"))


if __name__ == "__main__":
    unittest.main()
