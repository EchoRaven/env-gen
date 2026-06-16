"""
Tests for GitOps subprocess wrapper (Task 2).

Uses real git (git 2.25.1 on Linux). Default branch is 'master'.
All tests operate in isolated temporary directories.
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

from multi_agent.runtime.hubs.codehub.git_ops import GitOps, GitOpsError  # noqa: E402


class TestGitOpsInit(unittest.TestCase):
    def test_init_creates_dot_git(self):
        with tempfile.TemporaryDirectory() as td:
            ops = GitOps(Path(td))
            ops.init()
            self.assertTrue((Path(td) / ".git").is_dir())


class TestGitOpsCommit(unittest.TestCase):
    def _make_repo(self, td: str) -> GitOps:
        ops = GitOps(Path(td))
        ops.init()
        (Path(td) / "hello.txt").write_text("hello\n")
        ops.add("hello.txt")
        return ops

    def test_commit_returns_full_sha(self):
        with tempfile.TemporaryDirectory() as td:
            ops = self._make_repo(td)
            sha = ops.commit("initial commit")
            self.assertEqual(len(sha), 40)
            self.assertTrue(all(c in "0123456789abcdef" for c in sha))


class TestGitOpsWorktree(unittest.TestCase):
    def test_add_worktree_creates_isolated_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "repo"
            wt_path = Path(td) / "worktree"
            ops = GitOps(base)
            ops.init()
            (base / "file.txt").write_text("base content\n")
            ops.add("file.txt")
            ops.commit("base commit")

            ops.add_worktree(wt_path, "agent/test-agent")

            # Worktree directory exists and is independent
            self.assertTrue(wt_path.is_dir())
            self.assertTrue((wt_path / "file.txt").exists())

            # Branch is correctly recorded
            wt_ops = GitOps(wt_path)
            self.assertEqual(wt_ops.current_branch(), "agent/test-agent")

            # Cleanup
            ops.remove_worktree(wt_path, force=True)


class TestGitOpsDiff(unittest.TestCase):
    def test_diff_between_commits_shows_changes(self):
        with tempfile.TemporaryDirectory() as td:
            ops = GitOps(Path(td))
            ops.init()
            f = Path(td) / "code.py"
            f.write_text("x = 1\n")
            ops.add("code.py")
            sha1 = ops.commit("first")

            f.write_text("x = 1\ny = 2\n")
            ops.add("code.py")
            sha2 = ops.commit("second")

            diff = ops.diff(sha1, sha2)
            self.assertIn("+y = 2", diff)


class TestGitOpsShow(unittest.TestCase):
    def test_show_returns_file_content_at_commit(self):
        with tempfile.TemporaryDirectory() as td:
            ops = GitOps(Path(td))
            ops.init()
            f = Path(td) / "readme.txt"
            f.write_text("version one\n")
            ops.add("readme.txt")
            sha1 = ops.commit("v1")

            f.write_text("version two\n")
            ops.add("readme.txt")
            ops.commit("v2")

            content = ops.show(sha1, "readme.txt")
            self.assertIn("version one", content)
            self.assertNotIn("version two", content)


if __name__ == "__main__":
    unittest.main()
