"""#438 (product-specific fidelity, per the user's 'pursue >=0.65 product-specifically'
decision): the projector used generic Tailwind sizes (text-4xl) for the hero title,
while the design carries an exact measured `type_scale` (design_prep estimates
size_px/weight/family per role from the reference crops — e.g. hero-title 90px/700).
FIX: _type_scale_style_438 emits the exact measured size/weight/tracking as inline
style props, applied to the hero <h1>, tightening typography toward the real
product. Empty (Tailwind default kept) when no type_scale / no matching role — safe
for any app."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _type_scale_style_438, _render_reference_page)

_TS = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                         "theme": {"default": "dark"},
                         "type_scale": [
                             {"role": "hero-title-logo", "size_px": 90, "weight": 700,
                              "letter_spacing_em": -0.02, "line_height": 1.0},
                             {"role": "modal-title", "size_px": 44, "weight": 700}]},
       "assets": []}


def test_resolves_exact_measured_type_scale():
    s = _type_scale_style_438(_TS, ("hero-title", "hero"))
    assert "fontSize: '90px'" in s and "fontWeight: 700" in s
    assert "letterSpacing: '-0.02em'" in s and "lineHeight: 1.0" in s


def test_empty_when_no_type_scale_or_no_match():
    assert _type_scale_style_438({"design_system": {"palette": {}}}, ("hero",)) == ""
    assert _type_scale_style_438(_TS, ("nav", "footer")) == ""   # no matching role
    assert _type_scale_style_438(None, ("hero",)) == ""


def test_ignores_absurd_sizes():
    bad = {"design_system": {"type_scale": [{"role": "hero", "size_px": 9999, "weight": 700}]}}
    s = _type_scale_style_438(bad, ("hero",))
    assert "fontSize" not in s and "fontWeight: 700" in s  # weight kept, absurd px dropped


def test_hero_h1_gets_exact_size_in_render():
    # #546: the hero title is capped at 64px; a WITHIN-cap measured size still renders
    # EXACTLY (byte-identical below the cap). An over-cap size clamps — see
    # test_reliability_546. (_TS's 90px hero-title-logo now clamps, so use 56px here.)
    TS = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                            "theme": {"default": "dark"},
                            "type_scale": [
                                {"role": "hero-title-logo", "size_px": 56, "weight": 700,
                                 "letter_spacing_em": -0.02, "line_height": 1.0}]},
          "assets": []}
    scr = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.05, 1.0, 0.6]},
        {"id": "rail", "role": 'poster rail of "Trending"', "region": [0, 0.65, 1, 0.85],
         "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, TS,
                                 [("Home", "/browse")], "/api/titles")
    assert "fontSize: '56px'" in out, "hero <h1> applies the exact measured size below the cap"


def test_hero_h1_unchanged_without_type_scale():
    D = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}}, "assets": []}
    scr = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.05, 1.0, 0.6]},
        {"id": "rail", "role": 'poster rail of "Trending"', "region": [0, 0.65, 1, 0.85],
         "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, D,
                                 [("Home", "/browse")], "/api/titles")
    assert "text-4xl" in out and "fontSize:" not in out.split("<h1")[1].split(">")[0]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
