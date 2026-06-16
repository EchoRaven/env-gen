"""Tests for WorkHub dependency enforcement at claim time (Cutover 23)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class ClaimTaskDepsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_deps_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claim_succeeds_when_no_deps(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", assignee="backend")
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertEqual(result.get("status"), "in_progress")

    def test_claim_blocked_when_dep_pending(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)
        self.assertIn("blocked", result["error"].lower())

    def test_claim_succeeds_after_dep_completed(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        self.reg.workhub.claim_task(dep["id"], agent="backend")
        self.reg.workhub.complete_task(dep["id"], agent="backend", result={"ok": True})
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertEqual(result.get("status"), "in_progress")

    def test_claim_blocked_when_any_dep_pending(self) -> None:
        a = self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        b = self.reg.workhub.create_task(title="b", agent="orch", assignee="backend")
        self.reg.workhub.claim_task(a["id"], agent="backend")
        self.reg.workhub.complete_task(a["id"], agent="backend", result={"ok": True})
        # b is still pending; task with deps [a, b] should be blocked
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend",
            depends_on=[a["id"], b["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)

    def test_claim_error_message_names_blocker(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn(dep["id"], result["error"])

    def test_claim_missing_dep_id_rejected(self) -> None:
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend",
            depends_on=["task_nonexistent"])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)
        self.assertIn("nonexistent", result["error"])


class ReadyBlockedHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_ready_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_ready_empty_when_nothing_pending(self) -> None:
        self.assertEqual(self.reg.workhub.list_ready_tasks(), [])

    def test_ready_includes_pending_with_no_deps(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", assignee="backend")
        ready = self.reg.workhub.list_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["id"], t["id"])

    def test_blocked_separates_from_ready(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        blocked = self.reg.workhub.create_task(
            title="b", agent="orch", assignee="backend", depends_on=[dep["id"]])
        ready = self.reg.workhub.list_ready_tasks()
        blocked_list = self.reg.workhub.list_blocked_tasks()
        ready_ids = {t["id"] for t in ready}
        blocked_ids = {t["id"] for t in blocked_list}
        self.assertIn(dep["id"], ready_ids)
        self.assertIn(blocked["id"], blocked_ids)
        self.assertNotIn(dep["id"], blocked_ids)
        self.assertNotIn(blocked["id"], ready_ids)

    def test_list_ready_filters_by_assignee(self) -> None:
        self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        self.reg.workhub.create_task(title="b", agent="orch", assignee="frontend")
        backend_ready = self.reg.workhub.list_ready_tasks(assignee="backend")
        self.assertEqual(len(backend_ready), 1)
        self.assertEqual(backend_ready[0]["title"], "a")

    def test_get_blockers_returns_incomplete_deps(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        blockers = self.reg.workhub.get_blockers_for(t["id"])
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["id"], dep["id"])

    def test_get_blocked_by_returns_dependents(self) -> None:
        a = self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        b = self.reg.workhub.create_task(
            title="b", agent="orch", assignee="backend", depends_on=[a["id"]])
        c = self.reg.workhub.create_task(
            title="c", agent="orch", assignee="backend", depends_on=[a["id"]])
        dependents = self.reg.workhub.get_blocked_by(a["id"])
        dep_ids = {t["id"] for t in dependents}
        self.assertEqual(dep_ids, {b["id"], c["id"]})


if __name__ == "__main__":
    unittest.main()
