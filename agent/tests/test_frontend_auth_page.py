"""#460 (r40 login 0.35: 'generic card missing the single-step flow, header gradient,
help/reCAPTCHA, full footer'). login is design-matched → goes through
_render_reference_page, which had NO auth branch → rendered the generic APP-SHELL
(nav + bands) instead of the real auth form. _project_page_component already renders
auth pages via _AUTH_PAGE_TEMPLATE; #460 mirrors that branch into
_render_reference_page so BOTH projection paths render auth pages consistently.
Detector-gated (_is_auth_page); non-auth screens unaffected. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)

_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": []}
_LOGIN = {"route": "/login", "name": "login", "kind": "page", "components": [
    {"id": "form", "region": [0.36, 0.22, 0.64, 0.36], "role": "email input + CTA"},
    {"id": "footer", "region": [0.0, 0.9, 1.0, 1.0], "role": "footer link columns"}]}


def _r(name, page, screen):
    return _render_reference_page(name, page, screen, _DESIGN, [("Home", "/browse")], "")


def test_login_renders_auth_form_not_appshell():
    out = _r("Login", {"route": "/login", "id": "login_page"}, _LOGIN)
    # real auth form (framework /auth/login), NOT the app-shell nav+bands
    assert ("/auth/login" in out or "handleSubmit" in out or "onSubmit" in out), "real auth form"
    assert not ("flex min-h-screen" in out and "fw-nav:start" in out), "not the app-shell page"


def test_signup_route_is_auth():
    scr = {"route": "/signup", "name": "signup", "kind": "page", "components": []}
    out = _r("Signup", {"route": "/signup"}, scr)
    assert ("/auth/register" in out or "/auth/login" in out or "handleSubmit" in out)


def test_non_auth_page_unaffected():
    scr = {"route": "/browse", "name": "browse_home", "kind": "page", "components": [
        {"id": "hero", "role": "hero billboard", "region": [0.0, 0.05, 1.0, 0.6]},
        {"id": "rail", "role": "poster rail of Trending Now",
         "region": [0.0, 0.65, 1.0, 0.85], "geometry": {"columns": 6}}]}
    out = _render_reference_page("browse_home", {"route": "/browse"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/titles")
    assert "flex min-h-screen" in out, "browse page still app-shell"
    assert "/auth/login" not in out, "browse page is not an auth page"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_auth_page_has_footer_chrome_463():
    # #463 (login/landing stuck at 0.35: judge 'missing footer/help/reCAPTCHA'):
    # the auth template now renders a footer (help/legal line + link columns).
    out = _r("Login", {"route": "/login", "id": "login_page"}, _LOGIN)
    assert "<footer" in out, "auth page renders a footer"
    assert "not a bot" in out, "reCAPTCHA-style legal line present"
    assert "Help Center" in out and "Terms of Use" in out, "footer link columns present"
