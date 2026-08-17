"""#440 (the REAL >=0.65 lever): the frontend agent authors high-fidelity nav
components (r30: components/NetflixTopNav.jsx — scroll-aware, exact items,
search/bell) but the DELIVERED projector pages render a generic inline nav and
never import them, so the agent's work is orphaned. _rewire_fw_nav swaps the
projector's MARKED inline nav for the agent's component + import, recovering that
fidelity. Pure/testable; no-op without the markers. Generalizable (any app's
agent nav). This is the mechanism; wiring it into the delivery pass (after the
agent authors the component) is the gated live step."""
import tempfile, os
from pathlib import Path
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _rewire_fw_nav, _render_reference_page, recover_agent_nav)

_PAGE = (
    "import { useState } from 'react';\n"
    "import { foo } from './x.js';\n"
    "export default function P() {\n"
    "  return (\n"
    "    <div>\n"
    "        {/* fw-nav:start */}\n"
    "        <nav className=\"flex\"><a href=\"/browse\">Home</a></nav>\n"
    "        {/* fw-nav:end */}\n"
    "      <main>body</main>\n"
    "    </div>\n"
    "  );\n"
    "}\n")


def test_rewire_swaps_marked_nav_and_adds_import():
    out = _rewire_fw_nav(_PAGE, "NetflixTopNav", "../components/NetflixTopNav.jsx")
    assert "<NetflixTopNav />" in out, "the agent nav component replaces the inline nav"
    assert "import NetflixTopNav from '../components/NetflixTopNav.jsx';" in out
    assert "fw-nav:start" not in out and "<nav className" not in out, "inline nav gone"
    assert "<main>body</main>" in out, "rest of the page preserved"


def test_rewire_is_noop_without_markers():
    plain = "export default function P() { return <div><nav/></div>; }"
    assert _rewire_fw_nav(plain, "NetflixTopNav", "../c/NetflixTopNav.jsx") == plain


def test_rewire_noop_without_component():
    assert _rewire_fw_nav(_PAGE, "", "x") == _PAGE


def test_rewire_import_not_duplicated():
    once = _rewire_fw_nav(_PAGE, "NetflixTopNav", "../components/NetflixTopNav.jsx")
    twice = _rewire_fw_nav(once, "NetflixTopNav", "../components/NetflixTopNav.jsx")
    assert twice.count("import NetflixTopNav from") == 1  # idempotent-ish (markers gone → 2nd is no-op)


# ── the projector emits the fw-nav markers so the rewire has a target ──
def test_projector_emits_fw_nav_markers():
    _D = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                            "theme": {"default": "dark"}}, "assets": []}
    scr = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "topnav", "role": "top navigation bar", "region": [0.0, 0.0, 1.0, 0.08]},
        {"id": "rail", "role": 'poster rail of "Trending"', "region": [0, 0.6, 1, 0.82],
         "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, _D,
                                 [("Home", "/browse")], "/api/titles")
    assert "fw-nav:start" in out and "fw-nav:end" in out, "projector must mark its nav"
    # and the rewire then works end-to-end on real projector output
    swapped = _rewire_fw_nav(out, "NetflixTopNav", "../components/NetflixTopNav.jsx")
    assert "<NetflixTopNav />" in swapped and "fw-nav:start" not in swapped


# ── recover_agent_nav: end-to-end recovery of an orphaned agent nav component ──
def _mk_frontend(tmp, nav_src=None, page_has_markers=True):
    fd = Path(tmp)
    (fd / "src" / "components").mkdir(parents=True)
    (fd / "src" / "pages").mkdir(parents=True)
    if nav_src is not None:
        (fd / "src" / "components" / "NetflixTopNav.jsx").write_text(nav_src, encoding="utf-8")
    page = _PAGE if page_has_markers else _PAGE.replace("{/* fw-nav:start */}", "").replace("{/* fw-nav:end */}", "")
    (fd / "src" / "pages" / "BrowseHomePage.jsx").write_text(page, encoding="utf-8")
    return fd


def test_recover_rewires_pages_to_agent_nav():
    with tempfile.TemporaryDirectory() as tmp:
        _mk_frontend(tmp, nav_src="export default function NetflixTopNav(){return <nav>real</nav>;}\n")
        rep = recover_agent_nav(tmp)
        assert rep["nav"] == "NetflixTopNav" and "BrowseHomePage.jsx" in rep["rewired"]
        out = (Path(tmp) / "src" / "pages" / "BrowseHomePage.jsx").read_text()
        assert "<NetflixTopNav />" in out and "import NetflixTopNav from" in out
        assert "fw-nav:start" not in out


def test_recover_noop_without_agent_nav_component():
    with tempfile.TemporaryDirectory() as tmp:
        _mk_frontend(tmp, nav_src=None)  # no nav component
        rep = recover_agent_nav(tmp)
        assert rep["nav"] is None and rep["rewired"] == []


def test_recover_ignores_projector_authored_nav():
    # a components file that is projector/stub-authored must NOT be treated as the agent's
    with tempfile.TemporaryDirectory() as tmp:
        _mk_frontend(tmp, nav_src="// framework-projected page (reference-structured)\nexport default function Header(){}\n")
        rep = recover_agent_nav(tmp)
        assert rep["nav"] is None, "projector-marked component must be skipped"


def test_recover_never_raises_on_bad_dir():
    assert recover_agent_nav("/nonexistent/xyz")["rewired"] == []
