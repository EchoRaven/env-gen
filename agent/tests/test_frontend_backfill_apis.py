"""#384 (N-P0-4): a ui_page with EMPTY apis_used ships as a flagged fallback stub and
HARD-blocks delivery (netflix r9: profiles + search — kickoff-registered with no apis,
skipped by #225/#226 as 'already covered', shipped as deliverability_frontend_fallback_page
even though GET /api/profiles and GET /api/search exist). backfill_page_apis fills a GET
endpoint by token overlap so the page projects a REAL measured floor the lane refines.
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    backfill_page_apis, _project_page_component)
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _is_generic_fallback_page)

_EPS = [
    {"method": "GET", "path": "/api/profiles"},
    {"method": "GET", "path": "/api/search"},
    {"method": "GET", "path": "/api/titles"},
    {"method": "GET", "path": "/api/genres"},
    {"method": "POST", "path": "/api/my-list"},
    {"method": "GET", "path": "/api/titles/{id}"},  # param path -> excluded
]

# real-run condition for the measured floor to be a genuine (non-fallback) BUILT page
_DESIGN = {"design_system": {"theme": {"default": "dark"}, "palette": {
    "bg": "#141414", "surface": "#232323", "text": "#ffffff",
    "accent": "#e50914", "border": "rgba(255,255,255,0.2)"}}}


def test_backfill_profiles_and_search():
    pages = [
        {"name": "profiles_page", "route": "/profiles-page",
         "component": "ProfilesPage", "apis_used": []},
        {"name": "search_results_page", "route": "/search-results-page",
         "component": "SearchResultsPage", "apis_used": []},
    ]
    out = {p["component"]: p["apis_used"] for p in backfill_page_apis(pages, _EPS)}
    assert out["ProfilesPage"] == ["GET /api/profiles"]
    assert out["SearchResultsPage"] == ["GET /api/search"]


def test_never_overrides_declared_apis():
    pages = [{"name": "browse", "route": "/browse", "component": "BrowseHomePage",
              "apis_used": ["GET /api/titles"]}]
    assert backfill_page_apis(pages, _EPS)[0]["apis_used"] == ["GET /api/titles"]


def test_no_endpoints_leaves_empty_unchanged():
    pages = [{"name": "x", "route": "/x", "component": "XPage", "apis_used": []}]
    assert backfill_page_apis(pages, [])[0]["apis_used"] == []


def test_no_match_leaves_empty_unchanged():
    # a page whose tokens overlap no GET collection segment stays api-less (never a
    # spurious wrong endpoint) -> remains a flagged stub, correctly surfaced not hidden
    pages = [{"name": "zzz", "route": "/zzz", "component": "ZzzPage", "apis_used": []}]
    assert backfill_page_apis(pages, _EPS)[0]["apis_used"] == []


def test_param_paths_excluded_from_backfill():
    # only bare GET collections are backfill targets; /api/titles/{id} must not win
    pages = [{"name": "title_detail", "route": "/title", "component": "TitlePage",
              "apis_used": []}]
    got = backfill_page_apis(pages, _EPS)[0]["apis_used"]
    assert got == ["GET /api/titles"]  # collection, not the {id} detail path


def test_malformed_pages_survive():
    pages = [None, "nope", {"component": "OkPage", "apis_used": []},
             {"apis_used": ["GET /api/titles"]}]
    out = backfill_page_apis(pages, _EPS)
    assert out[0] is None and out[1] == "nope"


def test_end_to_end_backfill_clears_fallback_flag():
    """The whole point: backfill -> project -> the delivery-gate fallback detector no
    longer flags the page (measured floor, not a stub)."""
    for comp, route, ep in [("ProfilesPage", "/profiles-page", "/api/profiles"),
                            ("SearchResultsPage", "/search-results-page", "/api/search")]:
        raw = {"name": comp, "route": route, "component": comp, "apis_used": []}
        fixed = backfill_page_apis([raw], _EPS)[0]
        before = _project_page_component(comp, raw, design=_DESIGN)
        after = _project_page_component(comp, fixed, design=_DESIGN)
        assert _is_generic_fallback_page(before) is True, f"{comp} pre-fix should be flagged"
        assert _is_generic_fallback_page(after) is False, f"{comp} post-fix should pass"
        assert ep in after  # fetches its own declared endpoint


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
