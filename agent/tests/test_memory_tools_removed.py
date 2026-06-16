"""Regression: memory_tools deleted (Cutover 18); UpdateMemoryBankTool moved."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class MemoryToolsRemovedTests(unittest.TestCase):
    def test_memory_tools_module_no_longer_importable(self) -> None:
        with self.assertRaises(ImportError):
            import tools.memory_tools  # noqa: F401

    def test_remember_recall_share_classes_gone(self) -> None:
        import tools
        for cls in ("RememberTool", "RecallTool", "ShareKnowledgeTool",
                    "GetOperationHistoryTool", "GetMemoryContextTool",
                    "MemoryHealthSummaryTool"):
            self.assertFalse(hasattr(tools, cls),
                             f"{cls} should not be exported anymore")

    def test_update_memory_bank_tool_relocated_to_agent_interaction(self) -> None:
        from tools.agent_interaction_tools import UpdateMemoryBankTool  # noqa: F401

    def test_update_memory_bank_still_in_tools_package(self) -> None:
        # Importing via the top-level package should still work.
        from tools import UpdateMemoryBankTool  # noqa: F401


class AgentsConfigStrippedOfMemoryToolsBundleTests(unittest.TestCase):
    def test_no_profile_declares_memory_tools_bundle(self) -> None:
        import yaml
        cfg_path = (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml")
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        for name, prof in cfg.get("profiles", {}).items():
            bundles = prof.get("tool_bundles") or []
            self.assertNotIn("memory_tools", bundles,
                             f"profile {name!r} still declares memory_tools bundle")


if __name__ == "__main__":
    unittest.main()
