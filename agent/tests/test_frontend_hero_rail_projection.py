"""HERO + RAIL fidelity enrichment of the page-projector (_render_reference_page).

Confirmed gap: browse-type reference screens (streaming home, storefront, dashboard)
encode a HERO band (a big featured item + action buttons) OVER one-or-more horizontal
poster RAILS, but the projector rendered the main content as a SINGLE grid/list — so
those screens scored ~0.15 on the visual-fidelity gate (0.65 bar).

Fix (additive, generalizable — role/region/geometry keywords, NO product literals):
_render_reference_page now detects hero + rail components from the MEASURED regions and
emits a full-width hero banner (bg image + overlaid title + named action buttons) over
horizontal-scroll poster rails. Screens with NEITHER a hero nor a rail keep the existing
grid/list/media behavior unchanged.

  (a) a screen WITH a hero component + rail components → the emitted JSX carries a hero
      band (bg image + title + a Play-ish button) AND horizontal-scroll rails
      (overflow-x-auto, mapping the fetched rows), one strip per rail component;
  (b) a screen with NEITHER → the current grid behavior is unchanged (no hero band, a
      gridTemplateColumns surface), and the structured markers / GET fetch are intact.
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)
from env_generator.llm_generator.multi_agent.runtime.frontend_page_projector import (
    _STRUCTURED_MARKER)


_DESIGN = {
    "design_system": {
        "palette": {"bg": "#141414", "accent": "#e50914", "text": "#f5f5f5"},
        "theme": {"default": "dark"},
    },
    "assets": [
        {"id": "hero-art", "file": "hero.png", "type": "png",
         "dims": [1920, 1080], "staged_path": "public/assets/hero.png"},
    ],
}

# A hero+rail home screen (the browse_home shape): left nav, hero title-art with a
# mapped asset, an action-buttons sub-region naming Play/More Info, then two rail
# headers + two horizontal poster rails (the second stacks low → "bottom" band).
_HERO_RAIL_SCREEN = {
    "route": "/browse", "name": "browse_home",
    "components": [
        {"id": "nav", "region": [0.0, 0.0, 0.16, 1.0], "role": "left nav sidebar"},
        {"id": "hero-title-art", "region": [0.16, 0.05, 1.0, 0.55],
         "role": "stylized title/logo artwork", "assets": ["hero-art"]},
        {"id": "hero-action-buttons", "region": [0.18, 0.45, 0.6, 0.52],
         "role": "Play (primary) and More Info (secondary) buttons"},
        {"id": "hero-metadata-row", "region": [0.18, 0.40, 0.7, 0.44],
         "role": "metadata row (year, rating, duration)"},
        {"id": "rail-header-a", "region": [0.16, 0.58, 0.5, 0.62],
         "role": "section title 'TV Action & Adventure'"},
        {"id": "content-rail-tv-action", "region": [0.16, 0.62, 1.0, 0.82],
         "role": "horizontal poster rail of TV Action & Adventure titles",
         "geometry": {"columns": 6, "rows": 1}},
        {"id": "rail-header-b", "region": [0.16, 0.84, 0.5, 0.875],
         "role": "section title 'Trending Now'"},
        {"id": "content-rail-trending", "region": [0.16, 0.88, 1.0, 1.0],
         "role": "horizontal poster rail of Trending Now titles",
         "geometry": {"columns": 6, "rows": 1}},
    ],
}

# A plain gallery screen: left nav + ONE whole-page grid region. No hero (the content
# region spans the whole height → _is_hero_comp rejects it) and no rail (grid role, <4
# measured columns, not wide-short).
_GRID_SCREEN = {
    "route": "/explore", "name": "explore",
    "components": [
        {"id": "nav", "region": [0.0, 0.0, 0.16, 1.0], "role": "left nav sidebar"},
        {"id": "grid", "region": [0.16, 0.0, 1.0, 1.0],
         "role": "Grid layout of video thumbnails", "geometry": {"columns": 3}},
    ],
}


def _render(name, screen):
    return _render_reference_page(
        name, {}, screen, _DESIGN,
        [("Home", "/browse"), ("New", "/new")], "/api/titles")


def test_hero_and_rail_screen_emits_hero_band_and_rails():
    out = _render("BrowseHomePage", _HERO_RAIL_SCREEN)

    # structured floor markers + the declared GET fetch survive (non-breaking)
    assert _STRUCTURED_MARKER in out
    assert 'data-projected="ref"' in out
    assert "/api/titles" in out

    # ── HERO band ──
    assert "flex flex-col justify-end" in out, "expected a hero banner section"
    # background image = the hero component's resolved asset (public/ stripped)
    assert "/assets/hero.png" in out, "hero should paint its mapped asset as bg"
    assert "absolute inset-0 h-full w-full object-cover" in out
    # overlaid large title, from the row's _titleOf else the app label
    assert "<h1" in out and "_titleOf(cur)" in out
    # named action buttons: Play (primary, accent) + More Info (secondary)
    assert '{"Play"}' in out, "the named Play action must render as a real button"
    assert '{"More Info"}' in out
    assert "#e50914" in out, "the primary action button uses the measured accent"

    # ── RAILS: one horizontal-scroll strip per rail component (2 here), each
    #    mapping the fetched rows; the low rail (bottom band) is still rendered ──
    assert out.count("overflow-x-auto") == 2, "expected two horizontal rails"
    assert out.count("flex gap-3 overflow-x-auto") == 2
    # rows are sliced across the rails (a floor the lane refines)
    assert "_railSlice(rows, 2, 0)" in out
    assert "_railSlice(rows, 2, 1)" in out
    # rail headers come from the sibling rail-header regions
    assert '{"TV Action & Adventure"}' in out
    assert '{"Trending Now"}' in out
    # rail cards map the fetched rows via the shared helpers
    assert out.count("_railSlice(rows, 2,") == 2
    assert "_imgOf(row)" in out and "_titleOf(row)" in out


def test_plain_grid_screen_keeps_current_behavior():
    out = _render("ExplorePage", _GRID_SCREEN)

    # NO hero + NO rail were detected → the existing grid/list surface is unchanged
    assert "flex flex-col justify-end" not in out, "no hero band for a plain grid"
    assert "overflow-x-auto" not in out, "no horizontal rail for a plain grid"
    assert "_railSlice(" not in out
    # the current measured grid surface still renders (columns from the geometry)
    assert "gridTemplateColumns" in out
    assert "<h2 " in out, "the plain grid keeps its section heading"
    # structured markers + GET fetch intact
    assert _STRUCTURED_MARKER in out
    assert 'data-projected="ref"' in out
    assert "/api/titles" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
