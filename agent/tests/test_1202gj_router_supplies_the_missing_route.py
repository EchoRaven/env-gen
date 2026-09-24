"""#1202gj — a page the router serves must not be invisible for want of a registry field.

A ui_page registration can carry `route: ""` while App.jsx wires that very page.
tiktok-r98 registered `home_page` with an empty route and a real file
(app/frontend/src/pages/HomePage.jsx) while App.jsx declares
`<Route path="/home" element={<HomePage />} />`. `load_ui_pages` drops a route-less entry,
so the framework could not see a page the app was serving: it never became a visual screen,
and no walk could reach it by route.

Measured over the 115 kept runs that have an App.jsx: 2111 registered pages, 843 (39.9%)
route-less, and 255 of those (30%) wired in App.jsx after all — 12% of every page ever
registered, invisible for want of a field the router already states.

Read-only: the registration is never rewritten, and a page whose component App.jsx does not
mention is left exactly as it was.
"""
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    load_ui_pages, _routes_from_app_jsx_1202gj)

APP = '''
import { Routes, Route } from "react-router-dom";
export default function App() {
  return (<Routes>
    <Route path="/" element={<FeedPage />} />
    <Route path="/home" element={<HomePage />} />
    <Route path="/explore" element={<ExplorePage />} />
  </Routes>);
}
'''


def _run(tmp_path, pages):
    root = tmp_path / "env"
    (root / "shared" / "hubs").mkdir(parents=True)
    (root / "app" / "frontend" / "src").mkdir(parents=True)
    (root / "app" / "frontend" / "src" / "App.jsx").write_text(textwrap.dedent(APP))
    (root / "shared" / "hubs" / "registryhub_ui_pages.json").write_text(json.dumps(pages))
    return root


def test_the_router_supplies_a_missing_route(tmp_path):
    """r98's exact shape: empty route, real file, wired in App.jsx."""
    root = _run(tmp_path, {
        "_meta": {"version": 1},
        "home_page": {"name": "home_page", "route": "",
                      "path": "app/frontend/src/pages/HomePage.jsx", "component": ""},
    })
    pages = load_ui_pages(root)
    assert [p["route"] for p in pages] == ["/home"], pages


def test_the_component_field_is_used_when_present(tmp_path):
    root = _run(tmp_path, {"x": {"name": "x", "route": "", "component": "ExplorePage"}})
    assert [p["route"] for p in load_ui_pages(root)] == ["/explore"]


def test_a_registered_route_is_never_overridden(tmp_path):
    """The registration wins where it exists — this only fills a blank."""
    root = _run(tmp_path, {"home_page": {"name": "home_page", "route": "/declared",
                                         "path": "app/frontend/src/pages/HomePage.jsx"}})
    assert [p["route"] for p in load_ui_pages(root)] == ["/declared"]


def test_a_page_the_router_does_not_mention_stays_dropped(tmp_path):
    root = _run(tmp_path, {"ghost": {"name": "ghost", "route": "",
                                     "path": "app/frontend/src/pages/GhostPage.jsx"}})
    assert load_ui_pages(root) == []


def test_no_app_jsx_is_not_a_crash(tmp_path):
    root = _run(tmp_path, {"home_page": {"name": "home_page", "route": "",
                                         "path": "app/frontend/src/pages/HomePage.jsx"}})
    (root / "app" / "frontend" / "src" / "App.jsx").unlink()
    assert load_ui_pages(root) == []


def test_the_parser_reads_the_generated_shape(tmp_path):
    root = _run(tmp_path, {})
    m = _routes_from_app_jsx_1202gj(root)
    assert m == {"FeedPage": "/", "HomePage": "/home", "ExplorePage": "/explore"}, m


def test_the_projection_still_carries_path(tmp_path):
    """The first cut of this fix failed here: the dict projection dropped `path` at the
    door, so the component name could never be derived (#747 lost `metadata` the same way)."""
    root = _run(tmp_path, {"home_page": {"name": "home_page", "route": "/x",
                                         "path": "app/frontend/src/pages/HomePage.jsx"}})
    import inspect
    from multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.load_ui_pages)
    assert '"path": v.get("path")' in src, "the projection dropped `path` again"
