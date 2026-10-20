r"""#1203q6: two lane-facing prose lines were cut mid-word with nothing saying so.

The briefing's `Material:` line was `str(dsys["material"])[:200]` and its `Palette (measured):`
line was `pal_txt[:800]`. Both slice a string at a fixed width, so the lane was handed
sentences that stop mid-word -- "account popover is a light ", "Login has s" -- in a block it
treats as binding.

MEASURED over the 104 design docs:

    material    cap 200, longest 440   -> cut in 79 docs (76%)
    palette     cap 800, longest 1951  -> cut in 6
    type_scale  cap 400, longest 299   -> cut in 0, so it is LEFT ALONE (#647)

`material` is prose carrying real instructions ("do not sample wallpaper bleed as panel
color"). I checked for the worse failure and did NOT find it: 0 of the 79 cuts land
immediately after a negation, so this is information loss, not inverted meaning.

The idiom is #1203nj's, three lines down the same function -- it already truncates on a word
boundary and says so, in its own words "declares itself now instead of slicing mid-token".
#1203q6 lifts that into one owner so the other two lines share it (#1032).
"""
import sys
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.design_prep import (  # noqa: E402
    _bounded_prose_1203q6 as BOUND,
    design_system_summary_for_requirements as SUMMARY,
)


class TheCutIsDeclaredAndLandsOnAWord(unittest.TestCase):

    def test_a_long_line_says_it_was_truncated(self):
        out = BOUND("word " * 100, 200)
        self.assertIn("truncated at 200 chars", out)

    def test_it_cuts_on_a_WORD_boundary(self):
        """★ THE TICKET: the old form produced 'Login has s'. The marker must follow a whole
        word, not half of one."""
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima"
        # SWEEP the caps instead of picking one. The first version used cap=30 alone, where
        # "alpha bravo charlie delta echo" is exactly 30 chars -- a plain `t[:cap]` lands on
        # a word boundary BY LUCK there, so the mutation that reverts the fix read MISSED.
        # A fixture that happens to agree with the conclusion proves nothing; these caps
        # include several that fall inside a word.
        cut_midword = 0
        for cap in range(12, 60):
            out = BOUND(text, cap)
            head = out.split(" …")[0]
            self.assertTrue(text.startswith(head), (cap, head))
            self.assertIn(head.split()[-1], text.split(),
                          "cap=%d left a partial word: %r" % (cap, head))
            # the RAW cap point, not the trimmed output: `head` always ends on a word by
            # construction, so measuring it answers nothing. What matters is whether a plain
            # `t[:cap]` would have landed inside a word -- that is the case the fix exists
            # for, and the sweep has to contain some.
            if text[cap:cap + 1] not in (" ", ""):
                cut_midword += 1
        self.assertGreater(cut_midword, 10,
                           "no cap in the sweep actually fell inside a word, so this test "
                           "could not have caught a mid-token slice")

    def test_it_points_at_where_the_full_text_lives(self):
        self.assertIn("design_system.json", BOUND("word " * 100, 200))

    def test_a_short_line_is_returned_UNCHANGED(self):
        """#983: no clause when nothing was cut, and no reformatting either."""
        self.assertEqual(BOUND("short prose", 200), "short prose")

    def test_exactly_at_the_cap_is_unchanged(self):
        t = "x" * 200
        self.assertEqual(BOUND(t, 200), t)

    def test_a_single_unbroken_token_still_bounded(self):
        """No space to break on: it must still bound the text rather than return it whole."""
        out = BOUND("y" * 500, 200)
        self.assertLessEqual(len(out.split(" …")[0]), 200)
        self.assertIn("truncated", out)

    def test_junk_never_raises(self):
        for bad in (None, 0, [], {"a": 1}):
            BOUND(bad, 200)


class TheBriefingUsesIt(unittest.TestCase):

    def _ds(self, material=None, palette=None):
        d = {"design_system": {"palette": palette or {"bg": "#000"}},
             "screens": [{"name": "s", "components": []}]}
        if material:
            d["design_system"]["material"] = material
        return d

    def test_the_material_line_declares_its_cut(self):
        out = SUMMARY(self._ds(material="glass " * 100))
        line = [l for l in out.split("\n") if l.startswith("Material:")][0]
        self.assertIn("truncated at 200 chars", line)

    def test_the_palette_line_declares_its_cut(self):
        pal = {("k%03d" % i): ("#%06x" % i) for i in range(200)}
        out = SUMMARY(self._ds(palette=pal))
        line = [l for l in out.split("\n") if l.startswith("Palette")][0]
        self.assertIn("truncated at 800 chars", line)

    def test_a_short_material_line_is_not_marked(self):
        out = SUMMARY(self._ds(material="frosted glass panels"))
        line = [l for l in out.split("\n") if l.startswith("Material:")][0]
        self.assertNotIn("truncated", line)


class TheNonBitingCapIsLeftAlone(unittest.TestCase):
    """#647: type_scale's 400-char bound is never reached in 104 docs (longest 299), so it is
    deliberately NOT routed through the helper. Pinning that stops a later reader from
    'tidying' a cap that does not bite."""

    def test_type_scale_still_uses_its_plain_bound(self):
        import inspect
        src = inspect.getsource(SUMMARY)
        self.assertIn("[:400]", src, "type_scale's untouched bound was changed")


if __name__ == "__main__":
    unittest.main()
