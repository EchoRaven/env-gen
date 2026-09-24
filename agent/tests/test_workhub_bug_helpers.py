"""Tests for WorkHub bug helpers (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class WorkHubBugListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_bug_"))
        self.reg = HubRegistry(self.tmp)
        self.wh = self.reg.workhub

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_open_bugs_empty_when_no_tasks(self) -> None:
        self.assertEqual(self.wh.list_open_bugs(), [])

    def test_list_open_bugs_excludes_non_bug_tasks(self) -> None:
        self.wh.create_task(title="Feature work", agent="orch", kind="feature")
        self.assertEqual(self.wh.list_open_bugs(), [])

    def test_list_open_bugs_includes_open_and_triaged_and_in_progress(self) -> None:
        a = self.wh.create_task(title="BUG a", agent="orch", kind="bug",
                                bug_state="open", severity="P1")
        b = self.wh.create_task(title="BUG b", agent="orch", kind="bug",
                                bug_state="triaged", severity="P2")
        c = self.wh.create_task(title="BUG c", agent="orch", kind="bug",
                                bug_state="in_progress", severity="P0")
        self.wh.create_task(title="BUG d closed", agent="orch", kind="bug",
                            bug_state="closed", severity="P3")
        open_ids = {t["id"] for t in self.wh.list_open_bugs()}
        self.assertEqual(open_ids, {a["id"], b["id"], c["id"]})

    def test_list_open_bugs_sorted_by_severity_then_created_at(self) -> None:
        # Create in mixed order; expect P0 first, then P1, then P2.
        p2 = self.wh.create_task(title="BUG P2", agent="orch", kind="bug",
                                 bug_state="open", severity="P2")
        p0 = self.wh.create_task(title="BUG P0", agent="orch", kind="bug",
                                 bug_state="open", severity="P0")
        p1 = self.wh.create_task(title="BUG P1", agent="orch", kind="bug",
                                 bug_state="open", severity="P1")
        ids = [t["id"] for t in self.wh.list_open_bugs()]
        self.assertEqual(ids, [p0["id"], p1["id"], p2["id"]])

    def test_list_bugs_assigned_to_filters_by_assignee_and_open_states(self) -> None:
        self.wh.create_task(title="BUG x", assignee="backend", agent="orch",
                            kind="bug", bug_state="assigned", severity="P1")
        self.wh.create_task(title="BUG y", assignee="frontend", agent="orch",
                            kind="bug", bug_state="assigned", severity="P1")
        self.wh.create_task(title="BUG z closed", assignee="backend", agent="orch",
                            kind="bug", bug_state="closed", severity="P3")
        backend_bugs = self.wh.list_bugs_assigned_to("backend")
        backend_ids = {t["id"] for t in backend_bugs}
        self.assertEqual(len(backend_ids), 1)


class WorkHubBugLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_buglife_"))
        self.reg = HubRegistry(self.tmp)
        self.wh = self.reg.workhub
        self.bug = self.wh.create_task(
            title="BUG: feed 500", agent="verifier",
            kind="bug", bug_state="open", severity="P1",
            source="verifier",
            bug_artifacts={"failing_test": "test_x", "affected_endpoint": "POST /api/feed"},
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_bug_state_transitions_state(self) -> None:
        updated = self.wh.update_bug_state(self.bug["id"], "triaged",
                                           agent="bug_triage_orchestrator",
                                           note="owner=backend")
        self.assertEqual(updated["metadata"]["bug_state"], "triaged")

    def test_update_bug_state_appends_triage_history(self) -> None:
        self.wh.update_bug_state(self.bug["id"], "triaged",
                                 agent="bug_triage_orchestrator", note="step1")
        self.wh.update_bug_state(self.bug["id"], "assigned",
                                 agent="bug_triage_orchestrator", note="step2",
                                 assignee="backend")
        final = self.wh.stores.tasks.get(self.bug["id"])
        history = final["metadata"]["triage_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["action"], "triaged")
        self.assertEqual(history[1]["action"], "assigned")
        self.assertEqual(history[1]["by"], "bug_triage_orchestrator")
        self.assertEqual(final["assignee"], "backend")

    def test_close_bug_sets_state_and_fix_evidence(self) -> None:
        evidence = {"fix_pr": "PR-42", "verified_by_test": "test_x"}
        closed = self.wh.close_bug(self.bug["id"], agent="backend",
                                    fix_evidence=evidence)
        self.assertEqual(closed["metadata"]["bug_state"], "closed")
        self.assertEqual(closed["metadata"]["fix_evidence"], evidence)
        self.assertEqual(closed["status"], "completed")

    def test_escalate_bug_sets_state_and_records_reason(self) -> None:
        esc = self.wh.escalate_bug(self.bug["id"], agent="bug_triage_orchestrator",
                                    reason="3 failed fix attempts")
        self.assertEqual(esc["metadata"]["bug_state"], "escalated")
        self.assertEqual(esc["metadata"]["escalation_reason"], "3 failed fix attempts")

    def test_update_bug_state_rejects_unknown_state(self) -> None:
        with self.assertRaises(ValueError):
            self.wh.update_bug_state(self.bug["id"], "magic", agent="x")

    def test_update_bug_state_rejects_non_bug_task(self) -> None:
        feat = self.wh.create_task(title="feat", agent="orch", kind="feature")
        with self.assertRaises(ValueError):
            self.wh.update_bug_state(feat["id"], "triaged", agent="x")


if __name__ == "__main__":
    unittest.main()
