import http.server
import os
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.client import HTTPConnection
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class _FakeFinishingPopen:
    """A Popen mock that becomes `done` (returncode=0) on the Nth poll call."""
    def __init__(self, finish_after_polls: int = 999):
        self.pid = 12345
        self._finish_after = finish_after_polls
        self._polls = 0
        self._returncode = None
    def poll(self):
        self._polls += 1
        if self._polls >= self._finish_after:
            self._returncode = 0
        return self._returncode
    @property
    def returncode(self):
        return self._returncode
    def terminate(self): self._returncode = -15
    def kill(self): self._returncode = -9
    def wait(self, timeout=None): return self._returncode or 0



# #1202sx: the reader lives in `_sse_reader_1202sx` -- six call sites across three
# files had the same leak, so the fix is one helper, not six copies.
from _sse_reader_1202sx import read_stream_1202sx as _read_stream_1202sx


class TestLogStream(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE, _SESSIONS
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _SESSIONS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "demo"
        self.workspace.mkdir()
        (self.workspace / "logs").mkdir()
        self.log_path = self.workspace / "logs" / "generation.log"
        self.log_path.write_text("initial log line 1\ninitial log line 2\n")
        # Register a fake run
        self.run_id = "run_test_001"
        from live_monitor_server import _RUN_REGISTRY
        _RUN_REGISTRY[self.run_id] = {
            "run_id": self.run_id,
            "project_id": "demo",
            "started_at": time.time(),
            "command": ["fake"],
            "log_path": str(self.log_path),
            "popen": _FakeFinishingPopen(),
            "state": "running",
            "returncode": None,
        }

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY
        _RUN_REGISTRY.clear()
        self._tmp.cleanup()

    def test_log_stream_endpoint_sends_initial_snapshot(self):
        """SSE handler sends the existing log content as a first chunk."""
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received, meta, errors, rt = _read_stream_1202sx(
                port, f"/api/runs/{self.run_id}/log/stream", 1.5)
            rt.join(timeout=5.0)
            self.assertFalse(rt.is_alive(), "#1202sx: the reader outlived its own test")
            self.assertEqual(errors, [])
            # asserted HERE, on the test's own thread, where a failure can fail the test
            self.assertEqual(meta.get("status"), 200)
            self.assertIn("text/event-stream", meta.get("content_type", ""))
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn("data:", blob)
            self.assertIn("initial log line 1", blob)
            self.assertIn("initial log line 2", blob)
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_tails_new_lines(self):
        """Lines written after the connection opens must be streamed."""
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received, meta, errors, rt = _read_stream_1202sx(
                port, f"/api/runs/{self.run_id}/log/stream", 2.0)
            # Append after a brief delay so the stream is open
            time.sleep(0.5)
            with self.log_path.open("ab") as f:
                f.write(b"NEW LINE AFTER CONNECT\n")
                f.flush()
            rt.join(timeout=5.0)
            self.assertFalse(rt.is_alive(), "#1202sx: the reader outlived its own test")
            self.assertEqual(errors, [])
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn("NEW LINE AFTER CONNECT", blob)
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_unknown_run_returns_404(self):
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/runs/does_not_exist/log/stream")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            conn.close()
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_emits_end_event_when_run_completes(self):
        """When the underlying Popen finishes, the stream emits _end + closes."""
        from live_monitor_server import MonitorHandler, _RUN_REGISTRY
        # Force the fake to finish after ~3 polls
        _RUN_REGISTRY[self.run_id]["popen"] = _FakeFinishingPopen(finish_after_polls=3)
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received, meta, errors, rt = _read_stream_1202sx(
                port, f"/api/runs/{self.run_id}/log/stream", 3.0)
            rt.join(timeout=6.0)
            self.assertFalse(rt.is_alive(), "#1202sx: the reader outlived its own test")
            self.assertEqual(errors, [])
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn('"_end": true', blob)
            self.assertIn('"returncode": 0', blob)
        finally:
            server.shutdown(); server.server_close()


if __name__ == "__main__":
    unittest.main()
