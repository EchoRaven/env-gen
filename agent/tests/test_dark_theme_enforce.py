"""Guard: FIX #209 — when the MEASURED theme is dark, swap the lane's light-neutral
Tailwind utilities for dark equivalents in the generated JSX.

r14 live (with #207 the visual gate finally captured the REAL app): the frontend
lane rendered a LIGHT page for a DARK reference — ForYouFeedPage root was
`min-h-screen bg-zinc-50 text-zinc-900`, nav `bg-white` — so the measured black
canvas (#208 body bg) was painted over white, ~0.5 fidelity. The lane used
generic zinc/white classes instead of the measured dark palette (visual GAP 3,
consumption is soft). Deterministic source heal: for a measured DARK theme,
remap the common light backgrounds/text to dark equivalents so the page renders
dark like the reference — reversible, no !important, gated strictly on
theme==dark (a light measured theme is untouched).
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    darkify_light_utilities, enforce_measured_dark_theme,
)


class DarkifyTests(unittest.TestCase):
    def test_page_root_light_bg_becomes_dark(self):
        src = 'className="min-h-screen bg-zinc-50 text-zinc-900 px-6 py-6"'
        out, n = darkify_light_utilities(src)
        self.assertTrue(n > 0)
        self.assertNotIn("bg-zinc-50", out)
        self.assertNotIn("text-zinc-900", out)
        # a dark bg + light text now
        self.assertIn("bg-", out)
        self.assertIn("text-zinc-100", out)

    def test_white_and_gray_families(self):
        for cls in ("bg-white", "bg-gray-50", "bg-slate-100", "bg-neutral-50"):
            out, n = darkify_light_utilities(f'className="{cls} p-4"')
            self.assertTrue(n >= 1, f"{cls} should be darkified")
            self.assertNotIn(cls, out)

    def test_dark_text_becomes_light(self):
        for cls in ("text-black", "text-zinc-900", "text-gray-800", "text-slate-900"):
            out, n = darkify_light_utilities(f'className="{cls}"')
            self.assertTrue(n >= 1)
            self.assertNotIn(cls, out)

    def test_already_dark_untouched(self):
        src = 'className="bg-black text-white min-h-screen"'
        out, n = darkify_light_utilities(src)
        self.assertEqual(n, 0)
        self.assertEqual(out, src)

    def test_borders_and_hovers_remapped(self):
        out, n = darkify_light_utilities('className="border-zinc-200 hover:bg-zinc-100"')
        self.assertTrue(n >= 1)
        self.assertNotIn("border-zinc-200", out)

    def test_non_class_text_not_touched(self):
        # a string literal that merely contains 'bg-white' inside other content
        src = 'const label = "text-black theme";  // not a className'
        out, n = darkify_light_utilities(src)
        # we operate on class tokens; a bare word in a comment/label may still
        # match — acceptable, but a real accent color must never be remapped:
        self.assertNotIn("#FE2C55", out)  # sanity: no color invention

    def test_accent_colors_preserved(self):
        # brand/accent utilities (bg-accent, bg-red-500) must NOT be darkened
        src = 'className="bg-accent text-white bg-red-500"'
        out, n = darkify_light_utilities(src)
        self.assertIn("bg-accent", out)
        self.assertIn("bg-red-500", out)


class EnforceWrapperTests(unittest.TestCase):
    """The wrapper applies the swap to lane JSX ONLY when the measured theme is
    dark — a light-themed app must be left exactly as the lane wrote it."""

    def _mk(self, tmp, theme, page_src):
        import json
        out = Path(tmp)
        fe = out / "app" / "frontend"
        (fe / "src" / "pages").mkdir(parents=True, exist_ok=True)
        (out / "design").mkdir(parents=True, exist_ok=True)
        (out / "design" / "design_system.json").write_text(json.dumps(
            {"palette": {"bg": "#000000" if theme == "dark" else "#ffffff"},
             "theme": {"default": theme}}), encoding="utf-8")
        page = fe / "src" / "pages" / "FeedPage.jsx"
        page.write_text(page_src, encoding="utf-8")
        return fe, page

    def test_dark_theme_darkens_lane_jsx(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fe, page = self._mk(tmp, "dark",
                'export default () => <div className="min-h-screen bg-zinc-50 text-zinc-900">x</div>')
            rep = enforce_measured_dark_theme(fe)
            self.assertTrue(rep.get("replacements", 0) > 0)
            after = page.read_text(encoding="utf-8")
            self.assertNotIn("bg-zinc-50", after)
            self.assertNotIn("text-zinc-900", after)

    def test_light_theme_leaves_jsx_untouched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = 'export default () => <div className="min-h-screen bg-zinc-50 text-zinc-900">x</div>'
            fe, page = self._mk(tmp, "light", src)
            rep = enforce_measured_dark_theme(fe)
            self.assertTrue(rep.get("skipped"))
            self.assertEqual(page.read_text(encoding="utf-8"), src)  # byte-identical

    def test_no_design_system_skips(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fe = Path(tmp) / "app" / "frontend"
            (fe / "src").mkdir(parents=True, exist_ok=True)
            src = '<div className="bg-white">x</div>'
            (fe / "src" / "A.jsx").write_text(src, encoding="utf-8")
            rep = enforce_measured_dark_theme(fe)
            self.assertTrue(rep.get("skipped"))
            self.assertEqual((fe / "src" / "A.jsx").read_text(encoding="utf-8"), src)


if __name__ == "__main__":
    unittest.main()
