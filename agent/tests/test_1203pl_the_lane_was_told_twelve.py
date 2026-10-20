"""#1203pl: the glyph-icon task announced the CAP as if it were the total.

`glyph_icon_findings_1203kd` stops collecting at its `limit` (default 12) and used to `return
out` the moment it filled, saying nothing about the cut. `scaffolder` builds the lane's task
from that list:

    title=("Replace %d text character(s) used as icons with real icons" % len(_gi1203kd))
    ... % join_capped(_gi1203kd, total=len(_gi1203kd), cap=6)

so BOTH the headline number and the "and N more" note were computed against the capped length.

MEASURED with the framework's own detector against the runs' own delivered source:

    r185   12 at the default cap, 28 in fact   -- 16 hidden, 2.3x
    r186    5 / 5        r188   1 / 1          -- r187, r189, r190, r191 all 0

r185 is a run that DELIVERED. #1034's rule (a capped list must declare its cut) and #1203pa's
shape exactly: there the lane was told fifteen.

The fix follows this module's own out-parameter idiom (#657's `picker_screens`, #740's
`console_errors`, #935's `capture_errors`) so every existing caller is unchanged, and it hands
out a COUNT rather than appending a sentinel to the list -- #1203pa's lesson, because a sentinel
poisons `len()` and the `state_changed_1202ad` tuple that decides whether to re-file the task.

Context for why this one matters: iconography is the weakest of the judge's seven dimensions in
every era, and #1203kd is the only mechanism that can FORCE a change there (a score cannot fail
a screen; a task can). Its loop is confirmed working on live runs -- 31 "used as icons" tasks
across the corpus, 30 completed, all in r190/r191, which are exactly the runs with zero residual
findings. A mechanism that works is worth telling the truth to.
"""

import unittest
from pathlib import Path
import tempfile

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA


def _tree(n_glyphs, extra=""):
    d = Path(tempfile.mkdtemp()) / "src"
    d.mkdir(parents=True)
    body = "\n".join('  <span className="ico">⌷</span>' for _ in range(n_glyphs))
    (d / "Page.jsx").write_text(
        "export default function Page(){ return (<div>\n%s\n</div>); }\n%s" % (body, extra),
        encoding="utf-8")
    return d


class TheTotalIsTheTruth(unittest.TestCase):

    def test_the_scan_still_finds_glyphs(self):
        """Non-vacuity: a detector that found nothing would satisfy every test below."""
        self.assertTrue(FA.glyph_icon_findings_1203kd(_tree(3)))

    def test_under_the_cap_the_total_equals_what_is_shown(self):
        out = []
        shown = FA.glyph_icon_findings_1203kd(_tree(3), total_out=out)
        self.assertEqual((len(shown), out), (3, [3]))

    def test_PAST_the_cap_the_total_is_the_real_count(self):
        """The r185 case: 28 glyphs, 12 shown."""
        out = []
        shown = FA.glyph_icon_findings_1203kd(_tree(28), total_out=out)
        self.assertEqual(len(shown), 12, "the cap stopped collecting, which is intended")
        self.assertEqual(out, [28], "the TRUE count has to reach the caller")

    def test_the_cap_is_still_respected(self):
        """Counting past the cap must not start returning everything -- the list is what goes
        into a task description, and #1034 caps it on purpose."""
        self.assertEqual(len(FA.glyph_icon_findings_1203kd(_tree(50))), 12)

    def test_an_explicit_limit_is_honoured_and_the_total_is_not(self):
        out = []
        shown = FA.glyph_icon_findings_1203kd(_tree(20), limit=3, total_out=out)
        self.assertEqual((len(shown), out), (3, [20]))

    def test_a_caller_that_passes_nothing_is_unchanged(self):
        """The out-parameter idiom's whole point: existing callers keep working."""
        self.assertEqual(len(FA.glyph_icon_findings_1203kd(_tree(28))), 12)

    def test_a_missing_directory_reports_zero_rather_than_nothing(self):
        """#883: a reader must be able to tell "no glyphs" from "never looked"."""
        out = []
        shown = FA.glyph_icon_findings_1203kd(Path(tempfile.mkdtemp()) / "nope", total_out=out)
        self.assertEqual((shown, out), ([], [0]))

    def test_a_project_with_a_real_icon_library_reports_zero(self):
        """The detector is gated on the PROJECT, not the occurrence, and the total must agree
        with that gate rather than counting glyphs the gate has excused."""
        out = []
        shown = FA.glyph_icon_findings_1203kd(
            _tree(28, extra="import { Heart } from 'lucide-react';"), total_out=out)
        self.assertEqual((shown, out), ([], [0]))


class TheTaskTextUsesIt(unittest.TestCase):

    def test_the_call_site_passes_total_out_and_titles_from_it(self):
        """#1032: one owner. If the title goes back to `len(findings)` the lane is misinformed
        again, and nothing else would notice."""
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import scaffolder as SC
        src = inspect.getsource(SC)
        self.assertIn("total_out=_tot1203pl", src)
        self.assertIn('% _n1203pl)[:180]', src)
        self.assertIn("total=_n1203pl", src)
        self.assertNotIn('% len(_gi1203kd))[:180]', src)


if __name__ == "__main__":
    unittest.main()
