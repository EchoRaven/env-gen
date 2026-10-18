r"""#1203no: the finding named a culprit it could not see, and the task repeated the guess.

`#1202zp` fires when a list response carries `total <= len(items)` AND offers a `next_cursor`,
and its sentence ended

    ... so more rows exist than `total` admits

The block that writes it already records the counter-example that makes that a guess. From
`#1202zp`'s own comment, probed live:

    r139  GET /api/videos/feed  total=5 items=5 next_cursor=5    -- the walk reaches 35
          distinct ids and `videos` holds 35.                    => `total` under-counts
    r132  GET /api/videos/feed  total=5 items=5 next_cursor=<ts> -- page 2 comes back EMPTY
          while `videos` holds 78. "BOTH numbers wrong."         => the CURSOR lied

MEASURED over the 698 rows this branch has written: 322 carry `cursor == total` (r139's offset
shape), **321 carry an opaque cursor** (r132's shape), 55 carry some other integer. So 54% of
its own population is not the shape the claim was checked on.

AND IT TRAVELS. `#1203ie` publishes the rows and `#1203ii` turns them into a backend P1 whose
description said "report a `total` that is smaller than what their own `next_cursor` implies"
and whose only instruction was a COUNT query for `total`. Over the 28 rows that dispatch
currently carries across 22 runs: 12 offset, 11 opaque, 3 from the page WALK reading
`total=295 reachable=100` -- the opposite direction outright, where a COUNT is what already
produced 295 -- and 2 unclassified. 12 of 28 matched the asserted direction, and the cursor,
which is the other half of the contract, was never mentioned.

ONE OF THE TWO CASES IS NOT A GUESS, and the first draft of this repair threw that away by
hedging both. When `total < len(items)` the caller is holding more rows than `total` admits,
so the response proves its own under-count with no cursor consulted; that case now gets its
own sentence and must NOT read as undecided.

NOT WIDENED (#647): `total < len(items)` is self-contradictory whether or not a cursor is
offered, and the enclosing guard still requires one. A new detection routes a P1, there is no
measured instance in the corpus, so it gets a run before it gets a guard.
"""
import ast
import inspect
import json
import unittest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD

_F = VR._list_total_unreachable_1202w0


def _body(total, n_items, cursor):
    return json.dumps({"items": list(range(n_items)), "total": total,
                       "next_cursor": cursor})


class _NoHttp(unittest.TestCase):
    """Every case here must cost zero requests -- that bargain is why #1202zp exists."""

    def setUp(self):
        self.calls = []
        self._real = VR._http

        def fake(method, url, **kw):
            self.calls.append(url)
            return {"status": 200, "error": None, "body_text": '{"items": []}',
                    "headers": {}}

        VR._http = fake

    def tearDown(self):
        VR._http = self._real


class TheUndecidedContradiction(_NoHttp):
    """`total == len(items)` -- real contradiction, undecidable without a request."""

    def test_it_names_both_possibilities(self):
        got = _F("http://x", "/api/videos/feed", None, _body(5, 5, 5))
        self.assertIn("cannot both be right", got)
        self.assertIn("under-counts", got)
        self.assertIn("page that does not exist", got)
        self.assertEqual(self.calls, [])

    def test_it_no_longer_asserts_which_one_lied(self):
        got = _F("http://x", "/api/videos/feed", None, _body(5, 5, 5))
        self.assertNotIn("so more rows exist than", got)
        self.assertNotIn("is not the collection size", got)

    def test_r132s_opaque_cursor_gets_the_same_undecided_sentence(self):
        """The shape that made the old wording false."""
        got = _F("http://x", "/api/videos/feed", None,
                 _body(5, 5, "2026-02-26T22:16:19+00:00|31"))
        self.assertIn("cannot both be right", got)
        self.assertIn("2026-02-26T22:16:19", got)

    def test_it_still_carries_the_path_and_both_numbers(self):
        got = _F("http://x", "/api/feed/foryou", None, _body(7, 7, "abc"))
        self.assertIn("/api/feed/foryou", got)
        self.assertIn("total=7", got)
        self.assertIn("next_cursor=abc", got)


class TheProvenUnderCount(_NoHttp):
    """`total < len(items)` -- the response proves it; hedging would be a loss."""

    def test_it_says_total_under_counts_without_hedging(self):
        got = _F("http://x", "/api/list", None, _body(2, 9, "9"))
        self.assertIn("under-counts", got)
        self.assertIn("already carries 9 item(s)", got)
        self.assertNotIn("cannot both be right", got)

    def test_it_says_the_proof_needs_no_cursor_walk(self):
        got = _F("http://x", "/api/list", None, _body(2, 9, "9"))
        self.assertIn("without following next_cursor", got)

    def test_the_proof_is_attributed_to_the_RESPONSE_not_the_cursor(self):
        """A real gap the mutation run found (NO3). Replacing "the response proves it" with
        "the cursor says so" left every other assertion green while the sentence now credits
        the very field this case does not need -- which is the whole point of the split."""
        got = _F("http://x", "/api/list", None, _body(2, 9, "9"))
        self.assertIn("the response proves it", got)
        self.assertNotIn("the cursor says so", got)

    def test_the_two_cases_produce_different_sentences(self):
        """Non-vacuity for the split: if both branches said the same thing, every assertion
        above would pass while the distinction was gone."""
        equal = _F("http://x", "/api/list", None, _body(5, 5, "c"))
        below = _F("http://x", "/api/list", None, _body(2, 9, "c"))
        self.assertTrue(equal and below)
        self.assertNotEqual(equal, below)


class TheCursorCutIsDeclared(_NoHttp):
    """#1034 -- the 40-char bound on the cursor was silent."""

    def test_a_long_cursor_says_it_was_cut(self):
        got = _F("http://x", "/api/list", None, _body(5, 5, "z" * 90))
        self.assertIn("cut at 40 of 90 chars", got)

    def test_a_short_cursor_claims_no_cut(self):
        got = _F("http://x", "/api/list", None, _body(5, 5, "short"))
        self.assertIn("next_cursor=short", got)
        self.assertNotIn("cut at 40", got)

    def test_the_cut_is_at_the_boundary_not_one_off(self):
        exact = _F("http://x", "/api/list", None, _body(5, 5, "y" * 40))
        over = _F("http://x", "/api/list", None, _body(5, 5, "y" * 41))
        self.assertNotIn("cut at 40", exact)
        self.assertIn("cut at 40 of 41 chars", over)


class ItStaysSilentWhereItAlwaysDid(_NoHttp):
    """The guard is untouched: no new detection ships with this wording repair."""

    def test_no_cursor_means_no_finding_even_for_a_proven_under_count(self):
        """The deliberate non-widening. total=2 with 9 items IS self-contradictory, and it
        stays unreported because a new detection routes a P1 and no corpus instance exists."""
        self.assertEqual(_F("http://x", "/api/list", None, _body(2, 9, None)), "")
        self.assertEqual(_F("http://x", "/api/list", None, _body(2, 9, "")), "")

    def test_a_full_page_with_no_next_page_stays_silent(self):
        self.assertEqual(_F("http://x", "/api/list", None, _body(5, 5, None)), "")

    def test_a_non_dict_or_missing_total_stays_silent(self):
        self.assertEqual(_F("http://x", "/api/list", None, "[]"), "")
        self.assertEqual(_F("http://x", "/api/list", None, '{"items": []}'), "")
        self.assertEqual(_F("http://x", "/api/list", None, "not json"), "")

    def test_a_boolean_total_is_not_an_integer(self):
        self.assertEqual(
            _F("http://x", "/api/list", None,
               json.dumps({"items": [1], "total": True, "next_cursor": 1})), "")

    def test_a_boolean_cursor_is_not_a_cursor(self):
        self.assertEqual(
            _F("http://x", "/api/list", None,
               json.dumps({"items": [1], "total": 1, "next_cursor": True})), "")


def _dispatch_description() -> str:
    """Every string constant inside `dispatch_list_totals_unreachable_1203ii`, joined.

    Read through the AST: the description is built by implicit concatenation around a `+
    _shown +` interpolation, so there is no single literal to read, and a source slice would
    pick up the #1203no comment that quotes the sentence it replaced.

    ★ THE DOCSTRING IS DROPPED, and the first version of this helper kept it. A mutation run
    found the cost: removing the sentence that explains the `total=N reachable=M` row shape
    left `assertIn("reachable=", ...)` green, because this function's own docstring quotes
    `total=295 reachable=100` while recording the measurement. The prose about a fix was
    standing in for the fix.
    """
    tree = ast.parse(inspect.getsource(RD))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                fn.name == "dispatch_list_totals_unreachable_1203ii":
            body = list(fn.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]                   # the docstring, not an emitted string
            out = []
            for stmt in body:
                out += [n.value for n in ast.walk(stmt)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            return " ".join(out)
    raise AssertionError("dispatch_list_totals_unreachable_1203ii not found")


class TheTaskNoLongerRepeatsTheGuess(unittest.TestCase):
    def test_the_docstring_is_not_part_of_what_the_lane_reads(self):
        """Non-vacuity for the helper. The docstring records the measurement and therefore
        quotes the very phrases the assertions below look for; if it leaked back in, every
        one of them could pass with the task text empty."""
        d = _dispatch_description()
        self.assertNotIn("MEASURED", d)
        self.assertNotIn("#1203no", d)
        self.assertNotIn("total=295 reachable=100", d)
        self.assertIn("query.count()", d, "the helper stopped reading the task text at all")

    def test_it_drops_the_one_direction_claim(self):
        self.assertNotIn("smaller than what their own", _dispatch_description())

    def test_it_says_the_two_fields_contradict_each_other(self):
        self.assertIn("CONTRADICT each other", _dispatch_description())

    def test_it_explains_both_row_shapes_the_lane_will_see(self):
        d = _dispatch_description()
        self.assertIn("cannot both be right", d)
        self.assertIn("reachable=", d)

    def test_it_asks_for_both_fixes(self):
        d = _dispatch_description()
        self.assertIn("FIX BOTH HALVES", d)
        self.assertIn("query.count()", d)            # the `total` half, unchanged
        self.assertIn("null/absent on the LAST page", d)   # the cursor half, new

    def test_the_priority_is_still_P1(self):
        """The verdict is untouched; only the justification and the instruction moved."""
        tree = ast.parse(inspect.getsource(RD))
        for fn in ast.walk(tree):
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name == "dispatch_list_totals_unreachable_1203ii"):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                for kw in call.keywords:
                    if kw.arg == "priority" and isinstance(kw.value, ast.Constant):
                        self.assertEqual(kw.value.value, "P1")
                        return
        raise AssertionError("no priority keyword found in the dispatch")

    def test_the_assignee_is_still_the_backend(self):
        self.assertIn("backend", _dispatch_description())


if __name__ == "__main__":
    unittest.main()
