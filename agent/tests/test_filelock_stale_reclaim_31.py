"""PROPOSAL #31 S3 — _FileLock stale-lock reclamation.

Run #28: an orphaned .custom_routes.py.lock wedged the backend's writes for ~4 minutes
(no concurrent writer; the holder PROCESS was alive but its locked region was abandoned,
so pid-liveness alone couldn't detect it). _FileLock now reclaims a lock that is held by
a DEAD pid OR aged past _LOCK_STALE_SEC, and __exit__ only unlinks a lockfile that still
records OUR pid (so a reclaimer's new holder isn't clobbered).

RACE-SAFETY assertions: a fresh, live-held lock is NOT reclaimed; a dead-pid or aged lock
IS; reclamation never deletes a different owner's lock.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.file_tools import _FileLock, _LOCK_STALE_SEC  # noqa: E402


class StaleReclaim(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="p31_lock_"))
        self.target = self.d / "custom_routes.py"
        self.lockpath = self.d / f".{self.target.name}.lock"

    def _write_lock(self, pid: int, age_sec: float = 0.0):
        self.lockpath.write_text(f"{pid} {int(time.time() - age_sec)}\n")
        if age_sec:
            old = time.time() - age_sec
            os.utime(self.lockpath, (old, old))

    def test_dead_pid_lock_is_reclaimed(self):
        # a dead pid (99999990 — almost certainly not running) → reclaimed → acquire works
        self._write_lock(99999990, age_sec=1.0)
        with _FileLock(self.target, timeout_seconds=2.0):
            self.assertTrue(self.lockpath.exists())  # now held by US
        self.assertFalse(self.lockpath.exists())  # released on exit

    def test_aged_lock_is_reclaimed_even_if_pid_alive(self):
        # THE run-#28 case: holder process ALIVE (our own pid) but the lock is aged →
        # orphaned region → must reclaim on age (pid-liveness alone would miss it).
        self._write_lock(os.getpid(), age_sec=_LOCK_STALE_SEC + 5)
        with _FileLock(self.target, timeout_seconds=2.0):
            pass
        self.assertFalse(self.lockpath.exists())

    def test_fresh_live_lock_is_NOT_reclaimed(self):
        # a fresh lock held by a LIVE pid (us) must NOT be reclaimed → acquire times out
        self._write_lock(os.getpid(), age_sec=0.0)
        t0 = time.time()
        with self.assertRaises(TimeoutError):
            with _FileLock(self.target, timeout_seconds=0.5):
                pass
        self.assertGreaterEqual(time.time() - t0, 0.5)  # it actually waited (didn't reclaim)
        self.assertTrue(self.lockpath.exists())  # live lock untouched

    def test_exit_does_not_unlink_other_owners_lock(self):
        # acquire (reclaiming a dead-pid lock), then simulate a reclaimer taking over:
        # rewrite the lockfile with a DIFFERENT owner pid; our __exit__ must NOT unlink it.
        self._write_lock(99999990, age_sec=1.0)
        lk = _FileLock(self.target, timeout_seconds=2.0)
        lk.__enter__()
        self.assertTrue(self.lockpath.exists())
        self.lockpath.write_text(f"{os.getpid() + 12345} {int(time.time())}\n")  # other owner
        lk.__exit__(None, None, None)
        self.assertTrue(self.lockpath.exists(), "must not delete another owner's lock")
        self.lockpath.unlink()  # cleanup

    def test_timeout_default_is_generous(self):
        self.assertGreaterEqual(_FileLock(self.target)._timeout, 15.0)


if __name__ == "__main__":
    unittest.main()
