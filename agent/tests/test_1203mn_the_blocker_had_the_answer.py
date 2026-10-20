r"""#1203mn: the top end-of-run blocker held the answer and printed "no summary recorded".

`#1203jg` (2026-10-14) existed because `validation_ui_evidence_failed` — the commonest
final blocker — said nothing: 13 of 13 runs, zero prose. It added per-page prose. On r189,
the first run to exercise it, that prose printed `no summary recorded` **123 times out of
123**, while `codehub_checks.json` held, for the very same page:

    "Fresh browser re-walk of /explore still reports failed /assets/real_videos/*.mp4
     requests (spencerx, gordonramsayofficial, willsmith)."

which names the root cause `#1203mm` went on to remove. The failure #1203jg was written to
end, reproduced inside #1203jg.

TWO independent breakages, both in the lookup, both measured by replaying r189's real
records through the function:

  1. VOCABULARY. `hub_registry.get_validation_results` runs every row through
     `_canon_validation_status`, which maps `failure -> "failed"`. The lookup compared
     against the raw word `"failure"`, so every record was skipped before the page match
     ran. FIX #193 added that canonicaliser precisely because "every reader compares
     status=='passed'" while writers pass their vocabulary verbatim — and this reader was
     the one that did not use it.
  2. SHAPE. The same normaliser LIFTS `evidence.summary` to `summary` and FLATTENS
     `evidence.metadata` to `metadata`, so a normalised record has no `evidence` key at all
     and `ev.get("summary")` was always "". The widest-first `_pick` already in this file
     reads both shapes with a comment explaining why; this applies that rule here.

Either breakage alone is enough to empty the prose, which is why the test below pins each
one separately: a fix for one would otherwise look green on the other's fixture.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ui_evidence_prose_1203jg,
)

PAGE = "explore_grid_page"
WORDS = ("Fresh browser re-walk of /explore still reports failed "
         "/assets/real_videos/*.mp4 requests (spencerx, gordonramsayofficial, willsmith).")
BREADTH = {"pages_failed": [PAGE], "failed_records": 4}


def _normalised():
    """Exactly what `hub_registry.get_validation_results` hands the gate: canonical status,
    summary lifted, metadata flattened, NO `evidence` key."""
    return [{
        "task_id": "ui_flow:%s" % PAGE,
        "name": "validation:ui_flow:%s" % PAGE,
        "status": "failed",
        "summary": WORDS,
        "metadata": {"check": "ui_flow", "flow": PAGE},
    }]


def _raw():
    """The un-normalised CodeHub shape, which some callers still pass."""
    return [{
        "name": "validation:ui_flow:%s" % PAGE,
        "status": "failure",
        "evidence": {"summary": WORDS, "metadata": {"page": PAGE}},
    }]


class TheWordsReachTheBlocker(unittest.TestCase):
    def test_the_normalised_shape_is_read(self):
        """The regression: this is the shape the gate actually receives, and it produced
        `no summary recorded` on every record of r189."""
        got = _ui_evidence_prose_1203jg(_normalised(), BREADTH)
        self.assertIn(WORDS, got)
        self.assertNotIn("no summary recorded", got)

    def test_the_raw_shape_still_works(self):
        got = _ui_evidence_prose_1203jg(_raw(), BREADTH)
        self.assertIn(WORDS, got)
        self.assertNotIn("no summary recorded", got)

    def test_the_canonical_status_alone_is_enough_to_break_it(self):
        """Breakage 1 in isolation: raw shape, canonical status."""
        rec = _raw()[0]
        rec["status"] = "failed"
        self.assertIn(WORDS, _ui_evidence_prose_1203jg([rec], BREADTH))

    def test_the_lifted_shape_alone_is_enough_to_break_it(self):
        """Breakage 2 in isolation: raw status word, lifted fields."""
        rec = _normalised()[0]
        rec["status"] = "failure"
        self.assertIn(WORDS, _ui_evidence_prose_1203jg([rec], BREADTH))

    def test_the_count_is_still_declared(self):
        got = _ui_evidence_prose_1203jg(_normalised(), BREADTH)
        # #1203pr: still declared, still first; the page count now follows it.
        self.assertTrue(got.startswith("4 failed UI record(s)"), got[:60])


class ItStillMatchesThePageEveryWayItIsSpelled(unittest.TestCase):
    def _one(self, **over):
        rec = {"status": "failed", "summary": WORDS}
        rec.update(over)
        return _ui_evidence_prose_1203jg([rec], BREADTH)

    def test_by_check_name(self):
        self.assertIn(WORDS, self._one(name="validation:ui_flow:%s" % PAGE))

    def test_by_task_id(self):
        self.assertIn(WORDS, self._one(task_id="ui_flow:%s" % PAGE))

    def test_by_flattened_metadata_page(self):
        self.assertIn(WORDS, self._one(metadata={"page": PAGE}))

    def test_by_flattened_metadata_flow(self):
        """#236 derives `metadata.flow` from the check name; the page IS the flow here."""
        self.assertIn(WORDS, self._one(metadata={"flow": PAGE}))

    def test_a_different_page_is_not_borrowed(self):
        got = self._one(name="validation:ui_flow:some_other_page")
        self.assertNotIn(WORDS, got)
        self.assertIn("no summary recorded", got)


class SilenceIsStillReportedHonestly(unittest.TestCase):
    def test_a_record_with_no_words_says_so(self):
        rec = {"status": "failed", "name": "validation:ui_flow:%s" % PAGE, "summary": "  "}
        self.assertIn("no summary recorded", _ui_evidence_prose_1203jg([rec], BREADTH))

    def test_a_passing_record_is_not_quoted(self):
        rec = {"status": "passed", "name": "validation:ui_flow:%s" % PAGE, "summary": WORDS}
        got = _ui_evidence_prose_1203jg([rec], BREADTH)
        self.assertNotIn(WORDS, got)
        self.assertIn("no summary recorded", got)

    def test_no_failed_pages_is_empty(self):
        self.assertEqual(
            _ui_evidence_prose_1203jg(_normalised(), {"pages_failed": []}), "")

    def test_it_never_raises(self):
        for bad in (None, [], [None], [{"status": "failed"}], "x", 7):
            _ui_evidence_prose_1203jg(bad, BREADTH)


if __name__ == "__main__":
    unittest.main()
