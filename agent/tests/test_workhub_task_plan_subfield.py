"""Tier B B2: ``task.plan`` subfield pins.

Per docs/plan_task_stage_tier_b_design_2026_06_03.md (D1/D2/D3):
the canonical home for an agent's per-task structured-think is
the WorkHub task itself, as a subfield ``task.plan``. This file
pins:

  * ``claim_task(task_id, agent, plan=...)`` stores the plan on
    the claimed task row.
  * ``update_task_plan(task_id, plan, agent)`` re-flushes the
    plan from PlanTool's periodic sync; only the claimer can write.
  * Terminal states reject ``update_task_plan`` (the plan-on-task
    is frozen at completion).
  * No plan-update path creates ``plan:<...>`` mirror task rows
    (B1 retired the overflow; B2 must not reintroduce a similar
    bug under a different name).
"""
from __future__ import annotations

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

from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402


def _hub() -> WorkHub:
    tmp = tempfile.mkdtemp()
    return WorkHub(Path(tmp))


_SAMPLE_PLAN = {
    "title": "Implement POST /api/auth/register",
    "has_plan": True,
    "stages": {
        "design": {"tasks": {"choose_bcrypt_rounds": {"status": "completed"}}},
        "impl":   {"tasks": {"write_route":         {"status": "in_progress"}}},
        "test":   {"tasks": {"happy_path":          {"status": "pending"}}},
    },
    "stage_order": ["design", "impl", "test"],
    "current_stage_id": "impl",
}


class ClaimTaskAcceptsPlanArg(unittest.TestCase):

    def test_claim_task_with_plan_persists_plan_subfield(self):
        hub = _hub()
        task = hub.create_task(
            title="Implement POST /api/auth/register",
            task_id="impl.endpoint.post._api_auth_register",
            assignee="backend",
            agent="orchestrator",
        )
        claimed = hub.claim_task(task["id"], "backend", plan=_SAMPLE_PLAN)
        self.assertNotIn("error", claimed)
        self.assertEqual(claimed["plan"]["title"], _SAMPLE_PLAN["title"])
        self.assertEqual(claimed["plan"]["current_stage_id"], "impl")
        # Persisted on the task itself, not a separate store.
        stored = hub.get_task(task["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["plan"]["stages"]["impl"]["tasks"]["write_route"]["status"], "in_progress")

    def test_claim_task_without_plan_does_not_create_plan_subfield(self):
        """Back-compat: existing call sites that don't pass plan=
        produce a task with no ``plan`` key at all."""
        hub = _hub()
        task = hub.create_task(title="T1", assignee="backend", agent="orch")
        claimed = hub.claim_task(task["id"], "backend")
        self.assertNotIn("error", claimed)
        self.assertNotIn("plan", claimed)

    def test_claim_task_plan_is_deep_copy(self):
        """The stored plan must not share mutable state with the
        caller's dict — a later mutation of the source must NOT
        leak into the WorkHub copy."""
        hub = _hub()
        task = hub.create_task(title="T1", assignee="backend", agent="orch")
        plan_source = dict(_SAMPLE_PLAN)
        hub.claim_task(task["id"], "backend", plan=plan_source)
        plan_source["title"] = "MUTATED AFTER CLAIM"
        stored = hub.get_task(task["id"])
        self.assertNotEqual(stored["plan"]["title"], "MUTATED AFTER CLAIM")


class UpdateTaskPlanReflush(unittest.TestCase):

    def setUp(self):
        self.hub = _hub()
        task = self.hub.create_task(
            title="T1", task_id="t1", assignee="backend", agent="orch",
        )
        self.hub.claim_task(task["id"], "backend", plan={"title": "v1", "has_plan": True})

    def test_update_task_plan_overwrites_plan_subfield(self):
        result = self.hub.update_task_plan(
            "t1",
            {"title": "v2", "has_plan": True, "current_stage_id": "test"},
            agent="backend",
        )
        self.assertNotIn("error", result)
        stored = self.hub.get_task("t1")
        self.assertEqual(stored["plan"]["title"], "v2")
        self.assertEqual(stored["plan"]["current_stage_id"], "test")

    def test_update_task_plan_rejects_non_claimer(self):
        """Only the current claimer may overwrite the plan — this is
        the C2 fix from the architecture review (no cross-agent plan
        stomping)."""
        result = self.hub.update_task_plan(
            "t1", {"title": "stolen"}, agent="frontend",
        )
        self.assertIn("error", result)
        stored = self.hub.get_task("t1")
        self.assertEqual(stored["plan"]["title"], "v1")

    def test_update_task_plan_unknown_task_returns_error(self):
        result = self.hub.update_task_plan("nope", {}, agent="backend")
        self.assertIn("error", result)

    def test_update_task_plan_rejects_completed_task(self):
        """Plan freezes at completion. A post-completion flush would
        let an agent rewrite history; reject."""
        self.hub.complete_task("t1", "backend", result={})
        result = self.hub.update_task_plan(
            "t1", {"title": "post-mortem revision"}, agent="backend",
        )
        self.assertIn("error", result)

    def test_update_task_plan_rejects_failed_task(self):
        self.hub.fail_task("t1", "backend", reason="oops", force=True)
        result = self.hub.update_task_plan(
            "t1", {"title": "x"}, agent="backend",
        )
        self.assertIn("error", result)


class UpdateTaskPlanDoesNotCreateMirrorTasks(unittest.TestCase):
    """B1 invariant pin: update_task_plan must NOT fan out into the
    retired ``plan:<...>`` mirror task store. Catches accidental
    regression of the C1/C2/C3 bug shape under a B2-renamed API."""

    def test_update_task_plan_leaves_other_task_rows_alone(self):
        hub = _hub()
        a = hub.create_task(title="A", task_id="a", assignee="backend", agent="orch")
        b = hub.create_task(title="B", task_id="b", assignee="frontend", agent="orch")
        hub.claim_task("a", "backend", plan={"title": "p"})
        before = set((hub.stores.tasks.value() or {}).keys())
        hub.update_task_plan(
            "a", {"title": "p2", "has_plan": True, "stages": {
                "impl": {"tasks": {"foo": {"status": "pending"}}}
            }}, agent="backend",
        )
        after = set((hub.stores.tasks.value() or {}).keys())
        self.assertEqual(
            before, after,
            f"task store membership must not change on plan update; "
            f"diff: {after - before} added, {before - after} removed",
        )
        # Specifically: no ``plan:a:foo`` mirror row appeared.
        self.assertIsNone(hub.get_task("plan:a:foo"))


if __name__ == "__main__":
    unittest.main()
