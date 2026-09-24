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


class StrictApprovalTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            title="x", author="backend",
        )
        return hubs, ch, pr

    def test_pr_not_approved_until_all_reviewers_approve(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            # One of two reviewers approves — still not ready
            ch.submit_review(pr["id"], "frontend", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            after = ch.stores.pull_requests.get(pr["id"])
            self.assertEqual(after.get("merge_state"), "blocked")

    def test_pr_ready_only_after_all_approve(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            ch.submit_review(pr["id"], "frontend", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            ch.submit_review(pr["id"], "orchestrator", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            after = ch.stores.pull_requests.get(pr["id"])
            self.assertEqual(after.get("merge_state"), "ready")

    def test_request_changes_overrides_other_approvals(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            ch.submit_review(pr["id"], "frontend", "approve",
                             inline_comments=_SUBST_INLINE,
                             considered_alternatives=_SUBST_ALTS)
            ch.submit_review(pr["id"], "orchestrator", "request_changes")
            after = ch.stores.pull_requests.get(pr["id"])
            self.assertEqual(after.get("merge_state"), "changes_requested")


if __name__ == "__main__":
    unittest.main()
