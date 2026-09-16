"""#1202pf: a frontend section the framework salvages is built from the design's SCREENS.

When the frontend lane misses kickoff the framework authored its section from the endpoint list
— one `/<table>` CRUD page per collection — and never read `design/reference_spec.json`, which
names every screen with its `route_hint` before any lane runs. It fired in 6 of 15 runs
(r112-r126); r126 ended with 18 pages against 11 spec screens, all 11 derived pages claiming a
spec reference image. Uses r126's real spec.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402

R126_SPEC = {"screens": [
    {"name": "fyp_feed_logged_out", "route_hint": "/foryou"},
    {"name": "explore_grid", "route_hint": "/explore"},
    {"name": "following_suggested_creators", "route_hint": "/following"},
    {"name": "login_modal", "route_hint": "/login"},          # the auth page already covers it
    {"name": "broken_screen"},                                 # no route: not a page
]}


def _project(tmp_path, spec):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "reference_spec.json").write_text(json.dumps(spec))
    return tmp_path


def test_the_salvage_uses_the_screens_the_design_names(tmp_path):
    pages = RK.derive_frontend_pages_from_spec_1202pf(_project(tmp_path, R126_SPEC))
    routes = {p["route"]: p for p in pages}
    assert set(routes) == {"/login", "/signup", "/foryou", "/explore", "/following"}
    assert routes["/explore"]["reference_image"] == "explore_grid.png"
    assert routes["/explore"]["component"] == "ExploreGridPage"
    assert not any(p["route"] in ("/videos", "/comments") for p in pages)


def test_no_spec_or_no_routed_screen_falls_back(tmp_path):
    assert RK.derive_frontend_pages_from_spec_1202pf(tmp_path) == []
    assert RK.derive_frontend_pages_from_spec_1202pf(
        _project(tmp_path, {"screens": [{"name": "x"}]})) == []


def test_the_salvage_prefers_the_spec_and_falls_back_to_endpoints(tmp_path):
    eps = [{"method": "GET", "path": "/api/videos"}, {"method": "GET", "path": "/api/comments"}]
    with_spec = RK.salvaged_frontend_pages_1202pf(_project(tmp_path, R126_SPEC), eps)
    assert "/explore" in {p["route"] for p in with_spec}
    assert "/videos" not in {p["route"] for p in with_spec}
    without = RK.salvaged_frontend_pages_1202pf(tmp_path / "nowhere", eps)
    assert "/videos" in {p["route"] for p in without}
