"""#501 (netflix r79, 2026-08-05) — projector painted the CONTENT canvas with the
LETTERBOXING black. The design analyst captures two distinct palette keys — `page`
(#141414, "canonical Netflix page bg — measured on browse_home lower band") and `bg`
(#000000, "letterboxing") — but the projector's content renderers read `pal.get("bg")`,
so every catalog surface rendered pure #000000 while the reference content bg is #141414.
This is the fidelity judge's DOMINANT cross-screen delta ("expected #141414, actual
#000000" on browse_home/movies/shows/…). FIX: a shared `_content_bg` resolver (page → bg
→ background) wired into the app-wide body canvas (render_measured_base_css), the catalog
page container (_render_reference_page), and the measured floor (_measured_floor_colors).
Build-safe (a colour VALUE only). These tests lock the resolver + the two easily-driven
emit sites; the full per-screen fidelity lift validates by render."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _content_bg, render_measured_base_css, _measured_floor_colors)

# r79's real palette shape: page (content) distinct from bg (letterboxing).
_R79_PAL = {"bg": "#000000", "page": "#141414", "surface": "#181818",
            "text": "#ffffff", "accent": "#e50914"}


def _ds(pal):
    return {"design_system": {"palette": pal, "theme": {"default": "dark"}}}


def test_content_bg_prefers_page_over_letterbox():
    # THE bug: page (#141414) must win over bg (#000000).
    assert _content_bg(_R79_PAL) == "#141414"


def test_content_bg_falls_through_to_bg_when_no_page():
    # an app that measured only `bg` is unchanged (byte-identical behavior).
    assert _content_bg({"bg": "#0a0a0a"}) == "#0a0a0a"
    assert _content_bg({"background": "#101014"}) == "#101014"


def test_content_bg_none_when_no_usable_palette():
    assert _content_bg({}) is None
    assert _content_bg({"bg": ""}) is None
    assert _content_bg({"bg": "not-a-hex"}) is None
    assert _content_bg(None) is None


def test_base_css_body_uses_content_bg_not_letterbox():
    css = render_measured_base_css(_ds(_R79_PAL))
    # the app-wide body canvas must be painted #141414, never the letterboxing #000000.
    assert "background-color: #141414" in css, css
    assert "background-color: #000000" not in css, css


def test_base_css_single_bg_app_unchanged():
    # only `bg` measured → body uses it (no regression for apps w/o a page key).
    css = render_measured_base_css(_ds({"bg": "#0b0b0b", "text": "#fff"}))
    assert "background-color: #0b0b0b" in css, css


def test_measured_floor_colors_uses_content_bg():
    fc = _measured_floor_colors(_ds(_R79_PAL))
    assert fc is not None
    assert fc["bg"] == "#141414", fc
    # surface stays the measured elevated surface (unaffected by #501).
    assert fc["surface"] == "#181818", fc


def test_measured_floor_colors_none_without_palette():
    assert _measured_floor_colors({"design_system": {"palette": {}}}) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
