"""#342: staged brand fonts must actually be referenced by the app.

Design-prep stages the reference's real font files into
`app/frontend/public/assets/fonts/` on every run -- r91/r92/r93 each carry
TikTokDisplayFont-Bold, TikTokFont-{Bold,Regular,Semibold} and TikTokSans-VF --
and `design_system.json` carries a measured `font_stack`:

    "'TikTokFont', 'TikTokFont-Regular', -apple-system, ... sans-serif"

But `grep -rl "font-family|fontFamily|@font-face"` over `src/` + `index.html`
returns ZERO files in every run. The files ship and nothing points at them, so
every screen renders in the browser default while the reference uses the brand
face. Staging was implemented; wiring never was.

This is the cheapest remaining UI-fidelity win: fully deterministic, no LLM
involved, and it applies to any env whose design input stages fonts. No staged
fonts => no emission, so envs without design input are unaffected.
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

FONTS = ["TikTokFont-Regular.woff2", "TikTokFont-Semibold.woff2",
         "TikTokFont-Bold.woff2", "TikTokDisplayFont-Bold.woff2"]
DS = {
    "palette": {"bg": "#000000", "accent": "#fe2c55"},
    "theme": {"default": "dark"},
    "font_stack": "'TikTokFont', 'TikTokFont-Regular', -apple-system, sans-serif",
}


def _render(ds, fonts=None):
    from multi_agent.runtime.frontend_scaffold import render_measured_base_css
    return render_measured_base_css(ds, font_files=fonts)


class FontFacesAreEmitted(unittest.TestCase):

    def test_one_font_face_per_staged_file(self):
        css = _render(DS, FONTS)
        self.assertEqual(css.count("@font-face"), len(FONTS))

    def test_each_file_is_referenced_by_its_public_url(self):
        css = _render(DS, FONTS)
        for f in FONTS:
            self.assertIn(f"/assets/fonts/{f}", css)

    def test_woff2_format_and_swap_are_declared(self):
        css = _render(DS, FONTS)
        self.assertIn("format('woff2')", css)
        self.assertIn("font-display: swap", css)

    def test_weight_is_derived_from_the_filename_suffix(self):
        css = _render(DS, ["TikTokFont-Regular.woff2"])
        self.assertIn("font-weight: 400", css)
        css = _render(DS, ["TikTokFont-Semibold.woff2"])
        self.assertIn("font-weight: 600", css)
        css = _render(DS, ["TikTokFont-Bold.woff2"])
        self.assertIn("font-weight: 700", css)

    def test_family_name_drops_the_weight_suffix(self):
        """TikTokFont-Regular and TikTokFont-Bold are ONE family at two weights."""
        css = _render(DS, ["TikTokFont-Regular.woff2", "TikTokFont-Bold.woff2"])
        families = set(re.findall(r"font-family:\s*'([^']+)'", css))
        self.assertIn("TikTokFont", families)
        self.assertNotIn("TikTokFont-Bold", families)


class TheBodyActuallyUsesThem(unittest.TestCase):

    def test_body_font_family_is_set_from_the_measured_stack(self):
        css = _render(DS, FONTS)
        body = css.split("body", 1)[1]
        self.assertIn("TikTokFont", body)
        self.assertIn("sans-serif", body)

    def test_without_a_measured_stack_the_primary_family_is_used(self):
        ds = {k: v for k, v in DS.items() if k != "font_stack"}
        css = _render(ds, FONTS)
        self.assertIn("TikTokFont", css.split("body", 1)[1])


class NoStagedFontsIsANoOp(unittest.TestCase):
    """Envs generated without design input must be byte-identical to before."""

    def test_none_emits_no_font_face(self):
        self.assertNotIn("@font-face", _render(DS, None))

    def test_empty_list_emits_no_font_face(self):
        self.assertNotIn("@font-face", _render(DS, []))

    def test_non_font_files_are_ignored(self):
        self.assertNotIn("@font-face", _render(DS, ["README.md", "logo.png"]))


class FontsDoNotDependOnAMeasuredPalette(unittest.TestCase):
    """A run may stage fonts without a usable palette; the fonts must still wire."""

    def test_fonts_emit_even_with_no_palette(self):
        css = _render({}, FONTS)
        self.assertIn("@font-face", css)
        self.assertIn("/assets/fonts/TikTokFont-Regular.woff2", css)

    def test_layer_marker_present_so_the_caller_injects_it(self):
        """The caller drops everything before `@layer base`."""
        self.assertIn("@layer base", _render({}, FONTS))


if __name__ == "__main__":
    unittest.main()
