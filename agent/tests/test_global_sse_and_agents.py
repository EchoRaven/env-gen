"""Cutover 32 tests: global SSE hub + agent list service.

Plan: docs/superpowers/plans/2026-05-26-cutover-32-global-sse-agents.md

The plan's reference test file specifies a module-level ``_GLOBAL_SSE_HUB``
singleton. The actual implementation chose a workspaces-root-scoped cache
(``_GLOBAL_SSE_HUB_CACHE`` + ``_get_or_create_global_sse_hub``) so multiple
workspaces don't fight for one fan-out. The tests below exercise the same
behaviours described in the plan, adapted to the per-workspace API.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class TestGlobalSSEHub(unittest.TestCase):
    """Lifecycle helpers must publish onto the workspaces-root global hub."""

    def setUp(self):
        from live_monitor_server import (
            _GLOBAL_SSE_HUB_CACHE,
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
        )
        _GLOBAL_SSE_HUB_CACHE.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import (
            _GLOBAL_SSE_HUB_CACHE,
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
        )
        _GLOBAL_SSE_HUB_CACHE.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_create_project_broadcasts_global_event(self):
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            create_project_call,
        )
        hub = _get_or_create_global_sse_hub(self.root)
        q = hub.register("test_client")
        try:
            result = create_project_call(self.root, {"name": "demo"})
            self.assertNotIn("error", result, result)
            event = q.get(timeout=2.0)
            self.assertEqual(event.get("event_type"), "project_created")
            self.assertEqual(event.get("project_id"), result["id"])
        finally:
            hub.unregister("test_client")

    def test_set_project_status_broadcasts_global_event(self):
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            create_project_call,
            set_project_status_call,
        )
        result = create_project_call(self.root, {"name": "demo"})
        hub = _get_or_create_global_sse_hub(self.root)
        q = hub.register("test_client")
        try:
            set_project_status_call(self.root, result["id"], {"status": "paused"})
            # Drain until we see the status change (initial create event may
            # still be in the queue if registration happened before broadcast).
            found = False
            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    event = q.get(timeout=0.5)
                except Exception:
                    continue
                if event.get("event_type") == "project_status_changed":
                    self.assertEqual(event.get("payload", {}).get("status"), "paused")
                    found = True
                    break
            self.assertTrue(found, "project_status_changed event expected")
        finally:
            hub.unregister("test_client")

    def test_delete_project_broadcasts_global_event(self):
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            create_project_call,
            delete_project_call,
        )
        result = create_project_call(self.root, {"name": "demo"})
        hub = _get_or_create_global_sse_hub(self.root)
        q = hub.register("test_client")
        try:
            delete_project_call(self.root, result["id"], {"confirm": True})
            found = False
            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    event = q.get(timeout=0.5)
                except Exception:
                    continue
                if event.get("event_type") == "project_deleted":
                    self.assertEqual(event.get("project_id"), result["id"])
                    found = True
                    break
            self.assertTrue(found, "project_deleted event expected")
        finally:
            hub.unregister("test_client")

    def test_per_project_event_forwards_to_global(self):
        """Any EventHub publish on a project should also reach the global hub."""
        from live_monitor_server import (
            _get_or_create_global_sse_hub,
            create_project_call,
            _resolve_hubs,
        )
        result = create_project_call(self.root, {"name": "demo"})
        pid = result["id"]
        hub = _get_or_create_global_sse_hub(self.root)
        q = hub.register("test_client")
        try:
            # _resolve_hubs attaches the forwarder bridge on first cache fill.
            reg, _ = _resolve_hubs(self.root, pid)
            reg.eventhub.publish_event(
                source_hub="workhub",
                event_type="task_created",
                payload={"title": "x"},
                recipients=["alpha"],
            )
            found = False
            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    event = q.get(timeout=0.5)
                except Exception:
                    continue
                if event.get("event_type") == "task_created":
                    self.assertEqual(event.get("project_id"), pid)
                    found = True
                    break
            self.assertTrue(found, "task_created should have reached the global hub")
        finally:
            hub.unregister("test_client")


class TestGlobalEventsEndpoint(unittest.TestCase):
    """HTTP smoke: ``GET /api/events`` streams broadcasts as SSE."""

    def test_global_events_endpoint_streams(self):
        import http.server
        from functools import partial
        from http.client import HTTPConnection
        from live_monitor_server import (
            MonitorHandler,
            _GLOBAL_SSE_HUB_CACHE,
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            create_project_call,
        )

        _GLOBAL_SSE_HUB_CACHE.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()

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
                received: list = []

                def reader():
                    conn = HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request("GET", "/api/events")
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 200)
                    self.assertIn(
                        "text/event-stream",
                        resp.getheader("Content-Type", ""),
                    )
                    deadline = time.time() + 1.5
                    while time.time() < deadline:
                        try:
                            chunk = resp.fp.read1(256)
                        except Exception:
                            break
                        if not chunk:
                            break
                        received.append(chunk)
                    conn.close()

                rt = threading.Thread(target=reader, daemon=True)
                rt.start()
                time.sleep(0.3)
                create_project_call(root, {"name": "via_global_sse"})
                rt.join(timeout=2.0)
                blob = b"".join(received).decode("utf-8", errors="replace")
                self.assertIn("data:", blob)
                self.assertIn("project_created", blob)
            finally:
                server.shutdown()
                server.server_close()


class TestAgentsEndpoint(unittest.TestCase):
    """``_load_agent_profiles`` + ``build_agents_list`` cover the chat panel."""

    def test_load_agent_profiles_returns_known_agents(self):
        from live_monitor_server import _load_agent_profiles
        profiles = _load_agent_profiles()
        self.assertGreater(len(profiles), 5)
        sample = profiles[0]
        self.assertIn("id", sample)
        self.assertIn("name", sample)

    def test_load_agent_profiles_includes_orchestrator(self):
        from live_monitor_server import _load_agent_profiles
        profiles = _load_agent_profiles()
        ids = {p["id"] for p in profiles}
        self.assertIn("orchestrator", ids)

    def test_agents_endpoint_returns_payload(self):
        from live_monitor_server import (
            _GLOBAL_SSE_HUB_CACHE,
            _HUB_REGISTRY_CACHE,
            _SSE_HUB_CACHE,
            build_agents_list,
            create_project_call,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _GLOBAL_SSE_HUB_CACHE.clear()
            _HUB_REGISTRY_CACHE.clear()
            _SSE_HUB_CACHE.clear()
            result = create_project_call(root, {"name": "demo"})
            payload = build_agents_list(root, result["id"])
            self.assertIn("agents", payload)
            self.assertGreater(len(payload["agents"]), 5)

    def test_agents_endpoint_unknown_project_returns_error(self):
        from live_monitor_server import build_agents_list
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_agents_list(Path(tmp), "nope")
            self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
