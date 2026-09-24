import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class FakePopen:
    """Mimics subprocess.Popen surface used by RunHandle."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 99999
        self._returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._returncode

    @property
    def returncode(self):
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15  # SIGTERM exit code

    def kill(self):
        self.killed = True
        self._returncode = -9

    def wait(self, timeout=None):
        return self._returncode if self._returncode is not None else 0


class TestRunRegistry(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        # Ensure provider API-key env exists so start_run_call doesn't bail before spawn.
        os.environ.setdefault("OPENAI_API_KEY", "test-key")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_start_run_creates_workspace_and_returns_ids(self):
        from live_monitor_server import start_run_call
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo", "description": "a demo"})
        self.assertNotIn("error", result, result)
        self.assertIn("run_id", result)
        self.assertIn("project_id", result)
        self.assertTrue((self.root / result["project_id"]).exists())

    def test_start_run_requires_name(self):
        from live_monitor_server import start_run_call
        result = start_run_call(self.root, {})
        self.assertIn("error", result)

    def test_start_run_records_in_registry(self):
        from live_monitor_server import start_run_call, _RUN_REGISTRY
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        self.assertIn(result["run_id"], _RUN_REGISTRY)
        handle = _RUN_REGISTRY[result["run_id"]]
        self.assertEqual(handle["project_id"], result["project_id"])
        self.assertEqual(handle["state"], "running")

    def test_run_status_returns_running_then_completed(self):
        from live_monitor_server import start_run_call, get_run_status, _RUN_REGISTRY
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        run_id = result["run_id"]
        status = get_run_status(run_id)
        self.assertEqual(status["state"], "running")
        # Simulate completion
        _RUN_REGISTRY[run_id]["popen"]._returncode = 0
        status = get_run_status(run_id)
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["returncode"], 0)

    def test_stop_run_requires_confirm(self):
        from live_monitor_server import start_run_call, stop_run_call
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        stop_result = stop_run_call(result["run_id"], {})
        self.assertIn("error", stop_result)
        stop_result = stop_run_call(result["run_id"], {"confirm": True})
        self.assertEqual(stop_result.get("ok"), True)

    def test_list_runs_returns_handles(self):
        from live_monitor_server import start_run_call, list_runs
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            r1 = start_run_call(self.root, {"name": "first"})
            r2 = start_run_call(self.root, {"name": "second"})
        runs = list_runs()
        ids = {r["run_id"] for r in runs}
        self.assertIn(r1["run_id"], ids)
        self.assertIn(r2["run_id"], ids)


class TestDeliverEndpoint(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        result = create_project_call(self.root, {"name": "deliver-test"})
        self.assertNotIn("error", result, result)
        self.project_id = result["id"]

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_deliver_call_returns_blockers_when_not_ready(self):
        from live_monitor_server import deliver_project_call
        # Fresh project has no successful run -> should be blocked.
        result = deliver_project_call(self.root, self.project_id, {})
        self.assertIn("report", result)
        self.assertEqual(result["report"].get("verdict"), "blocked")
        self.assertTrue(len(result["report"].get("blockers", [])) > 0)

    def test_deliver_call_marks_completed_when_ready(self):
        from live_monitor_server import deliver_project_call, _resolve_hubs
        # Seed a passing RunHub run to flip the verdict. RunHub.record_run
        # takes positional (branch, generated_dir); we update to completed.
        reg, _ = _resolve_hubs(self.root, self.project_id)
        run = reg.runhub.record_run("main", "/tmp/dummy", agent="seed")
        reg.runhub.update_run_status(run["id"], "completed", agent="seed", fail_count=0)
        # Note: full compute_deliverability has multiple gates; we still pass
        # force_deliver=True to bypass coverage/seed/visual gates for this
        # test since they fail without real app code.
        result = deliver_project_call(self.root, self.project_id, {"force_deliver": True, "reason": "manual ready override"})
        self.assertEqual(result.get("ok"), True)
        # Project status should now be "completed".
        self.assertEqual(reg.project_metadata.status, "completed")

    def test_deliver_call_force_publishes_audit_event(self):
        from live_monitor_server import deliver_project_call, _resolve_hubs
        reg, _ = _resolve_hubs(self.root, self.project_id)
        # Get pre-publish event count
        pre = len(reg.eventhub.snapshot().get("events", {}))
        deliver_project_call(self.root, self.project_id, {"force_deliver": True, "agent": "ui_user", "reason": "manual override"})
        post = len(reg.eventhub.snapshot().get("events", {}))
        self.assertGreater(post, pre)

    def test_deliver_unknown_project_returns_error(self):
        from live_monitor_server import deliver_project_call
        result = deliver_project_call(self.root, "nope", {})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
