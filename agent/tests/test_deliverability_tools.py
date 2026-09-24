"""Tests for deliverability LLM tools (Cutover 24)."""

import asyncio
import json
import shutil
import sys
import tempfile
import time
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


def _passing_run(reg, ts_offset=0.0):
    now = time.time() + ts_offset
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = now
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class DeliverabilityToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="del_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        # The non-waivable AUTHORED-SEED gate (deliverability.py, added outlook
        # run-33 2026-07-02) requires app/backend/seed_data.json with domain-
        # realistic rows (>=10 structured rows, no placeholder markers) before a
        # run may be 'deliverable' — a passing RunHub run alone is no longer
        # sufficient. Author a genuinely-deliverable fixture seed.
        backend = self.app_root / "backend"
        backend.mkdir()
        (backend / "seed_data.json").write_text(json.dumps({
            "users": [
                {"email": "ava.chen@corpmail.com", "name": "Ava Chen", "password": "password"},
                {"email": "marcus.reed@corpmail.com", "name": "Marcus Reed", "password": "password"},
                {"email": "priya.nair@corpmail.com", "name": "Priya Nair", "password": "password"},
            ],
            "messages": [
                {"user_id": 1, "subject": "Re: Q3 planning sync", "body": "Can we move the sync to Thursday afternoon?", "is_read": False},
                {"user_id": 1, "subject": "Your invoice #4021 is ready", "body": "The March invoice is attached for review.", "is_read": False},
                {"user_id": 1, "subject": "Standup moved to 9:30", "body": "Daily standup is now 9:30am starting Monday.", "is_read": True},
                {"user_id": 2, "subject": "Lunch Thursday?", "body": "Want to grab lunch near the office at noon?", "is_read": True},
                {"user_id": 2, "subject": "Design review notes", "body": "Left comments on the checkout flow mockups.", "is_read": False},
                {"user_id": 2, "subject": "Vendor contract renewal", "body": "The vendor agreement renews next month.", "is_read": False},
                {"user_id": 3, "subject": "Weekend hiking plan", "body": "Trailhead at 8am, bring water and sunscreen.", "is_read": True},
                {"user_id": 3, "subject": "Sprint retro action items", "body": "Three follow-ups from the retro are tracked in the board.", "is_read": False},
            ],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_with_no_run_blocked(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["verdict"], "blocked")

    def test_check_with_passing_run_deliverable(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        _passing_run(self.reg)
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["verdict"], "deliverable",
                          f"blockers: {result.data['blockers']}")

    def test_summary_returns_one_line(self) -> None:
        from tools.deliverability_tools import DeliverabilitySummaryTool
        _passing_run(self.reg)
        tool = DeliverabilitySummaryTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertIn("verdict", result.data)
        self.assertIn("blocker_count", result.data)

    def test_check_data_includes_endpoint_and_mcp_probes(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        _passing_run(self.reg)
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertIn("endpoint_probes", result.data)
        self.assertIn("mcp_probes", result.data)


if __name__ == "__main__":
    unittest.main()
