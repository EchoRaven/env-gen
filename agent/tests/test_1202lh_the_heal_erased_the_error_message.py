"""#1202lh: the fabricated-fallback heal rewrote the error the user reads into a dash.

#175's heal rewrites `x || 'Literal'` to `(x ?? '—')` so a missing field renders honestly
instead of asserting invented data (gmrun9's `place.rating || '4.5'`). It runs at the
deliver-tail, over LANE-authored frontend files, without asking the lane.

tiktok-r119's framework delivery commit touched
`app/frontend/src/pages/NotificationsPage.jsx` -- nine prior commits, all lane -- and changed:

    - .catch((e) => setError(e.message || 'Couldn’t load notifications'))
    + .catch((e) => setError((e.message ?? '—')))
    - String(notification.type || 'Activity')
    + String((notification.type ?? '—'))

The message a user sees when notifications fail to load became "—".

The list already protected this SHAPE -- `unable to`, `cannot load`, `can't load`, and #1012's
`nothing here` / `unable to` additions, put there after measuring "228 literals the heal
actually considers, 6 rewritten, and three of those six were wrong". It had no entry for
`could not` / `couldn't`, and the curly apostrophe in `Couldn’t` does not match the straight
one either.

FINDING IT NEEDED GIT, because the heal ERASES ITS OWN EVIDENCE. Reading any delivered .jsx
shows `'—'`; only the pre-image side of the framework's own commit still holds what the lane
wrote. Classifying the shipped source of 450 lane literals suggested 2 error strings were at
risk; the diffs say otherwise.

A CORRECTION TO MY OWN FIRST READING, kept because it is the trap: those diffs also show
`'flex'`, `'center'`, `'#fff'`, `'transparent'`, `'block'` being rewritten, which looked like
the heal breaking CSS. It is not -- the CURRENT classifier already exempts every one of them.
Those lines are from runs built before that exemption existed. Old git history measures the
code of its time, not the code in front of you. What survives in the current classifier is
narrower: error copy, and a length carrying units.

WHAT IS VERIFIED: both spellings of "couldn't" and "could not", "went wrong", and CSS
dimensions are no longer classified as fabricated; every genuine fabrication in the corpus
(`4.5`, `1,234`, `password123`, `San Francisco, CA`, `HI Point Montara Lighthouse`) still is;
and the exemptions the heal already had still hold.

WHAT IS NOT: the UI-label case. `'TV Shows'`, `'Kids'`, `'Episode'`, `'Activity'` are still
classified as fabricated, and no rule here separates a section label from an invented title.
#1202gd's discipline applies -- stay strict where you cannot tell -- so that one is left named
and unfixed rather than guessed at.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    _is_fabricated_fallback_literal as is_fab)


class TheErrorTheUserReadsSurvives(unittest.TestCase):

    def test_r119s_exact_literal(self):
        """★ The case, with the curly apostrophe the lane actually typed."""
        self.assertFalse(is_fab("Couldn’t load notifications"))

    def test_both_apostrophes_and_the_spelled_out_form(self):
        for s in ("Couldn't load notifications", "Couldn’t load notifications",
                  "Could not load feed", "Could not load tenants"):
            self.assertFalse(is_fab(s), s)

    def test_something_went_wrong(self):
        self.assertFalse(is_fab("Something went wrong"))

    def test_the_shapes_that_were_already_protected_still_are(self):
        for s in ("Unable to load title.", "Cannot load feed", "Can't load comments",
                  "Nothing here yet.", "No results", "Try again"):
            self.assertFalse(is_fab(s), s)


class ACssLengthIsNotData(unittest.TestCase):

    def test_dimensions_with_units(self):
        for s in ("4px 0", "100%", "1.5rem", "0 auto", "12px", "2vh", "0.5s"):
            self.assertFalse(is_fab(s), s)

    def test_the_keyword_values_already_exempt_stay_exempt(self):
        for s in ("flex", "center", "block", "absolute", "transparent", "#fff", "none"):
            self.assertFalse(is_fab(s), s)


class GenuineFabricationIsStillCaught(unittest.TestCase):
    """★ The heal must not be blunted: these are the literals it exists for."""

    def test_the_corpus_fabrications(self):
        for s in ("4.5", "1,234", "San Francisco, CA", "password123",
                  "haibot2@illinois.edu", "THE CRASH", "Netflix Member",
                  "HI Point Montara Lighthouse"):
            self.assertTrue(is_fab(s), s)

    def test_a_bare_number_without_units_is_still_data(self):
        """`rating || '4.5'` is the founding case; only a UNIT makes it a length."""
        self.assertTrue(is_fab("4.5"))


class TheUnfixedCaseIsRecorded(unittest.TestCase):
    """Named, not guessed at (#1202gd): no rule separates a section label from a fake title."""

    def test_ui_labels_are_still_classified_fabricated(self):
        for s in ("TV Shows", "Kids", "Episode", "Activity"):
            self.assertTrue(is_fab(s),
                            "%r now passes — if that was deliberate, update this test and "
                            "say what rule distinguishes it from an invented title" % s)


if __name__ == "__main__":
    unittest.main()
