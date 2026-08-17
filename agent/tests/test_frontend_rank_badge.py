"""#435 (netflix r29 judge across browse screens: "Add TOP 10 badges", "Missing
red accent badges (Top 10, New Season)"). The visual gate scores STATIC
screenshots, so a hover-only affordance scores nothing — the badge must be
REST-VISIBLE. FIX: on a rail whose section title is a NUMBERED ranked list
('Top 10', 'Top 50', "Today's Top Ten"), each card gets a rest-visible rank
numeral badge in the brand accent. Fires ONLY on ranked rails (a generic Top-N /
Top-charts UI pattern, no product literals); every other rail is byte-identical.
Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _card_rank_badge_435, _render_reference_page)


def test_badge_fires_on_top_n_titles():
    for hdr in ("Top 10", "Top 10 in the U.S.", "Today's Top Ten", "Top 50 Songs"):
        out = _card_rank_badge_435(hdr, "#e50914")
        assert out, f"{hdr!r} is a ranked list → badge"
        assert "#e50914" in out and "absolute" in out and "(i + 1)" in out


def test_badge_absent_on_unranked_titles():
    for hdr in ("Trending Now", "Popular on Netflix", "New Releases", "Because You Watched", ""):
        assert _card_rank_badge_435(hdr, "#e50914") == "", f"{hdr!r} is not a ranked list"


# ── integration: a Top 10 rail gets rank badges + relative cards; a plain rail doesn't
_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": []}


def _render(rail_role):
    scr = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.05, 1.0, 0.55]},
        {"id": "rail", "role": rail_role, "region": [0.0, 0.6, 1.0, 0.82],
         "geometry": {"columns": 6}}]}
    return _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, _DESIGN,
                                  [("Home", "/browse")], "/api/titles")


def test_top10_rail_renders_giant_numeral():
    # #455: a ranked RAIL now carries the SIGNATURE giant OUTLINED numeral (not the
    # #435 small corner badge, which #455 replaced in the rail path).
    out = _render('poster rail of "Top 10 in the U.S. Today"')
    assert "{i + 1}" in out and "WebkitTextStroke" in out, "giant outlined rank numeral"
    assert "items-end" in out, "numeral + poster laid out side-by-side"
    assert "{'#' + (i + 1)}" not in out, "the small corner badge is replaced in the rail path"


def test_plain_rail_has_no_rank_numeral():
    out = _render('poster rail of "Trending Now"')
    # the small corner badge is replaced in the rail path (#455) — never emitted
    assert "{'#' + (i + 1)}" not in out
    # A single-rail page is wrapped by #531's runtime multi-row deriver. The DECLARED
    # plain rail is the *fallback* (rendered when _deriveRows returns null); it must be
    # byte-identical to a normal poster rail — no giant #455 numeral, no `items-end`.
    _fb = out[out.index("if (!_dr) return (<>"):
              out.index("\n            return (<>\n", out.index("if (!_dr) return (<>"))]
    assert "WebkitTextStroke" not in _fb and "items-end" not in _fb, \
        "the declared non-ranked rail stays byte-identical to a normal poster rail"
    # #531's derived rows share one card template; the giant numeral + its `items-end`
    # layout appear ONLY inside the g.ranked branch (the derived 'Top 10' shelf), so a
    # non-ranked derived row renders a plain poster card. Every occurrence is gated →
    # no unranked row can ever display a rank numeral.
    for _m in ("WebkitTextStroke", "items-end"):
        _i = out.find(_m)
        while _i != -1:
            assert "g.ranked ?" in out[max(0, _i - 300):_i], \
                f"{_m} must be gated on g.ranked (derived Top-10 only), never unconditional"
            _i = out.find(_m, _i + 1)


# ── #435 also covers the CATALOG-GRID path: a standalone 'Top N' collection that
#    collapses to one grid (charts-app style) still gets rest-visible rank numerals ──
def test_top_n_catalog_grid_gets_rank_badges():
    # a single ranked collection, no hero, no distinct sibling titles → catalog grid
    scr = {"route": "/charts", "name": "charts", "components": [
        {"id": "top50-rail", "role": 'rail of "Top 50 Global"',
         "region": [0.0, 0.2, 1.0, 0.5], "geometry": {"columns": 6}}]}
    out = _render_reference_page("ChartsPage", {"route": "/charts"}, scr, _DESIGN,
                                 [("Charts", "/charts")], "/api/tracks")
    assert "gridTemplateColumns" in out and "overflow-x-auto" not in out, "renders one grid"
    assert "{'#' + (i + 1)}" in out, "a Top-N grid must still carry rank numerals"


def test_plain_catalog_grid_no_rank_badges():
    scr = {"route": "/movies", "name": "movies", "components": [
        {"id": "grid", "role": "grid of poster cards for the catalog",
         "region": [0.0, 0.2, 1.0, 0.5], "geometry": {"columns": 5}}]}
    out = _render_reference_page("MoviesPage", {"route": "/movies"}, scr, _DESIGN,
                                 [("Movies", "/movies")], "/api/titles")
    assert "{'#' + (i + 1)}" not in out, "non-ranked catalog grid stays badge-free"


# ── #439: hero TOP-N rank badge (data-driven, uses semantic.top10_red else accent) ──
def _hero_render(design):
    scr = {"route": "/browse/movies", "name": "movies", "components": [
        {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.05, 1.0, 0.6]},
        {"id": "rail", "role": 'poster rail of "Gems"', "region": [0, 0.65, 1, 0.85],
         "geometry": {"columns": 6}}]}
    return _render_reference_page("MoviesPage", {"route": "/browse/movies"}, scr, design,
                                  [("Movies", "/browse/movies")], "/api/titles")


def test_hero_top10_badge_uses_semantic_color():
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914",
                                       "semantic": {"top10_red": "#e50914"}},
                           "theme": {"default": "dark"}}, "assets": []}
    out = _hero_render(d)
    assert "TOP 10" in out and "cur.top10_rank || cur.rank" in out, "data-driven rank badge"
    assert "#e50914" in out


def test_hero_top10_badge_falls_back_to_accent_without_semantic():
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#1db954"},
                           "theme": {"default": "dark"}}, "assets": []}
    out = _hero_render(d)
    assert "TOP 10" in out and "#1db954" in out, "uses the app accent when no semantic.top10_red"


# ── #445: hero mute toggle, gated on staged VIDEO (media context only) ──
def test_hero_mute_toggle_only_with_video():
    dv = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                            "theme": {"default": "dark"}},
          "assets": [{"id": "t", "type": "video", "file": "video/t.mp4"}]}
    assert 'aria-label="Mute"' in _hero_render(dv) and "<svg" in _hero_render(dv)


def test_hero_no_mute_toggle_without_video():
    dn = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                            "theme": {"default": "dark"}},
          "assets": [{"id": "p", "type": "jpg", "file": "posters/p.jpg"}]}
    assert 'aria-label="Mute"' not in _hero_render(dn), "non-media hero has no mute toggle"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
