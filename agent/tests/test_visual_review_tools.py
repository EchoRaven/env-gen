"""Tests for visual review LLM tools (Cutover 20)."""

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


_GOOD_DEV = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8", "actual": "#2563eb", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px gap", "actual": "8px gap", "severity": "medium"},
    {"aspect": "card border radius",
     "expected": "12px", "actual": "4px", "severity": "low"},
]


class VisualReviewToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_creates_visual_review_task(self) -> None:
        from tools.visual_review_tools import RegisterVisualReviewTaskTool
        tool = RegisterVisualReviewTaskTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            route="/feed", screenshot_path="/tmp/feed.png",
            reference_path="/tmp/ref-feed.png", critical=True))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["metadata"]["route"], "/feed")

    def test_list_pending_returns_pending_pages(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, ListPendingVisualReviewsTool,
        )
        _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        result = _run_async(ListPendingVisualReviewsTool(
            hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["pending"]), 1)

    def test_submit_approve_with_3_deviations(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(SubmitVisualReviewTool(
            hub_registry=self.reg).execute(
            page_id=page_id, state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches reference closely; minor color drift"))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["status"], "approved")

    def test_submit_approve_with_2_deviations_fails(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(SubmitVisualReviewTool(
            hub_registry=self.reg).execute(
            page_id=page_id, state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV[:2],
            summary="..............................."))
        self.assertFalse(result.success)

    def test_get_status_returns_current(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, GetVisualReviewStatusTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(GetVisualReviewStatusTool(
            hub_registry=self.reg).execute(page_id=page_id))
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pending")
        self.assertEqual(result.data["critical"], True)


if __name__ == "__main__":
    unittest.main()
