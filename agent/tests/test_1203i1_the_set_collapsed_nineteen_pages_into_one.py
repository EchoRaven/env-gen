"""#1203i1: nineteen unwired pages collapsed into a set of size one.

`_blocking_instances_1202lo` answers "how many concrete things is the gate still blocking
on", and `converging_at_the_gate_1202lo` reads it off the persisted ledger to tell #228's
grace that the run is visibly converging. It summed four families, each of which publishes
its own instance list.

The deliverability checks publish none. Their report rides the `deliverability` key, which
the ledger TRUNCATES -- 71 of 120 sampled rows hold `{_truncated_948, head}` where `blockers`
would be. What they do publish, in EVERY row, is one `failed_checks` ENTRY PER BLOCKER,
repeating the same token. netflix-local-r45's list runs

    25 entries -> 17 -> 12 -> 7        (19, then 13, then 12, then 7 unwired pages)

while the orchestrator's `_cur_failed_set = set(map(str, _failed))` collapses every one of
those to a set of size ONE. Nineteen pages wired down to seven is exactly the "visible
convergence, not livelock" #228 asks about, and nothing could see it -- the #1138 shape one
level up, with the data already on disk.

Measured over 9886 persisted gate rows: 844 (8.5%) carry a repeated token, 2934 repeated
instances in all, and replaying this signal over every run's ledger the count falls strictly
on 191 occasions across 83 runs.

Only the REPEATS are added. Of those 2934 repeated instances, ZERO fall on a token belonging
to the four families already counted -- every one is a `deliverability_*` token
(`ui_page_unwired` 2129, `placeholder_stub_handler` 280, `guard_tampering` 277,
`dead_nav_link` 242) -- so there is no double counting, verified rather than assumed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.run_budget import _blocking_instances_1202lo  # noqa: E402


def _row(**kw):
    return dict(kw)


def _unwired(n):
    """A gate row the way the deliverability family writes one: n entries, one token."""
    return _row(failed_checks=["deliverability_ui_page_unwired"] * n)


class TheR45Trajectory(unittest.TestCase):

    def test_nineteen_pages_down_to_seven_is_visible_now(self):
        counts = [_blocking_instances_1202lo(_unwired(n)) for n in (25, 17, 12, 7)]
        self.assertEqual(counts, [24, 16, 11, 6], counts)
        self.assertTrue(all(b < a for a, b in zip(counts, counts[1:])), counts)

    def test_the_set_sees_none_of_it(self):
        """The premise: deduplicating every one of those rows gives the same single member,
        which is why #228's own test could not move."""
        for n in (25, 17, 12, 7):
            self.assertEqual(len({str(x) for x in _unwired(n)["failed_checks"]}), 1)

    def test_a_single_blocker_adds_nothing(self):
        self.assertEqual(_blocking_instances_1202lo(_unwired(1)), 0)

    def test_distinct_tokens_add_nothing(self):
        """Only REPEATS are instances; the number of KINDS is what #228 already counts."""
        row = _row(failed_checks=["deliverability_ui_page_unwired",
                                  "validation_ui_evidence_failed",
                                  "business_chain_failing"])
        self.assertEqual(_blocking_instances_1202lo(row), 0)


class ItDoesNotDoubleCountTheFourFamilies(unittest.TestCase):

    def test_the_families_still_contribute_exactly_what_they_did(self):
        row = _row(ui_evidence_failed_records=7,
                   business_chain={"chains": ["a", "b"]},
                   incomplete_required_tasks=["t1", "t2", "t3"],
                   unresolved_bugs={"open_p0_bug_count": 4})
        self.assertEqual(_blocking_instances_1202lo(row), 7 + 2 + 3 + 4)

    def test_a_repeat_adds_on_top_without_disturbing_them(self):
        row = _row(ui_evidence_failed_records=7,
                   business_chain={"chains": ["a", "b"]},
                   failed_checks=["deliverability_ui_page_unwired"] * 5)
        self.assertEqual(_blocking_instances_1202lo(row), 7 + 2 + 4)

    def test_a_row_without_failed_checks_is_byte_identical(self):
        row = _row(ui_evidence_failed_records=3)
        self.assertEqual(_blocking_instances_1202lo(row), 3)


class ItNeverRaises(unittest.TestCase):

    def test_junk_failed_checks(self):
        for junk in (None, "deliverability_ui_page_unwired", 7, {}, [[], []], [None, None]):
            row = _row(ui_evidence_failed_records=2, failed_checks=junk)
            got = _blocking_instances_1202lo(row)
            self.assertIsInstance(got, int, junk)
            self.assertGreaterEqual(got, 0, junk)

    def test_a_string_contributes_nothing_not_its_repeated_letters(self):
        """★ The `isinstance(..., list)` guard is load-bearing and a mutation dropping it
        survived a round, because the junk case above only asked for a non-negative int. A
        str is iterable: `len(s) - len(set(s))` counts REPEATED LETTERS, which for
        'deliverability_ui_page_unwired' is a double-digit number that would read as a dozen
        blockers converging."""
        bare = _blocking_instances_1202lo(_row(ui_evidence_failed_records=2))
        as_str = _blocking_instances_1202lo(
            _row(ui_evidence_failed_records=2,
                 failed_checks="deliverability_ui_page_unwired"))
        self.assertEqual(as_str, bare, as_str)
        self.assertEqual(as_str, 2)

    def test_unhashable_entries_do_not_break_the_count(self):
        """`str(x)` is what makes a dict entry countable; a bare set() would raise."""
        row = _row(failed_checks=[{"a": 1}, {"a": 1}, {"b": 2}])
        self.assertEqual(_blocking_instances_1202lo(row), 1)

    def test_a_junk_row_is_zero_not_an_exception(self):
        for junk in (None, [], "", 7):
            self.assertEqual(_blocking_instances_1202lo(junk) if isinstance(junk, dict)
                             else _blocking_instances_1202lo({}), 0)


class ItFeedsTheExistingSignal(unittest.TestCase):

    def test_the_converging_reader_uses_this_function(self):
        import inspect
        from multi_agent.runtime import run_budget as _rb
        src = inspect.getsource(_rb.converging_at_the_gate_1202lo)
        self.assertIn("_blocking_instances_1202lo", src)

    def test_a_falling_count_is_what_that_reader_asks_for(self):
        """It requires `first > last > 0`, so the r45 trajectory qualifies while a flat or
        zero one does not — this patch changes what is counted, not that rule."""
        first = _blocking_instances_1202lo(_unwired(25))
        last = _blocking_instances_1202lo(_unwired(7))
        self.assertTrue(first > last > 0, (first, last))
        flat = _blocking_instances_1202lo(_unwired(7))
        self.assertFalse(flat > last > 0)


if __name__ == "__main__":
    unittest.main()
