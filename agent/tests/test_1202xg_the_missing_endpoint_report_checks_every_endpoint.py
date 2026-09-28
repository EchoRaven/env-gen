"""#1202xg: "the frontend calls what nobody implements" was asked against a filtered list.

`frontend_calls_without_backend_1202uv` writes an artifact a lane may act on, and its own
docstring sets the bar: "a wrong entry costs more than a missing one." The call site handed it
`endpoints`, which at that point holds `business_endpoints(registryhub.get_endpoints())` --
and `business_endpoints` exists to drop "the fixed auth/oauth/infra/spine surface", which is
exactly what a real frontend's login, logout, signup and tenant calls target.

So the detector was asked "does anything serve POST /api/auth/login?" against a list with the
auth surface removed, and answered no about a route the app serves -- the AS router is mounted
both bare and under `/api` (`include_router(_as_router, prefix="/api")`, main.py:765).

MEASURED on the two runs carrying the artifact, every reported endpoint is registered VERBATIM
-- same method, same normalised path:

    r136   GET /api/v1/tenants (kind=control), POST /api/v1/tenants, POST /api/auth/login
    r137   GET /api/v1/tenants (kind=infra),   POST /api/v1/tenants, POST /api/auth/logout,
           POST /api/auth/signup

7 of 7. A 100% false-positive rate. Replayed with the full registry: 0 and 0, and no new entry
appears, so the fix removes the false ones without hiding a true one.

#1202h beside it is unaffected -- it reads the backend source and reports lane routes that are
served but never registered; its two artifacts hold only `custom_routes.py` paths.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.lifecycle import business_endpoints  # noqa: E402
from multi_agent.runtime.scaffolder import (  # noqa: E402
    frontend_calls_without_backend_1202uv,
)

_SCAFFOLDER = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                           "runtime", "scaffolder.py")

_API_JS = (
    "export async function login(b){ return request('/api/auth/login', {method:'POST'}); }\n"
    "export async function listVideos(){ return request('/api/videos'); }\n"
)


def _app(tmp_path):
    src = tmp_path / "app" / "frontend" / "src" / "services"
    src.mkdir(parents=True)
    (src / "api.js").write_text(_API_JS, encoding="utf-8")
    return tmp_path


_REGISTRY = {
    "e1": {"method": "POST", "path": "/api/auth/login", "kind": "auth"},
    "e2": {"method": "GET", "path": "/api/videos"},
    "_meta": {"version": 3},
}


def test_the_auth_endpoint_is_not_reported_when_the_whole_registry_is_checked(tmp_path):
    """★ The defect, in miniature."""
    full = [e for e in _REGISTRY.values()
            if isinstance(e, dict) and str(e.get("path") or "").strip()]
    assert frontend_calls_without_backend_1202uv(_app(tmp_path), full) == []


def test_the_business_only_list_is_what_produced_the_false_positive(tmp_path):
    """★ Pins the cause, so a future reader sees why the argument matters rather than
    trusting a comment. If `business_endpoints` ever stops dropping the auth surface this
    fails, and the ticket's reasoning needs revisiting."""
    biz = business_endpoints(_REGISTRY)
    assert not any(str(e.get("path")) == "/api/auth/login" for e in biz), (
        "business_endpoints no longer drops the auth surface; #1202xg's premise has changed")
    got = frontend_calls_without_backend_1202uv(_app(tmp_path), biz)
    assert ("POST", "/api/auth/login") in got or "POST /api/auth/login" in [
        g if isinstance(g, str) else "%s %s" % g for g in got], got


def test_a_genuinely_absent_endpoint_is_still_reported(tmp_path):
    """★ The fix must not buy silence. #1202uv exists for r135's Like button."""
    src = tmp_path / "app" / "frontend" / "src" / "services"
    src.mkdir(parents=True)
    (src / "api.js").write_text(
        "export async function like(id){ return request(`/api/videos/${id}/like`, "
        "{method:'POST'}); }\n", encoding="utf-8")
    full = [e for e in _REGISTRY.values()
            if isinstance(e, dict) and str(e.get("path") or "").strip()]
    got = frontend_calls_without_backend_1202uv(tmp_path, full)
    assert got, "a call nothing serves is no longer reported"


def test_the_call_site_passes_the_unfiltered_registry():
    """★ Caught by mutation in every sibling ticket this session: the helper can be right
    while its only caller hands it the wrong argument."""
    with open(_SCAFFOLDER, encoding="utf-8") as _fh:      # #1202eu
        tree = ast.parse(_fh.read())
    call = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "frontend_calls_without_backend_1202uv"),
                None)
    assert call is not None, "the detector is no longer called"
    arg = ast.unparse(call.args[1])
    assert "business_endpoints" not in arg, (
        "the business-only list is back: %s" % arg)
    # ...and the list that name holds must filter on nothing but `path`. Caught by mutation:
    # asserting the NAME alone stayed green while a `kind` filter was added to its
    # construction, which is the original defect wearing a different variable.
    assign = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", "") == "_all_eps_1202xg" for t in n.targets)),
                  None)
    assert assign is not None, "_all_eps_1202xg is not built in this module"
    cond = ast.unparse(assign.value)
    for banned in ("kind", "business", "is_business", "deprecated"):
        assert banned not in cond, (
            "the list is filtered by %r, so the detector is again answering against a "
            "subset: %s" % (banned, cond))
    assert "path" in cond, cond

    assert arg == "_all_eps_1202xg", (
        "the second argument is %r; it must be the unfiltered registry list" % arg)
