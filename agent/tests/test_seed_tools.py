"""Tests for seed LLM tools (Cutover 21)."""

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


_GOOD = [{"id": 1, "name": "Alex", "email": "alex@gmail.com", "is_active": True}]


class SeedToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seed_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_seed_data_tool(self) -> None:
        from tools.seed_tools import RegisterSeedDataTool
        tool = RegisterSeedDataTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            table_name="users", row_count=42,
            sample_excerpt=[{"id": 1, "name": "Alex"}]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["record"]["row_count"], 42)

    def test_register_seed_data_unknown_table_fails(self) -> None:
        from tools.seed_tools import RegisterSeedDataTool
        tool = RegisterSeedDataTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            table_name="missing", row_count=10,
            sample_excerpt=[]))
        self.assertFalse(result.success)

    def test_seed_audit_check_clean(self) -> None:
        from tools.seed_tools import (
            RegisterSeedDataTool, SeedAuditCheckTool,
        )
        _run_async(RegisterSeedDataTool(hub_registry=self.reg).execute(
            table_name="users", row_count=42, sample_excerpt=_GOOD))
        result = _run_async(SeedAuditCheckTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertTrue(result.data["is_clean"])
        self.assertEqual(result.data["flagged_tables"], [])

    def test_seed_audit_check_flags_missing(self) -> None:
        from tools.seed_tools import SeedAuditCheckTool
        result = _run_async(SeedAuditCheckTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertFalse(result.data["is_clean"])
        self.assertEqual(result.data["flagged_tables"][0]["reason"], "missing_seed")

    def test_list_seed_issues_summary(self) -> None:
        from tools.seed_tools import ListSeedIssuesTool
        result = _run_async(ListSeedIssuesTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        # missing seed -> flagged
        self.assertEqual(len(result.data["issues"]), 1)


if __name__ == "__main__":
    unittest.main()
