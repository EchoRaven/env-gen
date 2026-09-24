"""Guard: FIX #210 — codehub.commit must stage the lane's REAL changes even when
the porcelain-enumerated candidate list contains a stale/nonexistent pathspec.

r14 live: 58/88 frontend `codehub_commit` calls FAILED with
`git add -A -- <real-file> design/ docs/ logs/ ... : fatal: pathspec 'design/'
did not match any files` (exit 128). `git add` aborts the WHOLE batch atomically
on the first non-matching pathspec, so the agent's real edit (custom_routes.py /
SidebarNavigation.jsx) never stages → the commit fails → the fix is lost → the
lane re-does it → 66% commit-failure churn that burns the delivery milestone
budget. The staging must tolerate a bad pathspec and still commit the rest.
Env-agnostic: every run's delivery convergence depends on lane commits landing.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.codehub.git_ops import GitOps  # noqa: E402
from multi_agent.runtime.hubs.codehub.service import _stage_paths_robust  # noqa: E402


class RobustStageTests(unittest.TestCase):
    def _repo(self, tmp):
        g = GitOps(Path(tmp))
        g.init()
        return g

    def _staged(self, g):
        r = g._run("diff", "--cached", "--name-only", check=False)
        return set((r.stdout or "").split())

    def test_bad_pathspec_does_not_drop_real_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._repo(tmp)
            (Path(tmp) / "foo.py").write_text("print('x')\n", encoding="utf-8")
            # 'ghost/' is a stale porcelain-style entry that isn't on disk.
            staged = _stage_paths_robust(g, ["foo.py", "ghost/"])
            self.assertIn("foo.py", self._staged(g))   # the REAL change landed
            self.assertIn("foo.py", staged)
            self.assertNotIn("ghost/", staged)

    def test_all_valid_batch_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._repo(tmp)
            (Path(tmp) / "a.py").write_text("a\n", encoding="utf-8")
            (Path(tmp) / "b.py").write_text("b\n", encoding="utf-8")
            staged = _stage_paths_robust(g, ["a.py", "b.py"])
            self.assertEqual(self._staged(g), {"a.py", "b.py"})
            self.assertEqual(set(staged), {"a.py", "b.py"})

    def test_empty_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._repo(tmp)
            self.assertEqual(_stage_paths_robust(g, []), [])

    def test_staged_deletion_survives_bad_pathspec(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._repo(tmp)
            f = Path(tmp) / "keep.py"
            f.write_text("v1\n", encoding="utf-8")
            g._run("add", "-A", "--", "keep.py")
            g.commit("seed")
            f.unlink()  # a DELETION must still stage (-A), despite a bad sibling
            staged = _stage_paths_robust(g, ["keep.py", "ghost/"])
            # keep.py deletion is staged
            r = g._run("diff", "--cached", "--name-only", "--diff-filter=D", check=False)
            self.assertIn("keep.py", (r.stdout or "").split())
            self.assertIn("keep.py", staged)


if __name__ == "__main__":
    unittest.main()
