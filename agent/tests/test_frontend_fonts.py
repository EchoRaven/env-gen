"""#442 (real fidelity bug + product-specific lever using STAGED assets). index.css
applied the staged DISPLAY font (Anton — a bold condensed TITLE font) to <body>
(r30 body font-family='display_anton_0'), so ALL text (nav/body/captions) rendered
as condensed titles, and the display font was never used on headings. design-prep
stages a display font ('display_*') AND a UI/text font ('ui_*'); the correct
assignment is body→UI font, headings/hero-title→display font (approximating the
reference's stylised title art). FIX: _font_face_blocks classifies families by role;
render_measured_base_css emits body→ui + h1/h2/h3→display. Generalizable (keys off
the family name), uses only staged assets. Lifts typography/style on every screen."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _font_face_blocks, render_measured_base_css)

_FONTS = ["display_anton_0.woff2", "display_anton_1.woff2",
          "ui_inter_0.woff2", "ui_inter_1.woff2"]
_DS = {"design_system": {"palette": {"bg": "#141414"}, "theme": {"default": "dark"}}}


def test_classifies_display_vs_ui_by_role():
    faces, ui, disp = _font_face_blocks(_FONTS)
    assert ui == "ui_inter_0", "body must use the UI/text font"
    assert disp == "display_anton_0", "headings must use the display font"
    assert "@font-face" in faces


def test_body_uses_ui_font_not_display():
    css = render_measured_base_css(_DS, _FONTS)
    pre_heading = css.split("h1, h2, h3")[0]
    # the body block (before the heading rule) must reference the UI font, not Anton
    body_region = pre_heading.split("@font-face")[-1]  # after the @font-face declarations
    assert "ui_inter_0" in body_region
    assert "display_anton" not in body_region, "the condensed display font must NOT be on body"


def test_headings_use_display_font():
    css = render_measured_base_css(_DS, _FONTS)
    assert "h1, h2, h3 { font-family: 'display_anton_0'" in css, \
        "the display font must be applied to headings (title-art approximation)"


def test_no_palette_still_wires_role_fonts():
    css = render_measured_base_css({"design_system": {}}, _FONTS)
    assert "h1, h2, h3 { font-family: 'display_anton_0'" in css
    assert "ui_inter_0" in css.split("h1, h2, h3")[0].split("@font-face")[-1]


def test_no_fonts_is_noop():
    assert _font_face_blocks([]) == ("", "", "")
    css = render_measured_base_css(_DS, [])
    assert "@font-face" not in css and "h1, h2, h3 { font-family" not in css


def test_only_ui_fonts_body_gets_ui_no_heading_rule():
    faces, ui, disp = _font_face_blocks(["ui_inter_0.woff2"])
    assert ui == "ui_inter_0" and disp == ""   # no display font staged
    css = render_measured_base_css(_DS, ["ui_inter_0.woff2"])
    assert "ui_inter_0" in css and "h1, h2, h3 { font-family" not in css


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
