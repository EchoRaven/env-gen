"""#434 (netflix landing 0.25 EVERY run — one of the lowest screens). The landing
was short-circuited to a generic static stub (white bg, blue buttons, "Sign in to
connect, organize, and get things done") that IGNORED the design entirely, so the
judge flagged: "primary action button is blue rather than Netflix red", impl bg
white (ref is dark), "Missing email input + Get Started CTA". FIX: render the
landing from the MEASURED palette — dark bg + brand-accent CTA + brand mark, and
an email input + accent 'Get Started' when the design's landing screen carries an
email-capture form (else Sign In / Create account). Generalizable — any app's
landing in its own measured colors, no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _landing_page_src, _project_page_component, _is_landing_page)

_DARK = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}}, "assets": []}
_EMAIL_SCREEN = {"route": "/", "name": "landing", "components": [
    {"id": "hero-headline", "role": "large centered marketing headline"},
    {"id": "email-signup-form", "role": "email input plus Get Started CTA"},
    {"id": "email-input", "role": "email address text field"}]}


def test_landing_uses_measured_dark_bg_and_accent_cta():
    out = _landing_page_src("LandingPage", "Netflix Landing", {"route": "/"}, _DARK, None)
    assert "#141414" in out, "must use the measured dark bg"
    assert "#e50914" in out, "CTA must use the brand accent, not blue"
    assert "bg-blue-600" not in out and "bg-white" not in out
    assert "Sign in to connect, organize" not in out, "no generic stub copy"


def test_landing_renders_email_capture_when_design_has_one():
    out = _landing_page_src("LandingPage", "Netflix Landing", {"route": "/"},
                            _DARK, _EMAIL_SCREEN)
    assert 'type="email"' in out and "Get Started" in out, "email + Get Started CTA"


def test_landing_without_email_form_falls_back_to_auth_ctas():
    out = _landing_page_src("LandingPage", "Netflix Landing", {"route": "/"}, _DARK, None)
    assert 'type="email"' not in out
    assert "Sign In" in out and "Create account" in out


def test_no_design_landing_is_light_neutral_not_blue():
    # a design-less app: stay light/neutral, never a stray blue (regression guard)
    out = _landing_page_src("LandingPage", "Landing", {"route": "/"}, {}, None)
    assert "bg-blue-600" not in out and "#2563eb" not in out
    assert "#ffffff" in out, "no palette ⇒ light page"


def test_headline_avoids_welcome_to_welcome():
    bare = _landing_page_src("LandingPage", "Landing", {"route": "/"}, _DARK, None)
    assert "Welcome to Welcome" not in bare
    named = _landing_page_src("LandingPage", "Netflix Landing", {"route": "/"}, _DARK, None)
    assert "Welcome to Netflix" in named


def test_integration_via_project_page_component():
    # the top-level dispatcher routes a landing page through the measured renderer
    out = _project_page_component("LandingPage", {"route": "/", "name": "landing"},
                                  [("Home", "/browse")], _DARK)
    assert "#e50914" in out and "bg-white" not in out
    assert "data-projected=\"landing\"" in out


def test_437_explicit_landing_name_wins_over_apis_used():
    # r30 regression: a page NAMED 'landing' with apis_used attached to '/' was
    # sent to the data-list projector (fetched titles) → judged vs the marketing
    # reference → 0.15. The explicit name must win; the guard still protects a
    # non-landing data-home.
    assert _is_landing_page("LandingPage", {"route": "/", "apis_used": ["GET /api/titles"]})
    assert _is_landing_page("WelcomePage", {"route": "/", "id": "welcome", "apis_used": ["GET /x"]})
    assert not _is_landing_page("HomePage", {"route": "/", "apis_used": ["GET /api/feed"]})


def test_437_landing_with_apis_used_renders_marketing_not_titles_fetch():
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}}, "assets": [],
         "screens": [{"name": "landing", "route": "/", "components": []}]}
    out = _project_page_component("LandingPage",
                                  {"route": "/", "name": "landing", "apis_used": ["GET /api/titles"]},
                                  [("Home", "/browse")], d)
    assert 'data-projected="landing"' in out and "api/titles" not in out
    assert "#141414" in out and "#e50914" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
