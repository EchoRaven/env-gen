"""Projected business pages share a top-nav so the app is NAVIGABLE (you can move
between inbox/calendar/contacts/…). User symptom: 'only landing, nothing else' —
the pages were disconnected dead-ends. LOCAL-ONLY (agent/tests/ gitignored)."""
import sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _project_page_component, _nav_links_jsx, scaffold_pages_from_contract)


def test_nav_links_jsx_builds_bar_or_empty():
    assert _nav_links_jsx([]) == ""           # no routes → no empty bar
    bar = _nav_links_jsx([("Inbox", "/inbox"), ("Calendar", "/calendar")])
    assert "<nav" in bar and 'href="/inbox"' in bar and 'href="/calendar"' in bar
    assert "Sign out" in bar


def test_get_page_gets_working_nav():
    nav = [("Inbox", "/inbox"), ("Calendar", "/calendar")]
    src = _project_page_component("InboxPage", {"route": "/inbox", "apis_used": ["GET /api/messages"]}, nav_routes=nav)
    assert 'href="/inbox"' in src and 'href="/calendar"' in src and "__NAV__" not in src


def test_auth_and_landing_have_no_business_nav():
    nav = [("Inbox", "/inbox")]
    for page in ({"route": "/login", "id": "login_page"}, {"route": "/", "id": "landing"}):
        src = _project_page_component("LoginPage", page, nav_routes=nav)
        assert 'href="/inbox"' not in src


def test_scaffold_cross_page_nav_excludes_auth_landing_and_detail():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir(parents=True)
    pages = [
        {"id": "landing", "route": "/", "component": "LandingPage"},
        {"id": "login", "route": "/login", "component": "LoginPage"},
        {"id": "inbox", "route": "/inbox", "component": "InboxPage", "apis_used": ["GET /api/messages"]},
        {"id": "calendar", "route": "/calendar", "component": "CalendarPage", "apis_used": ["GET /api/events"]},
        {"id": "read", "route": "/inbox/message/:id", "component": "ReadEmailPage", "apis_used": ["GET /api/messages/:id"]},
    ]
    scaffold_pages_from_contract(d, pages)
    inbox = (d / "src" / "pages" / "InboxPage.jsx").read_text()
    # nav links the two MAIN list routes, not auth/landing/param-detail
    assert 'href="/inbox"' in inbox and 'href="/calendar"' in inbox
    assert 'href="/login"' not in inbox and 'href="/inbox/message' not in inbox


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
