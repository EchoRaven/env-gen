"""#424 (netflix r18 verdict.json): login (0.15) and landing (0.20) were the LOWEST
scoring screens, dragging the average — the visual judge flagged 'login has no
header; reference shows the Netflix wordmark top-left' and 'landing: reference has
left logo + Sign In; implementation has app nav'. These are auth/marketing TEMPLATE
screens (not the projector), so they never got the brand chrome #421 added to the
projected pages. FIX: _brand_mark_jsx renders the app's staged wordmark <img> (via
_brand_logo_url) with a text fallback; the auth template gets a brand header (it
had none) and the landing header uses the brand mark instead of a generic app-name
text. Highest average leverage (the two lowest screens). Locks this in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _brand_mark_jsx, _project_page_component)

_D_LOGO = {"design_system": {"palette": {"bg": "#141414"}},
           "assets": [{"id": "netflix-wordmark", "file": "brand/netflix_wordmark.svg",
                       "type": "svg",
                       "staged_path": "public/assets/brand/netflix_wordmark.svg"}]}
_D_NONE = {"design_system": {"palette": {"bg": "#ffffff"}}, "assets": []}


def _login(design):
    return _project_page_component("LoginPage", {"route": "/login", "id": "login"},
                                   nav_routes=[], design=design)


def _landing(design):
    return _project_page_component("LandingPage", {"route": "/", "id": "landing"},
                                   nav_routes=[], design=design)


def test_brand_mark_img_when_wordmark_staged():
    m = _brand_mark_jsx(_D_LOGO, "Netflix")
    assert "<img" in m and "netflix_wordmark.svg" in m and 'href="/"' in m


def test_brand_mark_text_fallback_when_none():
    m = _brand_mark_jsx(_D_NONE, "MyApp")
    assert "<img" not in m and "MyApp" in m and 'href="/"' in m


def test_login_gets_brand_header_with_wordmark():
    out = _login(_D_LOGO)
    assert "<header" in out, "auth page must now have a header (had none)"
    assert "netflix_wordmark.svg" in out
    assert "__BRAND_HEADER__" not in out  # placeholder filled


def test_landing_header_uses_brand_mark():
    out = _landing(_D_LOGO)
    assert "netflix_wordmark.svg" in out
    assert "__BRAND_MARK__" not in out and "__APP__" not in out  # placeholders filled


def test_no_logo_app_still_valid_login_no_leftover_placeholder():
    out = _login(_D_NONE)
    assert "<img" not in out  # no wordmark → text fallback
    assert "__BRAND_HEADER__" not in out
    assert "<form" in out and "/auth/login" in out  # functional form intact


def test_landing_no_logo_no_leftover_and_keeps_signin():
    out = _landing(_D_NONE)
    assert "__BRAND_MARK__" not in out and "__APP__" not in out
    assert 'href="/login"' in out  # Sign-in nav preserved (navigation intact)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
