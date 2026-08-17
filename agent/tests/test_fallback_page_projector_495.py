"""#495 — overwrite DECLARED pages that shipped as the FRAMEWORK FALLBACK (netflix r66 task#47).

A declared page routed in App.jsx sometimes ships as the FRAMEWORK FALLBACK — the generic
data-list placeholder the projector emits, NOT the real projected page. The registry audit
(frontend_audit.ui_page_delivery_blockers, via _is_generic_fallback_page) flags it
"component X is a framework fallback page (generic list)" → deliverability_ui_page_unwired →
blocks delivery, and the LLM frontend lane repeatedly fails to author it (r66 wedged ~7min on
"ProfilesPage is a framework fallback stub (generic list), not the real page").

repair_fallback_declared_pages overwrites a CONFIRMED fallback (the gate's OWN fingerprint) with
the real projection — the sibling of #488 (inert stubs) — guarded so a real lane-authored page is
never clobbered. Includes a new "who's watching" PROFILE-SELECTION template so a profiles page (the
r66 wedge) projects a REAL avatar-grid picker, not the generic list."""
import json
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _is_profiles_page, _project_page_component, repair_fallback_declared_pages)
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _is_generic_fallback_page)


# The generic framework fallback: _PAGE_MARKER + data-fallback="1" + the helper constellation +
# the "No data yet"/divide-y list shell — exactly what _is_generic_fallback_page fingerprints
# (marker-strip-proof). __COMP__ is substituted per page.
_FALLBACK = (
    "// framework-generated page (frontend_page_projector) — edits are overwritten\n"
    "import { useState, useEffect } from 'react';\n"
    "import { useParams } from 'react-router-dom';\n"
    "\n"
    "const _imgOf = (r) => { return null; };\n"
    "const _titleOf = (r) => { return ''; };\n"
    "const _subOf = (r) => { return ''; };\n"
    "const _metaOf = (r) => { return []; };\n"
    "\n"
    "export default function __COMP__() {\n"
    "  const [data, setData] = useState(null);\n"
    "  useEffect(() => { fetch('/api/x').then((r) => r.json()).then(setData); }, []);\n"
    "  const rows = Array.isArray(data) ? data : [];\n"
    "  return (\n"
    '    <div data-fallback="1" className="min-h-screen bg-zinc-50 text-zinc-900 px-6 py-6">\n'
    '      <h2 className="text-xl font-semibold mb-4">Page</h2>\n'
    '      <div className="divide-y divide-zinc-200">{rows.map((row, i) => (<div key={i}>{_titleOf(row)}</div>))}</div>\n'
    "      {rows.length === 0 ? <p>No data yet.</p> : null}\n"
    "    </div>\n"
    "  );\n"
    "}\n"
)


def _fallback(name: str) -> str:
    return _FALLBACK.replace("__COMP__", name)


# A REAL lane-authored page (netflix-style): imports api.js, useEffect fetch, a real .map, a
# button — never a framework fallback per the fingerprint.
_REAL = (
    "import React, { useEffect, useState } from 'react';\n"
    "import api from '../services/api.js';\n"
    "export default function MoviesPage() {\n"
    "  const [titles, setTitles] = useState([]);\n"
    "  useEffect(() => { api.listTitles().then(setTitles); }, []);\n"
    "  return (<div className=\"bg-black text-white\">{titles.map((t) => "
    "<button key={t.id} onClick={() => {}}>{t.name}</button>)}</div>);\n"
    "}\n"
)

_DESIGN = {
    "design_system": {
        "palette": {"bg": "#141414", "text": "#ffffff", "surface": "#222222",
                    "border": "#333333", "accent": "#e50914"},
        "theme": {"default": "dark"},
    }
}


def _mk(tmp, app_jsx: str, pages: dict, design: bool = True):
    root = Path(tmp)
    fe = root / "app" / "frontend"
    src = fe / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for name, body in pages.items():
        (src / "pages" / name).write_text(body, encoding="utf-8")
    if design:
        (root / "design").mkdir(parents=True, exist_ok=True)
        (root / "design" / "design_system.json").write_text(
            json.dumps(_DESIGN), encoding="utf-8")
    return fe


# App.jsx with a plain content route (MoviesPage) AND a WRAPPER-guarded profiles route
# (netflix shape: <RequireAuth><ProfilesPage/></RequireAuth>) to prove wrapper-aware detection.
_APP = (
    "import MoviesPage from './pages/MoviesPage';\n"
    "import ProfilesPage from './pages/ProfilesPage';\n"
    "import BrowseHomePage from './pages/BrowseHomePage';\n"
    "function RequireAuth({ children }) { return children; }\n"
    "export default function App(){ return (<Routes>\n"
    '  <Route path="/movies" element={<MoviesPage/>} />\n'
    '  <Route path="/browse" element={<BrowseHomePage/>} />\n'
    '  <Route path="/profiles" element={<RequireAuth><ProfilesPage /></RequireAuth>} />\n'
    "</Routes>); }\n"
)

_UI_PAGES = [
    {"component": "MoviesPage", "route": "/movies", "apis_used": ["GET /api/titles"]},
    {"component": "BrowseHomePage", "route": "/browse", "apis_used": ["GET /api/titles"]},
    {"component": "ProfilesPage", "route": "/profiles",
     "apis_used": ["GET /api/profiles", "POST /api/profiles"]},
]


# ── unit: profiles-page detection (low false-positive) ───────────────────────
def test_is_profiles_page_true_for_plural_collection():
    assert _is_profiles_page("ProfilesPage",
                             {"route": "/profiles", "apis_used": ["GET /api/profiles"]}) is True


def test_is_profiles_page_false_for_singular_settings():
    # a single-user 'profile' settings page (singular, /profile) is NOT a picker
    assert _is_profiles_page("ProfilePage",
                             {"route": "/profile", "apis_used": ["GET /api/profile"]}) is False


def test_is_profiles_page_false_for_unrelated_page():
    assert _is_profiles_page("SettingsPage",
                             {"route": "/settings", "apis_used": ["GET /api/settings"]}) is False


def test_project_profiles_page_renders_who_is_watching_grid():
    body = _project_page_component(
        "ProfilesPage",
        {"route": "/profiles", "apis_used": ["GET /api/profiles", "POST /api/profiles"]},
        nav_routes=[("Browse", "/browse")], design=_DESIGN)
    assert "Who" in body and "watching" in body.lower(), "who's-watching heading"
    assert "/api/profiles" in body, "fetches the profiles collection"
    assert "profiles.map(" in body, "renders a profile grid"
    assert "active_profile_id" in body and "/browse" in body, "sets active profile + navigates"
    assert "Add Profile" in body, "add-profile affordance"
    assert not _is_generic_fallback_page(body), "a real projection, not a fallback"


# ── (a) a fallback declared page is overwritten with real projected content ───
def test_a_fallback_page_overwritten_with_real_content():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"MoviesPage.jsx": _fallback("MoviesPage"),
                             "ProfilesPage.jsx": _REAL.replace("MoviesPage", "ProfilesPage"),
                             "BrowseHomePage.jsx": _REAL.replace("MoviesPage", "BrowseHomePage")})
        before = (fe / "src" / "pages" / "MoviesPage.jsx").read_text()
        assert _is_generic_fallback_page(before), "precondition: MoviesPage is a fallback"
        out = repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES)
        after = (fe / "src" / "pages" / "MoviesPage.jsx").read_text()
        assert any("MoviesPage.jsx" in r for r in (out.get("repaired") or [])), out
        assert len(after) > len(before), "fallback replaced with bigger real content"
        assert ("fetch(" in after or "useEffect" in after), "carries a real api call"
        assert not _is_generic_fallback_page(after), "no longer a fallback per the detector"


# ── (b) a REAL lane-authored page is byte-identical (never clobbered) ─────────
def test_b_real_page_never_clobbered():
    with tempfile.TemporaryDirectory() as tmp:
        real_profiles = _REAL.replace("MoviesPage", "ProfilesPage")
        fe = _mk(tmp, _APP, {"MoviesPage.jsx": _REAL,
                             "ProfilesPage.jsx": real_profiles,
                             "BrowseHomePage.jsx": _REAL.replace("MoviesPage", "BrowseHomePage")})
        out = repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES)
        assert not (out.get("repaired") or []), "no fallbacks → nothing repaired"
        assert (fe / "src" / "pages" / "MoviesPage.jsx").read_text() == _REAL
        # a REAL profiles page must ALSO be left byte-identical (guard, not name-based)
        assert (fe / "src" / "pages" / "ProfilesPage.jsx").read_text() == real_profiles


# ── (c) a profiles-page fallback → real who's-watching template ──────────────
def test_c_profiles_fallback_gets_who_is_watching_template():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"MoviesPage.jsx": _REAL,
                             "ProfilesPage.jsx": _fallback("ProfilesPage"),
                             "BrowseHomePage.jsx": _REAL.replace("MoviesPage", "BrowseHomePage")})
        out = repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES)
        after = (fe / "src" / "pages" / "ProfilesPage.jsx").read_text()
        assert any("ProfilesPage.jsx" in r for r in (out.get("repaired") or [])), out
        assert "Who" in after and "watching" in after.lower(), "who's-watching heading"
        assert "profiles.map(" in after, "profile grid"
        assert "/api/profiles" in after, "fetches GET /api/profiles"
        assert "active_profile_id" in after, "sets the active profile on pick"
        assert "Add Profile" in after, "add-profile affordance"
        assert not _is_generic_fallback_page(after), "real projection, not a fallback"
        # the REAL MoviesPage was untouched
        assert (fe / "src" / "pages" / "MoviesPage.jsx").read_text() == _REAL


# ── (d) no App.jsx / no src → best-effort empty ──────────────────────────────
def test_d_best_effort_no_app_jsx():
    with tempfile.TemporaryDirectory() as tmp:
        fe = Path(tmp) / "app" / "frontend"
        (fe / "src").mkdir(parents=True)
        assert repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES) == {"repaired": []}
    with tempfile.TemporaryDirectory() as tmp:
        fe = Path(tmp) / "app" / "frontend"  # no src at all
        assert repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES) == {"repaired": []}


# ── (e) idempotent: a projected page is no longer a fallback → 2nd run no-op ──
def test_e_idempotent_second_run_noop():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mk(tmp, _APP, {"MoviesPage.jsx": _fallback("MoviesPage"),
                             "ProfilesPage.jsx": _fallback("ProfilesPage"),
                             "BrowseHomePage.jsx": _REAL.replace("MoviesPage", "BrowseHomePage")})
        first = repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES)
        assert first.get("repaired"), "first run fixes the fallbacks"
        movies1 = (fe / "src" / "pages" / "MoviesPage.jsx").read_text()
        profiles1 = (fe / "src" / "pages" / "ProfilesPage.jsx").read_text()
        second = repair_fallback_declared_pages(fe, ui_pages=_UI_PAGES)
        assert not (second.get("repaired") or []), "2nd run is a no-op"
        assert (fe / "src" / "pages" / "MoviesPage.jsx").read_text() == movies1
        assert (fe / "src" / "pages" / "ProfilesPage.jsx").read_text() == profiles1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
