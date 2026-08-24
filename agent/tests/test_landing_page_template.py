"""The landing/entry page must be a REAL navigable page (wordmark + working sign-in /
create-account nav), never the dead `<h2>Landing</h2>` no-api stub.

User looked at the app and saw "only landing, nothing else" — the landing was an
8-line stub with NO navigation, so there was no way into the app. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import _project_page_component, _is_landing_page  # noqa: E402


def test_landing_has_working_signin_and_signup_nav():
    src = _project_page_component("OutlookLanding", {"route": "/", "id": "outlook_landing"})
    assert 'href="/login"' in src and 'href="/signup"' in src   # real nav, not a dead heading
    # casing is not the property — the affordance is
    assert "sign in" in src.lower() and "Create" in src
    assert "Outlook" in src                                      # app wordmark derived from name
    assert "<h2" not in src                                      # not the bare stub


def test_bare_landing_falls_back_to_welcome():
    src = _project_page_component("LandingPage", {"route": "/", "id": "landing_page"})
    assert "Welcome" in src and 'href="/login"' in src


def test_home_feed_with_apis_is_a_list_not_a_marketing_splash():
    page = {"route": "/", "apis_used": ["GET /api/videos"]}
    assert _is_landing_page("HomePage", page) is False
    src = _project_page_component("HomePage", page)
    assert "divide-y" in src        # the light list, not the landing hero
    assert "Create free account" not in src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
