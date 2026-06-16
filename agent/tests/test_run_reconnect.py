import json
import os
import signal
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _dead_pid() -> int:
    """Return a pid that has already exited (so os.kill(pid, 0) raises)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class TestAttachedRunHandle(unittest.TestCase):
    def test_poll_returns_none_when_pid_alive(self):
        from live_monitor_server import _AttachedRunHandle
        h = _AttachedRunHandle(pid=os.getpid())
        self.assertIsNone(h.poll())
        self.assertIsNone(h.returncode)

    def test_poll_returns_zero_when_pid_dead(self):
        from live_monitor_server import _AttachedRunHandle
        h = _AttachedRunHandle(pid=_dead_pid())
        # Allow a brief moment for the OS to reap, then poll
        time.sleep(0.05)
        rc = h.poll()
        self.assertIsNotNone(rc)


class TestRegistryPersistence(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        self._tmp.cleanup()

    def test_save_registry_writes_runs_json(self):
        from live_monitor_server import _RUN_REGISTRY, _save_registry
        _RUN_REGISTRY["run_test"] = {
            "run_id": "run_test",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["python", "main.py"],
            "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": 12345, "poll": lambda self: None, "returncode": None})(),
            "state": "running",
            "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        runs_file = self.root / ".runs.json"
        self.assertTrue(runs_file.exists())
        data = json.loads(runs_file.read_text())
        self.assertIn("run_test", data)
        self.assertEqual(data["run_test"]["pid"], 12345)
        # popen object must not be persisted
        self.assertNotIn("popen", data["run_test"])

    def test_load_registry_creates_attached_handles_for_alive_pids(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY, _AttachedRunHandle
        # Use our own pid as a "still alive" fake run
        _RUN_REGISTRY["run_alive"] = {
            "run_id": "run_alive",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["python", "main.py"],
            "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": os.getpid(), "poll": lambda self: None, "returncode": None})(),
            "state": "running",
            "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        _load_registry(self.root)
        self.assertIn("run_alive", _RUN_REGISTRY)
        reloaded = _RUN_REGISTRY["run_alive"]
        self.assertEqual(reloaded["state"], "running")
        self.assertIsInstance(reloaded["popen"], _AttachedRunHandle)
        self.assertIsNone(reloaded["popen"].poll())  # still alive

    def test_load_registry_marks_dead_pids_as_completed(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY
        dead = _dead_pid()
        _RUN_REGISTRY["run_dead"] = {
            "run_id": "run_dead",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["x"], "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": dead, "poll": lambda self: None, "returncode": None})(),
            "state": "running", "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        time.sleep(0.05)  # ensure os has reaped
        _load_registry(self.root)
        self.assertIn("run_dead", _RUN_REGISTRY)
        self.assertEqual(_RUN_REGISTRY["run_dead"]["state"], "completed")

    def test_load_registry_idempotent_on_repeated_calls(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY["run_x"] = {
            "run_id": "run_x", "project_id": "p", "started_at": 1.0,
            "command": ["x"], "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": os.getpid(), "poll": lambda self: None, "returncode": None})(),
            "state": "running", "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        _load_registry(self.root)
        first_handle = _RUN_REGISTRY["run_x"]["popen"]
        _load_registry(self.root)
        second_handle = _RUN_REGISTRY["run_x"]["popen"]
        # Should NOT re-mint a new handle (idempotent)
        self.assertIs(first_handle, second_handle)

    def test_missing_runs_file_is_silent(self):
        from live_monitor_server import _load_registry, _RUN_REGISTRY
        _load_registry(self.root)
        # No file → no entries added; no exception
        self.assertEqual(len(_RUN_REGISTRY), 0)


class TestStartRunSavesRegistry(unittest.TestCase):
    """start_run_call must save the registry after registering the new handle."""
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        os.environ.setdefault("OPENAI_API_KEY", "test")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        self._tmp.cleanup()

    def test_start_run_persists_to_disk(self):
        from live_monitor_server import start_run_call
        # FakePopen-style mock at module level
        class FakePopen:
            def __init__(self, *a, **kw):
                self.pid = 99999
                self._rc = None
            def poll(self): return self._rc
            @property
            def returncode(self): return self._rc
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "persist-demo"})
        self.assertNotIn("error", result)
        runs_file = self.root / ".runs.json"
        self.assertTrue(runs_file.exists())
        data = json.loads(runs_file.read_text())
        self.assertIn(result["run_id"], data)
        self.assertEqual(data[result["run_id"]]["pid"], 99999)


if __name__ == "__main__":
    unittest.main()
