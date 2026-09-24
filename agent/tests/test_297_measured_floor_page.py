"""#297 — no-reference GET floor is a measured, structured (non-fallback) page when a palette exists."""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import _project_page_component  # noqa: E402
from multi_agent.runtime.frontend_audit import _is_generic_fallback_page  # noqa: E402
from multi_agent.runtime.frontend_page_projector import _STRUCTURED_MARKER, _PAGE_MARKER  # noqa: E402

_PAGE = {"route": "/explore", "component": "ExplorePage",
         "apis_used": ["GET /api/explore"], "name": "explore"}
_DESIGN = {"design_system": {"theme": {"default": "dark"}, "palette": {
    "bg": "#000000", "surface": "#121212", "text": "#ffffff",
    "text_2": "rgba(255,255,255,0.75)", "accent_red": "#EA445A", "border": "#2a2a2a"}}}


def test_measured_floor_is_structured_not_fallback():
    out = _project_page_component("ExplorePage", _PAGE,
                                  nav_routes=[("Home", "/"), ("Explore", "/explore")],
                                  design=_DESIGN)
    assert _STRUCTURED_MARKER in out                 # stamped structured
    assert 'data-projected="ref"' in out             # detector-exempt attr
    assert ("style={{ backgroundColor: '#000000'" in out
            or 'style={{ backgroundColor: "#000000"' in out)  # measured canvas paint
    assert 'data-fallback="1"' not in out            # not a fallback
    assert _PAGE_MARKER not in out                    # not marked fallback
    assert "/api/explore" in out                      # still fetches its OWN endpoint
    assert not _is_generic_fallback_page(out)         # gate treats it as BUILT


def test_no_palette_keeps_data_fallback():
    out = _project_page_component("ExplorePage", _PAGE, nav_routes=[], design={})
    assert 'data-fallback="1"' in out                 # unchanged behavior
    assert _is_generic_fallback_page(out)             # still a fallback


def test_write_only_page_unchanged_by_this_branch():
    page = {"route": "/settings", "component": "SettingsPage",
            "apis_used": ["PUT /api/settings"], "name": "settings"}
    out = _project_page_component("SettingsPage", page, nav_routes=[], design=_DESIGN)
    assert ("<form" in out.lower() or "onsubmit" in out.lower() or "handleSubmit" in out)
    assert _STRUCTURED_MARKER not in out              # write-only path untouched


def test_auth_page_unchanged():
    page = {"route": "/login", "component": "LoginPage",
            "apis_used": ["POST /auth/login"], "name": "login"}
    out = _project_page_component("LoginPage", page, nav_routes=[], design=_DESIGN)
    assert "password" in out.lower()                  # real login form, not the floor
    assert 'data-projected="ref"' not in out
