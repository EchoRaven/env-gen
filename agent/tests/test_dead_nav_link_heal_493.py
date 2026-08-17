"""#493 — deterministic, generalizable heal for DEAD NAV LINKS (netflix r60/r64 task#47).

A dead nav link (`to="/x"`/`navigate("/x")` whose absolute target resolves to NO App.jsx <Route>,
catch-all excluded) trips the `deliverability_dead_nav_link` gate (frontend_audit.dead_nav_link_blockers,
#238) and blocks delivery — and the LLM frontend lane repeatedly fails to clear it (r60 stalled
81min; r64 shipped 2× persistent /profiles + /account links in ProfileAvatarMenu.jsx, never cleared).

repair_dead_nav_links REPOINTS only the SAFE case — an LLM-invented extra target (Case 3: NOT a
declared App.jsx route AND NOT a reference screen) — at the nearest existing route, via a MINIMAL
target-literal swap (no element removal → no JSX-corruption risk). A declared App.jsx path (Case 1)
or a reference screen (Case 2) is LEFT UNTOUCHED (route-injection / the page projector own those).
"""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_dead_nav_links)
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    dead_nav_link_blockers)


# App.jsx wires: / /login /browse /movies /my-list /title/:id  (+ catch-all). It ALSO contains a
# dead nav <Link> in its own markup — the heal must SKIP App.jsx entirely (it owns the <Route>
# table), so that dead link is left for the detector, and no <Route path=...> is ever rewritten.
_APP = (
    "import { Routes, Route, Link } from 'react-router-dom';\n"
    "import LandingPage from './pages/LandingPage';\n"
    "export default function App(){ return (<>\n"
    '  <nav><Link to="/downloads">App-level dead link</Link></nav>\n'
    "  <Routes>\n"
    '    <Route path="/" element={<LandingPage/>} />\n'
    '    <Route path="/login" element={<LandingPage/>} />\n'
    '    <Route path="/browse" element={<LandingPage/>} />\n'
    '    <Route path="/movies" element={<LandingPage/>} />\n'
    '    <Route path="/my-list" element={<LandingPage/>} />\n'
    '    <Route path="/title/:id" element={<LandingPage/>} />\n'
    '    <Route path="*" element={<LandingPage/>} />\n'
    "  </Routes></>); }\n"
)

# Reference screens the design MEASURED (passed to the heal as reference_routes): /shows is a real
# reference page NOT wired in App.jsx → a link to it is dead but must be LEFT for the projector.
_REF_ROUTES = {"/", "/browse", "/movies", "/my-list", "/shows", "/title/:id"}


def _mk(tmp, app_jsx: str, components: dict):
    fe = Path(tmp) / "app" / "frontend"
    src = fe / "src"
    (src / "components").mkdir(parents=True, exist_ok=True)
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "pages" / "LandingPage.jsx").write_text(
        "export default function LandingPage(){ return <div>Home</div>; }\n", encoding="utf-8")
    if app_jsx is not None:
        (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for name, body in components.items():
        (src / "components" / name).write_text(body, encoding="utf-8")
    return fe


# A menu with FOUR link kinds: an invented extra (/downloads, Case 3), a valid link (/movies), a
# reference-screen link (/shows, Case 2), and a declared-path link (/browse, Case 1). Plus a
# token-matchable invented extra (/list → nearest existing route /my-list by segment token).
_NAV = (
    "import { Link } from 'react-router-dom';\n"
    "export default function NavMenu(){\n"
    "  return (\n"
    "    <div>\n"
    '      <Link to="/downloads" className="row">Downloads</Link>\n'
    '      <Link to="/list" className="row">My List</Link>\n'
    '      <Link to="/movies" className="row">Movies</Link>\n'
    '      <Link to="/shows" className="row">Shows</Link>\n'
    '      <Link to="/browse" className="row">Browse</Link>\n'
    "    </div>\n"
    "  );\n"
    "}\n"
)


def test_case3_invented_link_repointed_and_gate_clears():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"NavMenu.jsx": _NAV})
        # BEFORE: /downloads, /list, /shows are dead (/downloads+/list Case 3, /shows Case 2)
        before = dead_nav_link_blockers(fe / "src", reference_routes=_REF_ROUTES)
        assert any("/downloads" in b for b in before)
        assert any("/list" in b for b in before)

        out = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        rep = " ".join(out.get("repaired") or [])
        # (a) the invented extra with no token match → first CONTENT route (/browse)
        assert "components/NavMenu.jsx: /downloads -> /browse" in (out.get("repaired") or []), out
        # preference (1): /list token-matches the existing /my-list route → nearest route wins
        assert "components/NavMenu.jsx: /list -> /my-list" in (out.get("repaired") or []), out

        nav_after = (fe / "src" / "components" / "NavMenu.jsx").read_text()
        # links now resolve
        assert 'to="/browse"' in nav_after and 'to="/my-list"' in nav_after
        assert 'to="/downloads"' not in nav_after and 'to="/list"' not in nav_after
        # file is still valid JSX — no element removed, all 5 <Link>…</Link> pairs intact
        assert nav_after.count("<Link ") == 5 and nav_after.count("</Link>") == 5
        # the Case-3 dead links no longer trip the gate
        after = dead_nav_link_blockers(fe / "src", reference_routes=_REF_ROUTES)
        assert not any("/downloads" in b for b in after)
        assert not any("/list" in b for b in after)


def test_valid_link_byte_identical():
    with tempfile.TemporaryDirectory() as tmp:
        # ONLY a valid link that resolves — nothing to repair, file untouched byte-for-byte
        nav = ('import { Link } from "react-router-dom";\n'
               'export default function N(){ return <Link to="/movies">Movies</Link>; }\n')
        fe = _mk(tmp, _APP, {"N.jsx": nav})
        out = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        assert not (out.get("repaired") or []), out
        assert (fe / "src" / "components" / "N.jsx").read_text() == nav


def test_case2_reference_target_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        # /shows is dead (not wired) but IS a reference screen → LEAVE for the page projector
        nav = ('import { Link } from "react-router-dom";\n'
               'export default function N(){ return <Link to="/shows">Shows</Link>; }\n')
        fe = _mk(tmp, _APP, {"N.jsx": nav})
        out = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        assert not (out.get("repaired") or []), out
        assert (fe / "src" / "components" / "N.jsx").read_text() == nav


def test_case1_declared_path_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        # /browse IS a declared App.jsx path (resolves) → never repointed, byte-identical
        nav = ('import { Link } from "react-router-dom";\n'
               'export default function N(){ return <Link to="/browse">Browse</Link>; }\n')
        fe = _mk(tmp, _APP, {"N.jsx": nav})
        out = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        assert not (out.get("repaired") or []), out
        assert (fe / "src" / "components" / "N.jsx").read_text() == nav


def test_app_jsx_route_defs_never_modified():
    with tempfile.TemporaryDirectory() as tmp:
        # App.jsx has its OWN dead <Link to="/downloads"> AND all the <Route path=...> defs —
        # the heal must SKIP App.jsx entirely: byte-identical after the run.
        fe = _mk(tmp, _APP, {"NavMenu.jsx": _NAV})
        app_before = (fe / "src" / "App.jsx").read_text()
        repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        app_after = (fe / "src" / "App.jsx").read_text()
        assert app_after == app_before, "App.jsx (route table + its own links) must never be touched"
        # every <Route path=...> literal is preserved verbatim
        for p in ('path="/"', 'path="/login"', 'path="/browse"', 'path="/movies"',
                  'path="/my-list"', 'path="/title/:id"', 'path="*"'):
            assert p in app_after


def test_idempotent_second_run_no_change():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"NavMenu.jsx": _NAV})
        first = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        assert first.get("repaired"), first
        nav_after_first = (fe / "src" / "components" / "NavMenu.jsx").read_text()
        second = repair_dead_nav_links(fe, reference_routes=_REF_ROUTES)
        assert not (second.get("repaired") or []), second  # links now resolve → not re-touched
        assert (fe / "src" / "components" / "NavMenu.jsx").read_text() == nav_after_first


def test_best_effort_no_app_jsx_or_src():
    # no App.jsx → nothing to classify against → []
    with tempfile.TemporaryDirectory() as tmp:
        fe = Path(tmp) / "app" / "frontend"
        (fe / "src" / "components").mkdir(parents=True)
        (fe / "src" / "components" / "N.jsx").write_text(
            'import { Link } from "r";\nexport default ()=> <Link to="/x">x</Link>;\n',
            encoding="utf-8")
        assert repair_dead_nav_links(fe, reference_routes=_REF_ROUTES) == {"repaired": []}
    # no src dir at all → []
    with tempfile.TemporaryDirectory() as tmp:
        fe = Path(tmp) / "app" / "frontend"
        fe.mkdir(parents=True)
        assert repair_dead_nav_links(fe) == {"repaired": []}


def test_default_reference_routes_none():
    # reference_routes defaults to None → treated as empty set; a link to a real reference screen
    # (no reference info supplied) is then classified Case 3 and repointed. Confirms no crash and
    # the None-safe path works.
    with tempfile.TemporaryDirectory() as tmp:
        nav = ('import { Link } from "react-router-dom";\n'
               'export default function N(){ return <Link to="/downloads">D</Link>; }\n')
        fe = _mk(tmp, _APP, {"N.jsx": nav})
        out = repair_dead_nav_links(fe)  # no reference_routes
        assert out.get("repaired") == ["components/N.jsx: /downloads -> /browse"], out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
