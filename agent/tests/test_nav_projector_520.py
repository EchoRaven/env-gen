"""#520 (netflix r91/r92, 2026-08-06) — framework NAV PROJECTOR.

GROUND TRUTH: Part-A fidelity ceiling is STRUCTURAL, not imagery — r92 placed all brand
imagery (#518, BRAND-ASSET AUDIT 1916→66) yet visual scores stayed flat ~0.45. The
dominant structural gap is the NAV (flagged on ~11/12 screens): active state rendered as a
RED UNDERLINE (reference wants bold-white + pill), and a missing search/bell/profile right
cluster. The nav is LANE-authored and never converges despite the remediation loop feeding
the deviations every round. FIX #520: (A) `_ref_nav_jsx` active state → bold + full-opacity
+ subtle pill (no red underline, no accent-color text); (B) `_project_nav_component_src`
builds a standalone default-export nav from `_ref_nav_jsx` (nav_routes recovered from
App.jsx's Route table), and `recover_agent_nav` OVERWRITES the discovered lane nav with it
— gated (>=4 ref nav links) + fail-safe (any error / weak decomposition → keep the lane
nav, never break delivery). The 8 content pages that `import TopNavBar` inherit it.

These tests lock: Stage A active-state markup (bold-pill, no red underline); the projector
builds a valid default-export component with the nav links; the >=4-route gate; the
no-App.jsx fail-safe; and recover_agent_nav's end-to-end overwrite + fail-safe."""
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _ref_nav_jsx, _project_nav_component_src, recover_agent_nav)

_DESIGN = {"design_system": {"palette": {"bg": "#141414", "brand_red": "#e50914"}}}

_APP_JSX = """
import { Routes, Route } from 'react-router-dom';
export default function App() {
  return (
    <Routes>
      <Route path="/browse" element={<BrowseHomePage />} />
      <Route path="/shows" element={<ShowsPage />} />
      <Route path="/movies" element={<MoviesPage />} />
      <Route path="/games" element={<GamesPage />} />
      <Route path="/my-list" element={<MyListPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/title/:id" element={<TitleDetailPage />} />
    </Routes>
  );
}
"""


def _mk_frontend(tmp, app_jsx=_APP_JSX, design=_DESIGN, lane_nav=True):
    fe = Path(tmp) / "app" / "frontend"
    (fe / "src" / "components").mkdir(parents=True, exist_ok=True)
    (fe / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (Path(tmp) / "design").mkdir(parents=True, exist_ok=True)
    (fe / "src" / "App.jsx").write_text(app_jsx, encoding="utf-8")
    if design is not None:
        (Path(tmp) / "design" / "design_system.json").write_text(
            json.dumps(design), encoding="utf-8")
    if lane_nav:
        (fe / "src" / "components" / "TopNavBar.jsx").write_text(
            "export default function TopNavBar(){ return (<nav>LANE NAV "
            "<a style={{borderBottom:'2px solid red'}}>Home</a></nav>); }\n",
            encoding="utf-8")
    # a projector page carrying the fw-nav markers
    (fe / "src" / "pages" / "BrowseHomePage.jsx").write_text(
        "export default function BrowseHomePage(){ return (<div>\n"
        "  {/* fw-nav:start */}<nav>inline fw nav</nav>{/* fw-nav:end */}\n"
        "  <main>content</main></div>); }\n", encoding="utf-8")
    return fe


def test_stageA_active_state_is_bold_pill_not_red_underline():
    routes = [("Home", "/browse"), ("Shows", "/shows"), ("Movies", "/movies")]
    jsx = _ref_nav_jsx(routes, "#e50914", vertical=False, design=_DESIGN)
    assert "fontWeight: window.location.pathname" in jsx      # bold on active
    assert "backgroundColor: window.location.pathname" in jsx  # subtle pill on active
    assert "borderBottom: window.location.pathname" not in jsx  # NO underline treatment
    assert "2px solid" not in jsx                              # no accent underline anywhere


def test_projector_builds_default_export_component(tmp_path):
    fe = _mk_frontend(tmp_path)
    src = _project_nav_component_src(fe, _DESIGN, "TopNavBar")
    assert src is not None
    assert "export default function TopNavBar()" in src
    assert "<nav" in src and "<a href" in src
    # the projected nav LINKS come from App.jsx route segments (login/param excluded).
    # NB: '/login' legitimately appears in the avatar's logout redirect, so assert on the
    # link href, not mere substring presence.
    assert 'href="/browse"' in src and 'href="/shows"' in src and 'href="/movies"' in src
    assert 'href="/login"' not in src and "/title/:id" not in src
    assert "framework-projected nav (#520)" in src


def test_gate_returns_none_below_4_routes(tmp_path):
    thin = _APP_JSX.replace('      <Route path="/movies" element={<MoviesPage />} />\n', "") \
                   .replace('      <Route path="/games" element={<GamesPage />} />\n', "") \
                   .replace('      <Route path="/my-list" element={<MyListPage />} />\n', "")
    fe = _mk_frontend(tmp_path, app_jsx=thin)   # only /browse + /shows survive → <4
    assert _project_nav_component_src(fe, _DESIGN, "TopNavBar") is None


def test_failsafe_no_appjsx_returns_none(tmp_path):
    fe = Path(tmp_path) / "app" / "frontend"
    (fe / "src").mkdir(parents=True, exist_ok=True)   # no App.jsx
    assert _project_nav_component_src(fe, _DESIGN, "TopNavBar") is None


def test_recover_agent_nav_overwrites_lane_nav_and_rewires(tmp_path):
    fe = _mk_frontend(tmp_path)
    rep = recover_agent_nav(fe)
    assert rep.get("projected_nav") is True, rep
    nav_src = (fe / "src" / "components" / "TopNavBar.jsx").read_text(encoding="utf-8")
    assert "framework-projected nav (#520)" in nav_src   # lane nav replaced
    assert "LANE NAV" not in nav_src
    assert "2px solid red" not in nav_src                # the lane's red underline gone
    # projector page rewired to the (now framework) shared component:
    pg = (fe / "src" / "pages" / "BrowseHomePage.jsx").read_text(encoding="utf-8")
    assert "<TopNavBar />" in pg and "import TopNavBar" in pg


def test_recover_agent_nav_failsafe_no_design_keeps_lane_nav(tmp_path):
    fe = _mk_frontend(tmp_path, design=None)   # no design_system.json
    rep = recover_agent_nav(fe)
    assert rep.get("projected_nav") is False, rep
    nav_src = (fe / "src" / "components" / "TopNavBar.jsx").read_text(encoding="utf-8")
    assert "LANE NAV" in nav_src                          # lane nav preserved (never broke delivery)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
