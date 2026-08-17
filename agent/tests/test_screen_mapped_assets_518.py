"""#518 (netflix r91, 2026-08-06) — the page-projector must paint THIS SCREEN's
per-component MAPPED brand photos, not just the global photo pool.

GROUND TRUTH: r91's visual gate reported BRAND-ASSET AUDIT '1916 unused mapped asset(s);
46 mandated first-position on 12 failing screen(s)', and every screen scored ~0.45. The
manifest held 119 real photographic assets (posters/backdrops) mapped to 108 components,
all physically staged — but the projector's content surfaces (hero bg, rail/grid/rep-card
posters, detail modal) all consume the _REFIMGS pool via _refImg, and that pool was built
ONLY from the GLOBAL photo set (_ref_image_pool); it never consulted screens[].components[]
.assets. So the specific images the design maps to each screen's components were never
emitted into that screen's source (audit: 'unused') and cards/hero rendered generic
placeholders. FIX #518: _screen_mapped_photo_urls(design, screen) resolves the screen's
component->asset map to served photo URLs (same selection as _ref_image_pool: photographic
types only; exclude icon/logo/placeholder; prefer backdrop/poster/still), and
_render_reference_page prepends them to the pool so _refImg(0..) resolves the REAL mapped
imagery first, then falls back to the global pool.

These tests lock: the helper's selection (photo-only, exclude icons/logos, prefer
backdrop/poster, deduped, order-preserving, [] when none); and end-to-end that a projected
page's emitted _REFIMGS pool contains the screen's mapped poster/backdrop basenames."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _screen_mapped_photo_urls, _ref_image_pool)


def _design():
    return {"assets": [
        {"id": "bd1", "type": "jpg", "file": "backdrop_a.jpg",
         "staged_path": "public/assets/backdrops/backdrop_a.jpg"},
        {"id": "ps1", "type": "jpg", "file": "poster_a.jpg",
         "staged_path": "public/assets/posters/poster_a.jpg"},
        {"id": "ps2", "type": "jpg", "file": "poster_b.jpg",
         "staged_path": "public/assets/posters/poster_b.jpg"},
        {"id": "ic1", "type": "svg", "file": "play_icon.svg",
         "staged_path": "public/assets/icons/play_icon.svg"},
        {"id": "lg1", "type": "svg", "file": "brand_logo.svg",
         "staged_path": "public/assets/brand/brand_logo.svg"},
        # a global photo NOT mapped to this screen's components:
        {"id": "bd9", "type": "jpg", "file": "backdrop_global.jpg",
         "staged_path": "public/assets/backdrops/backdrop_global.jpg"},
    ]}


def _screen():
    return {"components": [
        {"id": "hero", "region": "main", "assets": ["bd1", "lg1"]},   # backdrop + a logo
        {"id": "rail", "region": "main", "assets": ["ps1", "ps2", "ic1"]},  # posters + icon
        {"id": "dup", "region": "main", "assets": ["ps1"]},           # duplicate poster ref
    ]}


def test_helper_resolves_mapped_photos_only():
    urls = _screen_mapped_photo_urls(_design(), _screen())
    # photographic mapped assets, served-URL form, icons/logos excluded, deduped:
    assert urls == ["/assets/backdrops/backdrop_a.jpg",
                    "/assets/posters/poster_a.jpg",
                    "/assets/posters/poster_b.jpg"]
    assert not any("icon" in u or "logo" in u for u in urls)   # svg icon/logo dropped
    assert "/assets/backdrops/backdrop_global.jpg" not in urls  # not mapped to this screen


def test_helper_prefers_backdrop_poster_ordering():
    # a plain photo (no prefer-token in id/file/path) sorts AFTER preferred ones.
    d = {"assets": [
        {"id": "misc", "type": "png", "file": "hh.png", "staged_path": "public/assets/hh.png"},
        {"id": "bd", "type": "jpg", "file": "backdrop_x.jpg",
         "staged_path": "public/assets/backdrops/backdrop_x.jpg"}]}
    s = {"components": [{"assets": ["misc", "bd"]}]}
    assert _screen_mapped_photo_urls(d, s) == ["/assets/backdrops/backdrop_x.jpg",
                                               "/assets/hh.png"]


def test_helper_empty_when_no_photos_mapped():
    d = _design()
    s = {"components": [{"assets": ["ic1", "lg1"]}]}   # only svg icon/logo mapped
    assert _screen_mapped_photo_urls(d, s) == []
    assert _screen_mapped_photo_urls(d, {"components": []}) == []
    assert _screen_mapped_photo_urls(d, {}) == []


def test_pool_prepends_screen_photos_before_global():
    # the exact composition _render_reference_page performs.
    d = _design()
    s = _screen()
    screen_pool = _screen_mapped_photo_urls(d, s)
    pool = screen_pool + [u for u in _ref_image_pool(d) if u not in set(screen_pool)]
    # screen-mapped photos lead; the un-mapped global backdrop still appears in the tail:
    assert pool[:3] == ["/assets/backdrops/backdrop_a.jpg",
                        "/assets/posters/poster_a.jpg",
                        "/assets/posters/poster_b.jpg"]
    assert "/assets/backdrops/backdrop_global.jpg" in pool
    assert len(pool) == len(set(pool))   # no dupes across screen + global


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
