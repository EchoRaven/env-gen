"""#351 (D-soft): make the visual gate report how much of the reference it judged.

`passed = all(r["passed"] for r in _blocking)` and `all([]) is True`, so the gate
returns PASS when it judged nothing. r92, verbatim:

    Visual fidelity PASSED (login_modal=0.08): all 0 screens >= 0.65
    [advisory (overlay, non-blocking): login_modal(0.08)]

The only capturable screen scored 0.08 and the gate said PASSED.

The mechanism is not statistical dilution, it is structural self-exemption: a
reference image only enters the judged set if it maps to a route the app ALREADY
SERVES, and one that does not is `skipped, not failed` (the framework's own
comment). So the denominator is "screens that happen to be built" -- not
building a page removes it from its own exam, and the fewer pages exist the
easier the gate passes. `design/visual_gate/` held 1 captured file (r93) and 3
(r91, r92) out of 11 references.

This is the REPORTING half, deliberately non-blocking: it computes
judged / measured coverage and names the unmapped screens so the shortfall is
visible in the run log and in the verdict. Turning it into a blocker comes after
the page-seeding fix, otherwise every run would simply start failing a gate it
cannot yet satisfy.

`owned` is optional and unused today: milestone->screen attribution currently
exists only as LLM prose in `description_slice` ("PAGES (this milestone):"),
which no prompt mandates, so parsing it would be guessing. Once design-prep
emits per-screen routes the caller can pass a structured owned set and the same
function scopes to it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _cov(**kw):
    from multi_agent.runtime.visual_fidelity import screen_coverage
    return screen_coverage(**kw)


MEASURED = ["fyp_feed", "explore", "login_modal", "profile"]


class ItCountsWhatWasActuallyJudged(unittest.TestCase):

    def test_the_r92_shape_is_reported_as_zero_blocking(self):
        """One advisory screen judged, nothing blocking -- the PASS-on-nothing case."""
        cov = _cov(results=[{"name": "login_modal", "advisory": True, "passed": False}],
                   measured=MEASURED)
        self.assertEqual(cov["blocking_judged"], 0)
        self.assertEqual(cov["measured"], 4)

    def test_unmapped_screens_are_named(self):
        cov = _cov(results=[{"name": "fyp_feed", "advisory": False, "passed": True}],
                   measured=MEASURED)
        self.assertEqual(sorted(cov["unjudged"]), ["explore", "login_modal", "profile"])

    def test_full_coverage_reports_no_gap(self):
        results = [{"name": n, "advisory": False, "passed": True} for n in MEASURED]
        cov = _cov(results=results, measured=MEASURED)
        self.assertEqual(cov["unjudged"], [])
        self.assertEqual(cov["blocking_judged"], 4)

    def test_coverage_ratio_is_reported(self):
        cov = _cov(results=[{"name": "fyp_feed", "advisory": False, "passed": True}],
                   measured=MEASURED)
        self.assertAlmostEqual(cov["coverage"], 0.25)

    def test_zero_measured_does_not_divide_by_zero(self):
        cov = _cov(results=[], measured=[])
        self.assertEqual(cov["coverage"], 0.0)
        self.assertEqual(cov["unjudged"], [])


class AdvisoryScreensCountAsJudgedButNotBlocking(unittest.TestCase):

    def test_advisory_is_judged_but_not_blocking(self):
        cov = _cov(results=[{"name": "login_modal", "advisory": True, "passed": True}],
                   measured=MEASURED)
        self.assertNotIn("login_modal", cov["unjudged"])
        self.assertEqual(cov["blocking_judged"], 0)


class OwnedScopingIsForwardCompatible(unittest.TestCase):
    """Once a structured owned set exists, the same function scopes to it."""

    def test_owned_narrows_the_denominator(self):
        cov = _cov(results=[{"name": "fyp_feed", "advisory": False, "passed": True}],
                   measured=MEASURED, owned=["fyp_feed", "login_modal"])
        self.assertEqual(cov["measured"], 2)
        self.assertEqual(cov["unjudged"], ["login_modal"])
        self.assertAlmostEqual(cov["coverage"], 0.5)

    def test_owned_none_means_the_whole_measured_set(self):
        cov = _cov(results=[], measured=MEASURED, owned=None)
        self.assertEqual(cov["measured"], 4)


class ItIsReportingOnly(unittest.TestCase):
    """D-soft: nothing here may change the pass/fail verdict yet."""

    def test_coverage_has_no_verdict_key(self):
        cov = _cov(results=[], measured=MEASURED)
        for forbidden in ("passed", "blocked", "failed"):
            self.assertNotIn(forbidden, cov)

    def test_the_verdict_moved_to_the_scoped_decision_in_353(self):
        """This assertion pinned the D-SOFT phase (report only, verdict
        untouched). #353 deliberately completed the soft->hard transition, so it
        now pins that the gate routes its verdict through the scoped decision
        rather than through `all(blocking)` -- which returned True on an empty
        exam. `screen_coverage` itself stays pure reporting (above)."""
        from multi_agent.runtime import visual_fidelity
        src = Path(visual_fidelity.__file__).read_text()
        self.assertIn("passed = _verdict[\"passed\"]", src)
        self.assertNotIn('passed = all(r["passed"] for r in _blocking)', src)


if __name__ == "__main__":
    unittest.main()
