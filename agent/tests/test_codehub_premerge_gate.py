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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402

# Cutover 13: substantive approve requires inline_comments + considered_alternatives
_SUBST_INLINE = [{"file": "x.py", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


class PreMergeGateTests(unittest.TestCase):
    def _setup_pr(self, td, endpoint_test_status="passed"):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        hubs.registryhub.register_endpoint("GET", "/api/feed", schema={},
                                       provider="backend", agent="backend")
        if endpoint_test_status is not None:
            hubs.registryhub.record_api_test(
                "GET /api/feed",
                {"passed": endpoint_test_status == "passed"},
                evidence={"trace": "ok" if endpoint_test_status == "passed" else "fail"},
                agent="verifier",
            )
        task = hubs.workhub.create_task(title="x", assignee="backend",
                                        agent="orchestrator")
        # Complete the task so it satisfies premerge
        hubs.workhub.claim_task(task["id"], "backend")
        hubs.workhub.complete_task(task["id"], "backend", result={"ok": True})
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            linked_apis=["GET /api/feed"],
            title="x", author="backend",
        )
        # Approve so merge gate isn't blocked at reviewer stage
        ch.submit_review(pr["id"], "frontend", "approve",
                         inline_comments=_SUBST_INLINE,
                         considered_alternatives=_SUBST_ALTS)
        ch.submit_review(pr["id"], "orchestrator", "approve",
                         inline_comments=_SUBST_INLINE,
                         considered_alternatives=_SUBST_ALTS)
        return hubs, ch, pr

    def test_premerge_gate_passes_when_contract_test_passed_and_task_complete(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="passed")
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get(pr["id"]))
            self.assertTrue(result["passed"])
            self.assertEqual(result["failed_checks"], [])

    def test_premerge_gate_fails_on_failed_contract_test(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("contract_test_failed", kinds)

    def test_premerge_gate_fails_on_missing_contract_test(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status=None)
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("contract_test_missing", kinds)

    def test_premerge_gate_fails_on_incomplete_linked_task(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.register_agent_repo("backend", str(Path(td) / "backend"))
            ch.ensure_branch("backend", "agent/backend")
            hubs.registryhub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="backend")
            hubs.registryhub.record_api_test("GET /api/feed", {"passed": True},
                                        evidence={}, agent="verifier")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            # Task left in 'pending' — NOT completed
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_apis=["GET /api/feed"],
                title="x", author="backend",
            )
            ch.submit_review(pr["id"], "frontend", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            ch.submit_review(pr["id"], "orchestrator", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("linked_task_incomplete", kinds)

    def test_merge_pull_request_returns_error_when_premerge_gate_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            result = ch.merge_pull_request(pr["id"], agent="orchestrator")
            self.assertEqual(result.get("error"), "premerge_gate_failed")

    def test_merge_pull_request_creates_workhub_fix_task_on_gate_failure(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            ch.merge_pull_request(pr["id"], agent="orchestrator")
            # A new WorkHub task should be assigned to the PR author
            tasks = list(hubs.workhub.snapshot()["tasks"].values())
            fix_tasks = [
                t for t in tasks
                if t.get("metadata", {}).get("source") == "codehub_premerge_gate"
                and t.get("assignee") == "backend"
            ]
            self.assertGreaterEqual(len(fix_tasks), 1)


if __name__ == "__main__":
    unittest.main()
