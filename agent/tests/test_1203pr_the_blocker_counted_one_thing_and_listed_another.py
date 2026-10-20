r"""#1203pr: the blocker a lane reads mixed two collections and cut one of them silently.

`_ui_evidence_prose_1203jg` returned

    "%d failed UI record(s); <page>: <why> | <page>: <why> ..."

where the count is `failed_records` and the list is built from `pages_failed`. Those are
different collections, and the page list is cut at 8 with nothing saying so.

The same file already knows this. The `#1017` log line ~330 lines above carries the rule in
its own comment -- "the count is `failed_records` but the list is built from `pages_failed`
-- two different collections, so 'N record(s): <list>' could never be read as 'these are the
N'. Print both, and declare the cut." That landed on the LOG, not on this, and this is the
half with a reader who acts: `blocker_prose` is the only path the text has to a lane (#983).

MEASURED over the 4439 breadth records carrying a failure (`pages_failed` has a SOLE writer,
so the rate is readable -- the trap #1203pa hit):

    count != number of pages      325 of 4439   7.3%   (netflix-r30: "4 record(s)", 2 pages)
    page list at or past the cut  200 of 8580 lists, up to 20 pages

Both are zero in the modern era, which is the argument FOR the fix rather than against it:
all 525 occurrences are netflix, googlemaps and instagram, while the modern era is 22 of 25
runs on one tiktok app whose screen count never reaches the cap.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ui_evidence_prose_1203jg as _prose)


def _rec(page, summary):
    return {"status": "failed", "metadata": {"page": page}, "summary": summary}


class ItStatesBothQuantities(unittest.TestCase):

    def test_netflix_r30s_shape_says_both_numbers(self):
        """★ THE TICKET: four records spread over two pages. The old sentence offered only
        the 4 and then listed two names, which cannot be read as "these are the 4"."""
        out = _prose([_rec("alpha", "boom"), _rec("beta", "bang")],
                     {"failed_records": 4, "pages_failed": ["alpha", "beta"]})
        self.assertTrue(out.startswith("4 failed UI record(s)"), out)
        self.assertIn("on 2 page(s)", out)

    def test_the_record_count_is_not_the_page_count(self):
        """A fix that printed `len(pages)` twice would satisfy a weaker assertion. The two
        numbers must come from the two different collections."""
        out = _prose([_rec("alpha", "boom")],
                     {"failed_records": 9, "pages_failed": ["alpha"]})
        self.assertIn("9 failed UI record(s)", out)
        self.assertIn("on 1 page(s)", out)

    def test_the_page_count_is_the_WHOLE_list_not_the_listed_part(self):
        """With more pages than the cut, the count must still be the real total -- otherwise
        the sentence is self-consistent and still wrong."""
        pages = ["p%02d" % i for i in range(12)]
        out = _prose([], {"failed_records": 30, "pages_failed": pages})
        self.assertIn("on 12 page(s)", out)


class ItDeclaresTheCut(unittest.TestCase):

    def test_a_cut_list_says_how_many_it_dropped(self):
        pages = ["p%02d" % i for i in range(12)]
        out = _prose([], {"failed_records": 12, "pages_failed": pages})
        self.assertIn("(+4 more not shown)", out)

    def test_the_listed_pages_are_still_capped(self):
        """The cut itself is deliberate -- a blocker is one line of prose. Declaring it must
        not turn into printing all 20."""
        pages = ["p%02d" % i for i in range(20)]
        out = _prose([], {"failed_records": 20, "pages_failed": pages})
        self.assertEqual(out.count("no summary recorded"), 8, out[:160])
        self.assertIn("(+12 more not shown)", out)

    def test_an_uncut_list_claims_no_cut(self):
        """#983: a clause that fires while naming nothing. "+0 more not shown" on every
        short list would be noise and would read as a cut that happened."""
        out = _prose([], {"failed_records": 3, "pages_failed": ["alpha", "beta"]})
        self.assertNotIn("not shown", out)

    def test_exactly_at_the_cut_claims_no_cut(self):
        pages = ["p%02d" % i for i in range(8)]
        out = _prose([], {"failed_records": 8, "pages_failed": pages})
        self.assertNotIn("not shown", out)
        self.assertIn("on 8 page(s)", out)

    def test_the_cut_is_declared_in_the_shared_wording(self):
        """#1032: `join_capped` owns this format. A local re-spelling would drift from the
        other 87 call sites and from the ratchets written against it."""
        from env_generator.llm_generator.multi_agent.runtime.message_format import join_capped
        expected = join_capped(["a", "b"], total=5, cap=2, sep=" | ")
        self.assertIn("(+3 more not shown)", expected)

    def test_one_past_the_cut_declares_exactly_one(self):
        pages = ["p%02d" % i for i in range(9)]
        out = _prose([], {"failed_records": 9, "pages_failed": pages})
        self.assertIn("(+1 more not shown)", out)


class TheOldPropertiesSurvive(unittest.TestCase):

    def test_nothing_to_say_is_still_nothing(self):
        self.assertEqual(_prose([], {"failed_records": 0, "pages_failed": []}), "")
        self.assertEqual(_prose([], {}), "")

    def test_the_reason_still_reaches_the_prose(self):
        out = _prose([_rec("alpha", "/api/auth/me returned 401")],
                     {"failed_records": 1, "pages_failed": ["alpha"]})
        self.assertIn("/api/auth/me returned 401", out)

    def test_a_page_with_no_record_still_contributes_its_name(self):
        out = _prose([], {"failed_records": 1, "pages_failed": ["lonely"]})
        self.assertIn("lonely", out)

    def test_junk_does_not_raise(self):
        for bad in (None, 0, "x", {"pages_failed": "notalist"}):
            _prose(None, bad)


if __name__ == "__main__":
    unittest.main()
