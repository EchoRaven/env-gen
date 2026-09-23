"""Tests for Cutover 31: SSE replacing polling.

This module hosts both the HubRegistry cache tests (Task 2) and the
``_SSEHub`` / endpoint tests (Task 3).
"""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from live_monitor_server import (  # noqa: E402
    _HUB_REGISTRY_CACHE,
    _clear_hub_registry_cache_for_project,
    _resolve_hubs,
)



# #1202sx: one helper for the five readers that used to outlive their tests.
from _sse_reader_1202sx import read_stream_1202sx

class TestHubRegistryCache(unittest.TestCase):
    def setUp(self):
        _HUB_REGISTRY_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        result = create_project_call(self.root, {"name": "demo"})
        self.assertNotIn("error", result, result)
        self.project_id = result["id"]

    def tearDown(self):
        _HUB_REGISTRY_CACHE.clear()
        self._tmp.cleanup()

    def test_resolve_hubs_returns_same_instance_across_calls(self):
        reg_a, err_a = _resolve_hubs(self.root, self.project_id)
        reg_b, err_b = _resolve_hubs(self.root, self.project_id)
        self.assertIsNone(err_a)
        self.assertIsNone(err_b)
        self.assertIs(reg_a, reg_b)
        self.assertIs(reg_a.eventhub, reg_b.eventhub)

    def test_clear_cache_evicts_project(self):
        reg_a, _ = _resolve_hubs(self.root, self.project_id)
        _clear_hub_registry_cache_for_project(self.root, self.project_id)
        reg_b, _ = _resolve_hubs(self.root, self.project_id)
        self.assertIsNot(reg_a, reg_b)

    def test_unknown_project_returns_error(self):
        reg, err = _resolve_hubs(self.root, "does-not-exist")
        self.assertIsNone(reg)
        self.assertIn("error", err)


# ---------------------------------------------------------------------------
# Task 3: _SSEHub class + GET /api/projects/<id>/events endpoint
# ---------------------------------------------------------------------------

import queue  # noqa: E402
import time  # noqa: E402
import json  # noqa: E402


class TestSSEHub(unittest.TestCase):
    def test_register_returns_a_queue(self):
        from live_monitor_server import _SSEHub
        hub = _SSEHub()
        q = hub.register("client1")
        self.assertIsInstance(q, queue.Queue)
        self.assertEqual(hub.client_count, 1)

    def test_broadcast_fans_out(self):
        from live_monitor_server import _SSEHub
        hub = _SSEHub()
        q1 = hub.register("a")
        q2 = hub.register("b")
        hub.broadcast({"event_type": "task_created", "id": "evt_1"})
        self.assertEqual(q1.get(timeout=1.0)["id"], "evt_1")
        self.assertEqual(q2.get(timeout=1.0)["id"], "evt_1")

    def test_unregister_removes_client(self):
        from live_monitor_server import _SSEHub
        hub = _SSEHub()
        hub.register("a")
        hub.unregister("a")
        self.assertEqual(hub.client_count, 0)

    def test_full_queue_drops_silently(self):
        from live_monitor_server import _SSEHub
        hub = _SSEHub(max_queue=2)
        q = hub.register("a")
        hub.broadcast({"id": "1"})
        hub.broadcast({"id": "2"})
        hub.broadcast({"id": "3"})
        items = []
        while not q.empty():
            items.append(q.get_nowait()["id"])
        self.assertEqual(items, ["1", "2"])

    def test_bridge_interface_deliver(self):
        from live_monitor_server import _SSEHub
        hub = _SSEHub()
        q = hub.register("a")
        hub.deliver({"id": "evt_99", "event_type": "task_created"})
        msg = q.get(timeout=1.0)
        self.assertEqual(msg["id"], "evt_99")


class TestSSEEndpointSmoke(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        self.project_id = create_project_call(self.root, {"name": "sse-smoke"})["id"]

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_sse_endpoint_streams_event_on_mutation(self):
        import http.server
        from functools import partial
        from http.client import HTTPConnection
        from live_monitor_server import MonitorHandler, _resolve_hubs

        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            # #1202sx: `read_stream_1202sx` bounds the socket BELOW the read window, so the
            # reader cannot outlive this test, and returns what it saw instead of asserting
            # in the thread (an assertion there cannot fail the test). ``read1`` rather than
            # ``read(n)`` because the latter blocks until n bytes or EOF and SSE frames are
            # smaller.
            received, meta, errors, rt = read_stream_1202sx(
                port, f"/api/projects/{self.project_id}/events", 1.5, chunk=256)
            time.sleep(0.3)
            reg, _ = _resolve_hubs(self.root, self.project_id)
            reg.eventhub.publish_event(
                source_hub="workhub",
                event_type="task_created",
                payload={"title": "sse-test"},
                recipients=["alpha"],
            )
            rt.join(timeout=5.0)
            self.assertFalse(rt.is_alive(), "#1202sx: the reader outlived its own test")
            self.assertEqual(errors, [])
            # asserted HERE, on the test's own thread, where a failure can fail the test
            self.assertEqual(meta.get("status"), 200)
            self.assertIn("text/event-stream", meta.get("content_type", ""))
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn("data:", blob)
            self.assertIn("task_created", blob)
        finally:
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------------------
# Cutover 32: _GlobalSSEHub + GET /api/events + lifecycle event publishing
# ---------------------------------------------------------------------------


class TestGlobalSSEHub(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import (
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            _GLOBAL_SSE_HUB_CACHE,
        )
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _GLOBAL_SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import (
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            _GLOBAL_SSE_HUB_CACHE,
        )
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _GLOBAL_SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_create_project_broadcasts_global_event(self):
        """create_project_call publishes a ``project_created`` event onto the
        workspaces-root-scoped global SSE hub.
        """
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            create_project_call,
        )
        hub = _get_or_create_global_sse_hub(self.root)
        q = hub.register("test_client")
        result = create_project_call(self.root, {"name": "demo"})
        self.assertNotIn("error", result, result)
        event = q.get(timeout=2.0)
        self.assertEqual(event.get("event_type"), "project_created")
        self.assertEqual(event.get("project_id"), result["id"])

    def test_per_project_event_forwards_to_global(self):
        """Any EventHub publish on a project also reaches the global hub via
        the ``_GlobalForwardBridge`` attached to each cached HubRegistry.
        """
        import time as _time
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            _resolve_hubs,
            create_project_call,
        )
        result = create_project_call(self.root, {"name": "demo"})
        pid = result["id"]
        hub = _get_or_create_global_sse_hub(self.root)
        # Drain the lifecycle event we already published
        q = hub.register("test_client")
        reg, _ = _resolve_hubs(self.root, pid)
        reg.eventhub.publish_event(
            source_hub="workhub",
            event_type="task_created",
            payload={"title": "x"},
            recipients=["alpha"],
        )
        found = False
        deadline = _time.time() + 2.0
        while _time.time() < deadline:
            try:
                event = q.get(timeout=0.5)
            except Exception:
                continue
            if event.get("event_type") == "task_created":
                self.assertEqual(event.get("project_id"), pid)
                found = True
                break
        self.assertTrue(
            found, "task_created event should have reached the global hub"
        )


class TestGlobalSSEEndpointSmoke(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import (
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            _GLOBAL_SSE_HUB_CACHE,
        )
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _GLOBAL_SSE_HUB_CACHE.clear()

    def tearDown(self):
        from live_monitor_server import (
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            _GLOBAL_SSE_HUB_CACHE,
        )
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _GLOBAL_SSE_HUB_CACHE.clear()

    def test_global_events_endpoint_streams_lifecycle_event(self):
        """``GET /api/events`` streams a ``project_created`` SSE frame when
        a project is created mid-stream.
        """
        import http.server
        from functools import partial
        from http.client import HTTPConnection
        from live_monitor_server import MonitorHandler, create_project_call

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handler = partial(
                MonitorHandler,
                directory=".",
                project_dir=None,
                workspaces_root=root,
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                received, meta, errors, rt = read_stream_1202sx(
                    port, "/api/events", 1.5, chunk=256)   # #1202sx, see above
                time.sleep(0.3)
                create_project_call(root, {"name": "via_global_sse"})
                rt.join(timeout=5.0)
                self.assertFalse(rt.is_alive(), "#1202sx: the reader outlived its own test")
                self.assertEqual(errors, [])
                self.assertEqual(meta.get("status"), 200)
                self.assertIn("text/event-stream", meta.get("content_type", ""))
                blob = b"".join(received).decode("utf-8", errors="replace")
                self.assertIn("data:", blob)
                self.assertIn("project_created", blob)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
