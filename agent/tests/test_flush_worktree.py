"""Guard: flush_worktree commits uncommitted/untracked APP work to the branch.

Root fix for the recurring stall: the frontend authored pages but never
finish-committed them, so the pre-validation squash merge saw 'nothing to merge'
and integration shipped a blank shell (frontend_navigable: 0). flush_worktree
captures that work before the merge. Excludes build junk (node_modules/dist).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.auto_commit import flush_worktree  # noqa: E402


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


class FlushWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp(prefix="flush_"))
        _git(["init", "-q"], self.wt)  # default branch name (version-robust)
        _git(["config", "user.email", "t@t"], self.wt)
        _git(["config", "user.name", "t"], self.wt)
        # an initial commit, then name the branch agent/frontend
        (self.wt / "README").write_text("x")
        _git(["add", "-A"], self.wt); _git(["commit", "-qm", "init"], self.wt)
        _git(["branch", "-M", "agent/frontend"], self.wt)

    def _tracked(self, rel):
        out = _git(["ls-files", rel], self.wt).stdout
        return bool(out.strip())

    def test_commits_untracked_pages(self):
        pages = self.wt / "app" / "frontend" / "src" / "pages"
        pages.mkdir(parents=True)
        (pages / "Home.jsx").write_text("export default function Home(){return null}")
        (pages / "Watch.jsx").write_text("export default function Watch(){return null}")
        self.assertFalse(self._tracked("app/frontend/src/pages/Home.jsx"))  # untracked before
        ok, info = flush_worktree(worktree_dir=self.wt, branch="agent/frontend", author="frontend")
        self.assertTrue(ok, info)
        self.assertTrue(self._tracked("app/frontend/src/pages/Home.jsx"))  # committed after
        self.assertTrue(self._tracked("app/frontend/src/pages/Watch.jsx"))

    def test_excludes_build_junk(self):
        nm = self.wt / "app" / "frontend" / "node_modules" / "react"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("// huge dep")
        (self.wt / "app" / "frontend" / "src").mkdir(parents=True)
        (self.wt / "app" / "frontend" / "src" / "main.jsx").write_text("x")
        ok, _ = flush_worktree(worktree_dir=self.wt, branch="agent/frontend", author="frontend")
        self.assertTrue(ok)
        self.assertTrue(self._tracked("app/frontend/src/main.jsx"))
        self.assertFalse(self._tracked("app/frontend/node_modules/react/index.js"))  # junk excluded

    def test_nothing_to_commit_is_ok(self):
        ok, info = flush_worktree(worktree_dir=self.wt, branch="agent/frontend", author="frontend")
        self.assertTrue(ok)  # no app dir → clean no-op
        self.assertIn("no deliverable", info)

    def test_non_git_dir_is_noop(self):
        d = Path(tempfile.mkdtemp(prefix="nogit_"))
        ok, info = flush_worktree(worktree_dir=d, branch="x", author="y")
        self.assertTrue(ok)
        self.assertIn("not a git", info)


if __name__ == "__main__":
    unittest.main()
