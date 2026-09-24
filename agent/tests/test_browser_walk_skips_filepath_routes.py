"""The browser test-user walks only real SPA URL routes, not file-path/component ui_pages
(outlook run-28 v1.1.0, 2026-07-01, live-confirmed).

The frontend lane registers junk ui_page entries whose ``route`` is a SOURCE FILE
(``src/pages/OutlookInboxPage.jsx``) or registers non-navigable COMPONENTS
(folder_rail/message_list/…) as ui_pages. Walking those navigates the SPA to a non-route →
BLANK → the browser gate reports a FALSE 'unusable', churns its deferral, and escape-ships a
perfectly usable app 'loudly'. run-28 v1.1.0: EVERY 'blank' page was a file-path/component
entry while the real routes /,/inbox,/calendar rendered and auth_ok=True. `_is_walkable_route`
keeps real routes and drops the junk. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.heal_pipeline import _is_walkable_route  # noqa: E402


# The EXACT entries the browser test-user reported blank at run-28 v1.1.0 — all junk.
_JUNK_ROUTES = [
    "src/pages/OutlookInboxPage.jsx",
    "src/pages/OutlookLandingPage.jsx",
    "app/frontend/src/pages/OutlookComposeReplyPage.jsx",
    "app/frontend/src/components/ReplyComposer.jsx",
]
# The real CONCRETE routes that rendered fine (NOT in the blank list).
_REAL_ROUTES = ["/", "/login", "/signup", "/inbox", "/calendar", "/calendar/new"]
# Real routes too — but PARAM routes are not URL-walkable AS WRITTEN (fix #35,
# outlook run-30: navigating the literal ':id' fetched resource ":id" → FALSE
# blank). heal_pipeline first RESOLVES them to a concrete id via
# test_user_runner.resolve_param_route (see test_param_route_walk.py); only the
# resolved form reaches the walker, and an unresolvable one is skipped.
_PARAM_ROUTES = ["/inbox/message/:id", "/inbox/message/:id/reply",
                 "/calendar/event/:id"]


def test_real_url_routes_are_walkable():
    for r in _REAL_ROUTES:
        assert _is_walkable_route(r) is True, r


def test_param_routes_walk_only_in_resolved_form():
    for r in _PARAM_ROUTES:
        assert _is_walkable_route(r) is False, r
    assert _is_walkable_route("/inbox/message/m_77") is True
    assert _is_walkable_route("/calendar/event/42") is True


def test_source_file_path_routes_are_skipped():
    for r in _JUNK_ROUTES:
        assert _is_walkable_route(r) is False, r


def test_absolute_file_path_route_is_skipped():
    # a file path that (unusually) starts with "/" is still caught by the source-file suffix
    assert _is_walkable_route("/app/frontend/src/pages/OutlookInboxPage.jsx") is False
    assert _is_walkable_route("/components/FolderRail.jsx") is False


def test_empty_or_relative_non_slash_routes_are_skipped():
    for r in ("", "  ", None, "inbox", "outlook_inbox", "components/Foo"):
        assert _is_walkable_route(r) is False, r


def test_route_with_query_or_trailing_slash_still_walkable():
    assert _is_walkable_route("/inbox/") is True
    assert _is_walkable_route("/search?q=hi") is True


def test_full_run28_blanklist_all_dropped_realroutes_all_kept():
    """The whole run-28 v1.1.0 signal: every 'blank' was junk; every real
    CONCRETE route was kept (param routes go through resolution first, #35)."""
    kept = [r for r in (_REAL_ROUTES + _PARAM_ROUTES + _JUNK_ROUTES)
            if _is_walkable_route(r)]
    assert set(kept) == set(_REAL_ROUTES)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
