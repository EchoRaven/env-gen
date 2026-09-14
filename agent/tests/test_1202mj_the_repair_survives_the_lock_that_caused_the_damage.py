"""#1202mj: the build-entry repair must not be defeated by the lock it repairs after.

`ensure_build_infra_staged_for_build` runs at EVERY build entry (validation_runner
before the clean boot, docker_tools at the build) and restores a dropped
`app/frontend` / `app/backend` from HEAD. It does that with `git checkout`, which
writes the index -- so a stale `.git/index.lock` fails it. tiktok-r122 held such a
lock for 46 minutes; had the directory gone missing in that window the image would
have baked a tree with no frontend, silently, because both callers discard this
function's return value inside a bare `except Exception: pass`.
"""
import json
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

from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402
from multi_agent.agents.runtime import auto_commit as AC  # noqa: E402


def _git(*a, cwd):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60)


class TheRepairClearsAStaleLockAndCompletes(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "run"
        (self.root / "app" / "frontend" / "src").mkdir(parents=True)
        (self.root / "app" / "frontend" / "src" / "App.jsx").write_text("x")
        (self.root / "app" / "backend").mkdir(parents=True)
        (self.root / "app" / "backend" / "main.py").write_text("x = 1\n")
        (self.root / "docker").mkdir()
        _git("init", "-q", cwd=self.root)
        _git("config", "user.email", "t@t", cwd=self.root)
        _git("config", "user.name", "t", cwd=self.root)
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", "init", cwd=self.root)
        self.lock = self.root / ".git" / "index.lock"
        AC._self_gitdir_1202mg.cache_clear()

    def tearDown(self):
        AC._self_gitdir_1202mg.cache_clear()
        self._tmp.cleanup()

    def _drop_frontend(self):
        import shutil
        shutil.rmtree(self.root / "app" / "frontend")

    def _plant_stale_lock(self):
        self.lock.write_text("")
        old = time.time() - (AC._LOCK_STALE_AFTER_1202MG + 600)
        os.utime(self.lock, (old, old))

    def test_without_a_lock_the_directory_comes_back(self):
        """The baseline the fix must not break."""
        self._drop_frontend()
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        self.assertTrue((self.root / "app" / "frontend" / "src" / "App.jsx").is_file())

    def test_a_stale_lock_no_longer_defeats_the_repair(self):
        self._drop_frontend()
        self._plant_stale_lock()
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        self.assertTrue(
            (self.root / "app" / "frontend" / "src" / "App.jsx").is_file(),
            "the frontend did not come back; the build would bake a tree without it")
        self.assertFalse(self.lock.exists())

    def test_a_FRESH_lock_is_left_alone_and_the_failure_is_recorded(self):
        """Counter-proof for the threshold, and for the record: a lock inside
        the contention window may belong to a running git."""
        self._drop_frontend()
        self.lock.write_text("")          # mtime = now
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        self.assertTrue(self.lock.exists(), "a fresh lock must not be removed")
        rec = self.root / "logs" / "build_infra_restore_1202mj.jsonl"
        self.assertTrue(rec.is_file(), "a failed repair left no trace")
        rows = [json.loads(l) for l in
                rec.read_text(encoding="utf-8").splitlines() if l.strip()]
        fe = [r for r in rows if "app/frontend" in r["path"]]
        self.assertTrue(fe, rows)
        self.assertEqual(fe[-1]["outcome"], "failed")


class TheRepairIsNoLongerInvisible(unittest.TestCase):
    """Both callers discard the return value inside a bare except, so the record
    is the only frame where this event survives."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "run"
        (self.root / "app" / "backend").mkdir(parents=True)
        (self.root / "app" / "backend" / "main.py").write_text("x = 1\n")
        (self.root / "docker").mkdir()
        _git("init", "-q", cwd=self.root)
        _git("config", "user.email", "t@t", cwd=self.root)
        _git("config", "user.name", "t", cwd=self.root)
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", "init", cwd=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_successful_restore_is_recorded(self):
        import shutil
        shutil.rmtree(self.root / "app" / "backend")
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        rec = self.root / "logs" / "build_infra_restore_1202mj.jsonl"
        self.assertTrue(rec.is_file())
        rows = [json.loads(l) for l in
                rec.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(rows[-1]["outcome"], "restored")
        self.assertIn("app/backend", rows[-1]["path"])

    def test_nothing_missing_writes_nothing(self):
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        self.assertFalse((self.root / "logs" /
                          "build_infra_restore_1202mj.jsonl").exists())

    def test_a_directory_this_app_never_had_is_not_a_failed_repair(self):
        """The first draft recorded a failure for `app/frontend` in a
        backend-only app, every single build. A path absent from HEAD was never
        dropped, and burying the real event under that noise would undo the
        point of recording it."""
        self.assertFalse((self.root / "app" / "frontend").exists())
        FS.ensure_build_infra_staged_for_build(self.root / "docker")
        rec = self.root / "logs" / "build_infra_restore_1202mj.jsonl"
        if rec.is_file():
            rows = [json.loads(l) for l in
                    rec.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r for r in rows if "frontend" in r["path"]], [])


if __name__ == "__main__":
    unittest.main()
