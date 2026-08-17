"""#531 (netflix, run netflix-web-r97) — two generalizable defects in the shared
`data-projected="ref"` catalog page template (frontend_scaffold._render_reference_
page) that capped ~7 thin catalog screens at 0.40-0.55 even once /api/titles
returned real data, while the SAME template rendered browse_home at 0.72:

  #531(a) HERO — the hero pasted a STATIC reference title-art crop
      (/assets/crops/<screen>__hero-title-art.png) over the live backdrop -> "a
      small floating card, not a data-driven billboard". FIX: when a live record is
      present (cur), render the record's OWN title as a large bold <h1> (via
      _titleOf); keep the static crop ONLY as the fallback for the no-record case.

  #531(b) MULTI-ROW — a catalog page that declares only ONE rail shipped a single
      thin poster row vs the reference's multiple named shelves. FIX: wrap a
      single-rail page so that AT RUNTIME, when the data supports it (>= 10 rows and
      a categorical field and/or a rank/date field), it renders several DATA-DERIVED
      named rows; otherwise it falls back to the EXACT original single rail. Row
      titles come from the data's own category values or the generic 'Top 10'/'New'
      labels.

Both are additive + data-gated: no live record -> the crop/generic fallback; thin
data or already-multiple rails -> byte-identical rendered output. No product
literals.
"""
import re

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)
import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as _fs


# ─────────────────────────────── fixtures ───────────────────────────────

def _design(crop_names=None):
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}},
         "assets": [{"id": "m1", "file": "backdrops/m1.jpg", "type": "video",
                     "staged_path": "public/assets/backdrops/m1.jpg"}]}
    if crop_names is not None:
        d["_crop_names"] = crop_names
    return d


_HERO = {"id": "hero", "region": [0.0, 0.0, 1.0, 0.56],
         "role": "hero billboard title art", "assets": ["m1"]}
_RAIL = {"id": "rail", "region": [0.0, 0.6, 1.0, 0.75],
         "role": "horizontal poster rail", "geometry": {"columns": 6, "rows": 1}}


def _render(screen, crop_names=None, name="MoviesPage", get_ep="/api/titles"):
    return _render_reference_page(name, {}, screen, _design(crop_names),
                                  [("Movies", "/movies")], get_ep)


def _single_rail_screen():
    return {"route": "/movies", "name": "movies",
            "components": [dict(_HERO), dict(_RAIL)]}


def _hero_only_screen():
    return {"route": "/movies", "name": "movies", "components": [dict(_HERO)]}


def _multi_rail_screen():
    return {"route": "/browse", "name": "browse_home", "components": [
        dict(_HERO),
        {"id": "r1", "region": [0.0, 0.6, 1.0, 0.72],
         "role": "carousel of 'Trending Now' titles", "geometry": {"columns": 6}},
        {"id": "r2", "region": [0.0, 0.75, 1.0, 0.9],
         "role": "carousel of 'New Releases' titles", "geometry": {"columns": 6}}]}


# ───────────────────────── #531(a) DATA-DRIVEN HERO ─────────────────────────

def test_hero_renders_data_driven_title_when_record_present():
    # a crop IS available for this screen, yet the hero title must be the live
    # record's own title (data-driven <h1>), guarded by `cur`
    out = _render(_single_rail_screen(), crop_names=["movies__hero-title-art.png"])
    assert "{cur ? <h1" in out                      # runtime record guard leads
    assert "_titleOf(cur)}</h1>" in out             # data-driven title heading
    # the title element leads with the guard, NOT the unconditional crop <img>
    assert re.search(r'px-8 pb-12">\s*\n\s*\{cur \? <h1', out)


def test_hero_keeps_static_crop_only_as_no_record_fallback():
    out = _render(_single_rail_screen(), crop_names=["movies__hero-title-art.png"])
    # the crop is still emitted (fallback for the no-record case) ...
    assert "movies__hero-title-art.png" in out
    # ... but ONLY as the else-branch of the cur ternary, never pasted on its own
    assert " : <img alt=" in out
    # data-driven title precedes the crop => crop is the fallback, not the hero title
    assert out.index("_titleOf(cur)}</h1>") < out.index("hero-title-art")


def test_hero_without_crop_is_byte_identical_generic_h1():
    # no reference title-art crop -> unchanged generic <h1> (already data-or-label)
    out = _render(_single_rail_screen(), crop_names=[])
    assert ('<h1 className="text-4xl font-bold drop-shadow-lg" '
            'style={{ color: \'#ffffff\' }}>{((cur && _titleOf(cur)) || "Movies")}'
            '</h1>') in out
    assert "hero-title-art" not in out          # no crop was available
    assert "md:text-6xl" not in out             # the data-h1 variant is not emitted


def test_hero_backdrop_stays_data_driven():
    # the hero fix must not regress the (already-correct) data-driven backdrop
    out = _render(_single_rail_screen(), crop_names=["movies__hero-title-art.png"])
    assert "(cur && _backdropOf(cur))" in out


def test_hero_change_applies_uniformly_to_multi_rail_home():
    # browse_home (multi-rail) with a crop also gets the data-driven hero title
    # (consistent), while its rails stay untouched (see multi-row tests below)
    out = _render(_multi_rail_screen(),
                  crop_names=["browse_home__hero-title-art.png"], name="BrowseHomePage")
    assert "{cur ? <h1" in out and "_titleOf(cur)}</h1>" in out


# ───────────────────────────── #531(b) MULTI-ROW ─────────────────────────────

def test_single_rail_synthesizes_data_derived_rows():
    out = _render(_single_rail_screen())
    # the runtime multi-row deriver is emitted for a single-rail catalog page
    assert "_deriveRows" in out
    assert "_dr.map((g, gi) =>" in out                 # renders one rail per group
    assert "<h3 className=\"mb-3 text-lg font-semibold\">{g.title}</h3>" in out
    # categorical grouping + themed rows, derived from generic data fields
    for f in ("'genre'", "'genres'", "'category'", "'kind'"):
        assert f in out
    assert "'Top 10'" in out and "'New'" in out


def test_hero_only_page_also_synthesizes_rows():
    # a hero with no explicit rail (its default single rail) is eligible too
    out = _render(_hero_only_screen())
    assert "_deriveRows" in out


def test_single_rail_preserves_exact_fallback():
    # when _deriveRows returns null (thin data / no fields) the page renders the
    # EXACT original single rail -> same DOM, byte-identical for data-less apps
    out = _render(_single_rail_screen())
    assert "if (!_dr) return (<>" in out
    assert "_railSlice(rows, 1, 0)" in out             # the untouched single rail


def test_multi_row_conservatism_guards():
    out = _render(_single_rail_screen())
    assert "if (arr.length < 10) return null;" in out          # thin-data guard
    assert "out.length >= 2 ? out.slice(0, 5) : null" in out   # >=2 rows, cap <=5
    # a category row needs a real bucket; not every field spawns a row
    assert "filter((e) => e[1].length >= 3)" in out


def test_multiple_rails_are_unchanged():
    # a genuine multi-rail home is NOT wrapped -> byte-identical rail path
    out = _render(_multi_rail_screen(), name="BrowseHomePage")
    assert "_deriveRows" not in out
    assert out.count("_railSlice(rows, 2,") == 2       # its two rails, intact
    assert "Trending Now" in out and "New Releases" in out


# ─────────────────────────────── invariants ───────────────────────────────

def test_no_product_literals_introduced():
    for scr, crop, nm in ((_single_rail_screen(), ["movies__hero-title-art.png"], "MoviesPage"),
                          (_multi_rail_screen(), None, "BrowseHomePage")):
        out = _render(scr, crop_names=crop, name=nm)
        low = out.lower()
        for bad in ("netflix", "disney", "hulu", "spotify"):
            assert bad not in low, f"product literal {bad!r} leaked"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
