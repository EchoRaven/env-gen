r"""#1203q5: the binding design block described 12 screens of 29 and did not say so.

Three lines below this cap, `#1203nj` named the per-screen COMPONENT cap "so the cut can be
declared against" it, and its comment says: "a cut list that does not say so is the harm
#1034 exists for, in the channel where it costs most: the lane reads this as the screen's
component inventory." The cap ENCLOSING that loop -- `for s in screens[:12]` -- never got the
same treatment, and it is the coarser of the two: a dropped component costs a detail, a
dropped screen costs the whole page.

MEASURED over the 104 design docs: 32 carry more than 12 screens. googlemaps runs carry 29,
so 17 -- 59% of the app -- were never mentioned; netflix carries 20 (8 hidden); tiktok's 11-12
fit, which is why this never surfaced on the product we run most. Same skew as #1203q3 and
#1203q4: the block is worst on the products that get run least.

The cap is NOT raised, for #1203nj's own reason: this is a prompt, 12 screens of component
inventory is already the bulk of the block, and nothing measured says the lane needs more.
What was missing is that it could not tell there WERE more.
"""
import sys
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.design_prep import (  # noqa: E402
    design_system_summary_for_requirements as SUMMARY,
)


def _ds(n_screens):
    return {
        "design_system": {"palette": {"bg": "#000"}},
        "screens": [{"name": "s%02d" % i,
                     "components": [{"id": "c%d" % i, "colors": {"bg": "#111"}}]}
                    for i in range(n_screens)],
    }


def _cut_line(ds):
    for line in SUMMARY(ds).split("\n"):
        if "further screen" in line:
            return line
    return ""


class TheScreenCutIsDeclared(unittest.TestCase):

    def test_googlemaps_shape_says_how_many_screens_it_skipped(self):
        """★ THE TICKET at the worst real figure: 29 screens, 12 described."""
        self.assertIn("+17 further screen", _cut_line(_ds(29)))

    def test_netflix_shape(self):
        self.assertIn("+8 further screen", _cut_line(_ds(20)))

    def test_a_design_that_fits_claims_no_cut(self):
        """tiktok's 11-12 screens fit; #983 -- a clause that fires while naming nothing."""
        self.assertEqual(_cut_line(_ds(11)), "")
        self.assertEqual(_cut_line(_ds(12)), "")

    def test_the_number_is_the_REMAINDER_not_the_total(self):
        line = _cut_line(_ds(29))
        self.assertNotIn("+29", line)
        self.assertNotIn("+12", line)

    def test_the_first_twelve_are_still_described(self):
        out = SUMMARY(_ds(29))
        for i in range(12):
            self.assertIn("s%02d:" % i, out)
        self.assertNotIn("s12:", out)

    def test_it_points_at_where_the_rest_lives(self):
        """A declaration a lane cannot act on is a tease; name the file that has them."""
        self.assertIn("design_system.json", _cut_line(_ds(29)))


class TheCapItselfIsUnchanged(unittest.TestCase):
    """#647/#1203nj: not raised. Pinning that stops a later reader from quietly enlarging a
    prompt every lane receives, which is a live-run decision (#1202w6)."""

    def test_exactly_twelve_screens_are_described(self):
        out = SUMMARY(_ds(40))
        described = sum(1 for i in range(40) if ("s%02d:" % i) in out)
        self.assertEqual(described, 12, described)

    def test_the_component_cap_still_declares_itself_too(self):
        """The neighbour this fix was modelled on must keep working -- two different cuts,
        each named (#1203nj's words)."""
        ds = _ds(1)
        ds["screens"][0]["components"] = [
            {"id": "c%d" % i, "colors": {"bg": "#111"}} for i in range(25)]
        out = SUMMARY(ds)
        self.assertIn("more", out, out[-200:])


class ItStillBehaves(unittest.TestCase):

    def test_no_screens_means_no_cut_line(self):
        self.assertEqual(_cut_line({"design_system": {"palette": {"a": "#1"}}}), "")

    def test_junk_screens_do_not_raise(self):
        self.assertEqual(_cut_line({"design_system": {"palette": {"a": "#1"}},
                                    "screens": ["x", None, 3]}), "")


if __name__ == "__main__":
    unittest.main()
