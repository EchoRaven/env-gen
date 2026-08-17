"""#421 (netflix r15, live verdict.json): iconography was the WORST visual dimension
(0.25 avg across all 13 judged screens). The judge flagged, on EVERY screen, that
the top nav was 'missing Netflix logo/wordmark, search, bell, avatar' — yet the
design_system staged+served brand/netflix_wordmark.svg + icons/netflix/{bell,search}.svg.
ROOT: _ref_nav_jsx prepended the logo ONLY in its vertical branch; the HORIZONTAL
top bar (what a streaming home uses) rendered nav links + Log out and NEVER the
wordmark or a right-side utility cluster. Also the logo lookup was scoped to the
nav COMPONENT's mapped assets, which routinely omit the wordmark.

FIX: _brand_logo_url searches the WHOLE design for the wordmark/logo; _nav_utility_icons
resolves search/bell/profile from staged icons; the horizontal _ref_nav_jsx now
renders [wordmark left] [links] [utility cluster + Log out right]. Generalizable
(asset-token driven, no product literals). Locks the behavior in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _brand_logo_url, _nav_utility_icons, _ref_nav_jsx)

_DESIGN = {"assets": [
    {"id": "netflix-n-icon", "file": "brand/netflix_n_icon.svg", "type": "svg",
     "staged_path": "public/assets/brand/netflix_n_icon.svg"},
    {"id": "netflix-wordmark", "file": "brand/netflix_wordmark.svg", "type": "svg",
     "staged_path": "public/assets/brand/netflix_wordmark.svg"},
    {"id": "search", "file": "icons/netflix/search.svg", "type": "svg",
     "staged_path": "public/assets/icons/netflix/search.svg"},
    {"id": "bell-2", "file": "icons/netflix/bell.svg", "type": "svg",
     "staged_path": "public/assets/icons/netflix/bell.svg"},
    {"id": "profile-avatar", "file": "icons/netflix/avatar.svg", "type": "svg",
     "staged_path": "public/assets/icons/netflix/avatar.svg"},
    # a non-image asset must never be picked
    {"id": "brand-font", "file": "fonts/netflix.woff2", "type": "woff2",
     "staged_path": "public/assets/fonts/netflix.woff2"},
]}
_NAV = [("Home", "/"), ("Movies", "/movies")]


def test_brand_logo_prefers_wordmark_over_icon_mark():
    assert _brand_logo_url(_DESIGN) == "/assets/brand/netflix_wordmark.svg"


def test_brand_logo_empty_when_none_staged():
    assert _brand_logo_url({}) == ""
    assert _brand_logo_url({"assets": [
        {"id": "poster", "file": "img/p.jpg", "type": "jpg",
         "staged_path": "public/assets/img/p.jpg"}]}) == ""


def test_utility_icons_resolved_from_staged_assets():
    got = dict(_nav_utility_icons(_DESIGN))
    assert got.get("Search") == "/assets/icons/netflix/search.svg"
    assert got.get("Notifications") == "/assets/icons/netflix/bell.svg"
    assert got.get("Account") == "/assets/icons/netflix/avatar.svg"


def test_horizontal_nav_renders_wordmark_utilities_and_links():
    out = _ref_nav_jsx(_NAV, "#e50914", vertical=False, design=_DESIGN)
    assert "netflix_wordmark.svg" in out, "horizontal top bar must render the wordmark"
    assert 'href="/"' in out  # wordmark links home
    # #551: search/bell render as INLINE svg (an <img> of these currentColor svgs is
    # invisible on a dark nav), force-rendered from the same staged-asset signal; the
    # avatar icon stays on the <img> channel.
    assert 'aria-label="Search"' in out and 'aria-label="Notifications"' in out
    assert "search.svg" not in out and "bell.svg" not in out  # not invisible <img>s
    assert "avatar.svg" in out
    assert "Home" in out and "Movies" in out  # nav links preserved
    # #457: the raw "Log out" TEXT button was removed (judge: extraneous, un-reference);
    # the account avatar carries the logout onClick instead.
    assert "Log out" not in out
    assert 'aria-label="Profile"' in out and "localStorage.clear()" in out, "avatar is the logout trigger"


def test_vertical_nav_still_renders_wordmark():
    out = _ref_nav_jsx(_NAV, "#e50914", vertical=True, design=_DESIGN)
    assert "netflix_wordmark.svg" in out


def test_nav_without_assets_is_safe_and_linkful():
    # no design → no logo/util, but a valid nav with links (never crash, never empty)
    out = _ref_nav_jsx(_NAV, "#e50914", vertical=False, design={})
    assert "<nav" in out and "Home" in out
    assert 'aria-label="Profile"' in out and "localStorage.clear()" in out  # #457 avatar=logout
    assert "<img" not in out.split("Home")[0], "no logo img when no wordmark staged"


def test_empty_routes_returns_empty():
    assert _ref_nav_jsx([], "#e50914", vertical=False, design=_DESIGN) == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
