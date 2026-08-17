"""#423 (netflix r15/r16 verdict.json): iconography (0.25) + components (0.31) were
the worst dimensions and DOMINATED by poster imagery — the projector rendered
PORTRAIT rail/grid cards (aspect-[2/3]) with a title caption, while the reference
row tiles are LANDSCAPE 16:9 stills with NO caption. FIX: _ref_card_style derives
the card shape from the app's OWN staged imagery — landscape 16:9 + wider card + no
caption when the design stages landscape backdrop/still assets (netflix
movie_*.jpg 1280x720); portrait 2:3 + caption fallback for poster-only apps. The
rail + grid cards use it. Generalizable (no product literals), portrait-safe
default. Locks the shape derivation + its application in the emitted JSX."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _ref_card_style, _render_reference_page)

_PAL = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                          "theme": {"default": "dark"}}}

_LANDSCAPE_ASSETS = [
    {"id": "movie-1", "file": "backdrops/movie_1.jpg", "type": "jpg",
     "dims": [1280, 720], "staged_path": "public/assets/backdrops/movie_1.jpg"},
    {"id": "movie-2", "file": "backdrops/movie_2.jpg", "type": "jpg",
     "dims": [1280, 720], "staged_path": "public/assets/backdrops/movie_2.jpg"},
]
_PORTRAIT_ASSETS = [
    {"id": "poster-1", "file": "posters/p1.jpg", "type": "jpg",
     "dims": [500, 750], "staged_path": "public/assets/posters/p1.jpg"},
    {"id": "poster-2", "file": "posters/p2.jpg", "type": "jpg",
     "dims": [400, 600], "staged_path": "public/assets/posters/p2.jpg"},
]

_RAIL_SCREEN = {
    "route": "/browse", "name": "browse_home",
    "components": [
        {"id": "content-rail", "region": [0.0, 0.6, 1.0, 0.85],
         "role": "horizontal poster rail of titles",
         "geometry": {"columns": 6, "rows": 1}},
    ],
}


def _design(assets):
    d = dict(_PAL)
    d["assets"] = assets
    return d


def _render(design):
    return _render_reference_page("BrowseHomePage", {}, _RAIL_SCREEN, design,
                                  [("Home", "/browse")], "/api/titles")


# ── pure shape derivation ──
def test_style_landscape_for_backdrop_assets():
    assert _ref_card_style(_design(_LANDSCAPE_ASSETS)) == ("16 / 9", "w-64", False)


def test_style_portrait_for_poster_only_app():
    assert _ref_card_style(_design(_PORTRAIT_ASSETS)) == ("2 / 3", "w-40", True)


def test_style_defaults_portrait_when_no_or_dimless_assets():
    assert _ref_card_style({"assets": []}) == ("2 / 3", "w-40", True)
    # a landscape banner without dims can't decide → safe portrait default
    assert _ref_card_style({"assets": [
        {"id": "banner", "file": "banner.jpg", "type": "jpg"}]}) == ("2 / 3", "w-40", True)


def test_hero_banner_alone_does_not_force_landscape_tiles():
    # a landscape HERO/COVER banner must NOT make the rail TILES landscape
    d = {"assets": [{"id": "hero-art", "file": "hero.png", "type": "png",
                     "dims": [1920, 1080]},
                    {"id": "cover", "file": "cover.jpg", "type": "jpg",
                     "dims": [1920, 800]}]}
    assert _ref_card_style(d) == ("2 / 3", "w-40", True)


# ── applied in the emitted JSX ──
def test_rail_renders_landscape_no_caption_for_streaming():
    out = _render(_design(_LANDSCAPE_ASSETS))
    assert "aspectRatio: '16 / 9'" in out, "streaming rail tiles must be 16:9"
    assert "aspect-[2/3]" not in out, "no hardcoded portrait aspect for a landscape app"
    # caption (_titleOf(row)) dropped for landscape tiles (reference has none)
    assert 'mt-1 truncate text-xs opacity-80">{_titleOf(row)}' not in out


def test_rail_renders_portrait_with_caption_for_poster_app():
    out = _render(_design(_PORTRAIT_ASSETS))
    assert "aspectRatio: '2 / 3'" in out
    assert "{_titleOf(row)}" in out  # caption kept for poster apps


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
