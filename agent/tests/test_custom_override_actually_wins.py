"""FIX #124 — a custom route the override policy favors must ACTUALLY win the match
(instagram-core-di run-43 M1, 2026-07-09 22:3x, live-reproduced).

The projector emitted POST /api/users/{id}/unfollow as a generic USER-entity CREATE
(User(**{}) → NotNull violation → global handler → 400 'integrity constraint
violated' on the HAPPY PATH), while the lane's custom_routes.py carried a correct
DELETE-from-follows handler. _custom_route_overrides_projected correctly says
custom wins for action-suffix paths — but it only FILTERS the custom router;
FastAPI matches routes in REGISTRATION order and every projected @app.<verb> is
registered before app.include_router(_custom_router), so the projected nonsense
matched first and the chain wedged 35+ min (follow 201 then unfollow 400, denied
even immediately after a successful follow). Fix: the rendered skeleton now REMOVES
from app.routes any projected route whose (method, path) is claimed by a SURVIVING
custom route before including the custom router — the policy becomes effective in
both directions. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_backend_modules(monkeypatch, tmp_path):
    """Stub the skeleton's companion modules (database/auth_dependency/models) so the
    rendered main can exec without a real DB; put tmp on sys.path for custom_routes."""
    import types
    db = types.ModuleType("database")
    class _Meta:
        def create_all(self, bind=None): pass
    class _Base:
        metadata = _Meta()
    db.Base, db.engine, db.get_db = _Base, None, (lambda: None)
    # the rendered main.py's `from database import ...` gained SessionLocal;
    # a stub without it fails as "cannot import name ... (unknown location)"
    db.SessionLocal = lambda *a, **k: None
    auth = types.ModuleType("auth_dependency")
    auth.get_current_user = lambda: {"sub": "1"}
    models = types.ModuleType("models")
    class User:  # minimal ORM-ish stand-in the projected create references
        def __init__(self, **kw): pass
    models.User = User
    models.__all__ = ["User"]
    for name, mod in (("database", db), ("auth_dependency", auth), ("models", models)):
        monkeypatch.setitem(sys.modules, name, mod)


def _render_and_exec(tmp_path):
    """Render the skeleton with a projected unfollow + a custom_routes twin, exec it,
    return the FastAPI TestClient (mirrors test_backend_integrity_handler's pattern)."""
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    src = render_skeleton_main(
        [{"method": "POST", "path": "/api/users/{id}/unfollow", "auth_required": False},
         {"method": "GET", "path": "/api/users", "auth_required": False}],
        {"users": {"columns": [{"name": "id", "type": "integer"},
                               {"name": "username", "type": "text"}]}})
    (tmp_path / "custom_routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/api/users/{id}/unfollow')\n"
        "def unfollow_user(id: int):\n"
        "    return {'item': {'status': 'unfolowed-by-custom', 'id': id}}\n",
        encoding="utf-8")
    src = src[:src.index("if __name__ ==")]
    sys.path.insert(0, str(tmp_path))
    try:
        ns = {"__name__": "generated_main"}
        exec(compile(src, "main.py", "exec"), ns)
        return ns["app"]
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("custom_routes", None)


def test_custom_action_route_wins_over_projected(tmp_path, monkeypatch):
    # neutralize DB deps: the projected handlers use Depends(get_db) but the custom
    # action route we hit never touches it.
    _stub_backend_modules(monkeypatch, tmp_path)
    app = _render_and_exec(tmp_path)
    # assert at the ROUTE-TABLE level (the global auth middleware guards /api/* HTTP
    # calls): the surviving handler for (POST, /api/users/{id}/unfollow) must be the
    # CUSTOM function, and the projected twin must be GONE.
    matches = [r for r in app.routes
               if getattr(r, "path", "") == "/api/users/{id}/unfollow"
               and "POST" in (getattr(r, "methods", None) or ())]
    # FastAPI matches in registration order: the CUSTOM handler must be FIRST (wins).
    assert matches and matches[0].endpoint.__name__ == "unfollow_user", (
        [getattr(m.endpoint, "__name__", "?") for m in matches])


def test_projected_survives_when_no_custom_twin(tmp_path, monkeypatch):
    _stub_backend_modules(monkeypatch, tmp_path)
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    src = render_skeleton_main(
        [{"method": "POST", "path": "/api/users/{id}/unfollow", "auth_required": False}],
        {"users": {"columns": [{"name": "id", "type": "integer"}]}})
    src = src[:src.index("if __name__ ==")]
    ns = {"__name__": "generated_main"}
    exec(compile(src, "main.py", "exec"), ns)           # no custom_routes on path
    paths = {getattr(r, "path", "") for r in ns["app"].routes}
    assert "/api/users/{id}/unfollow" in paths           # fallback still registered


def test_unmapped_action_projects_404_stub_not_entity_create(tmp_path, monkeypatch):
    """#124 semantic core: with NO custom handler, the projected fallback for an
    action segment that resolved to no model must be a 404 stub — never a
    parent-entity CREATE (run-43: User(**{}) on /unfollow → NotNull → 400 on the
    happy path). 404 sits in every chain expect-family; 400-on-happy-path wedges."""
    _stub_backend_modules(monkeypatch, tmp_path)
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    src = render_skeleton_main(
        [{"method": "POST", "path": "/api/users/{id}/unfollow", "auth_required": False}],
        {"users": {"columns": [{"name": "id", "type": "integer"},
                               {"name": "username", "type": "text"}]}})
    import re
    i = src.index("_projected_post_api_users_id_unfollow")
    block = src[i:i + 900]
    assert "status_code=404" in block, block[:400]
    assert "User(**valid)" not in block                    # the run-43 nonsense, gone
