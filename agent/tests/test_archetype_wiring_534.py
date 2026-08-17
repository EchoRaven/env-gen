"""#534/#535/#536/#537 (netflix, run netflix-web-r98, 2026-08-06) — four
generalizable projector fixes that close the visual-fidelity gap where a route
serves the WRONG archetype / stale template while the CORRECT component already
exists in the emitted app but is UNWIRED.

GROUND TRUTH (netflix-web-r98 judge):
  - title_detail 0.06 — /title/:id shipped a full-screen VIDEO PLAYER (scrubber/
    transport controls). The projector mis-resolves the detail route to the PLAYER
    design screen (title_detail is kind=overlay, excluded from the page-kind fuzzy
    match), so it emits a player — yet a correct components/TitleDetailModal.jsx
    already exists, unwired.
  - my_list 0.30 — a stale inline <nav> (duplicate 'Browse', 'Sign out' link) +
    generic contact-list + 'No data yet'; it does NOT use the shared AppHeader +
    poster grid the other catalog pages use (its route never resolves to a design
    screen — 'my'/'list' are stopword-stripped).
  - genre_category ~0.40 — a visible 'Error: HTTP 404': the fetch derives
    params.<endpointParam> ('id' from /api/genres/{id}/titles) but useParams()
    returns the ROUTE param ('genreId' from /browse/genre/:genreId) -> id
    undefined -> /api/genres//titles -> 404.
  - browse_home_rows 0.50 — the hero fills the fold; a bright/gold backdrop washes
    the title out (scrim too weak).

FIXES:
  #534 wire_detail_modal_534 — mount the lane's existing detail-modal component at
       the detail param route (not a player). Byte-identical when absent.
  #535 wire_owned_list_shell_535 — an owned-items list page (My List / Watchlist /
       Favorites) gets the shared nav + poster-grid shell. Byte-identical when the
       nav/grid components are absent or the page already uses them.
  #536 _render_reference_page — remap the fetch to the ROUTE's own param name when
       it differs from the endpoint's (fixes the 404); suppress raw 'Error: HTTP'
       display (graceful empty state). Byte-identical when the names match.
  #537 _render_reference_page — measured hero height capped <=62vh; a darker/taller
       hero scrim for legibility over bright backdrops. Region-derived height (no
       measured value) is byte-identical.
"""
import re
import tempfile
from pathlib import Path

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page, wire_detail_modal_534, wire_owned_list_shell_535)


# ───────────────────────────── shared fixtures ─────────────────────────────

_MODAL_SRC = (
    "import React from 'react';\n"
    "import { useNavigate } from 'react-router-dom';\n"
    "export default function TitleDetailModal({ titleId, onClose }) {\n"
    "  return <div className=\"fixed inset-0\">detail {titleId}</div>;\n"
    "}\n")

_PLAYER_PAGE_SRC = (
    "// framework-projected page (reference-structured)\n"
    "import { useState, useEffect } from 'react';\n"
    "import { useParams } from 'react-router-dom';\n"
    "export default function TitleDetailPage() {\n"
    "  return (<div><button aria-label=\"Pause\">||</button>"
    "<div className=\"scrub\" /><button aria-label=\"Fullscreen\" /></div>);\n"
    "}\n")

_APP_SRC = (
    "import { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
    "export default function App() {\n"
    "  return (<BrowserRouter><Routes>\n"
    "    <Route path=\"/browse\" element={<BrowseHomePage />} />\n"
    "    <Route path=\"/title/:id\" element={<TitleDetailPage />} />\n"
    "    <Route path=\"/watch/:titleId\" element={<PlayerPage />} />\n"
    "  </Routes></BrowserRouter>);\n"
    "}\n")

_APPHEADER_SRC = (
    "// framework-projected nav (#520) — deterministic top-nav.\n"
    "export default function AppHeader() {\n"
    "  return (<nav><a href=\"/browse\">Home</a></nav>);\n"
    "}\n")

_POSTERGRID_SRC = (
    "import React from 'react';\n"
    "export default function PosterGrid({ items = [] }) {\n"
    "  return (<div className=\"grid\">{items.map((t, i) => <div key={i} />)}</div>);\n"
    "}\n")

_STALE_MYLIST_SRC = (
    "import React, { useState, useEffect } from 'react';\n"
    "import { Link, useNavigate } from 'react-router-dom';\n"
    "export default function MyListPage() {\n"
    "  const [rows, setRows] = useState([]);\n"
    "  useEffect(() => { fetch('/api/my-list').then(r => r.json()).then(setRows); }, []);\n"
    "  return (<div>\n"
    "    <nav><Link to=\"/browse\">Browse</Link><a href=\"/logout\">Sign out</a></nav>\n"
    "    <ul>{rows.length ? rows.map((r, i) => <li key={i}>{r.name}</li>) : <p>No data yet</p>}</ul>\n"
    "  </div>);\n"
    "}\n")


def _mk_frontend(components: dict, pages: dict, app_src: str = None):
    """Build a throwaway app/frontend tree; returns its Path."""
    root = Path(tempfile.mkdtemp())
    fe = root / "app" / "frontend"
    (fe / "src" / "components").mkdir(parents=True)
    (fe / "src" / "pages").mkdir(parents=True)
    for name, src in components.items():
        (fe / "src" / "components" / (name + ".jsx")).write_text(src, encoding="utf-8")
    for name, src in pages.items():
        (fe / "src" / "pages" / (name + ".jsx")).write_text(src, encoding="utf-8")
    if app_src is not None:
        (fe / "src" / "App.jsx").write_text(app_src, encoding="utf-8")
    return fe


# ══════════════════════════ #534 detail-modal wiring ══════════════════════════

def test_534_detail_route_mounts_modal_not_player():
    fe = _mk_frontend(
        {"TitleDetailModal": _MODAL_SRC},
        {"TitleDetailPage": _PLAYER_PAGE_SRC}, _APP_SRC)
    rep = wire_detail_modal_534(str(fe))
    assert rep.get("wired") == "TitleDetailPage"
    assert rep.get("modal") == "TitleDetailModal"
    out = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    assert "import TitleDetailModal from '../components/TitleDetailModal.jsx';" in out
    assert "<TitleDetailModal" in out
    assert "titleId={params.id}" in out                 # id-prop from route param
    assert "onClose={() => nav(-1)}" in out
    # the player markers are gone
    for player in ('aria-label="Pause"', "scrub", 'aria-label="Fullscreen"'):
        assert player not in out, f"player marker {player!r} still present"


def test_534_id_prop_detected_from_modal_signature():
    # a modal that destructures `id` (not titleId) gets `id=` wired
    modal = _MODAL_SRC.replace("{ titleId, onClose }", "{ id, onClose }")
    fe = _mk_frontend({"TitleDetailModal": modal},
                      {"TitleDetailPage": _PLAYER_PAGE_SRC}, _APP_SRC)
    wire_detail_modal_534(str(fe))
    out = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    assert "id={params.id}" in out


def test_534_byte_identical_without_modal_component():
    fe = _mk_frontend({}, {"TitleDetailPage": _PLAYER_PAGE_SRC}, _APP_SRC)
    before = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    rep = wire_detail_modal_534(str(fe))
    after = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    assert rep.get("wired") is None and after == before


def test_534_player_watch_route_never_rewired():
    # only the DETAIL route is touched; the player/watch route stays a player
    fe = _mk_frontend(
        {"TitleDetailModal": _MODAL_SRC},
        {"TitleDetailPage": _PLAYER_PAGE_SRC,
         "PlayerPage": _PLAYER_PAGE_SRC.replace("TitleDetailPage", "PlayerPage")},
        _APP_SRC)
    wire_detail_modal_534(str(fe))
    player = (fe / "src" / "pages" / "PlayerPage.jsx").read_text()
    assert "TitleDetailModal" not in player       # watch route untouched


def test_534_idempotent_when_already_mounted():
    fe = _mk_frontend({"TitleDetailModal": _MODAL_SRC},
                      {"TitleDetailPage": _PLAYER_PAGE_SRC}, _APP_SRC)
    wire_detail_modal_534(str(fe))
    once = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    rep2 = wire_detail_modal_534(str(fe))
    twice = (fe / "src" / "pages" / "TitleDetailPage.jsx").read_text()
    assert rep2.get("wired") is None and twice == once


# ═══════════════════════════ #535 owned-list shell ═══════════════════════════

def test_535_mylist_gets_shared_shell():
    fe = _mk_frontend(
        {"AppHeader": _APPHEADER_SRC, "PosterGrid": _POSTERGRID_SRC},
        {"MyListPage": _STALE_MYLIST_SRC})
    rep = wire_owned_list_shell_535(str(fe))
    assert rep.get("wired") == ["MyListPage.jsx"]
    assert rep.get("nav") == "AppHeader" and rep.get("grid") == "PosterGrid"
    out = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    assert "import AppHeader from '../components/AppHeader.jsx';" in out
    assert "import PosterGrid from '../components/PosterGrid.jsx';" in out
    assert "<AppHeader />" in out
    assert "<PosterGrid items={rows}" in out
    assert "/api/my-list" in out                       # keeps the page's own endpoint
    # the stale inline nav + 'No data yet' + Sign out are gone
    assert "Sign out" not in out and "No data yet" not in out
    assert "<nav>" not in out
    # a graceful empty state (not a bare 'No data yet')
    assert "Titles you add will appear here." in out


def test_535_byte_identical_without_poster_grid():
    fe = _mk_frontend({"AppHeader": _APPHEADER_SRC},
                      {"MyListPage": _STALE_MYLIST_SRC})
    before = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    rep = wire_owned_list_shell_535(str(fe))
    after = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    assert rep.get("wired") == [] and after == before


def test_535_byte_identical_without_nav():
    fe = _mk_frontend({"PosterGrid": _POSTERGRID_SRC},
                      {"MyListPage": _STALE_MYLIST_SRC})
    before = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    rep = wire_owned_list_shell_535(str(fe))
    after = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    assert rep.get("wired") == [] and after == before


def test_535_skips_page_already_using_shell():
    # a page that already imports the shared nav is not clobbered (byte-identical)
    good = ("import AppHeader from '../components/AppHeader';\n"
            "export default function MyListPage() { return <div><AppHeader /></div>; }\n")
    fe = _mk_frontend({"AppHeader": _APPHEADER_SRC, "PosterGrid": _POSTERGRID_SRC},
                      {"MyListPage": good})
    before = (fe / "src" / "pages" / "MyListPage.jsx").read_text()
    wire_owned_list_shell_535(str(fe))
    assert (fe / "src" / "pages" / "MyListPage.jsx").read_text() == before


def test_535_non_owned_pages_untouched():
    fe = _mk_frontend({"AppHeader": _APPHEADER_SRC, "PosterGrid": _POSTERGRID_SRC},
                      {"MoviesPage": _STALE_MYLIST_SRC.replace("MyListPage", "MoviesPage")})
    before = (fe / "src" / "pages" / "MoviesPage.jsx").read_text()
    wire_owned_list_shell_535(str(fe))
    assert (fe / "src" / "pages" / "MoviesPage.jsx").read_text() == before


# ═══════════════════════ #536 genre endpoint / error ════════════════════════

def _design(lc=None):
    ds = {"palette": {"bg": "#141414", "accent": "#e50914"},
          "theme": {"default": "dark"}}
    if lc is not None:
        ds["layout_constants"] = lc
    return {"design_system": ds,
            "assets": [{"id": "m1", "file": "backdrops/m1.jpg", "type": "jpg",
                        "staged_path": "public/assets/backdrops/m1.jpg"}]}


_CATALOG_SCREEN = {"route": "/browse/genre/:slug", "name": "genre_category",
                   "components": [
                       {"id": "hero", "region": [0.0, 0.0, 1.0, 0.56],
                        "role": "hero billboard title art", "assets": ["m1"]},
                       {"id": "rail", "region": [0.0, 0.6, 1.0, 0.75],
                        "role": "horizontal poster rail",
                        "geometry": {"columns": 6, "rows": 1}}]}


def test_536_fetch_uses_route_param_not_endpoint_param():
    page = {"route": "/browse/genre/:genreId", "name": "genre_category"}
    out = _render_reference_page("GenreCategoryPage", page, _CATALOG_SCREEN,
                                 _design(), [("Home", "/browse")],
                                 "/api/genres/{id}/titles")
    # remapped to the ROUTE's own param -> resolves; the empty-id 404 path is gone
    assert "(params.genreId || '')" in out
    assert "'/api/genres/' + (params.id" not in out          # no /api/genres//titles


def test_536_byte_identical_when_param_names_match():
    # /title/:id + /api/titles/{id} -> both 'id' -> unchanged fetch target
    page = {"route": "/title/:id", "name": "title_detail"}
    out = _render_reference_page("TitleDetailPage", page, _CATALOG_SCREEN,
                                 _design(), [("Home", "/browse")], "/api/titles/{id}")
    assert "'/api/titles/' + (params.id || '')" in out


def test_536_no_param_endpoint_unchanged():
    out = _render_reference_page("MoviesPage", {"route": "/movies"}, _CATALOG_SCREEN,
                                 _design(), [("Home", "/browse")], "/api/titles")
    assert "fetch('/api/titles'," in out


def test_536_raw_http_error_suppressed():
    out = _render_reference_page("GenreCategoryPage",
                                 {"route": "/browse/genre/:genreId"},
                                 _CATALOG_SCREEN, _design(),
                                 [("Home", "/browse")], "/api/genres/{id}/titles")
    # the catch suppresses HTTP-status errors instead of surfacing 'Error: HTTP 404'
    assert "/\\bHTTP\\b/.test(String(e))" in out
    assert ".catch((e) => setError(String(e)))" not in out


# ═════════════════════════════ #537 hero polish ═════════════════════════════

_HERO_SCREEN = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "hero", "region": [0.0, 0.0, 1.0, 0.80],
     "role": "hero billboard title art", "assets": ["m1"]},
    {"id": "rail", "region": [0.0, 0.85, 1.0, 0.98],
     "role": "horizontal poster rail", "geometry": {"columns": 6, "rows": 1}}]}


def test_537_measured_hero_capped_at_62():
    out = _render_reference_page("BrowseHomePage", {}, _HERO_SCREEN,
                                 _design({"hero_backdrop_height_vh": 80}),
                                 [("Home", "/browse")], "/api/titles")
    m = re.search(r"minHeight: '(\d+)vh'", out)
    assert m and int(m.group(1)) <= 62


def test_537_region_derived_height_byte_identical():
    # no measured value -> today's region-derived height (0.80*100 clamped) is kept
    out = _render_reference_page("BrowseHomePage", {}, _HERO_SCREEN, _design(),
                                 [("Home", "/browse")], "/api/titles")
    assert "minHeight: '80vh'" in out


def test_537_hero_scrim_strengthened():
    out = _render_reference_page("BrowseHomePage", {}, _HERO_SCREEN, _design(),
                                 [("Home", "/browse")], "/api/titles")
    # a darker bottom + a taller multi-stop ramp than the old 0.85->0.25@55%
    assert "rgba(0,0,0,0.9) 0%" in out
    assert out.count("rgba(0,0,0,") >= 4                     # multi-stop scrim
    # the weak old ramp is gone
    assert "rgba(0,0,0,0.25) 55%" not in out


def test_537_browse_home_still_emits_hero_and_rows():
    # regression: the passing browse_home keeps its hero + data-derived rows
    out = _render_reference_page("BrowseHomePage", {}, _HERO_SCREEN, _design(),
                                 [("Home", "/browse")], "/api/titles")
    assert "minHeight:" in out and "absolute inset-0 h-full w-full object-cover" in out
    assert "_deriveRows" in out or "_railSlice" in out


# ────────────────────────────── no product literals ──────────────────────────

def test_no_product_literals_in_emitted_shell_and_pages():
    fe = _mk_frontend(
        {"AppHeader": _APPHEADER_SRC, "PosterGrid": _POSTERGRID_SRC,
         "TitleDetailModal": _MODAL_SRC},
        {"MyListPage": _STALE_MYLIST_SRC, "TitleDetailPage": _PLAYER_PAGE_SRC},
        _APP_SRC)
    wire_owned_list_shell_535(str(fe))
    wire_detail_modal_534(str(fe))
    for p in ("MyListPage", "TitleDetailPage"):
        low = (fe / "src" / "pages" / (p + ".jsx")).read_text().lower()
        for bad in ("netflix", "disney", "hulu", "spotify"):
            assert bad not in low, f"product literal {bad!r} leaked into {p}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
