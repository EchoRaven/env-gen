"""#428 (netflix r21/r24: components=0.333 WORST dim; verdict 'reference shows a
~5-col grid, implementation is horizontal rows' on browse_by_languages/movies/
shows/my_list — the bulk of the low screens): a single-collection CATALOG screen
gets decomposed into per-row bands, each caught by _is_rail_comp, so it shipped as
N horizontal poster carousels instead of ONE vertical grid (confirmed from r24's
generated BrowseByLanguagesPage.jsx: 4 overflow-x-auto rails + a hero <h1> showing
{cur} instead of the page name). FIX: no hero + <2 distinct curated section titles
⇒ render one vertical grid with a page heading. Genuine multi-rail homes (a hero
and/or >=2 distinct section titles) keep their rails. Generalizable — keys off
section-title distinctness, no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)

_DESIGN = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "poster-1", "file": "posters/p1.jpg", "type": "jpg",
                "dims": [400, 600],
                "staged_path": "public/assets/posters/p1.jpg"}],
}


def _render(screen, nav=(("Movies", "/movies"),), get_ep="/api/titles"):
    return _render_reference_page(
        "P", {}, screen, _DESIGN, list(nav), get_ep)


# ── a no-hero single collection whose rows classify as rails but carry no
#    distinct section titles → must become ONE grid, not carousels ──
_CATALOG = {"route": "/movies", "name": "movies", "components": [
    {"id": "grid-row-1", "role": "title thumbnails",
     "region": [0.0, 0.28, 1.0, 0.50], "geometry": {"columns": 5}},
    {"id": "grid-row-2", "role": "title thumbnails",
     "region": [0.0, 0.52, 1.0, 0.74], "geometry": {"columns": 5}}]}


def test_catalog_no_hero_generic_rows_render_grid():
    out = _render(_CATALOG)
    assert "gridTemplateColumns" in out, "catalog screen must render a grid"
    assert "overflow-x-auto" not in out, "must NOT ship horizontal rail carousels"


def test_catalog_grid_has_page_heading_and_measured_columns():
    # heading text is the page label (derived from the component name); assert the
    # static page-heading <h2> is present (a real page name, not a hero {cur} title)
    out = _render_reference_page(
        "MoviesPage", {}, _CATALOG, _DESIGN, [("Movies", "/movies")], "/api/titles")
    assert '<h2 className="mb-4 text-xl font-semibold">Movies</h2>' in out, \
        "grid must carry the page name as a heading (not a hero {cur} title)"
    assert "repeat(5, minmax(0, 1fr))" in out, "columns from the measured grid width"


# ── a genuine home: a hero over distinct curated rails → keep rails ──
_HOME = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "hero", "role": "hero billboard title art",
     "region": [0.0, 0.0, 1.0, 0.5], "assets": ["poster-1"]},
    {"id": "rail-trending", "role": 'poster rail of "Trending"',
     "region": [0.0, 0.55, 1.0, 0.75], "geometry": {"columns": 6}},
    {"id": "rail-top10", "role": 'poster rail of "Top 10"',
     "region": [0.0, 0.78, 1.0, 0.98], "geometry": {"columns": 6}}]}


def test_home_with_hero_keeps_rails():
    out = _render(_HOME, nav=(("Home", "/browse"),), get_ep="/api/titles")
    assert "overflow-x-auto" in out, "a hero+distinct-rails home must keep its rails"
    # hero banner present (not collapsed to a grid)
    assert "flex flex-col justify-end" in out


# ── no hero, but >=2 DISTINCT curated section titles → still a real multi-rail
#    screen, must NOT be flattened to one grid ──
_MULTI = {"route": "/new", "name": "new_and_popular", "components": [
    {"id": "rail-new", "role": 'poster rail of "New Releases"',
     "region": [0.0, 0.10, 1.0, 0.32], "geometry": {"columns": 6}},
    {"id": "rail-pop", "role": 'poster rail of "Popular"',
     "region": [0.0, 0.35, 1.0, 0.57], "geometry": {"columns": 6}}]}


def test_no_hero_but_distinct_section_titles_keeps_rails():
    out = _render(_MULTI, nav=(("New", "/new"),), get_ep="/api/titles")
    assert "overflow-x-auto" in out, \
        ">=2 distinct curated sections is a genuine multi-rail screen, not a grid"


# ── #430: a single narrow poster/title CARD must NOT be classed as a rail ──
# (r27 my_list over-decomposed into row + individual cards; card "The Crash" had
# 'poster' in its id → mis-counted as a rail + its item-name as a 2nd section title,
# defeating the grid detection). A rail must be a WIDE horizontal strip.
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _is_rail_comp)


def test_narrow_poster_card_is_not_a_rail():
    card = {"id": "my-list-poster-card-1", "role": "first title card thumbnail 'The Crash'",
            "region": [0.03, 0.26, 0.22, 0.48], "geometry": {"columns": 2}}
    assert _is_rail_comp(card) is False, "a single narrow poster card is not a rail"


def test_wide_poster_rail_still_a_rail():
    rail = {"id": "trending-rail", "role": "horizontal poster rail of trending",
            "region": [0.0, 0.55, 1.0, 0.78], "geometry": {"columns": 6}}
    assert _is_rail_comp(rail) is True, "a wide poster rail is still a rail"


def test_single_collection_with_stray_cards_grids():
    # a my_list-style screen: one wide row + individual narrow cards → ONE grid,
    # not rails (the stray cards must not inflate the section-title count)
    D = {"design_system": {"palette": {"bg": "#141414"}, "theme": {"default": "dark"}},
         "assets": [{"id": "p", "file": "posters/p.jpg", "type": "jpg",
                     "dims": [400, 600], "staged_path": "public/assets/posters/p.jpg"}]}
    scr = {"route": "/my-list", "name": "my_list", "components": [
        {"id": "row", "role": "horizontal row of saved title cards",
         "region": [0.02, 0.25, 0.55, 0.5], "geometry": {"columns": 5}},
        {"id": "poster-card-1", "role": "first title card thumbnail 'The Crash'",
         "region": [0.03, 0.26, 0.22, 0.48], "geometry": {"columns": 2}},
        {"id": "poster-card-2", "role": "second title card 'Avatar'",
         "region": [0.22, 0.26, 0.4, 0.48], "geometry": {"columns": 1}}]}
    out = _render_reference_page("MyListPage", {"route": "/my-list"}, scr, D,
                                 [("Home", "/browse")], "/api/my-list")
    assert "gridTemplateColumns" in out and "overflow-x-auto" not in out, \
        "single collection + stray cards must render one grid, not rails"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
