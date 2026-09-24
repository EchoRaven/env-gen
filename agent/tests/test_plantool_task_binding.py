"""Tier B B2: PlanTool ``task_id`` binding pins.

Per docs/plan_task_stage_tier_b_design_2026_06_03.md (D5):
PlanTool's plan is private working state until the agent claims a
WorkHub task. ``attach_to_task(task_id)`` then binds the tool to
that task, and every subsequent ``_sync_plan_index`` additionally
flushes the plan to ``WorkHub.task[task_id].plan``.

Pins:
  * attach_to_task → ``self._task_id`` set; subsequent
    ``_sync_plan_index`` writes to ``task.plan``.
  * detach_from_task → ``self._task_id`` cleared; subsequent
    syncs do NOT touch any task.
  * Pre-attach syncs only touch the agent-keyed snapshot, not any
    task.plan.
  * Flush failure on a terminal task auto-detaches (no infinite
    re-flush loop on a doomed task).
"""
from __future__ import annotations

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
from tools.reasoning_tools import PlanTool, StagedPlan, PlanStage, PlanTask  # noqa: E402


def _build_plantool_bound_to_hubs(hubs: HubRegistry, agent_id: str = "backend") -> PlanTool:
    """Construct a PlanTool with a minimal plan + binding to a
    HubRegistry. Mirrors the runtime ``set_agent`` path without
    requiring an actual Agent instance."""
    tool = PlanTool(agent_id=agent_id)
    tool._hubs = SimpleNamespace(hubs=hubs)
    tool._plan = StagedPlan(
        name="impl POST /api/auth/register",
        description="Plan for the register endpoint",
        stages={
            "design": PlanStage(
                id="design", name="Design", description="design stage",
                tasks={
                    "choose_rounds": PlanTask(
                        id="choose_rounds", description="bcrypt rounds",
                        status="completed",
                    ),
                },
            ),
            "impl": PlanStage(
                id="impl", name="Implement", description="impl stage",
                tasks={
                    "write_route": PlanTask(
                        id="write_route", description="route handler",
                        status="in_progress",
                    ),
                },
            ),
        },
        stage_order=["design", "impl"],
        current_stage_id="impl",
    )
    return tool


def _seed_task(hubs: HubRegistry, task_id: str, agent: str = "backend") -> dict:
    return hubs.workhub.create_task(
        title=f"impl {task_id}", task_id=task_id,
        assignee=agent, agent="orchestrator",
    )


class AttachDetach(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.hubs = HubRegistry(Path(self._td.name))
        self.tool = _build_plantool_bound_to_hubs(self.hubs)

    def tearDown(self):
        self._td.cleanup()

    def test_attach_to_task_sets_task_id(self):
        self.assertIsNone(self.tool._task_id)
        self.tool.attach_to_task("t1")
        self.assertEqual(self.tool._task_id, "t1")

    def test_detach_clears_task_id(self):
        self.tool.attach_to_task("t1")
        self.tool.detach_from_task()
        self.assertIsNone(self.tool._task_id)

    def test_reset_clears_task_id(self):
        """reset() is the wipe-everything escape hatch — also clears
        any task binding so a fresh plan doesn't accidentally flush
        to a stale task."""
        self.tool.attach_to_task("t1")
        self.tool.reset()
        self.assertIsNone(self.tool._task_id)

    def test_re_attach_to_different_task_rebinds(self):
        self.tool.attach_to_task("t1")
        self.tool.attach_to_task("t2")
        self.assertEqual(self.tool._task_id, "t2")


class SyncBehavior(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.hubs = HubRegistry(Path(self._td.name))
        self.tool = _build_plantool_bound_to_hubs(self.hubs)
        _seed_task(self.hubs, "t1")
        # Backend claims (without a plan arg; the sync is the path
        # that should flush).
        self.hubs.workhub.claim_task("t1", "backend")

    def tearDown(self):
        self._td.cleanup()

    def test_sync_pre_attach_does_not_touch_task_plan(self):
        """Before attach_to_task, _sync_plan_index only writes the
        agent-keyed snapshot — NOT any task.plan."""
        self.tool._sync_plan_index(source_action="test")
        task = self.hubs.workhub.get_task("t1")
        self.assertNotIn("plan", task)

    def test_sync_post_attach_flushes_to_task_plan(self):
        self.tool.attach_to_task("t1")
        self.tool._sync_plan_index(source_action="test")
        task = self.hubs.workhub.get_task("t1")
        self.assertIn("plan", task)
        # Round-trips the live plan content.
        self.assertEqual(task["plan"]["current_stage_id"], "impl")
        self.assertEqual(task["plan"]["plan_name"], "impl POST /api/auth/register")

    def test_sync_after_detach_does_not_overwrite_task_plan(self):
        self.tool.attach_to_task("t1")
        self.tool._sync_plan_index(source_action="initial")
        self.tool.detach_from_task()
        # Mutate the in-memory plan; if the sync still wrote, we'd see it.
        self.tool._plan.current_stage_id = "design"
        self.tool._sync_plan_index(source_action="post-detach")
        task = self.hubs.workhub.get_task("t1")
        self.assertEqual(
            task["plan"]["current_stage_id"], "impl",
            "post-detach sync must not overwrite the task.plan snapshot",
        )

    def test_sync_after_task_completes_auto_detaches(self):
        """Flush to a completed task fails (update_task_plan rejects
        terminal). PlanTool must auto-detach so subsequent steps
        don't hammer the doomed task_id."""
        self.tool.attach_to_task("t1")
        self.hubs.workhub.complete_task("t1", "backend", result={})
        # First flush attempt fails; auto-detach happens.
        self.tool._sync_plan_index(source_action="after_complete")
        self.assertIsNone(
            self.tool._task_id,
            "PlanTool must auto-detach after flush to terminal task fails",
        )

    def test_sync_silent_when_no_hubs(self):
        """A PlanTool without hubs (test fixtures, early bootstrap)
        must not raise. Already covered by _sync_plan_index's
        try/except, but pin it."""
        tool = PlanTool(agent_id="orphan")
        tool._hubs = None
        tool.attach_to_task("t1")
        # Should not raise.
        tool._sync_plan_index(source_action="orphan_test")


if __name__ == "__main__":
    unittest.main()
