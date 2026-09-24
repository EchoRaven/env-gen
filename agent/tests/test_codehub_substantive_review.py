"""Tests for substantive-review validation on CodeHub.submit_review (Cutover 13)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _make_pr(reg, branch="agent/backend", agent="backend"):
    task = reg.workhub.create_task(title="t", assignee=agent, agent="orchestrator")
    pr = reg.codehub.open_pull_request(
        branch=branch,
        target="main",
        # Phase 4.6 gate: 'r1' added so test fixture passes
        # data-driven allowed_set = pr.reviewers ∪ {orchestrator}.
        reviewers=["frontend", "orchestrator", "r1"],
        linked_tasks=[task["id"]],
        title="t",
        author=agent,
    )
    return pr


_INLINE_OK = [{"file": "backend/x.py", "line": 10, "body": "consider extracting"}]
_ALT_OK = ["considered separate validator module; rejected because too small to extract"]


class SubmitReviewSubstantiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="subst_rev_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = _make_pr(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_approve_with_inline_and_alternatives_is_accepted(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=_ALT_OK)
        self.assertNotIn("error", result)
        self.assertEqual(result["state"], "approve")
        self.assertEqual(result["considered_alternatives"], _ALT_OK)

    def test_approve_without_inline_comments_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=[],
            considered_alternatives=_ALT_OK)
        self.assertIn("error", result)
        self.assertIn("inline_comments", result["error"].lower())

    def test_approve_without_considered_alternatives_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=[])
        self.assertIn("error", result)
        self.assertIn("alternative", result["error"].lower())

    def test_approve_with_missing_considered_alternatives_kwarg_is_rejected(self) -> None:
        # Backwards-compat: existing callers that don't pass considered_alternatives at all
        # must also be rejected when state=="approve".
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK)
        self.assertIn("error", result)
        self.assertIn("alternative", result["error"].lower())

    def test_approve_with_whitespace_only_alternative_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=["", "   "])
        self.assertIn("error", result)

    def test_request_changes_with_no_inline_no_alternatives_is_accepted(self) -> None:
        # Blocking a PR doesn't need substantive structure - that's a separate signal
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="request_changes",
            inline_comments=[],
            considered_alternatives=[])
        self.assertNotIn("error", result)
        self.assertEqual(result["state"], "request_changes")

    def test_comment_state_does_not_require_substantive_fields(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="comment",
            inline_comments=[],
            considered_alternatives=[])
        self.assertNotIn("error", result)

    def test_failed_validation_does_not_mutate_pr_reviews_array(self) -> None:
        pr_before = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        reviews_before = list(pr_before.get("reviews", []))
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=[], considered_alternatives=[])
        pr_after = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertEqual(pr_after.get("reviews", []), reviews_before)


if __name__ == "__main__":
    unittest.main()
