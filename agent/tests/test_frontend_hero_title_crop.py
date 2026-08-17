"""#461 (unblocks the #1 fidelity ceiling — per-title HERO TITLE-ART). The pipeline
crops each reference component to design/crops/<screen>__<component>.png; the hero
title-logo/art crop IS the real reference wordmark. Previously heroes showed Anton
TEXT (judge's recurring 'missing title art'), the crops weren't staged/served, and
_render_reference_page didn't use them. FIX: (1) _load_design_for_projection exposes
design['_crop_names']; (2) stage_design_assets copies design/crops → /assets/crops/;
(3) the hero renders the matching title-art crop as an <img> (else the text <h1>).
Generalizable (uses the design's own crops). Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _hero_title_crop_url_461, _render_reference_page)


def test_matches_hero_title_crop_by_screen_and_component():
    design = {"_crop_names": [
        "browse_home__hero-title-logo.png", "browse_home__hero-billboard.png",
        "genre_category__hero-title-art.png", "games__hero-title-block.png",
        "movies__hero-brand-tag.png", "shows__netflix-logo.png"]}
    assert _hero_title_crop_url_461({"name": "browse_home"}, design) == "/assets/crops/browse_home__hero-title-logo.png"
    assert _hero_title_crop_url_461({"name": "genre_category"}, design) == "/assets/crops/genre_category__hero-title-art.png"
    assert _hero_title_crop_url_461({"name": "games"}, design) == "/assets/crops/games__hero-title-block.png"
    assert _hero_title_crop_url_461({"name": "movies"}, design) == "/assets/crops/movies__hero-brand-tag.png"


def test_no_crop_when_no_title_component_or_no_manifest():
    # shows has only a netflix-logo crop (nav brand), not a hero title-art → ''
    design = {"_crop_names": ["shows__netflix-logo.png", "shows__hero-billboard.png"]}
    assert _hero_title_crop_url_461({"name": "shows"}, design) == ""
    assert _hero_title_crop_url_461({"name": "browse_home"}, {}) == ""  # no manifest
    assert _hero_title_crop_url_461({"name": ""}, design) == ""


def test_no_cross_screen_match():
    design = {"_crop_names": ["browse_home__hero-title-logo.png"]}
    # a different screen must NOT borrow browse_home's crop
    assert _hero_title_crop_url_461({"name": "movies"}, design) == ""


# ── integration: the hero renders the crop <img>, not the text <h1> ──
_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": [],
           "_crop_names": ["browse_home__hero-title-logo.png"]}
_SCR = {"route": "/browse", "name": "browse_home", "kind": "page", "components": [
    {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.05, 1.0, 0.6]},
    {"id": "rail", "role": "poster rail of Trending Now",
     "region": [0.0, 0.65, 1.0, 0.85], "geometry": {"columns": 6}}]}


def test_hero_renders_title_crop_img():
    out = _render_reference_page("browse_home", {"route": "/browse"}, _SCR, _DESIGN,
                                 [("Home", "/browse")], "/api/titles")
    assert "/assets/crops/browse_home__hero-title-logo.png" in out, "hero renders the real title-art crop"
    # #468: the title-art cap was enlarged from the too-small max-h-40 (160px) to a
    # prominent responsive cap (judge: hero title-art 'drastically too small')
    assert "max-h-56" in out and "md:max-h-72" in out, "#468 enlarged hero title-art cap"
    assert "max-h-40 " not in out, "#468 the old too-small 160px cap must be gone"


def test_hero_falls_back_to_text_without_crop():
    d = dict(_DESIGN); d.pop("_crop_names")
    out = _render_reference_page("browse_home", {"route": "/browse"}, _SCR, d,
                                 [("Home", "/browse")], "/api/titles")
    assert "/assets/crops/" not in out and "text-4xl font-bold" in out, "text <h1> fallback"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
