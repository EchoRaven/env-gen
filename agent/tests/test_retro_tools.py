"""Tests for retro LLM tools (Cutover 16)."""

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


_PVR = [
    {"plan_item": "ship feed by EOD", "actual_outcome": "shipped morning of next day",
     "drift_reason": "schema gate fired late"},
    {"plan_item": "0 force-merges", "actual_outcome": "1 force-merge on auth PR",
     "drift_reason": "blocker on review queue"},
]
_LESSONS = ["catch schema drift earlier", "preview reviewer queue saturation"]
_PROMPT_CHANGES = [{"agent_profile": "design",
                     "change_description": "publish schema spec immediately when design moves to under_review"}]


class RetroToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_tool(self, cls, **kwargs):
        from tools import retro_tools as rt
        instance = cls(hub_registry=self.reg, generation_id=1000.0, **kwargs)
        return instance

    def test_submit_retro_with_required_fields_succeeds(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="generation 2026-05-24 retro",
            plan_vs_reality=_PVR, systematic_failures=["queue saturation"],
            lessons=_LESSONS, proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(result.success, f"failed: {result.error_message}")
        self.assertIn("id", result.data)
        retro = self.reg.gate_registry.get_latest_retro_for_generation(1000.0)
        self.assertIsNotNone(retro)
        self.assertEqual(retro["kind"], "retro")

    def test_submit_retro_rejects_under_2_plan_vs_reality(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR[:1],
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertFalse(result.success)

    def test_submit_retro_rejects_under_2_lessons(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=["only one"],
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertFalse(result.success)

    def test_submit_retro_rejects_empty_proposed_prompt_changes(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=[]))
        self.assertFalse(result.success)

    def test_submit_retro_accepts_empty_systematic_failures(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_retro_auto_populates_aggregated_stats(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        self.reg.workhub.create_task(title="b1", agent="orch", kind="bug",
                                       severity="P1", bug_state="closed")
        tool = self._make_tool(SubmitRetroTool)
        _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        retro = self.reg.gate_registry.get_latest_retro_for_generation(1000.0)
        meta = retro["metadata"]
        self.assertIn("bug_stats", meta)
        self.assertEqual(meta["bug_stats"]["total_bugs"], 1)
        self.assertIn("run_stats", meta)
        self.assertIn("review_stats", meta)

    def test_list_retros_returns_retros(self) -> None:
        from tools.retro_tools import SubmitRetroTool, ListRetrosTool
        _run_async(self._make_tool(SubmitRetroTool).execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        list_tool = self._make_tool(ListRetrosTool)
        result = _run_async(list_tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["retros"]), 1)

    def test_get_retro_stats_returns_aggregated_stats(self) -> None:
        from tools.retro_tools import GetRetroStatsTool
        self.reg.workhub.create_task(title="b", agent="orch", kind="bug",
                                       severity="P0", bug_state="open")
        tool = self._make_tool(GetRetroStatsTool)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["bug_stats"]["total_bugs"], 1)


if __name__ == "__main__":
    unittest.main()
