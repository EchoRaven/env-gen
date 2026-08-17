"""#415 STAGED-REFERENCE-IMAGE fidelity floor for the page-projector.

Confirmed gap: the projector rendered the HERO background + RAIL/GRID poster
<img>s from the SEED ROWS' image columns, which are generic placeholders
(/assets/placeholders/ph-img-*.svg), so projected browse screens looked like gray
placeholder boxes (~0.20 vs the 0.65 fidelity bar) — while the app's real staged
backdrops (design_system.json assets[]) sat UNUSED.

Fix (additive, generalizable — NO product literals): _ref_image_pool(design)
selects the app's real photographic staged assets, and _render_reference_page
injects them as a JS pool (_REFIMGS / _refImg) so the HERO bg + poster walls paint
real product imagery. _imgOf(row) stays the fallback → an app that stages no
photos renders exactly as before.

  (a) design WITH backdrop assets → the emitted page carries _REFIMGS with the
      staged /assets/backdrops/... urls (icons/logos/svgs excluded) and the hero +
      rails pick from the pool via _refImg(...);
  (b) design with NO image assets → _REFIMGS = [] and the posters fall back to
      _imgOf(row) with no crash.
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page, _ref_image_pool)
from env_generator.llm_generator.multi_agent.runtime.frontend_page_projector import (
    _STRUCTURED_MARKER)


# A design that STAGES real photographic backdrops (the #415 win) alongside a
# logo (svg) and a nav icon (png) that MUST be excluded from the photo pool.
_DESIGN_WITH_BACKDROPS = {
    "design_system": {
        "palette": {"bg": "#141414", "accent": "#e50914", "text": "#f5f5f5"},
        "theme": {"default": "dark"},
    },
    "assets": [
        {"id": "movie-1", "file": "movie_1.jpg", "type": "jpg",
         "dims": [1280, 720], "staged_path": "public/assets/backdrops/movie_1.jpg"},
        {"id": "movie-2", "file": "movie_2.jpg", "type": "jpg",
         "dims": [1280, 720], "staged_path": "public/assets/backdrops/movie_2.jpg"},
        {"id": "movie-3", "file": "movie_3.jpg", "type": "jpg",
         "dims": [1280, 720], "staged_path": "public/assets/backdrops/movie_3.jpg"},
        # excluded: an svg (non-photo type) and a png whose id/path says 'icon'
        {"id": "brand-logo", "file": "logo.svg", "type": "svg",
         "staged_path": "public/assets/logo.svg"},
        {"id": "nav-icon-home", "file": "home.png", "type": "png",
         "staged_path": "public/assets/icons/home.png"},
    ],
}

# A design with NO usable staged photos (only an svg icon) → the pool is empty.
_DESIGN_NO_IMAGES = {
    "design_system": {
        "palette": {"bg": "#141414", "accent": "#e50914", "text": "#f5f5f5"},
        "theme": {"default": "dark"},
    },
    "assets": [
        {"id": "brand-logo", "file": "logo.svg", "type": "svg",
         "staged_path": "public/assets/logo.svg"},
    ],
}

_BACKDROP_URLS = ["/assets/backdrops/movie_1.jpg",
                  "/assets/backdrops/movie_2.jpg",
                  "/assets/backdrops/movie_3.jpg"]

# A hero+rail home screen (same shape as tests/test_frontend_hero_rail_projection).
_HERO_RAIL_SCREEN = {
    "route": "/browse", "name": "browse_home",
    "components": [
        {"id": "nav", "region": [0.0, 0.0, 0.16, 1.0], "role": "left nav sidebar"},
        {"id": "hero-title-art", "region": [0.16, 0.05, 1.0, 0.55],
         "role": "stylized title/logo artwork", "assets": ["hero-art"]},
        {"id": "hero-action-buttons", "region": [0.18, 0.45, 0.6, 0.52],
         "role": "Play (primary) and More Info (secondary) buttons"},
        {"id": "rail-header-a", "region": [0.16, 0.58, 0.5, 0.62],
         "role": "section title 'Trending Now'"},
        {"id": "content-rail-a", "region": [0.16, 0.62, 1.0, 0.82],
         "role": "horizontal poster rail of Trending Now titles",
         "geometry": {"columns": 6, "rows": 1}},
        {"id": "rail-header-b", "region": [0.16, 0.84, 0.5, 0.875],
         "role": "section title 'New Releases'"},
        {"id": "content-rail-b", "region": [0.16, 0.88, 1.0, 1.0],
         "role": "horizontal poster rail of New Releases titles",
         "geometry": {"columns": 6, "rows": 1}},
    ],
}


def _render(name, screen, design):
    return _render_reference_page(
        name, {}, screen, design,
        [("Home", "/browse"), ("New", "/new")], "/api/titles")


def test_ref_image_pool_selects_photos_excludes_icons_logos():
    pool = _ref_image_pool(_DESIGN_WITH_BACKDROPS)
    assert pool == _BACKDROP_URLS, "photo pool = the staged jpg backdrops in order"
    # excluded: svg logo (non-photo type) + the png in an 'icon' path
    assert "/assets/logo.svg" not in pool
    assert "/assets/icons/home.png" not in pool
    # no staged photos at all → clean empty fallback
    assert _ref_image_pool(_DESIGN_NO_IMAGES) == []
    assert _ref_image_pool({}) == []


def test_hero_rail_with_backdrops_uses_staged_pool():
    out = _render("BrowseHomePage", _HERO_RAIL_SCREEN, _DESIGN_WITH_BACKDROPS)

    # structured floor markers + the declared GET fetch survive (non-breaking)
    assert _STRUCTURED_MARKER in out
    assert 'data-projected="ref"' in out
    assert "/api/titles" in out

    # the staged photo pool is injected as a JS const + wrapping accessor
    assert "const _REFIMGS = [" in out
    for u in _BACKDROP_URLS:
        assert u in out, "the staged backdrop url must be in the injected pool"
    assert "const _refImg = (i) =>" in out
    # excluded assets never leak into the PHOTO pool (_REFIMGS). #421: the brand
    # logo may now legitimately render as the nav WORDMARK and an icon as a nav-link
    # glyph, so scope this exclusion to the injected photo pool, not the whole page.
    _pool_slice = out.split("const _REFIMGS = [", 1)[1].split("]", 1)[0]
    assert "/assets/logo.svg" not in _pool_slice
    assert "/assets/icons/home.png" not in _pool_slice

    # HERO bg picks a real staged photo first (pool index 0), _imgOf as fallback
    assert "_refImg(0)" in out
    # RAILS: #481 — each card prefers the row's OWN real image; the running-index
    # pool (rail 0 base = 1, consecutive entries + i) is now the FALLBACK for a row
    # with no image (reference-FIRST painted every card the same positional photo).
    assert "_refImg(1 + 0 * Math.ceil(rows.length / 2) + i)" in out
    assert "_refImg(1 + 1 * Math.ceil(rows.length / 2) + i)" in out
    assert "_imgOf(row) || _refImg(1 +" in out
    # both rails still map the fetched rows (existing behavior intact)
    assert out.count("_railSlice(rows, 2,") == 2


def test_no_image_assets_falls_back_to_imgof():
    out = _render("BrowseHomePage", _HERO_RAIL_SCREEN, _DESIGN_NO_IMAGES)

    # empty pool → _refImg() always returns null at runtime
    assert "const _REFIMGS = [];" in out
    assert "const _refImg = (i) =>" in out
    # #481: cards are real-first — with an empty pool _refImg()→null at runtime, so
    # the row's own image renders (no crash; exactly the real data).
    assert "_imgOf(row) || _refImg(1 +" in out
    assert "_imgOf(row)" in out
    # the projected floor + GET fetch are still intact
    assert _STRUCTURED_MARKER in out
    assert "/api/titles" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
