"""Merge-gate defense: PR with non-substantive approve must not be merge-ready (Cutover 13)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_INLINE = [{"file": "backend/x.py", "line": 1, "body": "looked at it"}]
_ALT = ["considered an alt; not needed"]


class MergeSubstantiveGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="merge_subst_"))
        self.reg = HubRegistry(self.tmp)
        task = self.reg.workhub.create_task(
            title="t", assignee="backend", agent="orchestrator")
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend",
            target="main",
            reviewers=["reviewer2", "orchestrator"],
            linked_tasks=[task["id"]],
            title="t",
            author="backend",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inject_review_raw(self, reviewer, state, inline_comments=None, considered=None) -> str:
        """Bypass submit_review validation to inject a raw review row."""
        import time, uuid
        rid = f"review_{uuid.uuid4().hex[:10]}"
        review = {
            "id": rid, "pr_id": self.pr["id"], "reviewer": reviewer, "state": state,
            "comments": [], "inline_comments": inline_comments or [],
            "considered_alternatives": considered or [],
            "submitted_at": time.time(),
            "_updated_by": reviewer, "_updated_at": time.time(),
        }
        self.reg.codehub.stores.code_reviews.update(
            lambda m: m.set(rid, review, reviewer), change_info={"agent": reviewer})
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        pr.setdefault("reviews", []).append(rid)
        self.reg.codehub.stores.pull_requests.update(
            lambda m: m.set(self.pr["id"], pr, reviewer), change_info={"agent": reviewer})
        return rid

    def test_two_substantive_approvals_yield_pr_approved_true(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertTrue(self.reg.codehub._is_pr_approved(pr))

    def test_substantive_approve_plus_empty_approve_NOT_approved(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=[], considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))

    def test_substantive_approve_plus_inline_only_NOT_approved(self) -> None:
        # Has inline comments but missing considered_alternatives -> not substantive
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=_INLINE, considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))

    def test_two_empty_approvals_NOT_approved(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=[], considered=[])
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=[], considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))


if __name__ == "__main__":
    unittest.main()
