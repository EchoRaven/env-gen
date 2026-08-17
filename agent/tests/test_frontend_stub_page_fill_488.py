"""#488 — fill DECLARED pages that shipped as inert stubs (netflix r58/r60/r61 task#47).

A declared page routed in App.jsx sometimes ships as an INERT STUB (exists but a lone heading,
no api call / no children) — scaffold_missing_local_pages only fills MISSING files, so the stub
survives, trips the deliverability stub gate (_declared_but_inert) → deliverability_ui_page_unwired
→ blocks delivery (r61 LandingPage = 7 lines/210B `<h2>Landing</h2>`). repair_stub_declared_pages
overwrites a DEFINITIVE stub with the real projection, GUARDED so a real page is never clobbered
(r59 LandingPage was a real 103-line/6.6KB page yet the gate flagged it — must stay untouched)."""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _is_definitive_stub_page, repair_stub_declared_pages)


_STUB = (
    "export default function LandingPage() {\n"
    "  return (\n"
    '    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-8 py-16 text-center">\n'
    '      <h2 className="text-xl font-semibold">Landing</h2>\n'
    "    </div>\n"
    "  );\n"
    "}\n"
)
_REAL = (
    "import React, { useEffect, useState } from 'react';\n"
    "import * as api from '../services/api.js';\n"
    "export default function LandingPage() {\n"
    "  const [titles, setTitles] = useState([]);\n"
    "  useEffect(() => { api.getTitles().then(setTitles); }, []);\n"
    "  return (<div>{titles.map(t => <div key={t.id}>{t.name}</div>)}"
    "<button onClick={()=>{}}>Sign In</button></div>);\n"
    "}\n"
)


def test_is_definitive_stub_true_for_lone_heading():
    assert _is_definitive_stub_page(_STUB) is True


def test_is_definitive_stub_false_for_real_page():
    # has api. + useEffect + .map + <button → never a stub
    assert _is_definitive_stub_page(_REAL) is False


def test_is_definitive_stub_false_for_large_file():
    big = "export default function P(){ return (<div>" + ("x" * 800) + "</div>); }"
    assert _is_definitive_stub_page(big) is False  # >700 bytes → never overwritten


def test_is_definitive_stub_false_when_has_behavior_even_if_small():
    small_real = ("export default function P(){ const [x,setX]=useState(0);"
                  " return <button onClick={()=>setX(1)}>go</button>; }")
    assert _is_definitive_stub_page(small_real) is False  # has onClick/<button


def test_is_definitive_stub_false_on_empty_or_nonsense():
    assert _is_definitive_stub_page("") is False
    assert _is_definitive_stub_page("const x = 1;") is False  # no export default/return


def _mk(tmp, app_jsx: str, pages: dict):
    fe = Path(tmp) / "app" / "frontend"
    src = fe / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for name, body in pages.items():
        (src / "pages" / name).write_text(body, encoding="utf-8")
    return fe


_APP = (
    "import LandingPage from './pages/LandingPage';\n"
    "import MoviesPage from './pages/MoviesPage';\n"
    "export default function App(){ return (<Routes>\n"
    '  <Route path="/" element={<LandingPage/>} />\n'
    '  <Route path="/movies" element={<MoviesPage/>} />\n'
    "</Routes>); }\n"
)


def test_repair_fills_stub_landing_page():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"LandingPage.jsx": _STUB, "MoviesPage.jsx": _REAL})
        out = repair_stub_declared_pages(fe, ui_pages=[
            {"id": "landing", "route": "/", "apis_used": []},
            {"id": "movies_page", "route": "/movies", "apis_used": ["GET /api/titles"]},
        ])
        landing_after = (fe / "src" / "pages" / "LandingPage.jsx").read_text()
        movies_after = (fe / "src" / "pages" / "MoviesPage.jsx").read_text()
        # the stub landing page was overwritten with a bigger, real projection
        assert "LandingPage.jsx" in " ".join(out.get("repaired") or []), out
        assert len(landing_after) > len(_STUB) * 2, "stub should be replaced with real content"
        assert not _is_definitive_stub_page(landing_after), "no longer a stub after fill"
        # the REAL movies page must be byte-identical (never clobbered)
        assert movies_after == _REAL, "#488 must NOT touch a real page"


def test_repair_leaves_real_pages_byte_identical():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"LandingPage.jsx": _REAL, "MoviesPage.jsx": _REAL})
        out = repair_stub_declared_pages(fe, ui_pages=[{"id": "landing", "route": "/"}])
        assert not (out.get("repaired") or []), "no stubs → nothing repaired"
        assert (fe / "src" / "pages" / "LandingPage.jsx").read_text() == _REAL


def test_repair_best_effort_no_app_jsx():
    with tempfile.TemporaryDirectory() as tmp:
        fe = Path(tmp) / "app" / "frontend"
        (fe / "src").mkdir(parents=True)
        assert repair_stub_declared_pages(fe, ui_pages=[]) == {"repaired": []}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
