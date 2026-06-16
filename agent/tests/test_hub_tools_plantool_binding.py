"""Tier B B3a: hub_tools.py wires PlanTool attach/detach on the
LLM-facing claim/complete/fail/cancel tool surfaces.

Per docs/plan_task_stage_tier_b_design_2026_06_03.md §2:
when the LLM agent calls ``workhub_task(action='claim', ...)``,
the calling agent's PlanTool must auto-bind to the claimed task
so subsequent ``_sync_plan_index`` flushes populate ``task.plan``.
Symmetrically, ``complete`` / ``fail`` / ``cancel`` must auto-
detach.

Pins:
  * Successful claim → PlanTool._task_id set to claimed task_id.
  * Failed claim (wrong assignee / dep-blocked) → PlanTool stays
    unbound.
  * complete / fail / cancel → PlanTool._task_id cleared on
    success; left alone on error.
  * PlanTool side-effect must never break the hub call (best-effort).
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import (  # noqa: E402
    WorkHubTaskTool,
    WorkHubFailTaskTool,
    WorkHubCancelTaskTool,
)
from tools.reasoning_tools import PlanTool  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _setup(agent_id: str = "backend"):
    """Build a HubRegistry + bound tool + clean PlanTool instance."""
    td = tempfile.mkdtemp()
    hubs = HubRegistry(Path(td))
    # Tools expect ``self._hubs`` to be a registry-shaped object;
    # HubRegistry itself works since the tools call .workhub directly.
    plan_tool = PlanTool.get_instance(agent_id)
    plan_tool.reset()  # clear any state from earlier tests
    return hubs, plan_tool, td


def _bind(tool, hubs, agent_id):
    tool._hubs = hubs
    tool._agent_id = agent_id
    return tool


class ClaimAttachesPlanTool(unittest.TestCase):

    def test_claim_success_binds_plantool_task_id(self):
        hubs, plan_tool, _ = _setup("backend")
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="orch",
        )
        tool = _bind(WorkHubTaskTool(), hubs, "backend")
        self.assertIsNone(plan_tool._task_id)
        result = _run(tool._run(action="claim", task_id="t1"))
        self.assertNotIn("error", result.data or {})
        self.assertEqual(plan_tool._task_id, "t1")

    def test_claim_failure_does_not_bind(self):
        """Failed claim (wrong assignee) must NOT bind — otherwise the
        agent's PlanTool would point at a task someone else owns."""
        hubs, plan_tool, _ = _setup("backend")
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="frontend", agent="orch",
        )
        tool = _bind(WorkHubTaskTool(), hubs, "backend")
        result = _run(tool._run(action="claim", task_id="t1"))
        self.assertIn("error", result.data or {})
        self.assertIsNone(plan_tool._task_id)


class CompleteFailCancelDetachPlanTool(unittest.TestCase):

    def _claim(self, hubs, tool, task_id, plan_tool):
        _run(tool._run(action="claim", task_id=task_id))
        self.assertEqual(plan_tool._task_id, task_id)

    def test_complete_success_detaches(self):
        hubs, plan_tool, _ = _setup("backend")
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="orch",
        )
        tool = _bind(WorkHubTaskTool(), hubs, "backend")
        self._claim(hubs, tool, "t1", plan_tool)
        result = _run(tool._run(action="complete", task_id="t1"))
        self.assertNotIn("error", result.data or {})
        self.assertIsNone(plan_tool._task_id)

    def test_complete_failure_keeps_binding(self):
        """A complete call for a task we don't own returns error;
        the PlanTool binding (to our actual task) must stay."""
        hubs, plan_tool, _ = _setup("backend")
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="orch",
        )
        hubs.workhub.create_task(
            title="T2", task_id="t2", assignee="frontend", agent="orch",
        )
        tool = _bind(WorkHubTaskTool(), hubs, "backend")
        self._claim(hubs, tool, "t1", plan_tool)
        # Try to complete a task we don't own — should error + leave
        # our binding to t1 intact.
        result = _run(tool._run(action="complete", task_id="t2"))
        self.assertIn("error", result.data or {})
        self.assertEqual(
            plan_tool._task_id, "t1",
            "binding to t1 must survive failed complete of t2",
        )

    def test_fail_success_detaches(self):
        hubs, plan_tool, _ = _setup("backend")
        # creator == backend: completion discipline allows the CREATOR to fail
        # its own task; lanes failing others' tasks is denied at the service.
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="backend",
        )
        claim_tool = _bind(WorkHubTaskTool(), hubs, "backend")
        fail_tool = _bind(WorkHubFailTaskTool(), hubs, "backend")
        self._claim(hubs, claim_tool, "t1", plan_tool)
        result = _run(fail_tool._run(task_id="t1", reason="bug"))
        self.assertNotIn("error", result.data or {})
        self.assertIsNone(plan_tool._task_id)

    def test_cancel_success_detaches(self):
        hubs, plan_tool, _ = _setup("backend")
        # completion discipline: only the CREATOR (or orchestrator) cancels —
        # create the task as backend itself so its cancel is legitimate.
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="backend",
        )
        claim_tool = _bind(WorkHubTaskTool(), hubs, "backend")
        cancel_tool = _bind(WorkHubCancelTaskTool(), hubs, "backend")
        self._claim(hubs, claim_tool, "t1", plan_tool)
        result = _run(cancel_tool._run(task_id="t1", reason="abort"))
        self.assertNotIn("error", result.data or {})
        self.assertIsNone(plan_tool._task_id)


class HubResultIntegrity(unittest.TestCase):
    """The PlanTool side-binding must never alter the hub-call return
    value or break the tool. Pin: the tool returns the raw hub result
    plus exactly the same data shape with or without the binding."""

    def test_claim_result_is_unaltered(self):
        hubs, _, _ = _setup("backend")
        hubs.workhub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="orch",
        )
        tool = _bind(WorkHubTaskTool(), hubs, "backend")
        result = _run(tool._run(action="claim", task_id="t1"))
        # Standard hub fields present.
        for key in ("id", "claimed_by", "status", "claim_token"):
            self.assertIn(key, result.data)
        self.assertEqual(result.data["claimed_by"], "backend")
        self.assertEqual(result.data["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
