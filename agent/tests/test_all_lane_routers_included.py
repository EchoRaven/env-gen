"""FIX #127 — the skeleton includes EVERY APIRouter the lane defines in
custom_routes.py, not only the one named `router` (instagram-core-di run-46 M3,
2026-07-10 06:0x, live-diagnosed).

run-46 M3 wedged on POST /api/posts/{}/repost -> 404. Live artifact: the lane DID
write a correct repost handler — but on a SECOND router (`hidden_router = APIRouter()`)
that main.py never included (the skeleton does `from custom_routes import router as
_custom_router` — only the name `router`). So the real handler was orphaned and the
projected #124 fallback (404 'action not implemented') served the route, failing the
verifier's expect [200,201] chains. (Pre-#124 the projected fallback 400'd the same
route — orphaned-router is the ROOT either way.) Include ALL APIRouter instances the
module defines, applying the same override policy to each. ENV-AGNOSTIC + LOCAL-ONLY.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub(monkeypatch):
    db = types.ModuleType("database")
    class _Meta:
        def create_all(self, bind=None): pass
    class _Base: metadata = _Meta()
    db.Base, db.engine, db.get_db = _Base, None, (lambda: None)
    # the rendered main.py's `from database import ...` grew SessionLocal;
    # a stub module missing it fails as "cannot import name ... (unknown
    # location)" — the location is unknown because the stub has no __file__.
    db.SessionLocal = lambda *a, **k: None
    auth = types.ModuleType("auth_dependency"); auth.get_current_user = lambda: {"sub": "1"}
    models = types.ModuleType("models")
    class Post:
        def __init__(self, **kw): pass
    models.Post = Post; models.__all__ = ["Post"]
    for n, m in (("database", db), ("auth_dependency", auth), ("models", models)):
        monkeypatch.setitem(sys.modules, n, m)


_CUSTOM_TWO_ROUTERS = '''\
from fastapi import APIRouter
router = APIRouter()
hidden_router = APIRouter()

@router.get("/api/health-x")
def hx(): return {"ok": True}

@hidden_router.post("/api/posts/{id}/repost")
def repost_post(id: int):
    return {"item": {"status": "reposted", "id": id}}
'''


def test_second_router_repost_is_included(tmp_path, monkeypatch):
    _stub(monkeypatch)
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    src = render_skeleton_main(
        [{"method": "POST", "path": "/api/posts/{id}/repost", "auth_required": False}],
        {"posts": {"columns": [{"name": "id", "type": "integer"}]}})
    (tmp_path / "custom_routes.py").write_text(_CUSTOM_TWO_ROUTERS, encoding="utf-8")
    src = src[:src.index("if __name__ ==")]
    sys.path.insert(0, str(tmp_path))
    try:
        ns = {"__name__": "generated_main"}
        exec(compile(src, "main.py", "exec"), ns)
        app = ns["app"]
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("custom_routes", None)
    reposts = [r for r in app.routes
               if getattr(r, "path", "") == "/api/posts/{id}/repost"
               and "POST" in (getattr(r, "methods", None) or ())]
    # the lane's hidden_router repost must WIN (registered first, custom override policy)
    assert reposts and reposts[0].endpoint.__name__ == "repost_post", (
        [getattr(x.endpoint, "__name__", "?") for x in reposts])


def test_template_imports_module_not_only_router():
    from multi_agent.runtime import backend_skeleton as bs
    inc = bs._CUSTOM_ROUTES_INCLUDE
    # must discover ALL APIRouter instances, not just `import router`
    assert "APIRouter" in inc and "import custom_routes" in inc
