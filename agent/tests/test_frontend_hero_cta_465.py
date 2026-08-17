"""#465 (the r40 judge's single most-repeated hero miss: 'missing Play/More Info'
on shows 0.45 / movies 0.50 / browse_home 0.50 / genre_category 0.55). The hero CTA
buttons rendered ONLY when the decomposition happened to surface a clean action
component in bands['main'] — fragile, so on those screens action_labels came back
empty and the billboard rendered bare (title + bg only). FIX: a MEDIA hero (the app
stages a video asset) with no decomposed action labels falls back to the canonical
Play + More Info CTAs (rendered with #425's white play-pill + gray info styling).
Gated on staged video so a non-media hero (blog/dashboard) stays bare — mirrors the
#445 mute-button gate. Additive (fires only when labels empty), so heroes that
surface their own labels are untouched. Generalizable to any media/catalog app hero,
no product literals. Validate by DETERMINISTIC RENDER (single-run scores are noisy).
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)

_MEDIA_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                                   "theme": {"default": "dark"}},
                 "assets": [{"type": "video", "file": "preview.mp4"}]}
_NONMEDIA_DESIGN = {"design_system": {"palette": {"bg": "#ffffff", "accent": "#333333"},
                                      "theme": {"default": "light"}},
                    "assets": [{"type": "image", "file": "logo.png"}]}

_HERO_SCR = {"route": "/shows", "name": "shows", "kind": "page", "components": [
    {"id": "hero", "role": "hero billboard", "region": [0.0, 0.05, 1.0, 0.6]},
    {"id": "rail", "role": "poster rail", "region": [0.0, 0.65, 1.0, 0.85],
     "geometry": {"columns": 6}}]}


def test_media_hero_gets_default_play_more_info_when_no_action_comp():
    out = _render_reference_page("shows", {"route": "/shows"}, _HERO_SCR,
                                 _MEDIA_DESIGN, [("Shows", "/shows")], "/api/titles")
    assert '{"Play"}' in out and '{"More Info"}' in out, \
        "media hero with no action comp gets canonical Play/More Info CTAs"
    assert "▶" in out, "primary CTA carries the play glyph (white pill)"
    assert "backgroundColor: '#ffffff'" in out, "primary CTA is the white play pill (#425)"


def test_nonmedia_hero_stays_bare_without_action_comp():
    # same hero component, but the app stages NO video → the gate must NOT fire
    out = _render_reference_page("dashboard", {"route": "/shows"}, _HERO_SCR,
                                 _NONMEDIA_DESIGN, [("Home", "/shows")], "/api/titles")
    assert '{"Play"}' not in out and '{"More Info"}' not in out, \
        "non-media hero: no default CTAs injected (gate = staged video)"


_HERO_WITH_CTA = {"route": "/shows", "name": "shows", "kind": "page", "components": [
    {"id": "hero", "role": "hero billboard", "region": [0.0, 0.05, 1.0, 0.5]},
    {"id": "cta", "role": "Watch Now and Details buttons",
     "region": [0.0, 0.50, 0.6, 0.58]},
    {"id": "rail", "role": "poster rail", "region": [0.0, 0.65, 1.0, 0.85],
     "geometry": {"columns": 6}}]}


def test_own_action_labels_not_overridden_by_default():
    out = _render_reference_page("shows", {"route": "/shows"}, _HERO_WITH_CTA,
                                 _MEDIA_DESIGN, [("Shows", "/shows")], "/api/titles")
    assert '{"Watch Now"}' in out, "hero keeps its own decomposed action labels"
    assert '{"Play"}' not in out, "default CTAs NOT injected when labels already present"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
