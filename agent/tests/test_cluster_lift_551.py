"""#551 (netflix, run netflix-web-r104, 2026-08-06) — the deterministic final push on
the STABLE (post-#548 capture-stable) low-fidelity cluster. Each fix is spec/data-driven,
generalizable, byte-identical when the signal is absent, and carries no product literals.
Diagnosed from the r104 STABLE gate artifacts (verdict rationale + rendered PNGs +
emitted pages + design_system spec):

  FIX A — NAV search/bell invisible (cross-cutting, ~8 screens' iconography+components).
    The staged search/bell SVGs are authored with fill/stroke='currentColor'; loaded via
    <img> they can't inherit the nav's text color and paint black-on-dark (invisible).
    They ALSO masked the reliable inline-SVG chrome (_nav_chrome_454) by "covering" those
    labels in its skip set. FIX: drop search/notifications from the <img> asset channel so
    the inline-SVG chrome (currentColor inlined -> inherits) renders them, visibly.

  FIX B — new_and_popular rendered EMPTY (0.55, a blank page): its /api/titles/top10
    answered with a NAMED-collection envelope ({titles:[...]}) but the projected page read
    only data.items -> rows=[] -> empty rails + a permanent "Loading". FIX: fall back to the
    first array-valued property of the response object (the shape the app's api.js already
    tolerates). Byte-identical for {items}/{item}/bare-array.

  FIX C — browse_by_languages (0.40, worst) rendered a captioned 6-col GRID; the reference
    (and the design's OWN measured row1..row4 carousels) is landscape shelves + a language
    dropdown. FIX: a selector/preference NAME that ALSO carries >=2 measured content rails is
    a content BROWSE -> render ROWS; a true option-grid selector (no content rails) stays a
    GRID. Plus: distinguish the 'Original Language' TYPE selector from the language list so the
    two adjacent dropdowns don't collapse to one.

  FIX D — new_and_popular headings 'Top10 Tv'/'Top10 Movies' (abbreviated, copy 0.6): the
    rail-header extractor appended the id slug to the role, polluting the #472b capture ->
    de-slug fallback. FIX: extract from the ROLE alone ('Top 10 TV Shows'); the id still
    drives the de-slug fallback for a title-less role ('first rail' -> 'New on Netflix').

  FIX E — title_detail (0.55): episode runtime shown as a raw integer ('3120'); Like used a
    heart. FIX: a _fmtDur helper (seconds/minutes -> '52m'/'1h 34m') on episode + modal meta
    durations; a thumbs-up Like icon.
"""
import re

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _wants_rows_539, _render_reference_page, _ref_nav_jsx, _control_label_432b,
    _section_title_221, _REF_HELPERS_JS)


# --------------------------------- fixtures ---------------------------------

def _design(video=True):
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}},
         "assets": [], "screens": []}
    if video:
        d["assets"].append({"id": "m1", "file": "backdrops/m1.jpg", "type": "video",
                            "staged_path": "public/assets/backdrops/m1.jpg"})
    return d


_NAV = [("Home", "/browse"), ("Shows", "/shows")]
_TOP_NAV = {"id": "top-nav-bar",
            "role": "top navigation bar with logo, primary nav links, search, "
                    "notifications, profile", "region": [0.0, 0.0, 1.0, 0.06]}


def _bbl_screen():
    """browse_by_languages: 4 measured landscape carousels + 2 language dropdowns."""
    return {"name": "browse_by_languages", "route": "/browse/languages", "components": [
        dict(_TOP_NAV),
        {"id": "original-language-dropdown",
         "role": "dropdown for language type (Original/Dubbing/Subtitles) with open menu",
         "region": [0.685, 0.1, 0.83, 0.24]},
        {"id": "language-dropdown", "role": "open language selection dropdown",
         "region": [0.83, 0.1, 1.0, 0.95]},
        {"id": "row1-carousel", "role": "first row of title cards",
         "region": [0.0, 0.28, 0.83, 0.5], "geometry": {"columns": 8}},
        {"id": "row2-carousel", "role": "second row of title cards",
         "region": [0.0, 0.5, 0.83, 0.72], "geometry": {"columns": 12}},
        {"id": "row3-carousel", "role": "third row of title cards",
         "region": [0.0, 0.72, 0.83, 0.94], "geometry": {"columns": 10}},
        {"id": "row4-carousel", "role": "partial fourth row",
         "region": [0.0, 0.94, 0.83, 1.0], "geometry": {"columns": 7}},
    ]}


def _bbl_page():
    return {"name": "browse_by_languages", "route": "/browse/languages",
            "component": "BrowseByLanguagesPage", "apis_used": ["GET /api/titles"]}


def _nap_screen():
    return {"name": "new_and_popular", "route": "/new", "components": [
        dict(_TOP_NAV),
        {"id": "new-on-netflix-header", "role": "section title for first rail",
         "region": [0.03, 0.13, 0.3, 0.18]},
        {"id": "new-on-netflix-rail",
         "role": "horizontal row of landscape title cards with TOP 10 badges",
         "region": [0.03, 0.18, 1.0, 0.36], "geometry": {"columns": 6}},
        {"id": "top10-tv-header", "role": "section title for Top 10 TV Shows rail",
         "region": [0.03, 0.4, 0.35, 0.46]},
        {"id": "top10-tv-rail", "role": "ranked rail with large numerals 1-6",
         "region": [0.03, 0.46, 1.0, 0.7], "geometry": {"columns": 6}},
        {"id": "top10-movies-header", "role": "section title for Top 10 Movies rail",
         "region": [0.03, 0.72, 0.35, 0.78]},
        {"id": "top10-movies-rail", "role": "ranked rail with large numerals",
         "region": [0.03, 0.78, 1.0, 0.99], "geometry": {"columns": 6}},
    ]}


def _td_screen():
    return {"name": "title_detail", "route": "/title/:id", "kind": "overlay",
            "components": [
                {"id": "modal-container", "role": "centered detail modal for a title",
                 "region": [0.2, 0.03, 0.8, 1.0]},
                {"id": "episodes-header",
                 "role": "Episodes section title with season selector dropdown",
                 "region": [0.24, 0.86, 0.78, 0.92]},
                {"id": "episode-row-pilot",
                 "role": "First episode row: number, thumbnail, title, duration",
                 "region": [0.24, 0.955, 0.78, 1.0]}]}


_GRID = "gridTemplateColumns: 'repeat("


# ============ FIX A: nav search/bell as inline SVG (visible) ============

def test_551_nav_renders_inline_search_and_bell_for_media_app():
    out = _ref_nav_jsx(_NAV, "#e50914", vertical=False, design=_design(video=True))
    assert 'aria-label="Search"' in out and "<circle" in out       # inline magnifier
    assert 'aria-label="Notifications"' in out                     # inline bell


def test_551_nav_does_not_emit_invisible_currentcolor_img_for_search_bell():
    # the staged search/bell svgs must NOT be routed through <img> (currentColor ->
    # black-on-dark, invisible). Any staged search asset is rendered inline instead.
    design = _design(video=False)
    design["assets"].append({"id": "search", "file": "icons/search.svg", "type": "svg",
                             "staged_path": "public/assets/icons/search.svg"})
    design["screens"] = [{"components": [dict(_TOP_NAV)]}]  # nav role mentions 'search'
    out = _ref_nav_jsx(_NAV, "#e50914", vertical=False, design=design)
    assert 'src="/assets/icons/search.svg"' not in out            # not an <img>
    assert 'aria-label="Search"' in out                           # inline instead


def test_551_nav_byte_identical_when_no_search_signal():
    # a non-media app whose nav enumerates no search/notification utility -> the right
    # cluster is byte-identical to before (only the avatar chip, no search/bell).
    design = {"design_system": {"palette": {"bg": "#ffffff", "accent": "#2563eb"}},
              "assets": [], "screens": [{"components": [
                  {"id": "nav", "role": "top navigation bar with logo and links",
                   "region": [0.0, 0.0, 1.0, 0.06]}]}]}
    out = _ref_nav_jsx(_NAV, "#2563eb", vertical=False, design=design)
    assert 'aria-label="Search"' not in out
    assert 'aria-label="Notifications"' not in out


# ============ FIX B: response-shape robustness (empty-rail fix) ============

def test_551_projected_rows_fall_back_to_named_collection_envelope():
    out = _render_reference_page("NewAndPopularPage", {"route": "/new"}, _nap_screen(),
                                 _design(), _NAV, "/api/titles/top10")
    assert "Object.values(data).find((v) => Array.isArray(v))" in out
    # items/item/array branches still lead (byte-identical for those shapes)
    assert "Array.isArray(data && data.items)" in out
    assert "data && data.item ? [data.item]" in out


# ============ FIX C: browse_by_languages grid -> rows ============

def test_551_selector_with_content_rails_renders_rows():
    assert _wants_rows_539(_bbl_screen(), None, _bbl_page()) == "rows"


def test_551_browse_by_languages_renders_carousels_not_grid_no_aside():
    out = _render_reference_page("BrowseByLanguagesPage", _bbl_page(), _bbl_screen(),
                                 _design(), _NAV, "/api/titles")
    assert "overflow-x-auto" in out            # horizontal shelves (carousels)
    assert _GRID not in out                     # NOT the captioned poster grid
    assert "<aside" not in out                  # no invented language sidebar (#545 kept)


def test_551_selector_without_content_rails_stays_grid():
    # a TRUE option-grid selector (profile/account/settings picker) has no content
    # rails -> byte-identical GRID decision.
    for nm, route, comp in (("settings", "/settings", "SettingsPage"),
                            ("account", "/account", "AccountPage"),
                            ("preferences", "/preferences", "PreferencesPage")):
        screen = {"name": nm, "route": route, "components": [dict(_TOP_NAV)]}
        page = {"name": nm, "route": route, "component": comp}
        assert _wants_rows_539(screen, None, page) == "grid", nm


def test_551_two_language_dropdowns_get_distinct_labels():
    orig = {"id": "original-language-dropdown",
            "role": "dropdown for language type (Original/Dubbing/Subtitles)"}
    lang = {"id": "language-dropdown", "role": "open language selection dropdown"}
    assert _control_label_432b(orig) == "Original Language"
    assert _control_label_432b(lang) == "Language"


def test_551_browse_by_languages_shows_both_preference_dropdowns():
    out = _render_reference_page("BrowseByLanguagesPage", _bbl_page(), _bbl_screen(),
                                 _design(), _NAV, "/api/titles")
    assert "Original Language" in out and ">Language<" in out


# ============ FIX D: new_and_popular section headings ============

def test_551_ranked_rail_headings_from_role_not_abbreviated_slug():
    out = _render_reference_page("NewAndPopularPage", {"route": "/new"}, _nap_screen(),
                                 _design(), _NAV, "/api/titles/top10")
    assert "Top 10 TV Shows" in out and "Top 10 Movies" in out
    assert "Top10 Tv" not in out and "Top10 Movies" not in out


def test_551_titleless_positional_role_falls_back_to_deslug_id():
    # 'section title for first rail' (a POSITION, no curated title) -> the id de-slug
    # supplies the heading ('New on Netflix'), not the ordinal 'First'.
    out = _render_reference_page("NewAndPopularPage", {"route": "/new"}, _nap_screen(),
                                 _design(), _NAV, "/api/titles/top10")
    assert "New on Netflix" in out
    assert ">First<" not in out and "First</h3>" not in out


def test_551_ordinal_only_role_yields_no_title():
    assert _section_title_221("section title for first rail") == ""
    assert _section_title_221("section title for Top 10 TV Shows rail") == "Top 10 TV Shows"


# ============ FIX E: title_detail duration format + thumbs-up ============

def test_551_fmtdur_helper_present_and_used():
    assert "const _fmtDur" in _REF_HELPERS_JS
    out = _render_reference_page("TitleDetailPage",
                                 {"route": "/title/:id", "component": "TitleDetailPage"},
                                 _td_screen(), _design(), _NAV, "/api/titles/{id}")
    assert "const _fmtDur" in out
    # #782: both sites now go through `_durOf`, which picks the key AND knows its unit. The old
    # assertions pinned bare `.duration || .runtime` reads: 17% of episode tables and 4% of title
    # tables spell it `duration_min`/`duration_minutes`/`duration_seconds` and rendered no runtime.
    assert "_durOf(ep)" in out                                    # episode runtime
    assert "_durOf(cur)" in out                                   # modal meta band
    assert "ep.duration || ep.runtime" not in out


def test_551_title_detail_like_is_thumbs_up_not_heart():
    out = _render_reference_page("TitleDetailPage",
                                 {"route": "/title/:id", "component": "TitleDetailPage"},
                                 _td_screen(), _design(), _NAV, "/api/titles/{id}")
    assert 'aria-label="Like"' in out
    assert "\\u2661" not in out and "♡" not in out           # no heart glyph
    assert "M7 10v12" in out                                       # thumbs-up path


# ============ no-regression: passing screens unchanged ============

def _hero_rail_screen(name, route):
    return {"name": name, "route": route, "components": [
        dict(_TOP_NAV),
        {"id": "hero", "role": "hero billboard", "region": [0.0, 0.06, 1.0, 0.82],
         "assets": ["m1"]},
        {"id": "rail", "role": "horizontal carousel of tiles",
         "region": [0.0, 0.86, 1.0, 1.0], "geometry": {"columns": 6}}]}


def test_551_games_still_hero_rails_not_grid():
    s = _hero_rail_screen("games", "/games")
    page = {"name": "games", "route": "/games", "component": "GamesPage"}
    assert _wants_rows_539(s, None, page) != "grid"
    out = _render_reference_page("GamesPage", page, s, _design(), _NAV, "/api/titles")
    assert "justify-end overflow-hidden" in out      # hero billboard intact
    assert _GRID not in out                           # not a grid


def test_551_browse_home_and_my_list_archetype_unchanged():
    bh = {"name": "browse_home", "route": "/browse", "components": []}
    assert _wants_rows_539(bh, None, {"route": "/browse", "component": "BrowseHomePage"}) \
        in ("rows", None)                            # never grid (content home)
    ml = {"name": "my_list", "route": "/browse/my-list", "components": [
        {"id": "grid", "role": "grid of title cards", "region": [0.0, 0.1, 1.0, 1.0],
         "geometry": {"columns": 6, "rows": 4}}]}
    assert _wants_rows_539(ml, None, {"route": "/browse/my-list",
                                      "component": "MyListPage"}) == "grid"


def test_551_genre_category_stays_content_page_not_modal():
    s = _hero_rail_screen("genre_category", "/browse/genre/:genreId")
    page = {"name": "genre_category", "route": "/browse/genre/:genreId",
            "component": "GenreCategoryPage"}
    out = _render_reference_page("GenreCategoryPage", page, s, _design(), _NAV,
                                 "/api/genres/{id}/titles")
    assert "fixed inset-0 z-50" not in out           # content page, not a modal
    assert "flex min-h-screen" in out


# ============ no product literals ============

def test_551_no_product_literals():
    # NOTE: headings like 'New on Netflix' / 'Top 10 TV Shows' are DE-SLUGGED / extracted
    # from the DESIGN's own component ids/roles — never hardcoded by the projector. To
    # prove the CODE injects no product string, render a new_and_popular whose spec ids
    # are GENERIC: the output must carry no product token.
    nap_generic = {"name": "new_and_popular", "route": "/new", "components": [
        dict(_TOP_NAV),
        {"id": "new-releases-header", "role": "section title for first rail",
         "region": [0.03, 0.13, 0.3, 0.18]},
        {"id": "new-releases-rail", "role": "horizontal row of landscape title cards",
         "region": [0.03, 0.18, 1.0, 0.36], "geometry": {"columns": 6}},
        {"id": "top-charts-header", "role": "section title for Top Charts rail",
         "region": [0.03, 0.4, 0.35, 0.46]},
        {"id": "top-charts-rail", "role": "ranked rail with large numerals",
         "region": [0.03, 0.46, 1.0, 0.7], "geometry": {"columns": 6}}]}
    outs = [
        _render_reference_page("BrowseByLanguagesPage", _bbl_page(), _bbl_screen(),
                               _design(), _NAV, "/api/titles"),
        _render_reference_page("NewAndPopularPage", {"route": "/new"}, nap_generic,
                               _design(), _NAV, "/api/titles/top10"),
        _render_reference_page("TitleDetailPage",
                               {"route": "/title/:id", "component": "TitleDetailPage"},
                               _td_screen(), _design(), _NAV, "/api/titles/{id}"),
        _ref_nav_jsx(_NAV, "#e50914", vertical=False, design=_design()),
    ]
    for out in outs:
        low = (out or "").lower()
        for bad in ("netflix", "disney", "hulu", "spotify"):
            assert bad not in low


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
