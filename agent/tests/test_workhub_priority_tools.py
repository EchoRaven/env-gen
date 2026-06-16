"""Tests for workhub LLM tools with priority support (Cutover 23)."""

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


class WorkhubPriorityToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_pri_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _find_tool(self, name: str):
        from tools.hub_tools import create_hub_tools
        for tool in create_hub_tools(agent_id="orch", hub_workspace=self.reg):
            if getattr(tool, "NAME", "") == name:
                return tool
        raise AssertionError(f"tool not found: {name}")

    def test_create_task_tool_accepts_priority(self) -> None:
        # WorkHubTaskTool is an action-dispatcher (NAME=workhub_task); use action="create"
        tool = self._find_tool("workhub_task")
        result = _run_async(tool._run(
            action="create", title="urgent", assignee="backend", priority="P0"))
        self.assertTrue(result.success)
        task_id = result.data["id"]
        task = self.reg.workhub.stores.tasks.get(task_id)
        self.assertEqual((task.get("metadata") or {}).get("priority"), "P0")

    def test_set_priority_tool(self) -> None:
        tool_create = self._find_tool("workhub_task")
        result = _run_async(tool_create._run(
            action="create", title="x", assignee="backend"))
        task_id = result.data["id"]
        # set priority via new tool
        tool_set = self._find_tool("workhub_set_priority")
        result = _run_async(tool_set._run(task_id=task_id, priority="P0"))
        self.assertTrue(result.success)
        task = self.reg.workhub.stores.tasks.get(task_id)
        self.assertEqual((task.get("metadata") or {}).get("priority"), "P0")

    def test_list_ready_tool(self) -> None:
        self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        self.reg.workhub.create_task(title="b", agent="orch", assignee="backend")
        tool = self._find_tool("workhub_list_ready")
        result = _run_async(tool._run(assignee="backend"))
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["ready"]), 2)

    def test_list_blocked_tool(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        self.reg.workhub.create_task(
            title="blocked", agent="orch", assignee="backend",
            depends_on=[dep["id"]])
        tool = self._find_tool("workhub_list_blocked")
        result = _run_async(tool._run(assignee="backend"))
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["blocked"]), 1)
        self.assertEqual(result.data["blocked"][0]["title"], "blocked")


if __name__ == "__main__":
    unittest.main()
