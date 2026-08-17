"""#406 (route-sprawl → fallback-stub + fidelity + ui_flow, one root): the registry can hold
TWO ui_pages per screen — a route-LESS #225 design-screen registration ('browse_home',
route='', component='') AND the real routed page ('browse_home_page' @ /browse /
BrowseHomePage). The component dedup misses the twin (different derived component names), so
the route-less twin was wired at a NAME-DERIVED VARIANT route ('/browse-home') that ships as a
framework FALLBACK STUB — which hard-blocks delivery (deliverability_frontend_fallback_page)
AND makes the reference screen map to the stub, so visual fidelity can never match (netflix r5:
App.jsx had /browse+/browse-home, /new+/new-and-popular, /title/:id+/title-detail,
/watch/:titleId+/player, ...). The fix drops a route-less page whose semantic tokens are a
SUBSET of an already-routed page's. This locks it — the duplicate variant routes are gone, the
real routed pages stay, and a genuinely-new screen is NOT falsely dropped.
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


# the exact netflix r5 shape: routed real page + its route-less #225 design-screen twin
_R5_PAGES = [
    {"name": "browse_home_page", "route": "/browse", "component": "BrowseHomePage",
     "apis_used": ["GET /api/titles"]},
    {"name": "browse_home", "route": "", "component": "", "apis_used": []},
    {"name": "new_and_popular_page", "route": "/new", "component": "NewAndPopularPage",
     "apis_used": ["GET /api/titles"]},
    {"name": "new_and_popular", "route": "", "component": "", "apis_used": []},
    {"name": "title_detail_page", "route": "/title/:id", "component": "TitleDetailPage",
     "apis_used": []},
    {"name": "title_detail", "route": "", "component": "", "apis_used": []},
]


def test_routeless_twin_variant_routes_dropped():
    routes = _wire(_R5_PAGES)
    # the real canonical routes survive
    assert "/browse" in routes
    assert "/new" in routes
    assert "/title/:id" in routes
    # the route-less twins' variant stub routes are GONE
    assert "/browse-home" not in routes, routes
    assert "/new-and-popular" not in routes, routes
    assert "/title-detail" not in routes, routes


def test_genuinely_new_routeless_page_is_kept():
    # a route-less page with NO routed twin must still be wired (not falsely dropped)
    routes = _wire([
        {"name": "browse_home_page", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": []},
        {"name": "settings", "route": "", "component": "", "apis_used": ["GET /api/settings"]},
    ])
    assert "/browse" in routes
    assert "/settings" in routes, routes  # distinct tokens → NOT a subset → kept


def test_partial_token_overlap_not_dropped():
    # 'browse_history' shares only 'browse' with the routed 'browse_home' page → NOT a subset,
    # so it is a distinct screen and must be kept (precision: subset, not any-overlap)
    routes = _wire([
        {"name": "browse_home_page", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": []},
        {"name": "browse_history", "route": "", "component": "", "apis_used": ["GET /api/history"]},
    ])
    assert "/browse" in routes
    assert "/browse-history" in routes, routes


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
