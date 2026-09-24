"""Tests for coverage LLM tools (Cutover 19)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class CoverageToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_tools_"))
        self.reg = HubRegistry(self.tmp / "hub")
        self.app_root = self.tmp / "app"
        self.app_root.mkdir(parents=True)
        # Bare main + one dead component
        (self.app_root / "frontend/src").mkdir(parents=True)
        (self.app_root / "frontend/src/main.tsx").write_text("x = 1;\n")
        (self.app_root / "frontend/src/Dead.tsx").write_text("x = 1;\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_coverage_audit_check_returns_report(self) -> None:
        from tools.coverage_tools import CoverageAuditCheckTool
        tool = CoverageAuditCheckTool(hub_registry=self.reg,
                                       app_root=str(self.app_root))
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertIn("dead_files", result.data)
        self.assertEqual(len(result.data["dead_files"]), 1)

    def test_mark_intentionally_dead_via_tool(self) -> None:
        from tools.coverage_tools import MarkIntentionallyDeadTool
        tool = MarkIntentionallyDeadTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            path="file:frontend/src/Dead.tsx",
            reason="WIP placeholder"))
        self.assertTrue(result.success)
        self.assertEqual(self.reg.gate_registry.list_coverage_allowlist()[0]["reason"],
                          "WIP placeholder")

    def test_list_dead_allowlist_returns_entries(self) -> None:
        from tools.coverage_tools import ListDeadAllowlistTool
        self.reg.gate_registry.mark_path_intentionally_dead(
            "file:x.tsx", reason="r", agent="orchestrator")
        tool = ListDeadAllowlistTool(hub_registry=self.reg)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["allowlist"]), 1)

    def test_mark_rejects_empty_reason(self) -> None:
        from tools.coverage_tools import MarkIntentionallyDeadTool
        tool = MarkIntentionallyDeadTool(hub_registry=self.reg)
        result = _run_async(tool.execute(path="file:x.tsx", reason=""))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
