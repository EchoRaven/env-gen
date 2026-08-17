"""#547 (netflix, run netflix-web-r102, 2026-08-06) — raise the Part-A FLOOR by giving
two high-value screens DATA-correct projected pages, keyed off STABLE contract signals
(route :id param + the app's content-entity dataset + the REGISTERED endpoints), never
the analyst's per-run phrasing. Additive; byte-identical when the signal/spec/endpoint is
absent; no product literals.

#547a — TITLE_DETAIL data rebind. The projected detail MODAL (route /title/:id) fetched a
  mis-recorded LIST endpoint (/api/genres) and rendered rows[0], so the opened title
  showed a GENRE ('Drama') and the metadata band + episode rows (already in the markup)
  collapsed. FIX: a PARAM-ROUTE detail modal fetches the REGISTERED single-record
  /api/<content-entity>/{id} for the record + the child /api/<content-entity>/{id}/
  <episodes> collection for cur.episodes — NOT the list. (r102 title_detail: /api/genres
  -> /api/titles/{id} + /api/titles/{id}/episodes.)

#547b — GENRE_CATEGORY stub -> hero+rails. It shipped as a 223-byte <h2> stub for TWO
  reasons: (1) repair_stub_declared_pages resolved App.jsx routes with a naive regex that
  captured the ROUTE-GUARD wrapper (<RequireAuth><GenreCategoryPage/> -> 'RequireAuth'),
  so the wrapped stub PAGE was never seen/re-projected; (2) the param route carries no
  content collection in apis_used (its data is a PARENT-scoped child list), so even when
  projected it was data-starved. FIX: repair_stub is WRAPPER-AWARE (unwraps to the page),
  and a param-route category page retargets its GET at the REGISTERED
  /api/<parent>/{id}/<content-entity> list (genre_category -> /api/genres/{genreId}/titles),
  so the SAME reference hero+rails template ShowsPage/MoviesPage use populates.
"""
import os
import tempfile

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _project_page_component, _render_reference_page,
    _collection_detail_get_ep_547b, _detail_item_eps_547a,
    _registered_get_paths_547, repair_stub_declared_pages,
)


# --------------------------------- fixtures ---------------------------------

_REG = [
    "GET /api/titles", "GET /api/titles/{id}", "GET /api/titles/{id}/episodes",
    "GET /api/titles/trending", "GET /api/genres", "GET /api/genres/{id}/titles",
    "GET /api/profiles", "GET /api/my-list",
]

_TOP_NAV = {"role": "top navigation bar with logo and links", "id": "top-nav-bar",
            "region": [0.0, 0.0, 1.0, 0.07]}
_HERO = {"role": "full-bleed hero billboard background for featured title",
         "id": "hero-billboard", "region": [0.0, 0.07, 1.0, 0.62]}
_HERO_SYN = {"role": "short description paragraph for featured title", "id": "hero-synopsis"}
_ROW_HDR = {"role": "row title text", "id": "row-header-your-next-watch"}
_ROW = {"role": "horizontal rail of show tiles", "id": "content-row-your-next-watch",
        "region": [0.0, 0.62, 1.0, 0.92], "geometry": {"columns": 6, "rows": 1}}
_TILE = {"role": "show card", "id": "tile-1"}

_EP_HDR = {"role": "Episodes section title with season selector dropdown", "id": "episodes-header"}
_EP_ROW = {"role": "single episode list row with number, thumbnail, title, duration, description",
           "id": "episode-row"}


def _design(screens=None, dataset=True, registered=True):
    d = {
        "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                          "theme": {"default": "dark"}},
        "screens": screens or [],
    }
    if dataset:
        d["dataset"] = [{"id": "titles",
                         "columns": ["id", "name", "poster_url", "backdrop_url",
                                     "synopsis", "year", "maturity_rating", "duration"],
                         "records": 30}]
    if registered:
        d["_registered_get_endpoints"] = list(_REG)
    return d


def _genre_screen(route="/browse/genre/:genreId"):
    return {"name": "genre_category", "route": route, "kind": "page",
            "components": [_TOP_NAV, _HERO, _HERO_SYN, _ROW_HDR, _ROW, _TILE]}


def _detail_screen(route="/title/:id"):
    return {"name": "title_detail", "route": route, "kind": "page",
            "components": [_TOP_NAV, _HERO, _HERO_SYN, _EP_HDR, _EP_ROW]}


# ============================ #547a — title_detail =============================

def test_547a_detail_modal_fetches_item_and_episodes_not_list():
    design = _design(screens=[_detail_screen()])
    # the contract mis-attached the aux LIST endpoint (the r102 bug)
    page = {"name": "title_detail", "route": "/title/:id",
            "component": "TitleDetailPage", "apis_used": ["GET /api/genres"]}
    out = _project_page_component("TitleDetailPage", page, nav_routes=[("Shows", "/shows")],
                                  design=design, get_endpoints=[])
    # renders as a centered detail modal, populated from the ITEM (not a genres list)
    assert 'data-projected="ref"' in out
    assert "fixed inset-0 z-50" in out                     # centered modal, not app-shell
    assert "/api/titles/' + (params.id || '')" in out      # single-record fetch
    assert "/api/titles/' + (params.id || '') + '/episodes'" in out  # child episodes
    assert "/api/genres" not in out                        # the wrong endpoint is gone


def test_547a_helper_resolves_item_and_episodes_from_registered():
    design = _design()
    item, eps = _detail_item_eps_547a(
        {"route": "/title/:id"}, _detail_screen(), design)
    assert item == "/api/titles/{id}"
    assert eps == "/api/titles/{id}/episodes"


def test_547a_title_renders_from_record_not_a_genre():
    # cur is derived from the fetched RECORD (data.item), so _titleOf(cur) is the title,
    # and cur.episodes is fed by the episodes fetch — no genre bleed-through.
    design = _design(screens=[_detail_screen()])
    page = {"route": "/title/:id", "component": "TitleDetailPage",
            "apis_used": ["GET /api/genres"]}
    out = _project_page_component("TitleDetailPage", page, design=design, get_endpoints=[])
    assert "const _rec = (data && data.item)" in out       # record-first derivation
    assert "setEps" in out and "episodes:" in out          # episodes merged into cur


def test_547a_non_param_detail_dialog_is_byte_identical():
    # a detail/dialog overlay WITHOUT a param route (rate_dialog) never gets the item
    # fetch — no registered item endpoint is resolvable from a param-less route.
    item, eps = _detail_item_eps_547a({"route": "/rate"}, {"name": "rate_dialog"}, _design())
    assert item is None and eps is None


def test_547a_no_content_entity_no_rebind():
    # no content-entity dataset -> (None, None) -> the caller keeps its existing fetch.
    item, eps = _detail_item_eps_547a(
        {"route": "/title/:id"}, _detail_screen(), _design(dataset=False))
    assert item is None and eps is None


# ============================ #547b — genre_category ==========================

def test_547b_genre_category_emits_hero_rails_page_not_stub():
    design = _design(screens=[_genre_screen()])
    page = {"name": "genre_category", "route": "/browse/genre/:genreId",
            "component": "GenreCategoryPage", "apis_used": []}
    out = _project_page_component("GenreCategoryPage", page, nav_routes=[("Shows", "/shows")],
                                  design=design, get_endpoints=[])
    assert 'data-projected="ref"' in out                   # reference-structured
    assert "_railSlice" in out                             # rail markup
    assert "<section" in out                               # hero/main section band
    assert "fixed inset-0 z-50" not in out                 # a full page, NOT a modal
    # fetches the parent-scoped child collection, param-remapped to the ROUTE param (#536)
    assert "/api/genres/' + (params.genreId || '') + '/titles'" in out
    # NOT the 223-byte lone-heading stub
    assert 'text-center">\n      <h2' not in out


def test_547b_genre_category_retargets_aux_genres_list():
    # even when the contract attached the AUXILIARY /api/genres list, it retargets at
    # the parent-scoped titles collection (a genre page must list TITLES, not genres).
    design = _design(screens=[_genre_screen()])
    page = {"name": "genre_category", "route": "/browse/genre/:genreId",
            "component": "GenreCategoryPage", "apis_used": ["GET /api/genres"]}
    out = _project_page_component("GenreCategoryPage", page, design=design, get_endpoints=[])
    assert "/api/genres/' + (params.genreId || '') + '/titles'" in out


def test_547b_helper_resolves_child_collection():
    ep = _collection_detail_get_ep_547b({"route": "/browse/genre/:genreId"}, _design())
    assert ep == "/api/genres/{id}/titles"


def test_547b_helper_none_when_no_registered_child():
    # no registered /api/<parent>/{id}/<content-entity> -> None (byte-identical).
    d = _design(registered=False)
    assert _collection_detail_get_ep_547b({"route": "/browse/genre/:genreId"}, d) is None


def test_547b_helper_none_for_non_param_route():
    # a non-param route is not a collection-detail page -> None.
    assert _collection_detail_get_ep_547b({"route": "/shows"}, _design()) is None


def test_547b_spec_less_screen_still_yields_stub():
    # a page with NO design screen, NO apis, NO dataset/registry to resolve an endpoint
    # from, NON-param route -> the true last-resort stub (byte-identical to the pre-#547
    # fallback path; my #547 resolvers require a param route + registered child + content
    # entity, none of which are present here, so they no-op).
    page = {"name": "misc", "route": "/misc", "component": "MiscPage", "apis_used": []}
    out = _project_page_component(
        "MiscPage", page, design=_design(screens=[], dataset=False, registered=False),
        get_endpoints=[])
    assert '<h2 className="text-xl font-semibold">Misc</h2>' in out
    assert 'data-projected="ref"' not in out
    assert "_railSlice" not in out


# ==================== #547b — repair_stub is WRAPPER-AWARE ====================

_APP_JSX_WRAPPED = """import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import GenreCategoryPage from './pages/GenreCategoryPage.jsx';
function RequireAuth({ children }) { return children; }
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/browse/genre/:genreId" element={<RequireAuth><GenreCategoryPage /></RequireAuth>} />
      </Routes>
    </BrowserRouter>
  );
}
"""

_STUB_PAGE = """export default function GenreCategoryPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-8 py-16 text-center">
      <h2 className="text-xl font-semibold">Genre Category</h2>
    </div>
  );
}
"""


def _write_frontend(tmp, design_screens):
    import json
    front = os.path.join(tmp, "app", "frontend")
    os.makedirs(os.path.join(front, "src", "pages"), exist_ok=True)
    with open(os.path.join(front, "src", "App.jsx"), "w") as f:
        f.write(_APP_JSX_WRAPPED)
    with open(os.path.join(front, "src", "pages", "GenreCategoryPage.jsx"), "w") as f:
        f.write(_STUB_PAGE)
    # design/design_system.json two levels up from app/frontend
    dz = os.path.join(tmp, "app", "design")  # not used; _load_design looks at ../../design
    design_dir = os.path.join(tmp, "app", "design")
    # _load_design_for_projection reads <frontend>.parent.parent / design / design_system.json
    # frontend = app/frontend -> parent.parent = app-parent = tmp; design at tmp/design
    os.makedirs(os.path.join(tmp, "design"), exist_ok=True)
    with open(os.path.join(tmp, "design", "design_system.json"), "w") as f:
        json.dump({"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                                     "theme": {"default": "dark"}},
                   "screens": design_screens,
                   "dataset": [{"id": "titles",
                                "columns": ["id", "name", "poster_url", "backdrop_url", "synopsis"],
                                "records": 30}]}, f)
    return front


def test_547b_repair_stub_reprojects_wrapped_genre_stub():
    # The stub PAGE is wrapped in <RequireAuth> in App.jsx — the pre-#547 naive
    # _ROUTE_ELEMENT regex captured 'RequireAuth', so this stub was NEVER re-projected.
    # It must now be unwrapped, detected, and re-projected to the hero+rails page.
    with tempfile.TemporaryDirectory() as tmp:
        front = _write_frontend(tmp, [_genre_screen()])
        page_path = os.path.join(front, "src", "pages", "GenreCategoryPage.jsx")
        before = open(page_path).read()
        assert len(before.encode()) < 300                  # the 223-byte stub
        rep = repair_stub_declared_pages(
            front, ui_pages=[{"route": "/browse/genre/:genreId",
                              "component": "GenreCategoryPage", "apis_used": []}])
        after = open(page_path).read()
        assert rep["repaired"], "wrapped stub was not repaired"
        assert len(after.encode()) > 3000                  # a real projected page
        assert 'data-projected="ref"' in after
        assert "_railSlice" in after


def test_547b_repair_stub_leaves_real_page_untouched():
    # a substantial lane-authored page (not a definitive stub) is NEVER clobbered.
    with tempfile.TemporaryDirectory() as tmp:
        front = _write_frontend(tmp, [_genre_screen()])
        page_path = os.path.join(front, "src", "pages", "GenreCategoryPage.jsx")
        real = ("import { useState } from 'react';\n"
                "export default function GenreCategoryPage() {\n"
                "  const [x] = useState(0);\n"
                "  return <div>" + ("real content " * 60) + "{x}</div>;\n}\n")
        open(page_path, "w").write(real)
        repair_stub_declared_pages(
            front, ui_pages=[{"route": "/browse/genre/:genreId",
                              "component": "GenreCategoryPage", "apis_used": []}])
        assert open(page_path).read() == real              # untouched


def test_547_registered_get_paths_helper():
    paths = _registered_get_paths_547(_design())
    assert "/api/titles/{id}" in paths
    assert "/api/genres/{id}/titles" in paths
    assert _registered_get_paths_547({"_registered_get_endpoints": []}) == []
