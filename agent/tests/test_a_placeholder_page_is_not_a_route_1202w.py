r"""#1202w: a page whose name says "placeholder" must not be a route a user can reach.

netflix-r25 ships `NoopVerifierRead.jsx` under the framework's own "framework-projected page"
header — I had blamed the lane for that file and was wrong. A lane registered the junk ui_page
NAME and the projector dutifully built a page for it. Swept over the 97 corpus runs that have an
App.jsx, four SHIPPED one as a live route:

    instagram run76   DummyToGetRegistryList
    tiktok r61        ExplorePlaceholderPage, FollowingPlaceholderPage, LivePlaceholderPage
    tiktok r69        PlaceholderPage
    tiktok r87        PlaceholderPage

A user navigating there gets a placeholder, which is the standing bar exactly: no dead UI, no
fake data.

★ Why the NAME and not "renders no API call": the broader check was tried first and flags
NotFoundPage, FallbackPage and ComingSoonPage, which are legitimately static — 8 of 97 runs, and
most of the hits correct behaviour. A gate that blocks a lane for shipping a working 404 is the
#566j false-blocker failure this repo has already paid 75 minutes for. The name is unambiguous
where the shape is not.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.deliverability import (  # noqa: E402
    _placeholder_route_blockers_1202w as blockers)


def _app(tmp_path, routes):
    src = "\n".join(
        '        <Route path="/x%d" element={<%s />} />' % (i, c)
        for i, c in enumerate(routes))
    d = tmp_path / "frontend" / "src"
    d.mkdir(parents=True)
    (d / "App.jsx").write_text("export default function App(){return (<Routes>\n%s\n</Routes>);}"
                               % src, encoding="utf-8")
    return tmp_path


def test_a_routed_placeholder_blocks(tmp_path):
    out = blockers(_app(tmp_path, ["BrowsePage", "PlaceholderPage"]))
    assert len(out) == 1
    assert "PlaceholderPage" in out[0]


def test_the_tiktok_r61_shape_names_all_three(tmp_path):
    out = blockers(_app(tmp_path, ["ExplorePlaceholderPage", "FollowingPlaceholderPage",
                                   "LivePlaceholderPage", "HomePage"]))
    assert "3 placeholder page(s)" in out[0]


def test_legitimately_static_pages_are_not_blocked(tmp_path):
    """The reason this checks the name and not the shape."""
    assert blockers(_app(tmp_path, ["NotFoundPage", "FallbackPage", "ComingSoonPage",
                                    "ProfilePage", "BrowsePage"])) == []


def test_a_dummy_registry_page_blocks(tmp_path):
    assert blockers(_app(tmp_path, ["DummyToGetRegistryList"]))


def test_no_app_jsx_is_not_a_finding(tmp_path):
    assert blockers(tmp_path) == []


def test_an_unreadable_app_is_survivable(tmp_path):
    d = tmp_path / "frontend" / "src"
    d.mkdir(parents=True)
    (d / "App.jsx").write_bytes(b"\xff\xfe not utf8 \xff")
    assert isinstance(blockers(tmp_path), list)


def test_it_is_wired_into_the_gate():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/deliverability.py"
           ).read_text(encoding="utf-8")
    assert "blockers.extend(_placeholder_route_blockers_1202w(app_root))" in src
