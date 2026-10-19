"""#1203p9: #618's figure was quoted in seven places, and five of them went stale together.

Found by inventorying every `N of M runs` claim in the framework (128 of them) and ranking by
denominator: `24 of 39` appeared SEVEN times in `visual_fidelity.py`, two of them in strings a
reader is told (a `_LOG.warning` and the note persisted into verdict.json). Grepping for the
warning's wording found only those two -- the other five use different wording for the same
number, which is how a figure rots unevenly.

Re-measured over `design/visual_gate/rounds.jsonl` (395 ledgers, 1715 rows) on 2026-10-19:

  A  the record beats the live capture   24/39 (62%, max +0.44) -> 60/79 (76%, max +0.66)
  B  the run delivers worse than its own best  24/39 (62%) -> 41/74 (55%); 24/45 (53%) of the
     runs that cut a release, by a mean 0.129 and up to 0.491

They are two propositions that shared a numerator, so there are two constants, not one.
"""

import ast
import inspect
import os
import re
import unittest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF

_VF = os.path.join(os.path.dirname(inspect.getfile(VF)), "visual_fidelity.py")
_RUNS_RE = re.compile(r"\b(\d{1,4})\s*(?:of|/)\s*(\d{1,4})\s+runs?\b", re.I)


def _src():
    with open(_VF, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


class TheRefreshedFiguresExist(unittest.TestCase):

    def test_both_propositions_have_their_own_constant(self):
        self.assertIn("60 of 79 runs", VF._RECORD_BEATS_LIVE_1203P9)
        self.assertIn("41 of 74 runs", VF._BEST_ROUND_SHORTFALL_1203P9)

    def test_neither_constant_carries_the_others_claim(self):
        """Collapsing A and B into one constant would merge two different propositions."""
        self.assertNotIn("41 of 74", VF._RECORD_BEATS_LIVE_1203P9)
        self.assertNotIn("60 of 79", VF._BEST_ROUND_SHORTFALL_1203P9)

    def test_each_names_the_population_it_counts(self):
        self.assertIn("live capture", VF._RECORD_BEATS_LIVE_1203P9)
        self.assertIn("two or more scored rounds", VF._BEST_ROUND_SHORTFALL_1203P9)
        self.assertIn("cut a release", VF._BEST_ROUND_SHORTFALL_1203P9)

    def test_each_says_when_it_was_measured(self):
        for c in (VF._RECORD_BEATS_LIVE_1203P9, VF._BEST_ROUND_SHORTFALL_1203P9):
            self.assertIn("2026-10-19", c, "#1203oa: a figure without a date cannot be aged")

    def test_each_keeps_the_figure_it_replaced(self):
        """#1202vs replaces the number; the provenance is what lets the next reader audit it."""
        for c in (VF._RECORD_BEATS_LIVE_1203P9, VF._BEST_ROUND_SHORTFALL_1203P9):
            self.assertIn("was 24 of 39", c)


class NoStaleCopySurvives(unittest.TestCase):

    def test_the_old_figure_is_only_ever_quoted_as_provenance(self):
        """Every surviving `24 of 39` must be inside the correction, never asserted afresh.

        #1203ox's lesson: a test that simply forbade the old words was failed by the correction
        quoting them. So the rule is about the VOICE, not the words -- an occurrence is allowed
        when it is marked as superseded (`was ...`) or sits in the #1203p9 block.
        """
        src = _src()
        p9 = src.find("_RECORD_BEATS_LIVE_1203P9 = ")
        block_start = src.rfind("# #1203p9", 0, p9)
        block_end = src.find("\n\n", src.find("_BEST_ROUND_SHORTFALL_1203P9 = "))
        offenders = []
        for m in re.finditer(r"\b24\s*(?:of|/)\s*39\b", src):
            i = m.start()
            if block_start <= i <= block_end:
                continue
            if "was " in src[max(0, i - 24):i]:
                continue
            line = src[src.rfind("\n", 0, i) + 1:src.find("\n", i)]
            offenders.append(line.strip()[:70])
        self.assertEqual(offenders, [], "a stale copy still asserts the old figure")

    def test_the_file_has_no_other_618_figure_that_disagrees(self):
        src = _src()
        bad = []
        for line in src.split("\n"):
            if "#618" not in line:
                continue
            for m in _RUNS_RE.finditer(line):
                # the match text carries the word "runs"; compare the NUMBERS
                if "%sof%s" % (m.group(1), m.group(2)) in (
                        "60of79", "41of74", "24of45", "24of39"):
                    continue
                bad.append((m.group(0), line.strip()[:60]))
        self.assertEqual(bad, [], "a #618 claim carries a figure nobody re-measured")


class TheEmittedCopiesStillRender(unittest.TestCase):
    """The figure contains a literal `%`, which is why it is passed as an argument.

    Both of these failed on the first attempt -- the note gained a `%s` and kept three args --
    and only rendering it catches that, never reading it.
    """

    def test_the_persisted_note_renders_with_the_constant(self):
        note = ("an earlier capture of this run scored %.3f (+%.3f) at commit %s — the bounded "
                "escape ships the LAST round, not the best one (%s)"
                % (0.61, 0.0246, "abc123def456", VF._BEST_ROUND_SHORTFALL_1203P9))
        self.assertIn("41 of 74", note)
        self.assertIn("0.610", note)

    def test_concatenating_the_constant_into_a_format_string_would_raise(self):
        """Pins WHY it is an argument: this is the mistake the design avoids."""
        # TypeError when the stray `%` sequences are read as placeholders and run out of
        # arguments, ValueError when one of them is an invalid format character -- which of the
        # two you get depends on the text, and either is the bug this design avoids.
        with self.assertRaises((ValueError, TypeError)):
            _ = ("scored %.3f " + VF._BEST_ROUND_SHORTFALL_1203P9) % (0.61,)

    def test_the_warning_passes_it_as_an_argument_with_a_matching_arg_count(self):
        tree = ast.parse(_src())
        checked = 0
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "warning" and call.args):
                continue
            fmt = call.args[0]
            if not (isinstance(fmt, ast.Constant) and isinstance(fmt.value, str)
                    and "better state available" in fmt.value):
                continue
            checked += 1
            placeholders = len(re.findall(r"%[-0-9.]*[sdfr]", fmt.value))
            self.assertEqual(placeholders, len(call.args) - 1,
                             "the #641 warning's placeholders and arguments disagree")
            self.assertTrue(
                any(isinstance(a, ast.Name) and a.id == "_BEST_ROUND_SHORTFALL_1203P9"
                    for a in call.args),
                "the figure must ride as an argument, not be concatenated in")
        self.assertEqual(checked, 1, "the #641 warning moved; re-aim this test")


if __name__ == "__main__":
    unittest.main()


class TheTwoEditsToThisFileCompose(unittest.TestCase):
    """#1203p8 and #1203p9 both landed in `visual_fidelity.py` in one session, ~30 lines apart.

    Each one's own tests pass against its own edit; neither proves they did not disturb each
    other. The rule that caught this before: patches sharing a function or a data path need a
    composition test, because each being green does not make the pair right.
    """

    def setUp(self):
        self.src = _src()

    def test_both_corrections_survive_in_the_same_file(self):
        self.assertIn("1203p8", self.src)
        self.assertIn("1203p9", self.src)

    def test_p9_did_not_reintroduce_the_sentence_p8_corrected(self):
        """p9 rewrote five comments in this region; one of them sits inside p8's paragraph."""
        # #943: walk BACK over the comment block, not a fixed 400 bytes -- p9 rewrote five
        # comments in this very region, which is exactly what moves a byte offset.
        lines = self.src.split("\n")
        hit = next((n for n, l in enumerate(lines) if "persisted nowhere" in l), None)
        self.assertIsNotNone(
            hit, "p8's quoted claim vanished -- the correction lost its subject")
        lo = hit
        while lo > 0 and lines[lo - 1].strip().startswith("#"):
            lo -= 1
        self.assertIn("1203p8", "\n".join(lines[lo:hit + 1]),
                      "the claim is quoted outside the paragraph that corrects it")

    def test_p8_did_not_strand_p9s_constants(self):
        for name in ("_RECORD_BEATS_LIVE_1203P9", "_BEST_ROUND_SHORTFALL_1203P9"):
            self.assertGreaterEqual(self.src.count(name), 2,
                                    "%s is defined but nothing uses it" % name)

    def test_the_region_still_imports_and_the_module_loads(self):
        """A comment edit cannot break an import -- but p9 also changed two live expressions."""
        self.assertTrue(callable(VF._blocking_similarity_average))
        self.assertIsInstance(VF._BEST_ROUND_SHORTFALL_1203P9, str)

