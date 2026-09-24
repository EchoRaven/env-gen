"""#343: project every MEASURED colour, not just three of them.

`render_measured_tailwind_theme` emitted only `bg`, `accent` and `accents.*`,
and `_HEX_RE_208` accepted only `#rrggbb`. Measured vs projected, per run:

    r91  26 colour values measured ->  7 tokens   (73% dropped)
    r92  23                        ->  8          (65%)
    r93  37                        ->  7          (81%)

Everything else the design analyst measured was discarded: surface, surface_2,
elevated, chrome_pill, hover, border, divider, text, text_2, text_3,
text_muted, input_bg, chip_bg... In r93 six of those are authored as `rgba(...)`
(text_2, text_muted, text_disabled, footer_text, video_progress_track) and were
rejected outright by the hex-only regex.

There is a second, quieter loss: the caller merges the rendered theme into any
existing tailwind.theme.js with a regex that ALSO matched hex only, so an
`rgba()` token would have been dropped again at merge time even once emitted.

`notes` is a prose field, not a colour, and must not become a token -- so the
rule is "every value that IS a colour", not "every value".
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

DS = {"palette": {
    "bg": "#000000",
    "accent": "#fe2c55",
    "surface": "#121212",
    "surface_2": "#1e1e1e",
    "border": "rgba(255,255,255,0.12)",
    "text_muted": "rgba(255, 255, 255, 0.5)",
    "notes": "measured from the logged-out feed",
    "accents": {"red": "#fe2c55", "blue": "#20d5ec"},
}}


def _theme(ds):
    from multi_agent.runtime.frontend_scaffold import render_measured_tailwind_theme
    return render_measured_tailwind_theme(ds)


def _tokens(css):
    return dict(re.findall(r"'([^']+)':\s*'([^']+)'", css))


class EveryMeasuredColourIsProjected(unittest.TestCase):

    def test_plain_hex_keys_beyond_bg_and_accent(self):
        t = _tokens(_theme(DS))
        self.assertEqual(t.get("surface"), "#121212")
        self.assertEqual(t.get("surface-2"), "#1e1e1e")

    def test_rgba_values_are_projected(self):
        t = _tokens(_theme(DS))
        self.assertEqual(t.get("border"), "rgba(255,255,255,0.12)")
        self.assertEqual(t.get("text-muted"), "rgba(255, 255, 255, 0.5)")

    def test_the_established_token_names_are_unchanged(self):
        """#334's auth template consumes bg-bg and bg-accent."""
        t = _tokens(_theme(DS))
        self.assertEqual(t.get("bg"), "#000000")
        self.assertEqual(t.get("accent"), "#fe2c55")

    def test_accents_keep_their_prefixed_names(self):
        t = _tokens(_theme(DS))
        self.assertEqual(t.get("accent-red"), "#fe2c55")
        self.assertEqual(t.get("accent-blue"), "#20d5ec")

    def test_snake_case_becomes_kebab_for_tailwind(self):
        self.assertIn("surface-2", _tokens(_theme(DS)))
        self.assertNotIn("surface_2", _tokens(_theme(DS)))


class NonColourValuesAreNotTokens(unittest.TestCase):

    def test_prose_is_skipped(self):
        self.assertNotIn("notes", _tokens(_theme(DS)))

    def test_numbers_and_nested_objects_are_skipped(self):
        t = _tokens(_theme({"palette": {"bg": "#000", "spacing": 8,
                                        "layout": {"a": "#fff"}}}))
        self.assertNotIn("spacing", t)
        self.assertNotIn("layout", t)


class EmptyAndDegenerateInputs(unittest.TestCase):

    def test_no_palette_returns_the_empty_baseline(self):
        self.assertEqual(_theme({}), "export default {}\n")

    def test_palette_with_no_colours_returns_the_empty_baseline(self):
        self.assertEqual(_theme({"palette": {"notes": "none"}}),
                         "export default {}\n")


class TheMergeRegexKeepsNonHexTokens(unittest.TestCase):
    """The caller merges rendered tokens into an existing theme file; a hex-only
    merge pattern would drop rgba() a second time."""

    def test_merge_pattern_matches_an_rgba_token(self):
        from multi_agent.runtime import frontend_scaffold
        src = Path(frontend_scaffold.__file__).read_text()
        m = re.search(r"_tok_re = re\.compile\(\s*(r?['\"].*?['\"])\s*\)", src, re.S)
        self.assertIsNotNone(m, "merge regex not found")
        pattern = eval(m.group(1))
        sample = "    'border': 'rgba(255,255,255,0.12)',\n    'bg': '#000000',"
        found = dict(re.findall(pattern, sample))
        self.assertEqual(found.get("border"), "rgba(255,255,255,0.12)")
        self.assertEqual(found.get("bg"), "#000000")


if __name__ == "__main__":
    unittest.main()
