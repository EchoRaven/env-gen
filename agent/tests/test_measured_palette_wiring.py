"""Guard: FIX #208 — hard-wire the MEASURED palette into the build (tailwind
theme + base CSS), by construction — don't leave it as prose the lane may ignore.

Visual-pipeline GAP 2 (Explore report): tailwind.theme.js is projected EMPTY
(`export default {}`) and index.css carries no measured colors; the measured
palette in design_system.json reaches the frontend only as a truncated "BINDING"
prose block + a voluntary file read, verified by nothing. So the app paints
whatever the model guessed while the ground-truth colors sit unused. Project the
measured background/accents straight into tailwind.theme.js AND a base CSS layer
(body background + derived text color), so the app's overall color impression
matches the reference (dark TikTok canvas, brand accent) deterministically.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    render_measured_tailwind_theme, render_measured_base_css,
)

_DS = {"palette": {"bg": "#000000", "accent": "#1f44f2",
                   "accents": {"blue": "#1f44f2", "red": "#d83039",
                               "green": "#84e299"}},
       "theme": {"default": "dark", "themes": ["dark"]}}


class TailwindThemeTests(unittest.TestCase):
    def test_measured_bg_and_accent_in_theme(self):
        js = render_measured_tailwind_theme(_DS)
        self.assertIn("export default", js)
        self.assertIn("#000000", js)      # measured bg
        self.assertIn("#1f44f2", js)      # measured accent
        self.assertIn("#d83039", js)      # a measured accent hue
        # named tokens the lane can use
        self.assertIn("colors", js)

    def test_empty_palette_falls_back_to_empty_theme(self):
        self.assertEqual(render_measured_tailwind_theme({}), "export default {}\n")
        self.assertEqual(render_measured_tailwind_theme({"palette": {}}),
                         "export default {}\n")

    def test_theme_js_is_valid_js_object(self):
        js = render_measured_tailwind_theme(_DS)
        # crude: balanced braces + starts with export default {
        self.assertTrue(js.strip().startswith("export default {"))
        self.assertEqual(js.count("{"), js.count("}"))

    def test_theme_shape_matches_pinned_config_consumer(self):
        """FIX #219 — the pinned tailwind.config.js consumes this module as
        `theme: { extend: theme || {} }`, i.e. the export IS the extend object.
        Emitting `{ theme: { extend: { colors } } }` double-nests to
        extend.theme.extend.colors and the tokens (bg-bg / text-accent) never
        resolve as utilities. The export must carry `colors` at top level."""
        import re
        js = render_measured_tailwind_theme(_DS)
        self.assertRegex(js, r"export default \{\s*colors:\s*\{")
        self.assertNotIn("theme:", js)
        self.assertNotIn("extend:", js)


class MergeLaneTokensTests(unittest.TestCase):
    """FIX #219b — _apply_measured_palette must not clobber lane-authored
    tokens: a lane that wrote `'ig-blue': '#0095F6'` and `@apply bg-ig-blue`
    would get a broken build when the measured overwrite drops the token.
    Measured tokens still WIN on name conflicts (ground truth)."""

    def test_lane_tokens_survive_and_measured_wins(self):
        import tempfile, json
        from multi_agent.runtime.frontend_scaffold import _apply_measured_palette
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            fe = out / "app" / "frontend"
            (fe / "src").mkdir(parents=True)
            (out / "design").mkdir()
            (out / "design" / "design_system.json").write_text(
                json.dumps({"design_system": _DS}), encoding="utf-8")
            (fe / "tailwind.theme.js").write_text(
                "export default {\n  colors: {\n    'ig-blue': '#0095F6',\n"
                "    'bg': '#123456'\n  },\n}\n", encoding="utf-8")
            _apply_measured_palette(fe)
            js = (fe / "tailwind.theme.js").read_text(encoding="utf-8")
            self.assertIn("'ig-blue': '#0095F6'", js)   # lane token preserved
            self.assertIn("'bg': '#000000'", js)         # measured wins conflict
            self.assertNotIn("#123456", js)
            self.assertIn("'accent': '#1f44f2'", js)


class BaseCssTests(unittest.TestCase):
    def test_dark_theme_sets_black_bg_light_text(self):
        css = render_measured_base_css(_DS)
        self.assertIn("@tailwind base", css)
        self.assertIn("@layer base", css)
        # body painted with the measured background
        self.assertIn("#000000", css)
        # dark theme → light default text (derived)
        low = css.lower()
        self.assertTrue("#fff" in low or "#f5f5f5" in low or "#ffffff" in low)

    def test_light_theme_sets_measured_bg_dark_text(self):
        ds = {"palette": {"bg": "#ffffff", "accent": "#0095f6"},
              "theme": {"default": "light"}}
        css = render_measured_base_css(ds)
        self.assertIn("#ffffff", css)
        # light theme → dark default text
        self.assertTrue(any(c in css.lower() for c in ("#000", "#111", "#18181b", "#1a1a1a")))

    def test_no_palette_is_plain_baseline(self):
        css = render_measured_base_css({})
        self.assertIn("@tailwind base", css)
        self.assertNotIn("@layer base", css)  # nothing measured to inject


if __name__ == "__main__":
    unittest.main()
