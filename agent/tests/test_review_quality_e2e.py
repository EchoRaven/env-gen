"""End-to-end test: enforces the Cutover-13 review-quality gate at the merge surface.

Proves:
- Two rubber-stamp approves cannot pass `_is_pr_approved` (and merge is blocked)
- Two substantive approves CAN pass, and merge succeeds.
"""

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
_ALT = ["considered alt approach; rejected because A"]


def _make_pr(reg, branch="agent/backend", agent="backend"):
    task = reg.workhub.create_task(title="t", assignee=agent, agent="orchestrator")
    pr = reg.codehub.open_pull_request(
        branch=branch,
        target="main",
        # Reviewers list kept tight — _is_pr_approved requires ALL
        # listed reviewers to approve, so widening would break the
        # "two substantive approves merge_ready" assertion. The
        # rubber-stamp test below uses reviewers already on this list.
        reviewers=["frontend", "orchestrator"],
        linked_tasks=[task["id"]],
        title="t",
        author=agent,
    )
    return pr


class ReviewQualityE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rq_e2e_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = _make_pr(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_rubber_stamp_approves_are_rejected_at_submit(self) -> None:
        r1 = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=[], considered_alternatives=[])
        # 'frontend' is already a listed reviewer — using it for the
        # second rubber-stamp keeps the test focused on the substantive
        # gate (the prior "reviewer2" caused a Phase 4.6 role-gate
        # rejection before the substantive check could fire).
        r2 = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="frontend", state="approve",
            inline_comments=[], considered_alternatives=[])
        self.assertIn("error", r1)
        self.assertIn("error", r2)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertEqual(pr.get("reviews", []), [],
                         "rejected submissions must not be stored on the PR")

    def test_two_substantive_approves_allow_merge_ready(self) -> None:
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="frontend", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertTrue(self.reg.codehub._is_pr_approved(pr))

    def test_substantive_plus_rubber_stamp_NOT_approved(self) -> None:
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        # second reviewer tries to rubber-stamp via the tool -> rejected at submit
        bad = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="frontend", state="approve",
            inline_comments=[], considered_alternatives=[])
        self.assertIn("error", bad)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        # Only one approve stored; 2-reviewer rule still requires both, so not approved
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))


if __name__ == "__main__":
    unittest.main()
