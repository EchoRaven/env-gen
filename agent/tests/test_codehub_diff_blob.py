"""
Tests for CodeHub.get_diff (Task 8), get_blob / get_file_content (Task 9),
and list_prs (Task 10).
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


def _make_hub(td: str) -> CodeHub:
    base = Path(td)
    crdt_dir = base / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    hub = CodeHub(base, crdt_dir)
    hub.ensure_repo()
    return hub


def _setup_agent_with_commit(hub: CodeHub, agent_id: str, filename: str, content: str) -> str:
    """Create worktree, write file, commit; return commit SHA."""
    wt_path = hub.register_agent_worktree(agent_id)
    (wt_path / filename).write_text(content)
    result = hub.commit(agent_id, f"Add {filename}", files=[filename])
    return result["sha"]


# ---------------------------------------------------------------------------
# Task 8 — get_diff
# ---------------------------------------------------------------------------

class TestCodeHubGetDiff(unittest.TestCase):
    def test_diff_returns_expected_content(self):
        """get_diff returns a diff string containing the added lines."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            sha = _setup_agent_with_commit(hub, "agent-diff", "api.py", "def hello(): pass\n")
            # Open a PR for this branch (no workhub -> task existence gate skipped)
            pr = hub.open_pull_request(
                branch="agent/agent-diff",
                target="master",
                author="agent-diff",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertNotIn("error", pr)

            result = hub.get_diff(pr["id"])
            self.assertNotIn("error", result)
            self.assertIn("diff", result)
            self.assertIn("hello", result["diff"])

    def test_diff_truncation_triggers_when_over_max(self):
        """get_diff truncates and sets truncated=True when diff exceeds max_lines."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            # Generate a large file to produce a big diff
            large_content = "\n".join(f"line_{i} = {i}" for i in range(500)) + "\n"
            sha = _setup_agent_with_commit(hub, "agent-trunc", "big.py", large_content)
            pr = hub.open_pull_request(
                branch="agent/agent-trunc",
                target="master",
                author="agent-trunc",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertNotIn("error", pr)

            result = hub.get_diff(pr["id"], max_lines=10)
            self.assertTrue(result.get("truncated"), "Expected truncated=True")
            self.assertIn("truncation_marker", result)
            lines = result["diff"].splitlines()
            self.assertLessEqual(len(lines), 10)

    def test_diff_for_missing_pr_returns_error(self):
        """get_diff returns an error dict for an unknown PR id."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            result = hub.get_diff("pr_nonexistent")
            self.assertIn("error", result)


# ---------------------------------------------------------------------------
# Task 9 — get_blob / get_file_content
# ---------------------------------------------------------------------------

class TestCodeHubGetBlob(unittest.TestCase):
    def test_get_blob_returns_file_content_at_commit(self):
        """get_blob returns the file content at a specific commit hash."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            sha = _setup_agent_with_commit(hub, "agent-blob", "blob.txt", "hello blob\n")
            content = hub.get_blob(sha, "blob.txt")
            self.assertIn("hello blob", content)

    def test_get_file_content_via_pr(self):
        """get_file_content returns content from the PR head commit."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            sha = _setup_agent_with_commit(hub, "agent-fc", "fc.py", "x = 99\n")
            pr = hub.open_pull_request(
                branch="agent/agent-fc",
                target="master",
                author="agent-fc",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertNotIn("error", pr)
            result = hub.get_file_content(pr["id"], "fc.py")
            self.assertNotIn("error", result)
            self.assertIn("x = 99", result["content"])
            self.assertEqual(result["commit"], sha)

    def test_get_file_content_for_missing_pr_returns_error(self):
        """get_file_content returns an error dict for an unknown PR."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            result = hub.get_file_content("pr_ghost", "any.py")
            self.assertIn("error", result)

    def test_get_blob_for_unknown_ref_raises(self):
        """get_blob raises GitOpsError for a nonexistent ref."""
        from multi_agent.runtime.hubs.codehub.git_ops import GitOpsError
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            hub.git.init()  # ensure repo exists
            with self.assertRaises(GitOpsError):
                hub.get_blob("deadbeef" * 5, "nope.txt")


# ---------------------------------------------------------------------------
# Task 10 — list_prs
# ---------------------------------------------------------------------------

class TestCodeHubListPRs(unittest.TestCase):
    def _make_hub_with_prs(self, td: str):
        hub = _make_hub(td)
        _setup_agent_with_commit(hub, "agent-alice", "alice.py", "# alice\n")
        _setup_agent_with_commit(hub, "agent-bob", "bob.py", "# bob\n")
        # No workhub attached -> task existence gate skipped; provide synthetic linked_tasks
        pr_alice = hub.open_pull_request(
            branch="agent/agent-alice",
            target="master",
            author="alice",
            reviewers=["reviewer1"],
            linked_tasks=["synthetic_task_1"],
        )
        pr_bob = hub.open_pull_request(
            branch="agent/agent-bob",
            target="master",
            author="bob",
            reviewers=["alice"],
            linked_tasks=["synthetic_task_2"],
        )
        return hub, pr_alice, pr_bob

    def test_list_prs_filter_by_status(self):
        """list_prs(status='open') returns only open PRs."""
        with tempfile.TemporaryDirectory() as td:
            hub, pr_alice, pr_bob = self._make_hub_with_prs(td)
            open_prs = hub.list_prs(status="open")
            self.assertEqual(len(open_prs), 2)
            merged_prs = hub.list_prs(status="merged")
            self.assertEqual(len(merged_prs), 0)

    def test_list_prs_filter_by_author(self):
        """list_prs(author='alice') returns only PRs authored by alice."""
        with tempfile.TemporaryDirectory() as td:
            hub, pr_alice, pr_bob = self._make_hub_with_prs(td)
            alice_prs = hub.list_prs(author="alice")
            self.assertEqual(len(alice_prs), 1)
            self.assertEqual(alice_prs[0]["author"], "alice")

            bob_prs = hub.list_prs(author="bob")
            self.assertEqual(len(bob_prs), 1)
            self.assertEqual(bob_prs[0]["author"], "bob")

    def test_list_prs_filter_by_reviewer(self):
        """list_prs(reviewer='alice') returns only PRs where alice is a reviewer."""
        with tempfile.TemporaryDirectory() as td:
            hub, pr_alice, pr_bob = self._make_hub_with_prs(td)
            # pr_bob has alice as reviewer; pr_alice has no reviewers
            alice_reviewed = hub.list_prs(reviewer="alice")
            self.assertEqual(len(alice_reviewed), 1)
            self.assertIn("alice", alice_reviewed[0]["reviewers"])


if __name__ == "__main__":
    unittest.main()
