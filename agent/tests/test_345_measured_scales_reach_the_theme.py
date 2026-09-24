"""#345: project the measured type / radius / shadow scales, like #343 did colours.

design_system.json carries measured `type_scale`, `radius_scale` and
`shadow_scale` on every run, and none of them ever reached tailwind.theme.js --
the file contains a `colors` block and nothing else. So the lane had no
measured name for a radius, a text size or an elevation and fell back to
Tailwind defaults, which is the same failure mode #343 fixed for colour.

The shapes are NOT stable across runs, which is the real constraint:

    r91  type_scale[].line_px / .font      radius_scale has a `notes` prose key
    r93  type_scale[].line_height / .family   shadow_scale[].css  (r91: .value)

so the projector reads both spellings and skips anything that is not a value.

`spacing_scale_px` is deliberately NOT projected. Tailwind's `spacing` keys are
the ones `p-4` / `gap-2` resolve through; emitting `{'4': '4px'}` would silently
redefine `p-4` from 16px to 4px and break every spacing utility already written
by the lane. A measured spacing ladder is only safe under a distinct prefix,
which is a bigger change than this one.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

R93 = {"palette": {"bg": "#000"},
       "type_scale": [{"role": "logo", "size_px": 28, "weight": 700},
                      {"role": "h1", "size_px": 24, "weight": 700, "line_height": 1.2}],
       "radius_scale": {"pill": 9999, "button": 4, "card": 8, "avatar": 9999},
       "shadow_scale": [{"role": "modal", "css": "0 4px 24px rgba(0,0,0,0.35)"},
                        {"role": "chip", "css": "none"}],
       "spacing_scale_px": [0, 4, 8, 12, 16]}

R91 = {"palette": {"bg": "#000"},
       "type_scale": [{"role": "h1_display", "size_px": 32, "line_px": 40, "weight": 700}],
       "radius_scale": {"pill": 999, "circle": "50%", "button": 4,
                        "notes": "Follow buttons are radius 4 -- NOT pill"},
       "shadow_scale": [{"role": "modal_backdrop", "value": "rgba(0,0,0,0.72)"}]}


def _theme(ds):
    from multi_agent.runtime.frontend_scaffold import render_measured_tailwind_theme
    return render_measured_tailwind_theme(ds)


class TypeScaleIsProjected(unittest.TestCase):

    def test_font_sizes_appear(self):
        t = _theme(R93)
        self.assertIn("fontSize", t)
        self.assertIn("'logo'", t)
        self.assertIn("28px", t)

    def test_line_height_spelling_r93(self):
        self.assertIn("1.2", _theme(R93))

    def test_line_px_spelling_r91(self):
        """r91 measured line_px instead of line_height."""
        self.assertIn("40px", _theme(R91))

    def test_weight_is_carried(self):
        self.assertIn("700", _theme(R93))


class RadiusScaleIsProjected(unittest.TestCase):

    def test_numeric_radii_get_px(self):
        t = _theme(R93)
        self.assertIn("borderRadius", t)
        self.assertIn("9999px", t)
        self.assertIn("'card': '8px'", t)

    def test_percent_radius_passes_through(self):
        self.assertIn("50%", _theme(R91))

    def test_prose_key_is_not_a_token(self):
        """r91's radius_scale carries a `notes` sentence."""
        self.assertNotIn("notes", _theme(R91))


class ShadowScaleIsProjected(unittest.TestCase):

    def test_css_spelling_r93(self):
        t = _theme(R93)
        self.assertIn("boxShadow", t)
        self.assertIn("0 4px 24px rgba(0,0,0,0.35)", t)

    def test_value_spelling_r91(self):
        self.assertIn("rgba(0,0,0,0.72)", _theme(R91))

    def test_none_is_a_legitimate_shadow(self):
        self.assertIn("'chip'", _theme(R93))


class SpacingIsDeliberatelyNotProjected(unittest.TestCase):
    """Emitting Tailwind `spacing` keys would redefine p-4 from 16px to 4px."""

    def test_no_spacing_block(self):
        self.assertNotIn("spacing", _theme(R93))


class ColoursAndDegenerateInputsAreUnaffected(unittest.TestCase):

    def test_colours_still_projected(self):
        self.assertIn("'bg': '#000'", _theme(R93))

    def test_no_scales_means_colours_only(self):
        t = _theme({"palette": {"bg": "#000"}})
        for block in ("fontSize", "borderRadius", "boxShadow"):
            self.assertNotIn(block, t)

    def test_nothing_measured_returns_the_empty_baseline(self):
        self.assertEqual(_theme({}), "export default {}\n")

    def test_scales_without_a_palette_still_project(self):
        t = _theme({"radius_scale": {"card": 8}})
        self.assertIn("borderRadius", t)


class TheCallerPreservesTheNonColourSections(unittest.TestCase):
    """The merge path rebuilds the file from `colors` alone; without a fix the
    new blocks would be discarded on the very next tick."""

    def test_scaffolder_writes_the_measured_sections(self):
        from multi_agent.runtime import frontend_scaffold
        src = Path(frontend_scaffold.__file__).read_text()
        self.assertIn("render_measured_theme_sections", src)


if __name__ == "__main__":
    unittest.main()
