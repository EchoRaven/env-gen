"""Test that codehub_review_pr tool accepts + forwards considered_alternatives.

Note: the plan referred to this tool as `codehub_submit_review`, but the actual
NAME constant is `codehub_review_pr` (class `CodeHubReviewPRTool`). This test
targets the real NAME.
"""

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

from tools.hub_tools import (  # noqa: E402
    create_hub_tools as _create_hub_tools,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _find_submit_review_tool(reg):
    # The PR-review ceremony tool is UNREGISTERED (agents can't call it), but the
    # review-quality SERVICE contract (considered_alternatives forwarding) is still
    # pinned here — construct the class directly.
    from tools.hub_tools import CodeHubReviewPRTool
    return CodeHubReviewPRTool(agent_id="reviewer", hub_workspace=reg)


class SubmitReviewToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="srt_"))
        self.reg = HubRegistry(self.tmp)
        task = self.reg.workhub.create_task(title="t", assignee="backend", agent="orchestrator")
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend",
            target="main",
            # Phase 4.6 gate: 'reviewer' included so the tool fixture
            # (agent_id='reviewer' at line 36) passes the data-driven
            # allowed_set = pr.reviewers ∪ {orchestrator}.
            reviewers=["frontend", "orchestrator", "reviewer"],
            linked_tasks=[task["id"]],
            title="t",
            author="backend",
        )
        self.tool = _find_submit_review_tool(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tool_accepts_considered_alternatives(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="approve",
            inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}],
            considered_alternatives=["considered alt A; rejected because B"],
        ))
        self.assertTrue(result.success, f"tool failed: {result.error_message}")

    def test_tool_forwards_empty_alternatives_to_failure(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="approve",
            inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}],
            considered_alternatives=[],
        ))
        self.assertFalse(result.success)

    def test_tool_request_changes_does_not_require_alternatives(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="request_changes",
            inline_comments=[],
            considered_alternatives=[],
        ))
        self.assertTrue(result.success, f"tool failed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
