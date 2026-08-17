"""#425 (netflix r18 verdict.json): components (0.33) was the worst dimension. The
hero-band deviations on every streaming screen: "Play button is red rectangle
instead of a white pill with a play glyph; buttons lack icons" and "missing
metadata line (year/rating/duration)". #414 rendered the Play/More-Info buttons but
with accent-fill + no glyph. FIX: primary CTA = WHITE pill + ▶ glyph, secondaries =
translucent gray + ⓘ glyph; plus a data-driven metadata row (year/maturity_rating/
duration) from the title's own fields. Generic media-CTA styling + data-driven
content — generalizable, no product literals. Locks this in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)

_DESIGN = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "movie-1", "file": "backdrops/movie_1.jpg", "type": "jpg",
                "dims": [1280, 720],
                "staged_path": "public/assets/backdrops/movie_1.jpg"}],
}
_HERO_SCREEN = {
    "route": "/browse", "name": "browse_home",
    "components": [
        {"id": "hero", "region": [0.0, 0.0, 1.0, 0.55],
         "role": "hero billboard title art", "assets": ["movie-1"]},
        {"id": "hero-actions", "region": [0.05, 0.45, 0.6, 0.52],
         "role": "Play (primary) and More Info (secondary) buttons"},
        {"id": "rail", "region": [0.0, 0.6, 1.0, 0.85],
         "role": "horizontal poster rail", "geometry": {"columns": 6, "rows": 1}},
    ],
}


def _render():
    return _render_reference_page("BrowseHomePage", {}, _HERO_SCREEN, _DESIGN,
                                  [("Home", "/browse")], "/api/titles")


def test_primary_cta_is_white_pill_with_play_glyph():
    out = _render()
    assert "▶" in out, "primary CTA must carry a play glyph"
    assert "'#ffffff'" in out and "'#000000'" in out, "Play is a white pill w/ black text"
    assert '{"Play"}' in out


def test_secondary_cta_has_info_glyph():
    out = _render()
    assert "ⓘ" in out
    assert '{"More Info"}' in out


def test_hero_metadata_row_is_data_driven():
    out = _render()
    assert "_ratingOf(cur)" in out and "_yearOf(cur)" in out
    # guarded so a non-media row (no such fields) renders nothing
    assert "_yearOf(cur) || _ratingOf(cur)" in out


def test_hero_metadata_row_does_not_read_bare_field_names_782():
    """#782. This assertion used to read `"cur.year" in out` — it pinned the defect: the projector
    cannot know whether the app spells the column `year` or `release_year`, which is exactly why
    every other accessor in _REF_HELPERS_JS is a multi-key fallback list. 13% of the corpus names
    it `release_year` and lost the chip silently."""
    out = _render()
    assert "cur.year" not in out
    assert "cur.duration" not in out and "cur.runtime" not in out


def test_hero_still_builds_without_action_labels():
    # a hero comp with no Play/More-Info role → no buttons, but still a valid hero
    screen = {"route": "/x", "name": "x", "components": [
        {"id": "hero", "region": [0.0, 0.0, 1.0, 0.6], "role": "hero banner",
         "assets": ["movie-1"]},
        {"id": "rail", "region": [0.0, 0.65, 1.0, 0.9], "role": "poster rail",
         "geometry": {"columns": 6, "rows": 1}}]}
    out = _render_reference_page("X", {}, screen, _DESIGN, [("H", "/x")], "/api/x")
    assert "flex flex-col justify-end" in out  # hero band present, no crash


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
