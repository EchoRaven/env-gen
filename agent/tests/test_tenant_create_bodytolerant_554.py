"""#554 — tenant-create must NEVER 400 on a body that omits the server-generated PK.

ROOT CAUSE (netflix r58 / task#47, verified): the tenant control plane is a FIXED
framework contract (control_plane.py) that pins method+path but NOT body shape. The old
prompt template told lanes the CLIENT supplies the tenant PK (`body.get("id") or
body.get("tenant_id")`), so a lane's `create_tenant` 400s when the verifier authors the
step the natural way — `POST /api/v1/tenants {"name": ...}` (or body-less). That 400 →
`business_chain_failing` blocked delivery on an otherwise fully-green app. The Tenant PK
is server-generatable (a text/uuid id defaults to a uuid), so a create that omits the id
must GENERATE one, never 400.

This locks BOTH complementary fixes:

  (A) the FRAMEWORK EMITS a body-tolerant create_tenant fill-in in the generated main.py
      (backend_skeleton `_fw_tenant_create`): accepts {name} OR {id}/{tenant_id}, generates
      the PK when omitted, persists, returns {id, name}; registered POST /api/v1/tenants
      only-if-absent (a lane-authored create still wins).

  (B) chain_executor.normalize_steps setdefaults a DETERMINISTIC id (from the step index)
      onto a body-less/id-less control-plane tenant POST AND saves the created id as
      `tenantId`, so the later `${tenantId}` steps (init-tenant / DELETE) resolve — they
      never did before (nothing saved it). Byte-identical when N/A (non-tenant apps; a
      create that already carries an id keeps it).
"""
import json
import re
import sys
import textwrap
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main
from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    normalize_steps, execute_chain, _CONTROL_PLANE_TENANT_CREATE)


# ─────────── fixtures: a fake ORM + Session for the extracted fill-in handler ───────────
class _FakeCol:
    def __init__(self, name):
        self.name = name


class _FakeTable:
    columns = [_FakeCol("id"), _FakeCol("name"), _FakeCol("status")]


class _FakeTenant:
    __table__ = _FakeTable()

    def __init__(self, **kw):
        self.id = kw.get("id")
        self.name = kw.get("name")
        self.status = kw.get("status")


class _FakeDB:
    def __init__(self):
        self.rows = {}
        self._pending = None

    def get(self, _cls, pk):
        return self.rows.get(pk)

    def add(self, obj):
        self._pending = obj

    def commit(self):
        if self._pending is not None:
            self.rows[self._pending.id] = self._pending
            self._pending = None

    def rollback(self):
        self._pending = None

    def refresh(self, _obj):
        pass


def _extract_fill_in():
    """Pull the framework's `_fw_tenant_create` out of the generated-main.py source and
    exec it with a fake ORM/Session so its BEHAVIOR (not just its text) is under test."""
    src = bs._CUSTOM_ROUTES_INCLUDE
    m = re.search(r"\n    def _fw_tenant_create\(.*?(?=\n    _fw_present_mp =)", src, re.S)
    assert m, "the _fw_tenant_create fill-in is missing from the generated main.py"
    block = textwrap.dedent(m.group(0))
    fake_models = types.ModuleType("models")
    fake_models.Tenant = _FakeTenant
    sys.modules["models"] = fake_models
    ns = {"Depends": lambda _x: None, "get_db": None, "_fw_dbg": lambda *a, **k: None}
    exec(compile(block, "fill_in.py", "exec"), ns)
    return ns["_fw_tenant_create"]


# ─────────────────────────── (A) framework EMITS a body-tolerant create ───────────────────────────
def test_create_tenant_name_only_generates_id_and_persists():
    """{name}-only (no id) → a generated id, persisted, returned as {id, name}. NEVER 400."""
    fn = _extract_fill_in()
    db = _FakeDB()
    out = fn(body={"name": "Acme Inc"}, db=db)
    assert out["name"] == "Acme Inc"
    assert out["id"], "a create that omits the PK must GENERATE one, not 400/return null"
    assert out["id"] in db.rows, "the tenant must be persisted"


def test_create_tenant_bodyless_generates_uuid_id():
    """A body-less create (verifier authored the step from just an endpoint id) → uuid id."""
    fn = _extract_fill_in()
    db = _FakeDB()
    out = fn(body=None, db=db)
    assert out["id"] and out["id"] in db.rows


def test_create_tenant_honours_client_supplied_id_and_is_idempotent():
    fn = _extract_fill_in()
    db = _FakeDB()
    first = fn(body={"id": "acme", "name": "Acme"}, db=db)
    assert first["id"] == "acme"
    again = fn(body={"id": "acme", "name": "Acme"}, db=db)   # idempotent get-or-create
    assert again["id"] == "acme"
    assert len(db.rows) == 1


def test_create_tenant_accepts_tenant_id_alias():
    fn = _extract_fill_in()
    db = _FakeDB()
    out = fn(body={"tenant_id": "beta"}, db=db)
    assert out["id"] == "beta" and "beta" in db.rows


def test_generated_main_registers_create_only_if_absent():
    """The framework main.py registers the POST create fill-in method-aware + only-if-absent
    (status 201), so a lane-authored POST /api/v1/tenants still wins (fill-in only)."""
    eps = [{"method": "GET", "path": "/api/posts", "status": "implemented"},
           {"method": "POST", "path": "/api/posts", "status": "implemented"}]
    tables = {"posts": {"name": "posts", "columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "caption", "type": "text"}]}}
    src = render_skeleton_main(eps, tables)
    assert "_fw_tenant_create" in src
    assert 'app.post("/api/v1/tenants", status_code=201)' in src
    assert '("POST", "/api/v1/tenants") not in _fw_present_mp' in src


# ─────────────────────────── (B) normalize_steps id-default + save ───────────────────────────
def test_control_plane_tenant_create_set_is_derived_from_the_fixed_surface():
    assert "/api/v1/tenants" in _CONTROL_PLANE_TENANT_CREATE


def test_normalize_defaults_id_and_saves_tenantId_for_bodyless_tenant_post():
    norm, errs = normalize_steps([
        {"method": "POST", "path": "/api/v1/tenants", "body": {"name": "Acme"},
         "expect": [200, 201]},
        {"method": "DELETE", "path": "/api/v1/tenants/${tenantId}", "expect": [200, 204]},
    ])
    assert errs == []
    create = next(s for s in norm if s["method"] == "POST"
                  and str(s["path"]).rstrip("/") == "/api/v1/tenants")
    assert create["body"].get("id") == "tenant_0", create["body"]      # deterministic (index 0)
    assert create["save"].get("tenantId") == "id", create["save"]      # captures the created id


def test_normalize_does_not_clobber_a_client_supplied_id():
    norm, _ = normalize_steps(
        [{"method": "POST", "path": "/api/v1/tenants", "body": {"id": "acme", "name": "A"}}])
    create = next(s for s in norm if str(s["path"]).rstrip("/") == "/api/v1/tenants")
    assert create["body"]["id"] == "acme"                              # setdefault never clobbers
    assert create["save"].get("tenantId") == "id"


def test_normalize_byte_identical_for_non_tenant_post():
    """A normal business POST must be UNTOUCHED — no tenantId save injected."""
    norm, _ = normalize_steps(
        [{"method": "POST", "path": "/api/posts", "body": {"caption": "x"}, "auth": "token"}])
    post = next(s for s in norm if s["path"] == "/api/posts")
    assert "tenantId" not in (post.get("save") or {})


# ─────────────────────────── (B) end-to-end: ${tenantId} resolves ───────────────────────────
class _TenantAppHandler(BaseHTTPRequestHandler):
    """A minimal control-plane app: register mints a token; POST /api/v1/tenants persists
    the (server- or client-supplied) id and echoes {id,name}; DELETE 200 only if that exact
    id was created — so a chain whose ${tenantId} did NOT resolve 404s and FAILS honestly."""
    store = set()

    def log_message(self, *_a):
        return

    def _send(self, code, payload):
        b = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def do_POST(self):
        body = self._body()
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/auth/register", "/auth/login"):
            return self._send(200, {"access_token": "tok-abc", "user": {"id": 1}})
        if path == "/api/v1/admin/init-tenant":
            return self._send(200, {"ok": True})
        if path == "/api/v1/tenants":
            tid = str(body.get("id") or body.get("tenant_id") or "gen-id")
            type(self).store.add(tid)
            return self._send(201, {"id": tid, "name": body.get("name")})
        return self._send(404, {"detail": "Not Found"})

    def do_DELETE(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        tid = path.rsplit("/", 1)[-1]
        # An UNRESOLVED "${tenantId}" (or any id never created) → 404 → the chain FAILS.
        if path.startswith("/api/v1/tenants/") and tid in type(self).store:
            return self._send(200, {"ok": True})
        return self._send(404, {"detail": "tenant not found"})


@pytest.fixture()
def tenant_app():
    _TenantAppHandler.store = set()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _TenantAppHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_bodyless_tenant_create_then_delete_placeholder_resolves(tenant_app):
    """The full round-trip the bug broke: a verifier authors `POST /api/v1/tenants {name}`
    then `DELETE /api/v1/tenants/${tenantId}`. After normalize+execute, the created id is
    saved as tenantId and the DELETE placeholder resolves → the chain passes (broken == [])."""
    norm, _ = normalize_steps([
        {"method": "POST", "path": "/api/v1/tenants", "body": {"name": "Acme"},
         "expect": [200, 201]},
        {"method": "DELETE", "path": "/api/v1/tenants/${tenantId}", "expect": [200, 204]},
    ])
    res = execute_chain(tenant_app, {"name": "tenant_lifecycle", "steps": norm}, endpoints=[])
    assert res["broken"] == [], f"${{tenantId}} did not resolve / create-delete broke: {res['broken']}"
