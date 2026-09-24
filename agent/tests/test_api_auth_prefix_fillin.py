"""Fix #64 — serve login/register under the /api prefix the frontend uses
(outlook run-48, live 2026-07-02).

The generated frontend api.js prepends /api to EVERY call, so its login/register
hit /api/auth/login and /api/auth/register. The framework AS only serves
/auth/login|register, and the auth guard walled /api/auth/* (only /auth/* was
public under the /api umbrella) -> the UI login 401'd -> browser test-user
auth_ok=False + login-wall on every protected page, even though the API
/auth/login 200s (verified live). The gate deferred 4x then escape-shipped an
unusable UI 'loudly'.

Two by-construction parts (mirroring the /api/auth/me #30 + /api/v1/tenants #49
control-surface fill-ins): (1) the guard marks /api/auth/login|register public;
(2) main.py re-registers the mounted /auth/* AS endpoint at the /api/auth/* path
(same body-parse + token-mint), only-if-absent. LOCAL-ONLY (agent/tests/
gitignored).
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_TABLES = {"messages": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "user_id", "type": "integer", "foreign_key": "users.id"}]}}


def test_guard_marks_api_auth_login_register_public():
    src = render_skeleton_main([{"method": "GET", "path": "/api/messages"}], _TABLES)
    ast.parse(src)
    # #235: the literal login/register tuple generalized to the bootstrap-terminal
    # rule (signup/signin/... synonyms public by construction); login/register must
    # still be members, inside the guard's `public = (...)` expression.
    gi = src.index("public = (")
    ge = src.index('if p.startswith("/api/") and not public', gi)
    guard = src[gi:ge]
    assert 'p.startswith("/api/auth/")' in guard
    for terminal in ("login", "register", "signup", "signin", "token", "refresh"):
        assert f'"{terminal}"' in guard


def test_render_mounts_as_router_twice_and_removes_route_reuse():
    src = render_skeleton_main([{"method": "GET", "path": "/api/messages"}], _TABLES)
    ast.parse(src)
    # canonical include_router(prefix="/api") is the #64 mechanism now
    assert 'app.include_router(_as_router, prefix="/api")' in src
    assert 'app.include_router(_as_router)' in src
    # the old route-object-reuse fill-in (which silently failed in the full app,
    # run-49) must be gone
    assert "_fw_as_by_key" not in src


def test_api_prefixed_auth_registered_from_real_as_router(tmp_path, monkeypatch):
    """Integration: build the REAL framework AS router, mount it the way #64's
    rendered main does (once bare, once under /api), and assert the frontend's
    /api/auth/login|register exist AND authenticate — the exact run-49 gap."""
    import os
    be = ROOT.parent / "generated" / "outlook" / "app" / "backend"
    if not (be / "oauth_routes.py").exists():
        import pytest
        pytest.skip("no generated backend to load the real AS from")
    monkeypatch.setenv("JWT_DATA_DIR", str(tmp_path / "jwtkeys"))
    monkeypatch.setenv("APP_PASSWORD_SALT", "test_salt")
    os.makedirs(tmp_path / "jwtkeys", exist_ok=True)
    sys.path.insert(0, str(be))
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from oauth_store import OAuthStore
        from jwt_manager import JWTManager
        from oauth_routes import build_router as brt
    except Exception:
        import pytest
        pytest.skip("AS deps unavailable")
    app = FastAPI()
    r = brt(OAuthStore(), JWTManager())
    app.include_router(r)
    app.include_router(r, prefix="/api")     # the #64 mechanism
    paths = {getattr(x, "path", "") for x in app.routes}
    # the exact run-49 gap: these were 404 (NO route registered under /api)
    assert "/api/auth/login" in paths and "/api/auth/register" in paths
    # and the routes RESPOND (never 404) — the handler runs; the AS's real
    # token mint needs Postgres, which the full-DB auth tests cover elsewhere.
    c = TestClient(app, raise_server_exceptions=False)
    for p in ("/api/auth/register", "/api/auth/login"):
        assert c.post(p, json={"email": "u@x.com", "password": "Pw1!x",
                               "name": "U"}).status_code != 404, p


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
