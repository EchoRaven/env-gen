"""#387: a ui_page kickoff-registered with an EMPTY route (netflix r12: profiles_page,
route='' component='' apis_used=[]) had its App.jsx route DERIVED from the name including
the '_page' suffix -> '/profiles-page', mismatching the canonical '/profiles' the ui_flow
gate + design expect -> '/profiles' renders BLANK -> deliverability_ui_flow_failed HARD-
blocks forever (the lane wires /profiles-page, reports M1 complete, never reconciles).
scaffold_pages_from_contract now drops a trailing 'page' token when deriving a route from
the name, so an empty-route page lands on its canonical route.
"""
import re
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    scaffold_pages_from_contract)


def _wire(ui_pages):
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True, exist_ok=True)
    scaffold_pages_from_contract(fe, ui_pages)
    app = (fe / "src" / "App.jsx")
    text = app.read_text(encoding="utf-8") if app.exists() else ""
    return set(re.findall(r'<Route\s+path=["\']([^"\']+)["\']', text))


def test_empty_route_page_gets_canonical_route():
    routes = _wire([
        {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": ["GET /api/titles"]},
        {"name": "profiles_page", "route": "", "component": "", "apis_used": ["GET /api/profiles"]},
    ])
    assert "/profiles" in routes
    assert "/profiles-page" not in routes


def test_multiple_page_suffixed_names_canonicalized():
    routes = _wire([
        {"name": "anchor", "route": "/x", "component": "Anchor", "apis_used": []},
        {"name": "my_list_page", "route": "", "component": "", "apis_used": ["GET /api/my-list"]},
        {"name": "new_and_popular_page", "route": "", "component": "", "apis_used": ["GET /api/new"]},
    ])
    assert "/my-list" in routes and "/my-list-page" not in routes
    assert "/new-and-popular" in routes and "/new-and-popular-page" not in routes


def test_non_empty_route_untouched():
    # an explicitly declared route (even one literally ending in -page) is never rewritten
    routes = _wire([
        {"name": "anchor", "route": "/x", "component": "Anchor", "apis_used": []},
        {"name": "landing_page", "route": "/landing-page", "component": "LandingPage",
         "apis_used": []},
    ])
    assert "/landing-page" in routes  # declared route preserved verbatim


def test_non_page_name_unchanged():
    routes = _wire([
        {"name": "anchor", "route": "/x", "component": "Anchor", "apis_used": []},
        {"name": "browse_home", "route": "", "component": "", "apis_used": ["GET /api/titles"]},
    ])
    # 'browse_home' has no 'page' token -> route derives to '/browse-home' unchanged
    assert "/browse-home" in routes


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
