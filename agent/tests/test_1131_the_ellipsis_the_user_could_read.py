r"""#1131: `Loading…` was shipped to the screen as those nine characters.

`frontend_scaffold.py` emits JSX. Six of its templates wrote the loading label as JSX TEXT:

    <p className="mt-6 text-sm opacity-50">Loading…</p>

A `\uXXXX` escape is decoded by JavaScript inside a STRING LITERAL. As JSX text it is not a
string literal -- it is character data, and React renders it verbatim. Every generated app
that reached a loading state displayed the literal `Loading…`.

Confirmed in delivered artifacts, not inferred: 9 generated .jsx files across
netflix-local-r1 (current code), tiktok-web-r81 and tiktok-web-r35 carry it, and the
visual-fidelity capture of netflix's /games page photographed it on screen.

The seventh site is CORRECT and is deliberately untouched:

    <p className="text-lg">{loading ? 'Loading…' : 'Titles you...'}</p>

there the escape sits inside a single-quoted JS string, which JS decodes to a real ellipsis.
The rule is about POSITION, not about the escape, so this test encodes the position rule
rather than pinning six line numbers.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
            / "frontend_scaffold.py")

# JS string literals as they appear in these templates: plain single quotes. An escape
# inside one is decoded by JavaScript and is correct; only CHARACTER DATA is the defect.
_QUOTED = re.compile(r"'(?:[^'\\\\]|\\\\.)*'")
_JSX_TEXT = re.compile(r">([^<>]{1,200})<")
_UNI_ESCAPE = re.compile(r"\\\\u[0-9a-fA-F]{4}")


def _jsx_text_escapes(src: str):
    """Every literal \\uXXXX sitting in JSX CHARACTER DATA, ignoring quoted JS strings."""
    hits = []
    for lineno, line in enumerate(src.split("\n"), 1):
        if "u2026" not in line and "\\\\u" not in line:
            continue
        # blank out quoted JS strings; an escape inside one is decoded by JS and is fine
        bare = _QUOTED.sub(lambda m: " " * len(m.group(0)), line)
        for m in _JSX_TEXT.finditer(bare):
            if _UNI_ESCAPE.search(m.group(1)):
                hits.append((lineno, m.group(1)[:60]))
    return hits


class TheEllipsisTheUserCouldRead(unittest.TestCase):

    def test_no_emitted_template_puts_an_escape_in_jsx_text(self):
        hits = _jsx_text_escapes(SCAFFOLD.read_text(encoding="utf-8"))
        self.assertEqual(
            hits, [],
            "these render verbatim on screen; use the character itself:\n  "
            + "\n  ".join(f"line {n}: {t}" for n, t in hits))

    def test_the_detector_would_have_caught_the_shipped_defect(self):
        """A test that cannot fail on the original bug pins nothing."""
        broken = r'''        "          <p className=\"mt-6 text-sm\">Loading\\u2026</p>",'''
        self.assertTrue(_jsx_text_escapes(broken), "detector is blind to the real defect")

    def test_the_detector_allows_an_escape_inside_a_js_string(self):
        """The seventh site: JS decodes it, so it is correct and must not be flagged."""
        ok = r'''        "            <p className=\"text-lg\">{loading ? 'Loading\\u2026' : 'x'}</p>",'''
        self.assertEqual(_jsx_text_escapes(ok), [])

    def test_the_loading_label_is_a_real_ellipsis_now(self):
        src = SCAFFOLD.read_text(encoding="utf-8")
        self.assertIn(">Loading…</p>", src)
        self.assertNotIn(r">Loading\\u2026</p>", src)


if __name__ == "__main__":
    unittest.main()
