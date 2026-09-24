"""A logged-in browser test-user that bounces back to the LOGIN form on the protected
pages means the app shipped a "login wall" — unusable even though it builds + serves
(outlook MM, 2026-06-29: a hardcoded absolute API origin failed every call → every
protected route rendered the Sign-in form). The walkthrough used to mark those pages OK
(a login form isn't "blank"), so the defect shipped. _finalize_walkthrough now raises a
``hollow_frontend`` verdict that heal_pipeline escalates to a P0 fix (delivery-blocking).
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.test_user_runner import _finalize_walkthrough, format_feedback  # noqa: E402


def _page(name, route, **kw):
    base = {"name": name, "route": route, "blank": False, "console_errors": [],
            "redirected_to_login": False}
    base.update(kw)
    return base


def _report(pages, steps=None):
    return {"ran": True, "pages": pages, "steps": steps or [{"step": "auth", "ok": True}],
            "shots": {}}


def test_all_protected_pages_redirect_is_hollow():
    rep = _finalize_walkthrough(_report([
        _page("Inbox", "/inbox", redirected_to_login=True),
        _page("Calendar", "/calendar", redirected_to_login=True),
        _page("Contacts", "/contacts", redirected_to_login=True),
        _page("Login", "/login"),  # the auth page itself is NOT counted as protected
    ]))
    assert rep["hollow_frontend"] is True
    assert set(rep["auth_redirect_pages"]) == {"Inbox", "Calendar", "Contacts"}


def test_half_redirect_is_hollow():
    rep = _finalize_walkthrough(_report([
        _page("Inbox", "/inbox", redirected_to_login=True),
        _page("Calendar", "/calendar"),
    ]))
    assert rep["hollow_frontend"] is True  # 1 of 2 protected ≥ ceil(2/2)=1


def test_healthy_app_is_not_hollow():
    rep = _finalize_walkthrough(_report([
        _page("Inbox", "/inbox"),
        _page("Calendar", "/calendar"),
        _page("Login", "/login"),
    ]))
    assert rep["hollow_frontend"] is False
    assert rep["auth_redirect_pages"] == []


def test_auth_pages_alone_never_trigger_hollow():
    # an app whose only walked routes are auth pages (no protected routes) is not hollow
    rep = _finalize_walkthrough(_report([
        _page("Login", "/login"), _page("Signup", "/signup")]))
    assert rep["hollow_frontend"] is False


def test_single_protected_page_redirect_is_hollow():
    rep = _finalize_walkthrough(_report([_page("Feed", "/feed", redirected_to_login=True)]))
    assert rep["hollow_frontend"] is True


def test_feedback_surfaces_the_login_wall_actionably():
    rep = _finalize_walkthrough(_report([
        _page("Inbox", "/inbox", redirected_to_login=True),
        _page("Mail", "/mail", redirected_to_login=True)]))
    fb = format_feedback(rep)
    assert "HOLLOW FRONTEND" in fb
    assert "RELATIVE" in fb            # the actionable hint (relative URLs, not absolute)
    assert "/inbox" in fb and "REDIRECTED TO LOGIN" in fb


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
