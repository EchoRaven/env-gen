"""
Tests for CodeHub.open_pull_request branch validation (Task 6).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hubs.codehub.service import CodeHub  # noqa: E402


class TestOpenPRBranchSanity(unittest.TestCase):
    def _make_hub(self, td: str) -> CodeHub:
        base = Path(td)
        crdt_dir = base / "shared" / "crdt"
        crdt_dir.mkdir(parents=True, exist_ok=True)
        hub = CodeHub(base, crdt_dir)
        hub.ensure_repo()
        return hub

    def test_open_pr_for_nonexistent_branch_returns_error(self):
        """open_pull_request returns an error dict when the branch does not exist in git."""
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_hub(td)
            # No branches created yet — "ghost-branch" definitely does not exist
            # Provide linked_tasks and reviewers so gates 1-3 pass (no workhub -> gate 5 skipped)
            result = hub.open_pull_request(
                branch="ghost-branch",
                target="master",
                author="test-agent",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertIn("error", result)
            self.assertIn("ghost-branch", result["error"])

    def test_open_pr_sets_real_head_sha(self):
        """open_pull_request sets pr['head'] to the real git SHA of the branch."""
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_hub(td)
            wt_path = hub.register_agent_worktree("agent-pr-test")
            # Write and commit a file in the worktree
            (wt_path / "work.py").write_text("# work\n")
            result = hub.commit("agent-pr-test", "PR work", files=["work.py"])
            sha = result["sha"]

            # Provide linked_tasks and reviewers so gates pass (no workhub -> task existence skipped)
            pr = hub.open_pull_request(
                branch="agent/agent-pr-test",
                target="master",
                author="agent-pr-test",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertNotIn("error", pr)
            self.assertEqual(pr["head"], sha)


if __name__ == "__main__":
    unittest.main()
