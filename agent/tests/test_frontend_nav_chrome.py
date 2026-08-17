"""#454 (netflix r36 judge, recurring across browse_home/movies/games/
new_and_popular/genre_category: "header/profile chrome incomplete", "proper header
profile controls" missing). The top-nav right cluster rendered utility icons ONLY
from staged ASSETS (#421 _nav_utility_icons), so when the design doesn't stage
search/bell icons (common) the cluster was empty. FIX: rest-visible inline-SVG
search + notifications bell + Kids link, gated on the design's own nav component-role
tokens (renders only what the nav enumerates). Deterministic (like #443 avatar /
#445 mute), no asset needed, generalizable — no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _nav_chrome_454, _ref_nav_jsx)


def _design(nav_role):
    return {"screens": [{"name": "browse_home", "components": [
        {"id": "topnav", "role": nav_role}]}]}


def test_renders_search_bell_kids_from_nav_role():
    d = _design("global top navigation with logo, primary links, search, "
                "notifications bell, kids badge, profile avatar dropdown")
    out = _nav_chrome_454(d)
    assert 'aria-label="Search"' in out and "<circle" in out, "inline search icon"
    assert 'aria-label="Notifications"' in out, "inline bell icon"
    assert ">Kids<" in out, "Kids link"


def test_renders_only_what_the_nav_enumerates():
    d = _design("top navigation with logo and primary links only")
    assert _nav_chrome_454(d) == "", "no search/bell/kids tokens → nothing"


def test_search_only_when_no_bell_or_kids():
    d = _design("navigation bar with a search box")
    out = _nav_chrome_454(d)
    assert 'aria-label="Search"' in out
    assert 'aria-label="Notifications"' not in out and ">Kids<" not in out


def test_skip_avoids_duplication_with_asset_icons():
    d = _design("nav with search, notifications, kids")
    out = _nav_chrome_454(d, skip={"search"})
    assert 'aria-label="Search"' not in out, "search already covered by an asset icon → skipped"
    assert 'aria-label="Notifications"' in out, "bell still rendered"


def _media_design(nav_role):
    return {"assets": [{"type": "video", "file": "trailer.mp4"}],
            "screens": [{"name": "browse_home", "components": [
                {"id": "topnav", "role": nav_role}]}]}


def test_469_media_app_gets_default_search_and_bell():
    # #469: the design's nav enumerates NEITHER search nor bell, but the app stages
    # video (media/streaming) → the canonical search + bell chrome renders by default
    # (fixes r46's inconsistent-per-run cluster: shows had search, no bell).
    d = _media_design("top navigation with logo and primary links only")
    out = _nav_chrome_454(d)
    assert 'aria-label="Search"' in out, "#469 media app gets default search chrome"
    assert 'aria-label="Notifications"' in out, "#469 media app gets default bell chrome"


def test_469_nonmedia_app_stays_data_gated():
    # no staged video → NOT a media app → chrome stays enumeration-gated (no default)
    d = _design("top navigation with logo and primary links only")
    assert _nav_chrome_454(d) == "", "#469 non-media app: no default chrome (data-gated)"


def test_ignores_non_nav_component_tokens():
    # 'search' appearing on a NON-nav component must not trigger nav chrome
    d = {"screens": [{"name": "s", "components": [
        {"id": "body", "role": "a page body with a search results grid"}]}]}
    assert _nav_chrome_454(d) == "", "search on a non-nav component is not nav chrome"


# ── integration: the horizontal top nav includes the chrome ──
def test_top_nav_includes_chrome_cluster():
    d = _design("top navigation bar: logo, primary links, search, notifications, "
                "kids, profile avatar")
    out = _ref_nav_jsx([("Home", "/browse"), ("Movies", "/browse/movies")], "#e50914",
                       vertical=False, design=d)
    assert 'aria-label="Search"' in out and 'aria-label="Notifications"' in out
    assert 'aria-label="Profile"' in out, "#443 avatar still present alongside chrome"


def test_vertical_nav_has_no_top_chrome():
    d = _design("nav with search and notifications")
    out = _ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=True, design=d)
    assert 'aria-label="Search"' not in out, "chrome is a top-bar element only"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
