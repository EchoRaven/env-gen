"""FIX #225 — ui_pages seeded by-construction from the measured design screens.

r19: kickoff declared ONE ui_page for the whole TikTok surface, so most
measured screens had no page, no route, no flow requirement — the app shipped
with the surface undeclared. The design screens (kind=page + classified
route, #132) are ground truth for WHICH pages the app must have; any screen
route not covered by a registered ui_page gets one synthesized (component
name from the screen, apis_used inferred by token overlap with the
registered GET collection endpoints). LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import missing_design_screen_pages  # noqa: E402


_DESIGN = {
    "screens": [
        {"name": "fyp_feed", "kind": "page", "route": "/", "reference": "fyp.png",
         "components": [{"id": "video-player", "role": "Main content area displaying a video"}]},
        {"name": "explore_grid", "kind": "page", "route": "/explore",
         "reference": "explore.png",
         "components": [{"id": "video-grid", "role": "Grid of video thumbnails"}]},
        {"name": "messages_dm", "kind": "page", "route": "/messages",
         "reference": "messages.png",
         "components": [{"id": "conversation-list", "role": "List of DM conversations"}]},
        {"name": "login_modal", "kind": "overlay", "route": "/",
         "reference": "login.png", "components": [{"id": "modal", "role": "Login"}]},
    ],
}

_ENDPOINTS = [
    {"method": "GET", "path": "/api/videos"},
    {"method": "GET", "path": "/api/messages"},
    {"method": "GET", "path": "/api/videos/{id}"},
    {"method": "POST", "path": "/api/auth/login"},
]


def test_synthesizes_pages_for_uncovered_screen_routes():
    existing = [{"name": "feed_page", "route": "/", "component": "FeedPage",
                 "apis_used": ["GET /api/videos"]}]
    out = missing_design_screen_pages(_DESIGN, existing, _ENDPOINTS)
    routes = {p["route"]: p for p in out}
    assert set(routes) == {"/explore", "/messages"}   # '/' covered; overlay skipped
    assert routes["/explore"]["apis_used"] == ["GET /api/videos"]
    assert routes["/messages"]["apis_used"] == ["GET /api/messages"]
    assert routes["/explore"]["component"] == "ExploreGridPage"
    assert routes["/explore"]["metadata"]["reference_image"] == "explore.png"


def test_no_design_or_full_coverage_is_noop():
    assert missing_design_screen_pages({}, [], _ENDPOINTS) == []
    covered = [{"name": "a", "route": "/"}, {"name": "b", "route": "/explore"},
               {"name": "c", "route": "/messages"}]
    assert missing_design_screen_pages(_DESIGN, covered, _ENDPOINTS) == []


def test_unmatchable_endpoint_leaves_apis_empty():
    design = {"screens": [{"name": "zzz_screen", "kind": "page", "route": "/zzz",
                           "reference": "z.png", "components": []}]}
    out = missing_design_screen_pages(design, [], _ENDPOINTS)
    assert out and out[0]["apis_used"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_fuzzy_covered_screens_not_duplicated():
    """#226 (r20 live): kickoff's `activity` page at /activity must count as
    covering the notifications_activity screen at /notifications — otherwise a
    TWIN page is registered and one of the two ships as a generic fallback."""
    design = {"screens": [
        {"name": "notifications_activity", "kind": "page", "route": "/notifications",
         "reference": "n.png", "components": []},
        {"name": "profile_own", "kind": "page", "route": "/profile",
         "reference": "p.png", "components": []},
        {"name": "explore_grid", "kind": "page", "route": "/explore",
         "reference": "e.png", "components": []},
    ]}
    existing = [{"name": "activity", "route": "/activity", "component": "ActivityPage"},
                {"name": "profile", "route": "/@user", "component": "ProfilePage"}]
    out = missing_design_screen_pages(design, existing, [])
    assert [p["route"] for p in out] == ["/explore"]
