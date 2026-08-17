"""#513 (netflix r87, 2026-08-05) — content-endpoint correction for framework-projected pages.

GROUND TRUTH: r87 DELIVERED (2nd consecutive) but Part-A stuck at 0.463. The floor screens
(browse_home 0.35, shows 0.40, movies 0.50, my_list 0.60) are FRAMEWORK-PROJECTED pages, and each
fetched the WRONG endpoint because the design-analyst mis-recorded apis_used: /browse→GET
/api/profiles, /shows & /movies→GET /api/genres, /my-list→GET /api/profiles. So the projected pages
rendered profiles/genres, not the poster catalog → floor fidelity. backfill_page_apis only fills an
EMPTY apis_used, so the wrong one survived. FIX #513: the projector deterministically retargets a
content/catalog screen whose GET is auxiliary at the app's real CONTENT collection (the staged
dataset with image columns → /api/titles), or a route/name-matched collection (my-list→/api/my-list).

These tests lock: content-entity detection from dataset image columns; the correction picks the
content collection for a mis-recorded catalog screen; it is CONSERVATIVE (never touches auth /
detail(param) / aux-route screens, or a correct content GET); and the projected page fetches the
corrected endpoint end-to-end."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _content_entity_from_design, _corrected_content_get, _all_get_endpoints,
    _project_page_component)


_DESIGN = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "dataset": [{"id": "titles", "file": "titles.json",
                 "columns": ["id", "name", "poster", "backdrop", "synopsis"], "records": 60}],
    "screens": [],
}
# the app's known endpoint surface (union of ui_pages apis_used), as #513 receives it
_EPS = ["GET /api/profiles", "GET /api/genres", "GET /api/titles", "GET /api/titles/top10",
        "POST /auth/login"]


# ---- content-entity detection ----
def test_content_entity_from_image_columns():
    assert _content_entity_from_design(_DESIGN) == "titles"


def test_no_content_entity_when_no_image_columns():
    d = {"dataset": [{"id": "orders", "columns": ["id", "total", "status"], "records": 20}]}
    assert _content_entity_from_design(d) is None


def test_content_entity_prefers_most_records():
    d = {"dataset": [{"id": "avatars", "columns": ["image"], "records": 5},
                     {"id": "titles", "columns": ["poster"], "records": 60}]}
    assert _content_entity_from_design(d) == "titles"


# ---- the correction: mis-recorded catalog screens retarget to the content collection ----
def test_browse_profiles_corrected_to_titles():
    page = {"route": "/browse", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "BrowseHomePage", _DESIGN, _EPS,
                                  "/api/profiles") == "/api/titles"


def test_shows_genres_corrected_to_titles():
    page = {"route": "/shows", "apis_used": ["GET /api/genres"]}
    assert _corrected_content_get(page, "ShowsPage", _DESIGN, _EPS,
                                  "/api/genres") == "/api/titles"


def test_route_slug_match_wins_over_content_entity():
    # my-list SHOULD bind to /api/my-list (route-slug match) when it is in the endpoint surface,
    # not the generic content collection.
    eps = _EPS + ["GET /api/my-list"]
    page = {"route": "/my-list", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "MyListPage", _DESIGN, eps,
                                  "/api/profiles") == "/api/my-list"


# ---- conservative: never over-correct ----
def test_correct_content_get_untouched():
    # /new already fetches the content collection → no correction.
    page = {"route": "/new", "apis_used": ["GET /api/titles"]}
    assert _corrected_content_get(page, "NewPage", _DESIGN, _EPS, "/api/titles") is None


def test_aux_route_screen_keeps_its_endpoint():
    # a /profiles page SHOULD fetch /api/profiles — never corrected.
    page = {"route": "/profiles", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "ProfilesPage", _DESIGN, _EPS, "/api/profiles") is None


def test_detail_param_route_untouched():
    page = {"route": "/title/:id", "apis_used": ["GET /api/genres"]}
    assert _corrected_content_get(page, "TitleDetailPage", _DESIGN, _EPS, "/api/genres") is None


def test_auth_page_untouched():
    page = {"route": "/login", "apis_used": ["POST /auth/login"]}
    assert _corrected_content_get(page, "LoginPage", _DESIGN, _EPS, "") is None


def test_no_correction_without_content_entity():
    d = {"dataset": [{"id": "orders", "columns": ["id", "total"], "records": 5}]}
    page = {"route": "/browse", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "BrowsePage", d, _EPS, "/api/profiles") is None


def test_no_endpoints_no_correction():
    page = {"route": "/browse", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "BrowsePage", _DESIGN, [], "/api/profiles") is None


# ---- end-to-end: the projected page fetches the corrected endpoint ----
def test_projected_browse_page_fetches_titles_not_profiles():
    page = {"route": "/browse", "id": "browsehomepage", "apis_used": ["GET /api/profiles"]}
    body = _project_page_component("BrowseHomePage", page, nav_routes=[("Home", "/browse")],
                                   design=_DESIGN, get_endpoints=_EPS)
    assert "/api/titles" in body
    assert "fetch('/api/profiles'" not in body and "fetch(\"/api/profiles\"" not in body


def test_all_get_endpoints_union():
    ui_pages = [{"route": "/a", "apis_used": ["GET /api/titles"]},
                {"route": "/b", "apis_used": ["GET /api/titles", "GET /api/genres"]},
                {"route": "/c"}]
    assert _all_get_endpoints(ui_pages) == ["GET /api/titles", "GET /api/genres"]


# ---- #513 v2 (r88): phantom endpoints, user-specific endpoints, owner screens ----
# the app's REGISTERED contract surface (from registryhub_endpoints.json). Note /api/games is NOT
# here — r88's projected GamesPage fetched it → deliverability HARD-blocked delivery.
_REG = ["GET /api/titles", "GET /api/titles/trending", "GET /api/titles/top10",
        "GET /api/titles/{id}", "GET /api/genres", "GET /api/genres/{id}/titles",
        "GET /api/profiles", "GET /api/my-list", "GET /api/continue-watching", "GET /api/search"]


def test_phantom_endpoint_corrected_to_titles():
    # the r88 terminal blocker: /games fetches the UNREGISTERED /api/games → retarget to /api/titles.
    page = {"route": "/games", "apis_used": ["GET /api/games"]}
    assert _corrected_content_get(page, "GamesPage", _DESIGN, _EPS, "/api/games",
                                  registered_eps=_REG) == "/api/titles"


def test_user_specific_on_non_owner_corrected():
    # r88 /browse→/api/my-list (empty for a fresh session → blank rails) → retarget to /api/titles.
    page = {"route": "/browse", "apis_used": ["GET /api/my-list"]}
    assert _corrected_content_get(page, "BrowseHomePage", _DESIGN, _EPS, "/api/my-list",
                                  registered_eps=_REG) == "/api/titles"


def test_owner_screen_keeps_user_specific():
    # the my-list SCREEN legitimately owns /api/my-list → never retargeted.
    page = {"route": "/my-list", "apis_used": ["GET /api/my-list"]}
    assert _corrected_content_get(page, "MyListPage", _DESIGN, _EPS, "/api/my-list",
                                  registered_eps=_REG) is None


def test_owner_screen_repointed_to_owned():
    # a my-list screen mis-pointed at /api/profiles → corrected to its OWN collection /api/my-list.
    page = {"route": "/my-list", "apis_used": ["GET /api/profiles"]}
    assert _corrected_content_get(page, "MyListPage", _DESIGN, _EPS, "/api/profiles",
                                  registered_eps=_REG) == "/api/my-list"


def test_phantom_not_detected_without_registered_set():
    # phantom detection needs the registered set; without it a non-aux/non-user-specific phantom is
    # left as-is (documents the fallback — the loader supplies the set in real runs).
    page = {"route": "/games", "apis_used": ["GET /api/games"]}
    assert _corrected_content_get(page, "GamesPage", _DESIGN, _EPS, "/api/games") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
