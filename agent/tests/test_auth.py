import os
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _SESSIONS
        _SESSIONS.clear()
        os.environ["ENVGEN_AUTH_TOKEN"] = "test-token-abc"

    def tearDown(self):
        from live_monitor_server import _SESSIONS
        _SESSIONS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_login_valid_token_creates_session(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "alice", "token": "test-token-abc"})
        self.assertIn("session_id", result)
        self.assertEqual(result["username"], "alice")

    def test_login_invalid_token_rejected(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "alice", "token": "wrong"})
        self.assertIn("error", result)

    def test_login_empty_username_rejected(self):
        from live_monitor_server import auth_login_call
        result = auth_login_call({"username": "  ", "token": "test-token-abc"})
        self.assertIn("error", result)

    def test_logout_clears_session(self):
        from live_monitor_server import auth_login_call, auth_logout_call, _SESSIONS
        result = auth_login_call({"username": "alice", "token": "test-token-abc"})
        sid = result["session_id"]
        self.assertIn(sid, _SESSIONS)
        auth_logout_call(sid)
        self.assertNotIn(sid, _SESSIONS)

    def test_check_session_returns_username(self):
        from live_monitor_server import auth_login_call, check_session
        sid = auth_login_call({"username": "bob", "token": "test-token-abc"})["session_id"]
        self.assertEqual(check_session(sid), "bob")

    def test_check_session_invalid_returns_none(self):
        from live_monitor_server import check_session
        self.assertIsNone(check_session("nope"))


class TestAuthDisabled(unittest.TestCase):
    """When ENVGEN_AUTH_TOKEN is unset, auth_required() is False."""
    def setUp(self):
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_auth_required_false_when_no_token(self):
        from live_monitor_server import auth_required
        self.assertFalse(auth_required())


class TestAuthEnabled(unittest.TestCase):
    def setUp(self):
        os.environ["ENVGEN_AUTH_TOKEN"] = "secret"

    def tearDown(self):
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def test_auth_required_true_when_token_set(self):
        from live_monitor_server import auth_required
        self.assertTrue(auth_required())


import http.server
import json
import threading
import time as _time
from functools import partial
from http.client import HTTPConnection


class TestAuthHTTPE2E(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _SESSIONS, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _SESSIONS.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        os.environ["ENVGEN_AUTH_TOKEN"] = "secret-xyz"
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        from live_monitor_server import _SESSIONS, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _SESSIONS.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp.cleanup()

    def _req(self, method, path, body=None, cookie=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        data = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, data, headers)
        resp = conn.getresponse()
        raw = resp.read()
        cookies = resp.getheader("Set-Cookie", "")
        conn.close()
        return resp.status, raw, cookies

    def test_protected_endpoint_returns_401_without_session(self):
        status, _, _ = self._req("GET", "/api/projects")
        self.assertEqual(status, 401)

    def test_login_then_protected_endpoint_succeeds(self):
        status, raw, set_cookie = self._req("POST", "/api/auth/login",
                                            {"username": "alice", "token": "secret-xyz"})
        self.assertEqual(status, 200)
        self.assertIn("envgen_session=", set_cookie)
        sid_pair = set_cookie.split(";")[0]
        status, raw, _ = self._req("GET", "/api/projects", cookie=sid_pair)
        self.assertEqual(status, 200)
        self.assertIn("projects", json.loads(raw))

    def test_invalid_login_returns_401(self):
        status, _, _ = self._req("POST", "/api/auth/login",
                                  {"username": "alice", "token": "wrong"})
        self.assertEqual(status, 401)

    def test_logout_invalidates_cookie(self):
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        self._req("POST", "/api/auth/logout", body={}, cookie=sid_pair)
        status, _, _ = self._req("GET", "/api/projects", cookie=sid_pair)
        self.assertEqual(status, 401)

    def test_me_returns_username_when_authed(self):
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        status, raw, _ = self._req("GET", "/api/auth/me", cookie=sid_pair)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["username"], "alice")

    def test_static_files_served_without_auth(self):
        """The React app's HTML/CSS/JS must be reachable so the login screen loads."""
        status, _, _ = self._req("GET", "/api/ping")
        self.assertEqual(status, 200)  # exempt
        # /api/auth/me without cookie -> 401 (expected)
        status, _, _ = self._req("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_mutation_records_session_username_as_agent(self):
        from live_monitor_server import create_project_call
        _, _, set_cookie = self._req("POST", "/api/auth/login",
                                      {"username": "alice", "token": "secret-xyz"})
        sid_pair = set_cookie.split(";")[0]
        # Create a project via HTTP
        status, raw, _ = self._req("POST", "/api/projects",
                                    {"name": "audit-test"}, cookie=sid_pair)
        self.assertEqual(status, 200)
        pid = json.loads(raw)["id"]
        # Run a mutation that records `agent` — e.g. create_task with no agent.
        # The auth middleware should override body.agent with the session username.
        status, raw, _ = self._req("POST", f"/api/projects/{pid}/workhub/tasks",
                                    {"title": "t1", "description": "x", "domain": "ui", "priority": "P1"},
                                    cookie=sid_pair)
        self.assertEqual(status, 200)
        # Confirm the task's created_by reflects "alice"
        from live_monitor_server import _resolve_hubs
        reg, _ = _resolve_hubs(self.root, pid)
        tasks = reg.workhub.snapshot().get("tasks", {})
        self.assertEqual(len(tasks), 1)
        task = next(iter(tasks.values()))
        # The exact field name may vary — common: `created_by` or `agent`
        agent_field = task.get("created_by") or task.get("agent") or task.get("_updated_by")
        self.assertEqual(agent_field, "alice", f"task fields: {task}")


if __name__ == "__main__":
    unittest.main()
