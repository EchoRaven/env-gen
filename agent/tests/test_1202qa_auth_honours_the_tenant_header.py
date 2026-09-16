"""#1202qa: /auth/register and /auth/login honour the X-Tenant-Id header when the body names no
tenant. tiktok-r126's M2 test-user squad registered "into tenant B" with the header every other
route reads and got a `default`-tenant user and token (two framework-owned P0s)."""
import sys
import types
from unittest.mock import MagicMock

import pytest

from env_generator.llm_generator.multi_agent.runtime.oauth_scaffold import render_oauth_module

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class _DB:
    def __init__(self):
        self.calls = []

    def create_user(self, email, password, name="", tenant_id="default", extra=None):
        self.calls.append(("create", tenant_id))
        return {"id": 1, "email": email, "name": name, "tenant_id": tenant_id}

    def verify_user_password(self, email, password, tenant_id="default"):
        self.calls.append(("login", tenant_id))
        return {"id": 1, "email": email, "tenant_id": tenant_id}


def _client(monkeypatch):
    jm = types.ModuleType("jwt_manager")
    jm.ALGORITHM = "RS256"
    jm.JWTManager = object
    st = types.ModuleType("oauth_store")
    st.OAuthStore = object
    st.DatabaseUnavailable = type("DatabaseUnavailable", (Exception,), {})
    monkeypatch.setitem(sys.modules, "jwt_manager", jm)
    monkeypatch.setitem(sys.modules, "oauth_store", st)
    mod = types.ModuleType("oauth_routes_1202qa")
    exec(compile(render_oauth_module("oauth_routes.py"), "oauth_routes.py", "exec"), mod.__dict__)
    monkeypatch.setattr(mod, "_mint_user_token", lambda *a, **k: "tok", raising=False)
    db = _DB()
    jwt = MagicMock()
    jwt.sign_access_token.return_value = "tok"
    app = fastapi.FastAPI()
    app.include_router(mod.build_router(db, jwt))
    return TestClient(app), db


def test_register_and_login_take_the_tenant_from_the_header(monkeypatch):
    c, db = _client(monkeypatch)
    body = {"email": "a@x.io", "password": "pw"}
    c.post("/auth/register", json=body, headers={"X-Tenant-Id": "tenant_b"})
    c.post("/auth/login", json=body, headers={"X-Tenant-Id": "tenant_b"})
    assert ("create", "tenant_b") in db.calls
    assert ("login", "tenant_b") in db.calls


def test_the_body_still_wins_and_nothing_means_default(monkeypatch):
    c, db = _client(monkeypatch)
    c.post("/auth/register", json={"email": "a@x.io", "password": "pw", "tenant_id": "t_body"},
           headers={"X-Tenant-Id": "t_header"})
    c.post("/auth/login", json={"email": "a@x.io", "password": "pw"})
    assert ("create", "t_body") in db.calls
    assert ("login", "default") in db.calls
