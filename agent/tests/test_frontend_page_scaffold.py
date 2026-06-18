"""Guard: the frontend page-scaffold projects a stub per registered ui_page +
wires React-Router routes — the frontend analogue of the backend skeleton.

Closes the build-asymmetry root (youtube run #13): the backend is framework-
scaffolded from its contract so it completes reliably, but the frontend hand-
authored every page + routing from scratch → built 1 of 16, declared a
hallucinated 'done'. With pages projected from the contract, the lane FILLS bodies
and the app is navigable-by-construction. Safety: stubs only-if-missing; App.jsx
only (re)written while it carries the @framework-managed-routes marker.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    scaffold_pages_from_contract, _BASELINE_APP_JSX, _ROUTES_MARKER,
    _pascal_case,
)


def _mk_src():
    d = tempfile.mkdtemp()
    (Path(d) / "src").mkdir()
    return d


class PascalCaseTests(unittest.TestCase):
    def test_snake_to_pascal(self):
        self.assertEqual(_pascal_case("youtube_home"), "YoutubeHome")
        self.assertEqual(_pascal_case("youtube-channel-earn"), "YoutubeChannelEarn")
        self.assertEqual(_pascal_case(""), "Page")


class ScaffoldPagesFromContractTests(unittest.TestCase):
    def test_projects_stub_per_page_and_wires_routes(self):
        d = _mk_src()
        pages = [
            {"name": "youtube_home", "route": "/", "component": "HomePage"},
            {"name": "youtube_watch", "route": "/watch/:id"},
            {"name": "youtube_shorts", "route": "", "component": ""},
        ]
        rep = scaffold_pages_from_contract(d, pages)
        self.assertEqual(rep["routes"], 3)
        self.assertTrue(rep["app_wired"])
        built = sorted(os.listdir(Path(d) / "src" / "pages"))
        self.assertEqual(built, ["HomePage.jsx", "YoutubeShorts.jsx", "YoutubeWatch.jsx"])
        app = (Path(d) / "src" / "App.jsx").read_text()
        self.assertIn("BrowserRouter", app)
        self.assertEqual(app.count('<Route '), 3)  # 3 page routes (not the <Routes> wrapper)

    def test_replaces_social_baseline_app_with_generic_router(self):
        d = _mk_src()
        (Path(d) / "src" / "App.jsx").write_text(_BASELINE_APP_JSX)  # carries marker
        scaffold_pages_from_contract(d, [{"name": "home", "route": "/", "component": "Home"}])
        app = (Path(d) / "src" / "App.jsx").read_text()
        self.assertNotIn("getFeed", app)        # social shell gone
        self.assertIn("BrowserRouter", app)      # generic router in
        self.assertIn(_ROUTES_MARKER, app)       # still framework-managed

    def test_never_clobbers_lane_owned_app_or_pages(self):
        d = _mk_src()
        # lane took over App.jsx (no marker) + authored a real page
        (Path(d) / "src" / "App.jsx").write_text("export default function App(){return null}")
        (Path(d) / "src" / "pages").mkdir()
        (Path(d) / "src" / "pages" / "HomePage.jsx").write_text("// REAL lane page\n")
        rep = scaffold_pages_from_contract(
            d, [{"name": "home", "route": "/", "component": "HomePage"}])
        self.assertEqual(rep["scaffolded"], [])  # existing page untouched
        self.assertFalse(rep["app_wired"])        # lane App.jsx (no marker) preserved
        self.assertIn("REAL lane page", (Path(d) / "src" / "pages" / "HomePage.jsx").read_text())
        self.assertEqual((Path(d) / "src" / "App.jsx").read_text(),
                         "export default function App(){return null}")

    def test_idempotent(self):
        d = _mk_src()
        pages = [{"name": "home", "route": "/", "component": "Home"}]
        scaffold_pages_from_contract(d, pages)
        rep2 = scaffold_pages_from_contract(d, pages)  # second run
        self.assertEqual(rep2["scaffolded"], [])  # nothing new written

    def test_dedups_duplicate_routes(self):
        d = _mk_src()
        pages = [{"name": "a", "route": "/x", "component": "A"},
                 {"name": "b", "route": "/x", "component": "B"}]
        scaffold_pages_from_contract(d, pages)
        app = (Path(d) / "src" / "App.jsx").read_text()
        # both pages routed, but not to the SAME path
        self.assertEqual(app.count('<Route '), 2)
        self.assertIn('path="/x"', app)
        self.assertIn('path="/x/2"', app)

    def test_no_src_dir_is_safe_noop(self):
        d = tempfile.mkdtemp()  # no src/
        rep = scaffold_pages_from_contract(d, [{"name": "home", "route": "/"}])
        self.assertEqual(rep["scaffolded"], [])
        self.assertIn("skipped", rep)

    def test_empty_pages_no_app_write(self):
        d = _mk_src()
        rep = scaffold_pages_from_contract(d, [])
        self.assertFalse(rep["app_wired"])
        self.assertFalse((Path(d) / "src" / "App.jsx").exists())


if __name__ == "__main__":
    unittest.main()
