"""#538 (netflix, run netflix-web-r99) — the archetype classifier in
`frontend_scaffold._render_reference_page` mis-collapsed a genuine multi-rail home
into a single flat grid whenever the design analyst gave the header bands GENERIC,
title-less roles ("row title for first rail") instead of quoted titles.

Root cause: `_is_catalog_grid` was `hero is None and rails and len(_sec_titles) < 2`.
`_sec_titles` is built by running `_section_title_221` over each header/rail role; a
generic header role with no quoted title returns '' (its #459 rail-noun filter), so
`_sec_titles` fell to 0 and a 4-header-band + 4-rail home (new_and_popular) rendered
as ONE 6-col grid (r99 0.32) instead of stacked carousels (r98 rows 0.70).

FIX #538 (primary): count distinct HEADER BANDS as an alternative multi-section
signal — `>= 2` real header bands above the rails ⇒ render ROWS even when the bands
carry no extractable title. FIX #538 (booster): `_rail_header` de-slugs a matched
header band's OWN id ('new-on-netflix-header' → 'New on Netflix') as a last-resort
heading when neither role yields a curated title.

No product literals — keyed purely off structural signals (header-band count, id
de-slug). Sibling GRID pages (my_list / browse_by_languages) have 0 header bands so
they STAY grids; quoted-title homes (r98) already had `_sec_titles >= 2` so they are
byte-identical.
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page, _deslug_header_538)


# ─────────────────────────────── fixtures ───────────────────────────────

def _design():
    return {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                              "theme": {"default": "dark"}},
            "assets": [{"id": "m1", "file": "backdrops/m1.jpg", "type": "video",
                        "staged_path": "public/assets/backdrops/m1.jpg"}]}


def _render(screen, name="NewAndPopularPage", get_ep="/api/titles"):
    return _render_reference_page(name, {"route": screen.get("route")}, screen,
                                  _design(), [("Home", "/")], get_ep)


def _hdr(cid, role, y0, y1):
    return {"id": cid, "role": role, "region": [0.0, y0, 1.0, y1]}


def _rail(role, y0, y1, cols=6):
    return {"id": role.replace(" ", "-"), "role": role,
            "region": [0.0, y0, 1.0, y1], "geometry": {"columns": cols, "rows": 1}}


# 4 TITLE-LESS header bands (generic role, curated name only in the id slug) each
# stacked directly above its rail — the r99 new_and_popular case. All comps sit in
# the "main" band (0.22 < y < 0.85) so the rail pool sees them.
def _titleless_multirail_screen():
    return {"route": "/new", "name": "new_and_popular", "components": [
        _hdr("new-on-netflix-header", "row title for first rail", 0.24, 0.27),
        _rail("horizontal poster rail one", 0.28, 0.37),
        _hdr("coming-this-week-header", "row title for second rail", 0.38, 0.41),
        _rail("horizontal poster rail two", 0.42, 0.51),
        _hdr("top-10-in-the-us-header", "row title for third rail", 0.52, 0.55),
        _rail("horizontal poster rail three", 0.56, 0.65),
        _hdr("worth-the-wait-header", "row title for fourth rail", 0.66, 0.69),
        _rail("horizontal poster rail four", 0.70, 0.79),
    ]}


# 0 header bands: a single collection decomposed into per-row rails (my_list /
# browse_by_languages) — must STAY a grid.
def _no_header_grid_screen():
    return {"route": "/my-list", "name": "my_list", "components": [
        _rail("poster row alpha", 0.24, 0.37),
        _rail("poster row beta", 0.40, 0.53),
        _rail("poster row gamma", 0.56, 0.69),
    ]}


# quoted-title header bands (r98) — _sec_titles >= 2 already ⇒ rows, byte-identical.
def _quoted_header_screen():
    return {"route": "/new", "name": "new_and_popular", "components": [
        _hdr("hdr0", 'section title "New on Netflix"', 0.24, 0.27),
        _rail("horizontal poster rail one", 0.28, 0.37),
        _hdr("hdr1", 'section title "Coming This Week"', 0.38, 0.41),
        _rail("horizontal poster rail two", 0.42, 0.51),
    ]}


# 0 header bands but the RAILS themselves carry quoted titles ⇒ _sec_titles >= 2 ⇒
# rows. Guards that the pre-#538 _sec_titles path is NOT gated behind header bands.
def _quoted_rail_screen():
    return {"route": "/new", "name": "new_and_popular", "components": [
        _rail('poster rail "Trending Now"', 0.24, 0.37),
        _rail('poster rail "Only on Netflix"', 0.40, 0.53),
    ]}


_GRID_MARKER = "gridTemplateColumns: 'repeat("


# ─────────────────────────────── tests ───────────────────────────────

def test_titleless_header_bands_render_rows():
    """r99 new_and_popular: 4 title-less header bands + 4 rails + no hero ⇒ ROWS
    (multiple rail sections), NOT a single flat grid."""
    html = _render(_titleless_multirail_screen())
    assert _GRID_MARKER not in html, "collapsed into a single grid (the r99 bug)"
    # all four rails rendered as distinct stacked carousels
    for _ri in range(4):
        assert f"_railSlice(rows, 4, {_ri})" in html, f"rail {_ri} missing"


def test_zero_header_bands_stays_grid():
    """my_list / browse_by_languages: 0 header bands ⇒ still a GRID (no regression;
    the _header_bands signal only counts real header/section-title bands)."""
    html = _render(_no_header_grid_screen(), name="MyListPage",
                   get_ep="/api/my-list")
    assert _GRID_MARKER in html, "0-header-band collection should stay a grid"
    assert "_railSlice(rows, 3," not in html, "should not render stacked rails"


def test_quoted_title_headers_render_rows():
    """r98: quoted-title header bands ⇒ _sec_titles >= 2 already ⇒ ROWS (unchanged)."""
    html = _render(_quoted_header_screen())
    assert _GRID_MARKER not in html
    assert "_railSlice(rows, 2, 1)" in html


def test_quoted_title_rails_no_headers_render_rows():
    """The pre-#538 _sec_titles path is preserved: 0 header bands but >=2 quoted-title
    RAILS still classify as rows (the fix is additive, not gating)."""
    html = _render(_quoted_rail_screen())
    assert _GRID_MARKER not in html
    assert "_railSlice(rows, 2, 1)" in html


def test_rail_header_deslug_fallback_in_page():
    """Booster: a title-less header band whose id encodes the name surfaces that name
    as the rail heading, via _rail_header's id de-slug last-resort."""
    html = _render(_titleless_multirail_screen())
    assert "New on Netflix" in html
    assert "Coming This Week" in html


def test_deslug_header_538_unit():
    assert _deslug_header_538("new-on-netflix-header") == "New on Netflix"
    assert _deslug_header_538("coming-this-week-header") == "Coming This Week"
    assert _deslug_header_538("trending-now-rail") == "Trending Now"
    assert _deslug_header_538("top_10_row") == "Top 10"
    # no id ⇒ headerless (empty), current behavior preserved
    assert _deslug_header_538("") == ""
    assert _deslug_header_538(None) == ""
