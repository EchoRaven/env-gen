"""#1128: the failed-task re-wake was addressed to an agent both guards refuse.

`unresolved_failed_tasks` re-wakes an owner and prescribes two escapes -- COMPLETE it or
CANCEL it. WorkHub grants them to different agents (`complete_task` to the claimer,
`cancel_task` to the creator or the orchestrator), and the dispatcher routed on `assignee`,
which is neither for a task that was never claimed.

The collector was the reason it could not do better: it carried `assignee` (added by #1041 so
the task could be routed to somebody) but neither `claimed_by` nor `created_by`, so the
authority question was unanswerable at the point the decision is made.

Corpus: 33 failed tasks all carry an assignee; 6 of them (18%, across tiktok-web-r74,
tiktok-web-r92 and netflix-local-r1) name an assignee who is neither claimer nor creator --
every one an orchestrator-created task nobody ever claimed.
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
from multi_agent.runtime.delivery_gate import unresolved_bug_tasks_743  # noqa: E402
from multi_agent.runtime.remediation_dispatcher import failed_task_owner_1128  # noqa: E402


def _hub() -> WorkHub:
    return WorkHub(Path(tempfile.mkdtemp()))


class _Hubs:
    def __init__(self, wh):
        self.workhub = wh


class TheCollectorCarriesTheAnswer(unittest.TestCase):

    def test_the_failed_record_now_says_who_may_act(self):
        hub = _hub()
        t = hub.create_task("P0 backend: fix custom_routes 500s",
                            agent="orchestrator", assignee="backend")
        hub.fail_task(t["id"], agent="orchestrator", reason="stale blocker")

        rec = (unresolved_bug_tasks_743(_Hubs(hub), None, set()) or {})["failed"][0]

        self.assertEqual(rec.get("assignee"), "backend")
        self.assertEqual(rec.get("created_by"), "orchestrator")
        self.assertFalse(rec.get("claimed_by"), "nobody ever claimed it")


class RoutedToSomebodyWhoCanAct(unittest.TestCase):

    def test_the_netflix_shape_goes_to_the_creator_not_the_assignee(self):
        """assignee=backend, never claimed, created by the orchestrator."""
        owner = failed_task_owner_1128(
            {"assignee": "backend", "claimed_by": None, "created_by": "orchestrator"})
        self.assertEqual(owner, "orchestrator")

    def test_a_claimer_who_gave_up_still_gets_its_own_task_back(self):
        """The common case must not regress -- that agent CAN complete it."""
        owner = failed_task_owner_1128(
            {"assignee": "backend", "claimed_by": "backend", "created_by": "orchestrator"})
        self.assertEqual(owner, "backend")

    def test_an_assignee_that_created_it_keeps_it(self):
        """It cannot complete it, but it may cancel it -- that is a real escape."""
        owner = failed_task_owner_1128(
            {"assignee": "frontend", "claimed_by": None, "created_by": "frontend"})
        self.assertEqual(owner, "frontend")

    def test_an_older_ledger_keeps_the_pre_1128_behaviour(self):
        """Neither field present: unjudgeable, so do not silently re-route it."""
        self.assertEqual(failed_task_owner_1128({"assignee": "frontend"}), "frontend")

    def test_the_string_None_is_not_an_agent_name(self):
        """These ledgers round-trip through JSON and stringification."""
        owner = failed_task_owner_1128(
            {"assignee": "backend", "claimed_by": "None", "created_by": "orchestrator"})
        self.assertEqual(owner, "orchestrator")


class TheAdviceIsNowActuallyExecutable(unittest.TestCase):
    """The payoff: route -> authorise -> clear the gate. All three, end to end."""

    def test_the_agent_we_route_to_can_carry_out_what_we_asked(self):
        hub = _hub()
        t = hub.create_task("P0 backend: fix custom_routes 500s",
                            agent="orchestrator", assignee="backend")
        hub.fail_task(t["id"], agent="orchestrator", reason="stale blocker")
        hubs = _Hubs(hub)

        rec = (unresolved_bug_tasks_743(hubs, None, set()) or {})["failed"][0]
        owner = failed_task_owner_1128(rec)

        # the agent the OLD code addressed is refused both escapes it was told to take
        self.assertIn("error", hub.complete_task(t["id"], "backend", result={}))
        self.assertIn("error", hub.cancel_task(t["id"], agent="backend", reason="cannot"))

        # the agent #1128 addresses can do it, and doing it clears the blocker (#1127)
        self.assertNotIn("error",
                         hub.cancel_task(t["id"], agent=owner, reason="no longer holds"))
        self.assertFalse((unresolved_bug_tasks_743(hubs, None, set()) or {}).get("failed_count"))


if __name__ == "__main__":
    unittest.main()
