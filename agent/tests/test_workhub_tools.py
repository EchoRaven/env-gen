"""Tests for WorkHub LLM tool classes (Task 8 of Cutover 3)."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_WORKHUB_TOOLS = {
    "workhub_fail_task",
    "workhub_cancel_task",
    "workhub_get_task",
    "workhub_list_tasks",
    "workhub_available_tasks",
    "workhub_get_page",
    "workhub_list_documents",
    # ``workhub_get_plan`` retired in Tier B B3c — read ``task.plan``
    # via ``workhub_get_task`` instead.
    "workhub_link_task_to_pr",
    "workhub_link_task_to_apis",
    "workhub_update_block",
    "workhub_archive_page",
    "workhub_record_decision",
    "workhub_comments_for",
}


def _run(coro):
    return asyncio.run(coro)


class WorkHubToolsExportTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        ws = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="backend", hub_workspace=ws.hubs)
        return ws.hubs, {tool.NAME: tool for tool in tools}

    def test_all_required_workhub_tools_are_exported(self):
        """All 14 new WorkHub tool NAMEs must be present in create_hub_tools output."""
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_WORKHUB_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing tools: {missing}")

    def test_workhub_get_task_tool_happy_path(self):
        """workhub_get_task returns the task when it exists."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            task = hubs.workhub.create_task("Test Task", agent="backend")
            tool = tool_by_name["workhub_get_task"]
            result = _run(tool._run(task_id=task["id"]))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["id"], task["id"])
            self.assertEqual(data["title"], "Test Task")

    def test_workhub_list_tasks_tool_returns_tasks(self):
        """workhub_list_tasks returns a list of tasks in a dict."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.workhub.create_task("Task A", agent="backend")
            hubs.workhub.create_task("Task B", assignee="frontend", agent="backend")
            tool = tool_by_name["workhub_list_tasks"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertGreaterEqual(len(data.get("tasks", [])), 2)

    def test_workhub_list_tasks_tool_filters_by_assignee(self):
        """workhub_list_tasks filters by assignee when specified."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.workhub.create_task("Task A", assignee="frontend", agent="backend")
            hubs.workhub.create_task("Task B", assignee="backend", agent="backend")
            tool = tool_by_name["workhub_list_tasks"]
            result = _run(tool._run(assignee="frontend"))
            data = result.data if hasattr(result, "data") else result
            tasks = data.get("tasks", [])
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["assignee"], "frontend")

    def test_workhub_link_task_to_pr_tool_sets_linked_pr(self):
        """workhub_link_task_to_pr sets linked_pr on the task."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            task = hubs.workhub.create_task("PR Task", agent="backend")
            tool = tool_by_name["workhub_link_task_to_pr"]
            result = _run(tool._run(task_id=task["id"], pr_id="pr_abc123"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data.get("linked_pr"), "pr_abc123")

    def test_workhub_get_task_tool_missing_returns_failure(self):
        """workhub_get_task returns a failure ToolResult for unknown task_id."""
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["workhub_get_task"]
            result = _run(tool._run(task_id="task_nope"))
            success = result.success if hasattr(result, "success") else True
            self.assertFalse(success)

    def test_workhub_available_tasks_tool_returns_list(self):
        """workhub_available_tasks returns pending tasks with no unmet deps."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.workhub.create_task("Free Task", agent="backend")
            tool = tool_by_name["workhub_available_tasks"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertGreaterEqual(len(data.get("tasks", [])), 1)

    def test_workhub_comments_for_tool_returns_comments(self):
        """workhub_comments_for returns comments for the given resource_id."""
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("MyPage", agent="backend")
            hubs.workhub.comment(page["id"], "Hello!", agent="backend")
            tool = tool_by_name["workhub_comments_for"]
            result = _run(tool._run(resource_id=page["id"]))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(len(data.get("comments", [])), 1)


if __name__ == "__main__":
    unittest.main()
