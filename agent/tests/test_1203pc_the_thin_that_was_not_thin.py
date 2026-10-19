"""#1203pc: "live but thin" stopped being true, and the corrected number already existed.

`unstaged_seed_media_1202xn` detects local media the seed points at that is not on disk, and
its docstring justified the decision not to block with "Time-sliced it is live but thin -- of
the last fourteen tiktok runs, r124 (2), r129 (3) and r135 (1) each ship some, the rest none."

Re-measured on today's ledgers (456 rows / 15 runs): distinct missing media per run runs 1 to
35, and the MODERN era carries r187 with 9 and r190 with 7. `#1203np`'s own docstring, in
`remediation_dispatcher`, had already measured the delivered side at 135 references across 21
runs including r187 9, r186 8 and r191 6 -- so the corrected figure existed in the repository
while this copy still said "the rest none". #1202vs: a correction replaces the number in EVERY
copy.

The same pass corrected the claim itself: #1203np added a dispatcher, so "REPORTS, NEVER
BLOCKS" understated what happens. And it added the datum that names the cause exactly -- of
the 161 distinct missing media in the corpus, 160 are `.mp4` and one is `.jpg`, which is the
stager's `jpe?g|png|webp|gif` regex with video outside it.
"""

import inspect
import re
import unittest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as FS


class TheCorrectedFigureIsHere(unittest.TestCase):

    def setUp(self):
        self.doc = inspect.getdoc(FS.unstaged_seed_media_1202xn) or ""

    def test_the_docstring_exists_and_is_substantial(self):
        self.assertGreater(len(self.doc), 600, "the docstring shrank; re-aim this test")

    def test_the_modern_runs_that_disprove_thin_are_named(self):
        for token in ("r187", "r190"):
            self.assertIn(token, self.doc,
                          "the run that disproves 'the rest none' must be named")

    def test_the_mp4_ratio_that_names_the_cause_is_stated(self):
        self.assertIn("160", self.doc)
        self.assertIn(".mp4", self.doc)

    def test_the_stale_claim_is_only_ever_quoted_by_its_correction(self):
        """#1203ox's split: the correction may quote the words it corrects; nothing else may
        assert them."""
        i = self.doc.find("live but thin")
        self.assertGreater(i, -1, "the correction must quote what it corrects")
        before = self.doc[max(0, i - 400):i]
        self.assertIn("1203pc", before,
                      "'live but thin' survives outside the paragraph that corrects it")

    def test_the_never_blocks_claim_now_names_the_dispatcher(self):
        """Anchored on the line that makes the CLAIM, not the first line saying "REPORTS".

        The first version searched for `REPORTS[^\n]*` and was satisfied by my own correction
        paragraph ("IT NO LONGER ONLY REPORTS. `#1203np` added ..."), so a mutation that
        reverted the claim itself survived. The claim is the line that also says NEVER BLOCKS.
        """
        lines = [l for l in self.doc.split("\n") if "NEVER BLOCKS" in l]
        self.assertEqual(len(lines), 1, "the reports/blocks claim moved; re-aim this test")
        self.assertIn("1203np", lines[0],
                      "the claim must say a task is filed, which #1203np added")

    def test_it_still_says_it_never_blocks(self):
        """The DECISION is unchanged -- only the figure and the completeness were wrong.
        Turning this into a gate is a behaviour change that needs a live run (#1202w6)."""
        self.assertIn("NEVER BLOCKS", self.doc)

    def test_the_reason_for_not_synthesising_a_placeholder_survives(self):
        self.assertIn("grey stand-in", self.doc)


class TheDetectorStillWorks(unittest.TestCase):
    """The docstring changed; the behaviour must not have."""

    def test_it_is_pure_and_takes_one_argument(self):
        sig = inspect.signature(FS.unstaged_seed_media_1202xn)
        self.assertEqual(list(sig.parameters), ["output_dir"])

    def test_a_missing_tree_answers_empty_rather_than_raising(self):
        self.assertEqual(FS.unstaged_seed_media_1202xn("/nonexistent/path/1203pc"), [])

    def test_a_fault_returns_empty_not_an_exception(self):
        class Boom:
            def __str__(self):
                raise RuntimeError("no")
        self.assertEqual(FS.unstaged_seed_media_1202xn(Boom()), [])


if __name__ == "__main__":
    unittest.main()
