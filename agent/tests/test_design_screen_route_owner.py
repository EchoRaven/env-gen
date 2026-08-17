"""#389: missing_design_screen_pages blindly trusted the analyst-authored screen `kind`
(page/overlay) to pick which design screen owns a route. But the analyst INVERTED page/
overlay for screens that share a route (netflix r13: browse_home[overlay]↔card_hover_
preview[page] @ /browse, title_detail[overlay]↔rate_dialog[page] @ /title/:id), so the
OVERLAY claimed the page route and the real page got no route → shipped a framework
fallback → deliverability_frontend_fallback_page hard-block. The fix resolves each route
to the screen whose NAME STEM contains the route's last segment (kind-independent), and
only trusts kind for lone screens (so a correctly-labeled lone overlay is never promoted).
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    missing_design_screen_pages)

_EPS = [{"method": "GET", "path": "/api/titles"}, {"method": "GET", "path": "/api/genres"}]
# kickoff already registered / and /login
_UIP = [{"name": "landing", "route": "/", "component": "LandingPage"},
        {"name": "login", "route": "/login", "component": "LoginPage"}]


def _seed(screens):
    specs = missing_design_screen_pages({"screens": screens}, _UIP, _EPS)
    return {s["route"]: (s["name"], s["component"]) for s in specs}


def test_inverted_kind_collision_resolves_to_real_page():
    got = _seed([
        {"name": "browse_home", "route": "/browse", "kind": "overlay"},        # inverted
        {"name": "card_hover_preview", "route": "/browse", "kind": "page"},     # inverted
        {"name": "account_menu", "route": "/browse", "kind": "overlay"},
        {"name": "title_detail", "route": "/title/:id", "kind": "overlay"},     # inverted
        {"name": "rate_dialog", "route": "/title/:id", "kind": "page"},         # inverted
    ])
    assert got.get("/browse") == ("browse_home_page", "BrowseHomePage")
    assert got.get("/title/:id") == ("title_detail_page", "TitleDetailPage")
    # the overlays must NOT own a page route
    names = {v[0] for v in got.values()}
    assert not any(n.startswith(("card_hover", "rate_dialog", "account_menu")) for n in names)


def test_lone_overlay_not_promoted_to_page():
    # a correctly-labeled lone overlay at its own route is NOT seeded as a page
    got = _seed([
        {"name": "player_controls", "route": "/player-controls", "kind": "overlay"},
        {"name": "shows_genres_menu", "route": "/shows-menu", "kind": "overlay"},
    ])
    assert "/player-controls" not in got
    assert "/shows-menu" not in got


def test_lone_page_kind_seeded():
    got = _seed([
        {"name": "shows", "route": "/shows", "kind": "page"},
        {"name": "new_and_popular", "route": "/new", "kind": "page"},
    ])
    assert got.get("/shows") == ("shows_page", "ShowsPage")
    assert got.get("/new") == ("new_and_popular_page", "NewAndPopularPage")


def test_overlay_named_screen_never_wins_even_in_collision():
    # a dialog/menu-NAMED screen loses to any non-overlay competitor, and if it is the
    # only competitor whose name matches the route it is still excluded by the name test
    got = _seed([
        {"name": "settings_dialog", "route": "/settings", "kind": "page"},   # overlay name
        {"name": "settings", "route": "/settings", "kind": "overlay"},       # real page (name matches)
    ])
    assert got.get("/settings") == ("settings_page", "SettingsPage")


def test_covered_routes_not_reseeded():
    got = _seed([
        {"name": "landing", "route": "/", "kind": "page"},        # already covered
        {"name": "login", "route": "/login", "kind": "page"},     # already covered
        {"name": "movies", "route": "/movies", "kind": "page"},
    ])
    assert "/" not in got and "/login" not in got
    assert got.get("/movies") == ("movies_page", "MoviesPage")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
