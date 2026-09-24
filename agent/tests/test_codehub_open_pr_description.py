"""Guard: codehub_open_pr accepts + persists a PR `description` (body).

Agents naturally call `codehub_open_pr(..., description="...")` to give the PR a
body. Before this fix the tool advertised only `title`, so the natural call
crashed with "unexpected keyword argument 'description'" — one wasted round, then
a retry without the body. This pins that the kwarg is accepted end-to-end (tool →
service) and the body lands on the PR record. Domain-agnostic.
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
from tools.hub_tools import CodeHubOpenPRTool  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class OpenPRDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="oprd_"))
        self.reg = HubRegistry(self.tmp)
        self.task = self.reg.workhub.create_task(title="t", assignee="backend", agent="orchestrator")
        self.tool = CodeHubOpenPRTool(agent_id="backend", hub_workspace=self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_schema_advertises_description(self):
        self.assertIn("description", CodeHubOpenPRTool.PARAMETERS["properties"])

    def test_description_kwarg_accepted_and_persisted(self):
        body = "Implements the search endpoint and wires the results page."
        res = _run_async(self.tool._run(
            branch="agent/backend",
            linked_tasks=[self.task["id"]],
            reviewers=["frontend", "orchestrator"],
            title="Add search",
            description=body,
        ))
        self.assertTrue(res.success, getattr(res, "error_message", None))
        pr_id = res.data["id"]
        pr = self.reg.codehub.get_pull_request(pr_id) if hasattr(self.reg.codehub, "get_pull_request") else res.data
        self.assertEqual(pr.get("description"), body)

    def test_description_optional(self):
        # Omitting it still works and yields an empty body (no crash, no None-vs-missing surprise).
        res = _run_async(self.tool._run(
            branch="agent/backend",
            linked_tasks=[self.task["id"]],
            reviewers=["frontend", "orchestrator"],
            title="No body",
        ))
        self.assertTrue(res.success, getattr(res, "error_message", None))
        self.assertEqual(res.data.get("description", ""), "")


if __name__ == "__main__":
    unittest.main()
