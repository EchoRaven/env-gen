"""Inline-comment-at-file:line tests for CodeHub.submit_review."""
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


class CodeHubInlineCommentsTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        # Create a WorkHub task so the linked_tasks gate passes
        task = hubs.workhub.create_task(title="Feed API task", assignee="backend",
                                        agent="orchestrator")
        # Open a minimal PR (metadata-only is fine — we don't need real git for review tests)
        pr = ch.open_pull_request(
            branch="agent/backend",
            target="main",
            reviewers=["frontend"],
            linked_tasks=[task["id"]],
            title="Implement feed API",
            author="backend",
        )
        return hubs, ch, pr

    def test_submit_review_with_inline_comments_persists_them(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            review = ch.submit_review(
                pr_id=pr["id"],
                reviewer="frontend",
                state="comment",
                comments=["Overall LGTM, two nits below."],
                inline_comments=[
                    {"file": "app/backend/feed.py", "line": 42, "body": "Use async here"},
                    {"file": "app/backend/feed.py", "line": 67, "body": "Missing error handling"},
                ],
            )
            self.assertIn("error", review) is False if "error" in review else None  # no error
            self.assertNotIn("error", review)
            self.assertEqual(len(review["inline_comments"]), 2)
            self.assertEqual(review["inline_comments"][0]["file"], "app/backend/feed.py")
            self.assertEqual(review["inline_comments"][0]["line"], 42)
            self.assertEqual(review["inline_comments"][0]["agent"], "frontend")
            self.assertTrue(review["inline_comments"][0]["id"].startswith("ic_"))

    def test_submit_review_rejects_malformed_inline_comment(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            # Missing line
            r1 = ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                inline_comments=[{"file": "x.py", "body": "no line"}],
            )
            self.assertIn("error", r1)
            # Non-int line
            r2 = ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                inline_comments=[{"file": "x.py", "line": "1", "body": "str line"}],
            )
            self.assertIn("error", r2)
            # Zero/negative line
            r3 = ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                inline_comments=[{"file": "x.py", "line": 0, "body": "zero"}],
            )
            self.assertIn("error", r3)
            # Empty body
            r4 = ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                inline_comments=[{"file": "x.py", "line": 5, "body": ""}],
            )
            self.assertIn("error", r4)

    def test_submit_review_without_inline_comments_still_works(self):
        # Cutover 13: approve now requires inline_comments + considered_alternatives.
        # Non-approve states (comment, request_changes) still accept reviews
        # without inline comments — they're independent signals.
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            review = ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                comments=["Looks good"],
            )
            self.assertNotIn("error", review)
            self.assertEqual(review["inline_comments"], [])
            self.assertEqual(review["state"], "comment")

    def test_list_inline_comments_filters_by_file(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            ch.submit_review(
                pr_id=pr["id"], reviewer="frontend", state="comment",
                inline_comments=[
                    {"file": "feed.py", "line": 10, "body": "x"},
                    {"file": "feed.py", "line": 25, "body": "y"},
                    {"file": "auth.py", "line": 5, "body": "z"},
                ],
            )
            feed_only = ch.list_inline_comments(pr["id"], file="feed.py")
            self.assertEqual(len(feed_only), 2)
            self.assertEqual([c["line"] for c in feed_only], [10, 25])  # sorted by line

            all_comments = ch.list_inline_comments(pr["id"])
            self.assertEqual(len(all_comments), 3)

    def test_list_inline_comments_unknown_pr_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, _ = self._setup(td)
            self.assertEqual(ch.list_inline_comments("pr_bogus"), [])


if __name__ == "__main__":
    unittest.main()
