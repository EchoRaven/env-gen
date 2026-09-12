"""#1202kw: a STALE .git lock must be cleared by the framework, because no lane can.

`GitOps._run` is the wrapper every CodeHub git operation goes through, and it had no retry at
all. Its own comment already named the cause -- "an operation waiting on an `index.lock` left by
a crashed process (the git pain here is documented -- 'could not write index' 187 times)".

`auto_commit._run_git` retries this same signature 3x with 200/400ms backoff, for the case it
documents: "two agents finishing in the same millisecond". That is real contention and backoff
is the right answer to it. Backoff cannot answer a lock left by a git that was killed.

tiktok-r118 died of one, measured: a ZERO-BYTE `.git/index.lock` dated 17:16:08 (git creates it
O_EXCL and writes the new index into it, so empty means it never got that far) was still on disk
when the run aborted at 18:36 -- 80 minutes in which `codehub_resolve_merge_conflict` failed
every time. The lanes could not clear it BY CONSTRUCTION: the debugger replied "my available
tool subset has no filesystem/shell/delete capability", the orchestrator raised a P0
"filesystem-capable cleanup" task anyway, and the backend lane's attempt was refused by the path
sandbox ("'..' escapes its route's root"). The run then hit DELIVERY-GATE NO-CONVERGENCE ABORT.

WHAT IS VERIFIED: a stale lock is removed and the operation retried; a FRESH lock is left alone
(that window belongs to auto_commit's backoff); non-lock failures are untouched; the threshold
is derived from #1075's ceiling rather than picked; a linked worktree's lock is found through
rev-parse; and the clear never raises.

WHAT IS NOT: that this makes the merge succeed. It removes an obstruction no agent could remove.
Whatever the merge's real state is then applies.
"""
from __future__ import annotations

import os
import shutil
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

from multi_agent.runtime.hubs.codehub.git_ops import (  # noqa: E402
    _GIT_TIMEOUT_1075, _LOCK_STALE_AFTER_1202KW, GitOps, GitOpsError)

GIT = "/usr/bin/git"


def _git(repo, *args):
    return subprocess.run([GIT, *args], cwd=str(repo), capture_output=True, text=True)


@unittest.skipUnless(os.path.exists(GIT), "git not installed")
class AStaleLock(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="kw_repo_"))
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "a.txt").write_text("one\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "first")
        self.ops = GitOps(self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _lock(self, age_seconds):
        """r118's exact artefact: a zero-byte index.lock of a given age."""
        lock = self.repo / ".git" / "index.lock"
        lock.write_bytes(b"")
        old = time.time() - age_seconds
        os.utime(lock, (old, old))
        return lock

    def test_a_stale_lock_is_cleared_and_the_operation_retried(self):
        """★ The r118 case."""
        lock = self._lock(_LOCK_STALE_AFTER_1202KW + 120)
        (self.repo / "b.txt").write_text("two\n")
        self.ops._run("add", "-A")            # would fail on the lock
        self.assertFalse(lock.exists(), "the stale lock was not cleared")

    def test_it_says_so(self):
        self._lock(_LOCK_STALE_AFTER_1202KW + 120)
        (self.repo / "b.txt").write_text("two\n")
        with self.assertLogs("multi_agent.runtime.hubs.codehub.git_ops",
                             level="WARNING") as cm:
            self.ops._run("add", "-A")
        said = "\n".join(cm.output)
        self.assertIn("#1202kw", said)
        self.assertIn("index.lock", said)
        self.assertIn("No lane", said)

    def test_a_fresh_lock_is_left_alone(self):
        """★ Narrowness: the sub-threshold window is auto_commit's contention case, and
        removing a lock a LIVE git holds would corrupt the index."""
        lock = self._lock(5)
        (self.repo / "b.txt").write_text("two\n")
        with self.assertRaises(GitOpsError):
            self.ops._run("add", "-A")
        self.assertTrue(lock.exists(), "a fresh lock must not be removed")

    def test_a_non_lock_failure_clears_nothing(self):
        """`rev-parse --verify` does not take the index lock, so its failure is genuinely
        unrelated. NOTE: `checkout` is NOT such a command -- it grabs index.lock BEFORE it
        resolves the branch, so `checkout no-such-branch` on a locked repo reports the lock,
        not the branch. Picking it here asserted the opposite of what it looked like."""
        lock = self._lock(_LOCK_STALE_AFTER_1202KW + 120)
        with self.assertRaises(GitOpsError):
            self.ops._run("rev-parse", "--verify", "no-such-ref")
        self.assertTrue(lock.exists(), "an unrelated failure must not clear locks")

    def test_the_threshold_is_derived_from_the_1075_ceiling(self):
        """Not a tuned constant (#647): every git call here is bounded by #1075, so a lock
        older than that ceiling cannot be held by one that is still running."""
        self.assertGreater(_LOCK_STALE_AFTER_1202KW, _GIT_TIMEOUT_1075)

    def test_clearing_never_raises(self):
        self.assertEqual(self.ops._clear_stale_locks_1202kw(Path("/nonexistent/xyz")), [])

    def test_a_git_dir_outside_repo_root_is_refused(self):
        """★ The hazard this fix could otherwise CREATE. `git rev-parse` WALKS UP: run it in a
        directory that is not itself a repo and it answers with the nearest ANCESTOR repo.
        Measured on this checkout, `rev-parse --absolute-git-dir` from `generated/` returns
        the development repo's own .git. Clearing a lock there would corrupt the tree this
        code lives in, so a git dir that does not resolve inside repo_root is refused.

        (An earlier version of this test used a symlinked lock instead. It was vacuous twice
        over: the name check refused it before containment ran, and `unlink` removes a symlink
        rather than its target, so nothing outside was ever at risk that way.)
        """
        inner = self.repo / "nested"
        inner.mkdir()
        _git(inner, "init", "-q")
        _git(inner, "config", "user.email", "t@example.com")
        _git(inner, "config", "user.name", "t")
        outer_ops = GitOps(inner)          # repo_root = the INNER repo
        stale = time.time() - (_LOCK_STALE_AFTER_1202KW + 120)

        # a stale lock in the OUTER repo, which is NOT under outer_ops.repo_root
        outer_lock = self.repo / ".git" / "index.lock"
        outer_lock.write_bytes(b"")
        os.utime(outer_lock, (stale, stale))

        # cwd is the outer repo: rev-parse answers with the OUTER git dir
        self.assertEqual(outer_ops._clear_stale_locks_1202kw(self.repo), [])
        self.assertTrue(outer_lock.exists(),
                        "a lock outside repo_root was deleted")

        # and the inner repo's own lock is still cleared normally
        inner_lock = inner / ".git" / "index.lock"
        inner_lock.write_bytes(b"")
        os.utime(inner_lock, (stale, stale))
        self.assertTrue(outer_ops._clear_stale_locks_1202kw(inner))
        self.assertFalse(inner_lock.exists())

    def test_a_linked_worktree_lock_is_found_through_rev_parse(self):
        """A worktree's `.git` is a FILE; the lock does not live beside the checkout."""
        wt = Path(tempfile.mkdtemp(prefix="kw_wt_"))
        shutil.rmtree(wt)
        r = _git(self.repo, "worktree", "add", "-q", str(wt))
        if r.returncode != 0:
            self.skipTest(f"worktree unsupported: {r.stderr.strip()}")
        try:
            self.assertTrue((wt / ".git").is_file(), "expected a linked worktree")
            gitdir = self.ops._git_dir_1202kw(wt)
            self.assertIsNotNone(gitdir)
            self.assertNotEqual(gitdir, self.repo / ".git")
            lock = gitdir / "index.lock"
            lock.write_bytes(b"")
            old = time.time() - (_LOCK_STALE_AFTER_1202KW + 120)
            os.utime(lock, (old, old))
            self.assertTrue(self.ops._clear_stale_locks_1202kw(wt))
            self.assertFalse(lock.exists())
        finally:
            shutil.rmtree(wt, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
