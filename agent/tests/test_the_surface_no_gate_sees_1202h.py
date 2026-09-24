r"""#1202h: a route the app serves but never registered is ungated by construction.

Every delivery gate evaluates the REGISTRY. A route that exists only in the code is therefore
never checked for auth, never checked for owner scoping, never counted by coverage — and it
still ships.

Measured across all 114 generated backends: 8 such routes in 7 environments, every one of them
delivered.

    POST /api/admin/fix        googlemaps    an admin action
    GET  /api/debug_routes2    tiktok        debugging scaffolding
    GET  /api/test_debug       tiktok        "
    GET  /api/health2          instagram     "
    GET  /api/test_feed        instagram     "
    POST /api/posts            instagram     a real business endpoint
    GET  /api/users/following  tiktok        "
    POST /api/oauth/register   netflix       "

Five of the eight are debug or admin scaffolding a lane wrote while working and never removed.
No audit in the system could see them, because no audit reads the code for routes.

This REPORTS rather than blocks: a lane may have a good reason for an extra route, and #1166
already restores lane routes that nothing else serves. What it must not be is invisible.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import unregistered_routes_1202h  # noqa: E402

_DECLARED = [{"method": "GET", "path": "/api/titles"},
             {"method": "GET", "path": "/api/titles/{id}"}]


def _backend(tmp_path, src):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(src, encoding="utf-8")
    return be


def test_a_debug_route_nobody_declared_is_reported(tmp_path):
    be = _backend(tmp_path, '@router.get("/api/debug_routes2")\ndef dbg(): return {}\n')
    out = unregistered_routes_1202h(be, _DECLARED)
    assert out and "/api/debug_routes2" in out[0]


def test_a_declared_route_is_not_reported(tmp_path):
    be = _backend(tmp_path, '@router.get("/api/titles")\ndef t(): return {}\n')
    assert unregistered_routes_1202h(be, _DECLARED) == []


def test_a_parameterised_declaration_matches_its_route(tmp_path):
    """`/api/titles/{id}` declared, `/api/titles/{title_id}` served — same endpoint."""
    be = _backend(tmp_path, '@router.get("/api/titles/{title_id}")\ndef t(x): return {}\n')
    assert unregistered_routes_1202h(be, _DECLARED) == []


def test_the_framework_owned_surface_is_not_reported(tmp_path):
    """The control plane and the auth entry points are the framework's, not the contract's."""
    be = _backend(tmp_path,
                  '@router.get("/api/v1/tenants")\ndef a(): return {}\n'
                  '@router.post("/api/auth/login")\ndef b(): return {}\n'
                  '@router.get("/oauth/jwks")\ndef c(): return {}\n')
    assert unregistered_routes_1202h(be, _DECLARED) == []


def test_a_non_api_route_is_not_reported(tmp_path):
    be = _backend(tmp_path, '@app.get("/health")\ndef h(): return {}\n')
    assert unregistered_routes_1202h(be, _DECLARED) == []


def test_a_missing_or_broken_backend_never_raises(tmp_path):
    assert unregistered_routes_1202h(tmp_path / "nope", _DECLARED) == []
    assert unregistered_routes_1202h(None, None) == []
    assert unregistered_routes_1202h(_backend(tmp_path, "not python ((("), "nonsense") == []


def test_it_is_wired_where_the_backend_is_written():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
           ).read_text(encoding="utf-8")
    assert "unregistered_routes_1202h" in src
    at = src.index("unregistered_routes_1202h")
    # #1201: its own try, so a failure here cannot switch off anything else.
    enclosing = src.rindex("try:", 0, at)
    assert "heal_pipeline" not in src[enclosing:at]
