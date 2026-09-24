"""#1202as: end-of-run worktree reclamation must free space without losing work."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.worktree_reclaim import reclaim_run_worktrees_1202as  # noqa: E402


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True)


class WorktreeReclaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="wt_1202as_"))
        _git("init", "-q", cwd=self.root)
        _git("config", "user.email", "t@t", cwd=self.root)
        _git("config", "user.name", "t", cwd=self.root)
        (self.root / "app").mkdir()
        (self.root / "app" / "seed.bin").write_bytes(b"x" * 50000)
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", "base", cwd=self.root)
        self.wt = self.root / "worktrees"
        self.wt.mkdir()

    def tearDown(self) -> None:
        os.environ.pop("ENVGEN_KEEP_WORKTREES", None)
        shutil.rmtree(self.root, ignore_errors=True)

    def _add_lane(self, name):
        path = self.wt / name
        _git("worktree", "add", "-b", f"agent/{name}", str(path), cwd=self.root)
        return path

    def test_clean_worktree_is_reclaimed_and_its_commits_survive(self):
        lane = self._add_lane("backend")
        (lane / "app" / "new.py").write_text("print('lane work')\n")
        _git("add", "-A", cwd=lane)
        _git("commit", "-qm", "lane work", cwd=lane)

        out = reclaim_run_worktrees_1202as(self.root)

        self.assertEqual(out["removed"], ["backend"])
        self.assertFalse(lane.exists())
        self.assertGreater(out["bytes_reclaimed"], 40000)
        # The branch — and therefore the lane's commits — must still be there.
        log = _git("log", "--oneline", "agent/backend", cwd=self.root).stdout
        self.assertIn("lane work", log)

    def test_a_worktree_with_uncommitted_work_is_kept(self):
        """The property that makes this safe: git refuses, and we accept the refusal."""
        lane = self._add_lane("frontend")
        (lane / "app" / "unsaved.py").write_text("work nobody committed\n")
        _git("add", "-A", cwd=lane)  # staged, uncommitted

        out = reclaim_run_worktrees_1202as(self.root)

        self.assertEqual(out["kept"], ["frontend"])
        self.assertEqual(out["removed"], [])
        self.assertTrue((lane / "app" / "unsaved.py").exists())

    def test_opt_out_keeps_everything(self):
        lane = self._add_lane("verifier")
        os.environ["ENVGEN_KEEP_WORKTREES"] = "1"

        out = reclaim_run_worktrees_1202as(self.root)

        self.assertEqual(out["skipped"], "ENVGEN_KEEP_WORKTREES=1")
        self.assertTrue(lane.exists())

    def test_missing_worktrees_directory_is_not_an_error(self):
        shutil.rmtree(self.wt)
        out = reclaim_run_worktrees_1202as(self.root)
        self.assertEqual(out["skipped"], "no worktrees directory")


    def test_a_worktree_dirty_only_with_build_junk_is_reclaimed(self):
        """#1202ay: `__pycache__` is not lane work being protected.

        Measured on the corpus: 4 of 52 recent worktrees are dirty, and r32's backend is
        dirty ONLY for `?? app/backend/__pycache__/` — 186MB kept checked out to preserve
        compiled Python. auto_commit refuses .pyc unconditionally (committed ones break
        agent->integration merges), so it can never be work worth saving.
        """
        lane = self._add_lane("backend")
        cache = lane / "app" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "main.cpython-311.pyc").write_bytes(b"\x00" * 2048)
        (lane / "app" / "stray.pyc").write_bytes(b"\x00" * 512)

        out = reclaim_run_worktrees_1202as(self.root)

        self.assertEqual(out["removed"], ["backend"])
        self.assertFalse(lane.exists())

    def test_real_source_beside_build_junk_still_keeps_the_worktree(self):
        """The half that must not regress: r31's backend held `M custom_routes.py`."""
        lane = self._add_lane("backend")
        cache = lane / "app" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "main.cpython-311.pyc").write_bytes(b"\x00" * 2048)
        (lane / "app" / "custom_routes.py").write_text("# real uncommitted lane work\n")
        _git("add", "-A", cwd=lane)

        out = reclaim_run_worktrees_1202as(self.root)

        self.assertEqual(out["kept"], ["backend"])
        self.assertTrue((lane / "app" / "custom_routes.py").exists())


if __name__ == "__main__":
    unittest.main()
