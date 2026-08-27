"""#1127: a FAILED task that was never claimed had no way out of `failed`.

`unresolved_failed_tasks` blocks the delivery cut on any task left in `failed`, and that
check's own comment tells the lane the escape is to "complete the task, or cancel it if it
was wrong". #1041 built a re-wake path on that sentence. Neither escape existed for a task
that was failed without ever being claimed:

    cancel_task   -> "Cannot cancel task in terminal state: failed"
    complete_task -> "Only claimer can complete task"   (claimed_by is None)
    claim_task    -> "Task is not pending"              (never re-claimable)

Corpus: 68 runs with a task ledger, 11 (16%) end holding a failed task, 4 (5%) hold 7 tasks
in this zero-exit shape. Live case netflix-local-r1 aborted after ~147 minutes with 153 of
173 tasks completed, blocked by one such task whose own fail_reason says the defect no
longer holds.
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
    return WorkHub(Path(tempfile.mkdtemp()))


def _orphan_failed(hub, title="P0 backend: fix custom_routes 500s"):
    """The netflix-local-r1 shape: created by the orchestrator, never claimed, failed."""
    task = hub.create_task(title, agent="orchestrator")
    hub.fail_task(task["id"], agent="orchestrator", reason="stale/terminal validation blocker")
    rec = hub.stores.tasks.get(task["id"])
    assert rec["status"] == "failed", rec["status"]
    assert not rec.get("claimed_by"), rec.get("claimed_by")
    return task["id"]


class TheDoorTheGatePromised(unittest.TestCase):

    def test_the_other_two_doors_really_are_shut(self):
        """The premise. If either of these ever opens, #1127 is the wrong fix."""
        hub = _hub()
        tid = _orphan_failed(hub)

        # complete: rejected -- there is no claimer to be.
        self.assertIn("error", hub.complete_task(tid, "backend", result={}))
        # claim: rejected -- so it can never acquire one either.
        self.assertIn("error", hub.claim_task(tid, "backend"))
        self.assertEqual(hub.stores.tasks.get(tid)["status"], "failed")

    def test_the_orchestrator_can_now_cancel_a_failed_task(self):
        """The fix: failed is no longer a dead end."""
        hub = _hub()
        tid = _orphan_failed(hub)

        result = hub.cancel_task(tid, agent="orchestrator", reason="defect no longer holds")

        self.assertNotIn("error", result)
        self.assertEqual(hub.stores.tasks.get(tid)["status"], "cancelled")

    def test_cancelling_it_actually_clears_the_delivery_blocker(self):
        """Status is not the point -- the point is that the GATE stops counting it.

        A fix that only renamed the status would leave the run just as stuck.
        """
        from multi_agent.runtime.delivery_gate import unresolved_bug_tasks_743

        hub = _hub()
        tid = _orphan_failed(hub)

        class _Hubs:
            pass
        hubs = _Hubs()
        hubs.workhub = hub

        before = unresolved_bug_tasks_743(hubs, None, set()) or {}
        self.assertEqual(before.get("failed_count"), 1,
                         "premise: the gate counts this task before the cancel")

        hub.cancel_task(tid, agent="orchestrator", reason="defect no longer holds")

        after = unresolved_bug_tasks_743(hubs, None, set()) or {}
        self.assertFalse(after.get("failed_count"),
                         "the gate still counts a task that was cancelled")

    def test_completed_and_cancelled_stay_refused(self):
        """The half of the guard that was doing real work is untouched."""
        hub = _hub()

        done = hub.create_task("Build API", agent="orchestrator")
        hub.claim_task(done["id"], "backend")
        hub.complete_task(done["id"], "backend", result={})
        self.assertIn("error", hub.cancel_task(done["id"], agent="orchestrator"))

        tid = _orphan_failed(hub, title="second")
        hub.cancel_task(tid, agent="orchestrator", reason="moot")
        # re-cancelling a cancelled task is still history rewriting.
        self.assertIn("error", hub.cancel_task(tid, agent="orchestrator", reason="again"))

    def test_a_stranger_lane_still_cannot_cancel_it(self):
        """#1127 relaxes the STATE check only. The 2026-06-10 bulk-cancel case stays closed."""
        hub = _hub()
        task = hub.create_task("orchestrator's plan item", agent="orchestrator")
        hub.fail_task(task["id"], agent="orchestrator", reason="blocked")

        result = hub.cancel_task(task["id"], agent="frontend", reason="I disagree with it")

        self.assertIn("error", result)
        self.assertIn("cancel denied", result["error"])
        self.assertEqual(hub.stores.tasks.get(task["id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
