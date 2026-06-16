"""Tests for bug-triage LLM tools (Cutover 10).

Adapted to the real `HubTool` convention used across `tools/hub_tools.py`:
  - Tool classes subclass `HubTool` (constructed with `agent_id=`, `hub_workspace=`)
  - Entry point is async `_run(self, **kwargs) -> ToolResult`
  - Tools reach the registry via `self._hubs` (a HubRegistry instance)
  - Identity is `self._agent_id`
This file therefore drives the tools the same way the framework would; it does
not depend on any MagicMock ctx shape.
"""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.bug_tools import (  # noqa: E402
    BugCreateTool, BugListOpenTool, BugListAssignedToTool,
    BugTriageTool, BugUpdateStateTool, BugCloseTool, BugEscalateTool,
)


def _run(tool, **kwargs):
    """Drive an async tool synchronously and unwrap its ToolResult.data.

    Uses an ad-hoc loop per call (and does NOT touch the process-wide default
    loop) so that interleaved tests in the discover suite which rely on
    ``asyncio.get_event_loop()`` are not polluted.
    """
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(tool._run(**kwargs))
    finally:
        loop.close()
    if not getattr(result, "success", True):
        raise AssertionError(f"tool failed: {getattr(result, 'error_message', '?')}")
    return result.data


class BugToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="bug_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tool(self, cls, agent_id="bug_triage_orchestrator"):
        return cls(agent_id=agent_id, hub_workspace=self.reg)

    def test_bug_create_creates_bug_task_with_metadata(self) -> None:
        tool = self._tool(BugCreateTool)
        out = _run(tool,
                   title="500 on POST /api/feed",
                   description="reproducible from test_x",
                   source="verifier",
                   severity="P1",
                   bug_artifacts={"affected_endpoint": "POST /api/feed"})
        self.assertIn("id", out)
        task = self.reg.workhub.stores.tasks.get(out["id"])
        self.assertEqual(task["metadata"]["kind"], "bug")
        self.assertEqual(task["metadata"]["severity"], "P1")
        self.assertEqual(task["metadata"]["bug_state"], "open")
        self.assertEqual(task["metadata"]["source"], "verifier")

    def test_bug_list_open_lists_only_open(self) -> None:
        create = self._tool(BugCreateTool)
        _run(create, title="a", source="verifier",
             severity="P1", bug_artifacts={"failing_test": "test_a"})
        b = _run(create, title="b", source="verifier",
                 severity="P0", bug_artifacts={"failing_test": "test_b"})
        out = _run(self._tool(BugListOpenTool))
        self.assertEqual(len(out["bugs"]), 2)
        self.assertEqual(out["bugs"][0]["id"], b["id"])  # P0 first

    def test_bug_triage_assigns_and_records_root_cause(self) -> None:
        self.reg.registryhub.register_endpoint("POST", "/api/feed", schema={},
                                          provider="backend", agent="backend")
        create = self._tool(BugCreateTool)
        created = _run(create, title="500 feed",
                       source="verifier", severity="P1",
                       bug_artifacts={"affected_endpoint": "POST /api/feed"})
        triaged = _run(self._tool(BugTriageTool),
                       task_id=created["id"],
                       root_cause="missing null check")
        self.assertEqual(triaged["assignee"], "backend")
        self.assertEqual(triaged["metadata"]["bug_state"], "assigned")
        self.assertEqual(triaged["metadata"]["root_cause_hypothesis"],
                         "missing null check")

    def test_bug_triage_with_explicit_assignee_overrides_resolver(self) -> None:
        created = _run(self._tool(BugCreateTool), title="x", source="manual",
                       severity="P2", bug_artifacts={"failing_test": "test_triage_override"})
        triaged = _run(self._tool(BugTriageTool),
                       task_id=created["id"],
                       root_cause="x", assignee="frontend")
        self.assertEqual(triaged["assignee"], "frontend")

    def test_bug_list_assigned_to_returns_assigned_bugs(self) -> None:
        self.reg.registryhub.register_endpoint("GET", "/api/y", schema={},
                                          provider="backend", agent="backend")
        created = _run(self._tool(BugCreateTool), title="500", source="verifier",
                       severity="P1",
                       bug_artifacts={"affected_endpoint": "GET /api/y"})
        _run(self._tool(BugTriageTool), task_id=created["id"], root_cause="x")
        out = _run(self._tool(BugListAssignedToTool, agent_id="backend"))
        self.assertEqual(len(out["bugs"]), 1)

    def test_bug_update_state_transitions(self) -> None:
        created = _run(self._tool(BugCreateTool), title="x", source="verifier",
                       severity="P1", bug_artifacts={"failing_test": "test_update_state"})
        _run(self._tool(BugTriageTool), task_id=created["id"],
             root_cause="x", assignee="backend")
        out = _run(self._tool(BugUpdateStateTool, agent_id="backend"),
                   task_id=created["id"],
                   new_state="in_progress", note="starting")
        self.assertEqual(out["metadata"]["bug_state"], "in_progress")

    def test_bug_close_sets_state_and_evidence(self) -> None:
        created = _run(self._tool(BugCreateTool), title="x", source="verifier",
                       severity="P1", bug_artifacts={"failing_test": "test_close"})
        _run(self._tool(BugTriageTool), task_id=created["id"],
             root_cause="x", assignee="backend")
        out = _run(self._tool(BugCloseTool, agent_id="backend"),
                   task_id=created["id"],
                   fix_evidence={"pr": "PR-1"})
        self.assertEqual(out["metadata"]["bug_state"], "closed")
        self.assertEqual(out["metadata"]["fix_evidence"], {"pr": "PR-1"})

    def test_bug_escalate_marks_state_escalated(self) -> None:
        created = _run(self._tool(BugCreateTool), title="x", source="verifier",
                       severity="P1", bug_artifacts={"failing_test": "test_escalate"})
        out = _run(self._tool(BugEscalateTool),
                   task_id=created["id"],
                   reason="3 failed fix attempts")
        self.assertEqual(out["metadata"]["bug_state"], "escalated")


if __name__ == "__main__":
    unittest.main()
