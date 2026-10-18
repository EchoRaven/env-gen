r"""#1203nj: a cap that never bit until #1203ni made it bite, in a channel that is a prompt.

`design_system_summary_for_requirements` renders one line per screen listing its components,
capped at 10. The cap was dead code for the whole modern era: the design_analyst's wholesale
rewrite left 2-4 components a screen (#1203nh measured 35 across 11 screens on r189/r190/r191),
so every component was always shown and nothing was ever cut.

#1203ni restores the measured components the rewrite dropped -- r191's `fyp_feed_logged_out`
goes from 4 to 19 -- so from this point the line is ALWAYS a cut list. A cut list that does
not say so is exactly #1034's harm, and this is the channel where it costs most: the lane
reads this line as the screen's component inventory and cannot tell there are more.

THE CAP IS NOT RAISED. Ten MEASURED components is already more than the 2-4 coarse ones the
line used to carry, and nothing measured says the lane needs more; what was missing was the
knowledge that more exist.

TWO CUTS, EACH NAMED. The pre-#1203nj code also sliced the rendered line with a bare `[:600]`.
That bound is kept -- this text is a prompt, so an unbounded line is a bill -- but it declares
itself instead of slicing mid-token.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _BRIEF_COMP_CAP_1203NJ as CAP,
    _BRIEF_LINE_CHARS_1203NJ as CHARS,
    design_system_summary_for_requirements as summarise,
)


def _ds(n_components, screen="fyp_feed_logged_out", id_len=12):
    return {"screens": [{"name": screen, "components": [
        {"id": ("c%02d" % i).ljust(id_len, "x"), "colors": {"bg": "#000000"}}
        for i in range(n_components)]}]}


def _line(text, screen="fyp_feed_logged_out"):
    for ln in text.split("\n"):
        if ln.startswith(screen + ":"):
            return ln
    return ""


class TheCutIsDeclared(unittest.TestCase):
    def test_r191s_restored_screen(self):
        """19 components, 10 shown -- the other 9 must be named as withheld."""
        ln = _line(summarise(_ds(19)))
        self.assertTrue(ln, "the screen line is gone")
        self.assertIn("+9 more not shown", ln)

    def test_the_number_withheld_is_the_real_remainder(self):
        for n in (CAP + 1, CAP + 5, 30):
            with self.subTest(components=n):
                ln = _line(summarise(_ds(n)))
                self.assertIn("+%d more not shown" % (n - CAP), ln)

    def test_exactly_the_cap_is_not_a_cut(self):
        ln = _line(summarise(_ds(CAP)))
        self.assertNotIn("more not shown", ln)
        self.assertIn("c%02d" % (CAP - 1), ln)

    def test_the_shape_the_line_used_to_carry_is_unchanged(self):
        """2-4 components -- every modern run before #1203ni -- must look exactly as before."""
        for n in (1, 2, 4):
            with self.subTest(components=n):
                ln = _line(summarise(_ds(n)))
                self.assertNotIn("more not shown", ln)
                self.assertNotIn("truncated", ln)
                for i in range(n):
                    self.assertIn("c%02d" % i, ln)

    def test_it_still_names_the_screen_and_the_colors(self):
        ln = _line(summarise(_ds(3)))
        self.assertTrue(ln.startswith("fyp_feed_logged_out:"))
        self.assertIn("bg:#000000", ln)


class TheCharacterBoundIsKeptAndDeclared(unittest.TestCase):
    def test_a_pathological_line_stays_bounded(self):
        ln = _line(summarise(_ds(19, id_len=90)))
        self.assertLessEqual(len(ln), CHARS + 80, len(ln))

    def test_the_truncation_says_so(self):
        ln = _line(summarise(_ds(19, id_len=90)))
        self.assertIn("truncated at %d chars" % CHARS, ln)

    def test_it_does_not_slice_mid_token(self):
        ln = _line(summarise(_ds(19, id_len=90)))
        body = ln.split(":", 1)[1].split(" …")[0]
        self.assertFalse(body.rstrip().endswith("x"),
                         "the cut landed inside an id: %r" % body[-40:])

    def test_an_ordinary_line_is_not_truncated(self):
        ln = _line(summarise(_ds(CAP)))
        self.assertNotIn("truncated", ln)


class TheCapsAreNamed(unittest.TestCase):
    """Read from the module rather than restated, so a change moves both at once (#1032)."""

    def test_the_component_cap(self):
        self.assertEqual(CAP, 10)

    def test_the_character_bound(self):
        self.assertEqual(CHARS, 600)

    def test_the_renderer_uses_the_named_cap(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(summarise).lstrip())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertIn("_BRIEF_COMP_CAP_1203NJ", names)
        self.assertIn("_BRIEF_LINE_CHARS_1203NJ", names)

    def test_the_cut_goes_through_join_capped(self):
        """#1032: one owner for the remainder rule."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(summarise).lstrip())
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("join_capped", calls)


class ItNeverRaises(unittest.TestCase):
    def test_the_shapes_that_occur(self):
        """A missing, empty or screen-less document is a real state -- the analyst can produce
        nothing at all (#813/#819 exist for that), and a component list can carry junk."""
        for ds in (None, {}, {"screens": None},
                   {"screens": [{"name": "s", "components": "nope"}]},
                   {"screens": [{"name": "s", "components": [None, 7]}]}):
            with self.subTest(ds=repr(ds)[:34]):
                self.assertIsInstance(summarise(ds), str)

    # ★ A NON-DICT ENTRY IN `screens` DOES RAISE, and is deliberately neither guarded nor
    # tested. Measured before deciding: 0 of the 104 `design_system.json` files in the corpus
    # carry a non-dict screen or component -- `screens` is a list in 104 of 104. The document
    # is agent-authored, so the shape is imaginable, but patching for a population that has
    # never existed is the habit #647 exists to stop, and the enclosing caller already logs
    # "Design-Prep phase failed (continuing)" if it ever happens. Written down rather than
    # fixed, because the next reader should see the number and not re-derive it.


if __name__ == "__main__":
    unittest.main()
