r"""#1203q3: "reference them, do NOT draw" about a list that had been silently halved.

`design_system_summary_for_requirements` builds, in its own docstring's words, a "Compact
BINDING block appended to the requirements every lane reads". One line of it is

    "Real assets (STAGED at public/assets/ -- reference them, do NOT draw): " + ", ".join(
        f"{id}->/assets/{file}" for a in assets[:24])[:1200]

Cut twice, neither declared: `[:24]` on the entries, then `[:1200]` on the joined string.
Two caps for one rule is #1203pr's shape; an undeclared cut is #1034's.

MEASURED over the 104 design documents that carry a mapped-asset list: 91 (87.5%) are cut
here, 5032 assets in total are never named to a lane, and all 7 modern runs are affected. The
severity is the generality half of it -- several netflix-local runs map 170 assets and the
lane is told about 24 (86% dropped), while modern tiktok maps 23 and loses a handful to the
character budget. The same code is far worse on the products that get run less often.

NOT the cause of the 14-of-36 icon mapping gap: `assets` here is `ds.get("assets")`, the
ALREADY-MAPPED set, so this is a second cut after that one. They stack.

Both bounds are KEPT -- they bound a prompt, and changing what every lane is sent needs a
live run (#1202w6). Only the remainder is now declared.
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


def _ds(n_assets, idlen=12):
    """A valid design doc with `n_assets` mapped assets."""
    return {
        "screens": [{"name": "s1", "components": []}],
        "design_system": {"palette": {"bg": "#000"}},
        "assets": [{"id": ("a%d" % i).ljust(idlen, "x"),
                    "file": "icons/a%d.svg" % i} for i in range(n_assets)],
    }


def _assets_line(ds):
    for line in SUMMARY(ds).split("\n"):
        if "Real assets" in line:
            return line
    return ""


class TheCutIsDeclared(unittest.TestCase):

    def test_a_list_past_the_entry_cap_says_how_many_it_left_out(self):
        """★ netflix-local's shape: 170 mapped, 24 is the cap."""
        import re
        line = _assets_line(_ds(170))
        self.assertIn("more not shown", line)
        # THE INVARIANT, not a hardcoded number: declared == total - shown. A literal
        # would be wrong for a different id length -- the real netflix-local-r9 doc declares
        # +147 because its longer ids leave room for only 23 entries, while this fixture's
        # short ids fit 24 and declare +146. Asserting the arithmetic cannot drift.
        shown = line.count("\u2192/assets/")
        declared = int(re.search(r"\+(\d+) more", line).group(1))
        self.assertEqual(declared, 170 - shown, (shown, declared, line[-60:]))
        self.assertGreater(declared, 100, "the entry cap stopped biting")

    def test_the_declared_total_is_the_REAL_total_not_the_shown_count(self):
        """The failure this guards: declaring `len(shown)` would make the sentence
        self-consistent and still wrong -- #1203pl's and #1203pa's exact defect."""
        line = _assets_line(_ds(60))
        self.assertIn("more not shown", line)
        self.assertNotIn("(+0 more", line)
        # 60 assets, at most 24 shown -> at least 36 declared missing
        import re
        n = int(re.search(r"\+(\d+) more", line).group(1))
        self.assertGreaterEqual(n, 36, line[-80:])

    def test_a_short_list_claims_no_cut(self):
        """#983: a clause that fires while naming nothing."""
        line = _assets_line(_ds(3))
        self.assertTrue(line)
        self.assertNotIn("not shown", line)

    def test_an_empty_asset_list_emits_no_line_at_all(self):
        self.assertEqual(_assets_line(_ds(0)), "")


class BothBoundsSurvive(unittest.TestCase):
    """They bound a prompt every lane is sent; #1202w6 keeps that a live-run decision."""

    def test_the_entry_cap_still_holds(self):
        line = _assets_line(_ds(170))
        self.assertLessEqual(line.count("->/assets/") + line.count("→/assets/"), 24, line[:120])

    def test_the_character_budget_still_holds(self):
        """Long ids must not blow the budget: the entry count is reduced until it fits, and
        what that reduction left out is declared too."""
        line = _assets_line(_ds(40, idlen=90))
        body = line.split(": ", 1)[1] if ": " in line else line
        self.assertLessEqual(len(body), 1400, len(body))
        self.assertIn("more not shown", line)

    def test_a_single_huge_entry_does_not_loop_forever(self):
        line = _assets_line(_ds(2, idlen=2000))
        self.assertTrue(line)


if __name__ == "__main__":
    unittest.main()
