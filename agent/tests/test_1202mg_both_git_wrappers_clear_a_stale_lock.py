"""#1202mg: a stale git lock must be clearable from BOTH git wrappers.

`#1202kw` gave GitOps._run a stale-lock remedy. The package has a second git
wrapper -- `auto_commit._run_git`, which ~30 call sites go through including
the auto-merge path -- and it got none. tiktok-r122 is what that costs: a lock
appeared at 18:17:10, every merge failed for the next 46 minutes, the delivery
gate went FULLY GREEN at 18:44:57 and the run still could not ship. The resume
took one GitOps path and `#1202kw` logged the age the lock had reached: 5410s.

Every test here drives the real function against a real repository and reads
the filesystem back. None of them assert on source text: a test that checks the
source for a line stays green when the line stops doing anything.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.runtime import auto_commit as AC  # noqa: E402


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60)


class StaleLockClearedFromAutoCommit(unittest.TestCase):
    """The wrapper that actually failed in r122."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _git("init", "-q", cwd=self.repo)
        _git("config", "user.email", "t@t", cwd=self.repo)
        _git("config", "user.name", "t", cwd=self.repo)
        (self.repo / "a.txt").write_text("one\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "init", cwd=self.repo)
        self.lock = self.repo / ".git" / "index.lock"
        AC._self_gitdir_1202mg.cache_clear()

    def tearDown(self):
        AC._self_gitdir_1202mg.cache_clear()
        self._tmp.cleanup()

    def _plant_lock(self, age_s):
        self.lock.write_text("")
        old = time.time() - age_s
        os.utime(self.lock, (old, old))

    def test_a_stale_lock_is_cleared_and_the_command_then_succeeds(self):
        # Older than any bounded call could hold: r122's reached 5410s.
        self._plant_lock(AC._LOCK_STALE_AFTER_1202MG + 120)
        rc, _out, err = AC._run_git(["checkout", "-q", "-b", "integration"],
                                    cwd=self.repo)
        self.assertEqual(rc, 0, "checkout still failed: %r" % err)
        self.assertFalse(self.lock.exists(), "the stale lock survived")
        # and the command really ran, rather than merely returning 0
        head = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo)
        self.assertEqual(head.stdout.strip(), "integration")

    def test_the_clearing_reaches_an_artifact_not_only_a_log(self):
        """#947: a remediation that exists only in a log line is not a
        measurement. A later reader -- a resume, a forensic pass -- must be able
        to ask whether the framework removed a lock here."""
        import json
        self._plant_lock(AC._LOCK_STALE_AFTER_1202MG + 900)
        rc, _o, _e = AC._run_git(["checkout", "-q", "-b", "integration"],
                                 cwd=self.repo)
        self.assertEqual(rc, 0)
        rec = self.repo / "logs" / "git_lock_clears_1202mg.jsonl"
        self.assertTrue(rec.is_file(), "no artifact was written")
        rows = [json.loads(l) for l in
                rec.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["outcome"], "cleared")
        self.assertTrue(any("index.lock" in c for c in rows[0]["cleared"]))
        # the age it had reached is the fact the r122 forensics turned on
        self.assertIn("age", rows[0]["cleared"][0])

    def test_a_FRESH_lock_writes_no_row(self):
        """Counter-proof: the artifact records remediations, not every failure."""
        self._plant_lock(0)
        AC._run_git(["checkout", "-q", "-b", "integration"], cwd=self.repo)
        self.assertFalse((self.repo / "logs" /
                          "git_lock_clears_1202mg.jsonl").exists())

    def test_a_FRESH_lock_is_left_alone_and_the_failure_is_reported(self):
        """The counter-proof for the threshold. A lock inside the contention
        window belongs to backoff -- deleting it could destroy the index of a
        git that is still running."""
        self._plant_lock(0)
        rc, _out, err = AC._run_git(["checkout", "-q", "-b", "integration"],
                                    cwd=self.repo)
        self.assertNotEqual(rc, 0, "a held lock must still fail the command")
        self.assertIn("index.lock", err)
        self.assertTrue(self.lock.exists(), "a fresh lock must NOT be removed")

    def test_clearing_is_attempted_once_not_spun_on(self):
        """A lock that is stale by age but cannot be removed must still return a
        legible git failure rather than loop."""
        self._plant_lock(AC._LOCK_STALE_AFTER_1202MG + 120)
        real_unlink = Path.unlink

        def refuse(self_path, *a, **k):
            if self_path.name == "index.lock":
                raise OSError("refused for the test")
            return real_unlink(self_path, *a, **k)

        Path.unlink = refuse
        try:
            started = time.time()
            rc, _out, err = AC._run_git(["checkout", "-q", "-b", "x"],
                                        cwd=self.repo)
        finally:
            Path.unlink = real_unlink
        self.assertNotEqual(rc, 0)
        self.assertIn("index.lock", err)
        self.assertLess(time.time() - started, 30, "it span on the error path")


class TheDevelopmentRepoIsNeverTouched(unittest.TestCase):
    """`rev-parse` WALKS UP. Every generated run lives inside the development
    tree, so a cwd that is not its own repo resolves to the framework's own git
    dir -- and clearing a lock there would be this fix corrupting its own tree.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _git("init", "-q", cwd=self.repo)
        self.lock = self.repo / ".git" / "index.lock"
        self.lock.write_text("")
        old = time.time() - (AC._LOCK_STALE_AFTER_1202MG + 500)
        os.utime(self.lock, (old, old))
        AC._self_gitdir_1202mg.cache_clear()

    def tearDown(self):
        AC._self_gitdir_1202mg.cache_clear()
        self._tmp.cleanup()

    def test_a_lock_in_the_frameworks_own_repo_is_refused(self):
        gitdir = str((self.repo / ".git").resolve())
        AC._self_gitdir_1202mg.cache_clear()
        orig = AC._self_gitdir_1202mg
        AC._self_gitdir_1202mg = lambda: gitdir          # pretend it is ours
        try:
            cleared = AC.clear_stale_git_locks_1202mg(self.repo)
        finally:
            AC._self_gitdir_1202mg = orig
        self.assertEqual(cleared, [], "it deleted a lock in its own repo")
        self.assertTrue(self.lock.exists())
        # and it wrote nothing there either. The first version recorded the
        # refusal under the resolved root -- which, in the real layout, IS the
        # development tree: verified by resolving a non-repo directory under
        # generated/, which lands on the framework's own .git.
        self.assertFalse((self.repo / "logs").exists(),
                         "the refusal wrote into the repository it refused to touch")

    def test_without_that_guard_the_same_lock_WOULD_go(self):
        """Counter-proof: the refusal above is the only thing holding it back."""
        cleared = AC.clear_stale_git_locks_1202mg(self.repo)
        self.assertEqual(len(cleared), 1, cleared)
        self.assertFalse(self.lock.exists())

    def test_containment_boundary_refuses_a_gitdir_outside_it(self):
        elsewhere = Path(self._tmp.name) / "not-the-repo"
        elsewhere.mkdir()
        cleared = AC.clear_stale_git_locks_1202mg(
            self.repo, contain_under=elsewhere)
        self.assertEqual(cleared, [])
        self.assertTrue(self.lock.exists(), "containment did not contain")


class GitOpsStillClearsThroughTheSharedPath(unittest.TestCase):
    """#1202kw's behaviour must survive being routed through one implementation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _git("init", "-q", cwd=self.repo)
        self.lock = self.repo / ".git" / "index.lock"
        AC._self_gitdir_1202mg.cache_clear()

    def tearDown(self):
        AC._self_gitdir_1202mg.cache_clear()
        self._tmp.cleanup()

    def test_stale_lock_cleared(self):
        from multi_agent.runtime.hubs.codehub import git_ops
        self.lock.write_text("")
        old = time.time() - (AC._LOCK_STALE_AFTER_1202MG + 300)
        os.utime(self.lock, (old, old))
        ops = git_ops.GitOps(self.repo)
        cleared = ops._clear_stale_locks_1202kw(self.repo)
        self.assertEqual(len(cleared), 1, cleared)
        self.assertFalse(self.lock.exists())

    def test_a_gitdir_outside_repo_root_is_still_refused(self):
        """GitOps' stricter boundary: the walk-up case #1202kw was written for."""
        from multi_agent.runtime.hubs.codehub import git_ops
        self.lock.write_text("")
        old = time.time() - (AC._LOCK_STALE_AFTER_1202MG + 300)
        os.utime(self.lock, (old, old))
        inner = self.repo / "sub" / "deeper"
        inner.mkdir(parents=True)
        # repo_root is a directory that is NOT an ancestor of the resolved gitdir
        ops = git_ops.GitOps(inner)
        self.assertEqual(ops._clear_stale_locks_1202kw(self.repo), [])
        self.assertTrue(self.lock.exists())


class TheThresholdOutlivesTheLongestBoundedCall(unittest.TestCase):

    def test_threshold_covers_the_larger_of_the_two_ceilings(self):
        """#647: not a tuned constant. Clearing at this module's own 30s ceiling
        could delete a lock a live 120s GitOps call still holds."""
        self.assertGreaterEqual(AC._GIT_CEILING_1202MG, AC._GIT_TIMEOUT)
        self.assertGreaterEqual(AC._GIT_CEILING_1202MG,
                                AC._env_git_timeout_1202mg())
        self.assertGreater(AC._LOCK_STALE_AFTER_1202MG, AC._GIT_CEILING_1202MG)


if __name__ == "__main__":
    unittest.main()
