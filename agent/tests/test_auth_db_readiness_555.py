"""#555 — auth-login 500 is a TRANSIENT DB-readiness race, not a bug: /auth/login must
answer a RETRYABLE 503 (not an uncaught 500) when Postgres is momentarily down, and the
delivery-gate readiness wait must gate on TRUE DB readiness, not just HTTP liveness.

ROOT CAUSE (netflix r105, verified): /auth/login (framework-owned oauth_routes) returns
200/401 only; the 500 was an UNCAUGHT psycopg OperationalError while Postgres was mid-
restart/reseed (verify_user_password opens a fresh psycopg.connect that races the DB).
And wait_backend_ready only probed `GET /` for status<500 — FastAPI answers HTTP while
Postgres is still coming up, so the delivery gate re-evaluated LIVE DB state too early and
killed otherwise-delivered runs.

This locks BOTH fixes:

  (A) wait_backend_ready ALSO clears a DB-touching probe (POST /auth/login, framework-owned,
      present in every app with the identity spine): it stays waiting while that probe 5xx's
      (DB down) and returns ready only once it answers non-5xx (401). Byte-identical for a
      DB-less app: a 404 (no such route) is <500 → the DB gate no-ops.

  (B) the framework-emitted oauth_store maps a psycopg connect/query OperationalError to a
      retryable `DatabaseUnavailable`, and the auth routes (login + register) map THAT to a
      503 (Retry-After) instead of a 500. The happy path is untouched.
"""
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr
from env_generator.llm_generator.multi_agent.runtime.oauth_scaffold import render_oauth_module


# ═══════════════════════════ (A) wait_backend_ready DB-readiness gate ═══════════════════════════
def _make_app(login_status):
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def _send(self, code):
            b = json.dumps({"detail": "x"}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            # HTTP liveness always answers (FastAPI is up) — regardless of DB state.
            if self.path.split("?", 1)[0].rstrip("/") in ("", "/"):
                return self._send(200)
            return self._send(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n) if n else b""
            if self.path.split("?", 1)[0].rstrip("/") == "/auth/login":
                return self._send(login_status)
            return self._send(404)

    return _H


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run_wait(tmp_path, monkeypatch, srv, timeout_s):
    """Point wait_backend_ready at the live test server (bypass docker port resolution)."""
    (tmp_path / "docker").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    port = srv.server_address[1]
    monkeypatch.setattr(vr, "_backend_host_port", lambda *a, **k: port)
    return vr.wait_backend_ready(tmp_path, timeout_s=timeout_s, gap_s=0.2)


def test_db_probe_helper_gates_on_5xx():
    """The unit: the DB probe is non-5xx-satisfied (401 ready), 5xx-blocked (DB down),
    and no-ops (404 ready) when there is no such endpoint."""
    for status, expected in [(401, True), (500, False), (503, False), (404, True)]:
        srv = _serve(_make_app(status))
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            assert vr._db_readiness_probe_ok(base) is expected, status
        finally:
            srv.shutdown(); srv.server_close()


def test_wait_backend_ready_waits_while_db_probe_5xx(tmp_path, monkeypatch):
    """GET / is 200 (HTTP live) but POST /auth/login 500s (DB down) → NOT ready: the wait
    must NOT return True on liveness alone (the exact r105 pre-fix false-ready)."""
    srv = _serve(_make_app(500))
    try:
        assert _run_wait(tmp_path, monkeypatch, srv, timeout_s=1) is False
    finally:
        srv.shutdown(); srv.server_close()


def test_wait_backend_ready_true_once_db_answers(tmp_path, monkeypatch):
    """GET / 200 AND POST /auth/login 401 (DB up, credentials rejected) → ready."""
    srv = _serve(_make_app(401))
    try:
        assert _run_wait(tmp_path, monkeypatch, srv, timeout_s=5) is True
    finally:
        srv.shutdown(); srv.server_close()


def test_wait_backend_ready_byte_identical_for_dbless_app(tmp_path, monkeypatch):
    """No /auth/login route (a DB-less app) → 404 → the DB gate no-ops → ready on liveness
    alone, exactly as before the fix."""
    srv = _serve(_make_app(404))
    try:
        assert _run_wait(tmp_path, monkeypatch, srv, timeout_s=5) is True
    finally:
        srv.shutdown(); srv.server_close()


# ═══════════════════════════ (B) oauth_store → 503, not 500 ═══════════════════════════
def _install_fake_psycopg(connect):
    pg = types.ModuleType("psycopg")

    class OperationalError(Exception):
        pass

    class Error(Exception):
        pass

    pg.OperationalError = OperationalError
    pg.Error = Error
    pg.connect = connect
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    pg.rows = rows
    sys.modules["psycopg"] = pg
    sys.modules["psycopg.rows"] = rows
    return pg


def _load_store(pg):
    ns = {"__name__": "oauth_store"}
    exec(compile(render_oauth_module("oauth_store.py"), "oauth_store.py", "exec"), ns)
    return ns


def test_store_maps_connect_operationalerror_to_databaseunavailable():
    """A connect-time OperationalError (Postgres momentarily down) → DatabaseUnavailable —
    the retryable class the route maps to 503, NOT the raw error that leaked a 500."""
    pg = _install_fake_psycopg(
        lambda *a, **k: (_ for _ in ()).throw(sys.modules["psycopg"].OperationalError("refused")))
    ns = _load_store(pg)
    store = ns["OAuthStore"]()
    DatabaseUnavailable = ns["DatabaseUnavailable"]
    with pytest.raises(DatabaseUnavailable):
        store.verify_user_password("a@b.com", "pw")
    with pytest.raises(DatabaseUnavailable):
        store.create_user("a@b.com", "pw")


def test_store_happy_path_unchanged(monkeypatch):
    """A working connection still commits + closes and returns the ordinary result (None for
    a missing user) — the 503-wrap only triggers on a connect/query error, never otherwise."""
    state = {}

    class _Cur:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class _Conn:
        def execute(self, *a, **k):
            return _Cur()

        def commit(self):
            state["committed"] = True

        def rollback(self):
            state["rolledback"] = True

        def close(self):
            state["closed"] = True

    pg = _install_fake_psycopg(lambda *a, **k: _Conn())
    ns = _load_store(pg)
    store = ns["OAuthStore"]()
    assert store.verify_user_password("x@y.com", "pw") is None   # no row → None, no raise
    assert state.get("committed") and state.get("closed")


def test_auth_routes_map_databaseunavailable_to_503():
    """The framework auth routes import DatabaseUnavailable and return a 503 (not 500/409)
    on the DB-down path, for BOTH login and register (verify_user_password + create_user)."""
    routes = render_oauth_module("oauth_routes.py")
    assert "from oauth_store import OAuthStore, DatabaseUnavailable" in routes
    assert "status_code=503" in routes
    assert routes.count("except DatabaseUnavailable") >= 2, routes.count("except DatabaseUnavailable")
    # the 409 unique-violation path is preserved (register still distinguishes it from 503)
    assert "status_code=409" in routes
