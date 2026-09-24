"""#353 (D-hard): the visual gate stops passing on an empty exam.

`passed = all(r["passed"] for r in _blocking)` and `all([]) is True`. r92:

    Visual fidelity PASSED (login_modal=0.08): all 0 screens >= 0.65

The denominator was "screens that happen to map to a route the app already
serves", and an unmapped screen is skipped rather than failed -- so NOT building
a page removed it from its own exam, and the fewer pages existed the easier the
gate passed.

The denominator is now the milestone's DECLARED scope: measured screens that
#352 marked `kind == page` AND whose route matches a REGISTERED ui_page. That is
the commitment the milestone actually made, which is the scoping the user asked
for -- a milestone should be judged on its own pages, not on pages a later
milestone owns. r93's registry declares three routes (/, /login, /signup), so
r93 would be judged on three screens and fail for judging none.

Two rules:
  * an owned screen that was never judged is a FAILURE, not a skip;
  * a non-empty owned set with zero blocking judgments cannot PASS.

Deliberate escape hatch: when NO ui_page is registered yet (pre-kickoff ticks),
the owned set is empty and the verdict is left exactly as it was. Blocking there
would wedge every run before it has declared anything.
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


def _decide(**kw):
    from multi_agent.runtime.visual_fidelity import visual_gate_verdict
    return visual_gate_verdict(**kw)


OWNED = ["fyp_feed", "login_modal", "signup"]


class TheEmptyExamNoLongerPasses(unittest.TestCase):

    def test_the_r92_case_now_fails(self):
        """One advisory screen judged, nothing blocking, three screens owned."""
        v = _decide(results=[{"name": "login_modal", "advisory": True, "passed": False}],
                    owned=OWNED)
        self.assertFalse(v["passed"])

    def test_zero_results_with_owned_screens_fails(self):
        self.assertFalse(_decide(results=[], owned=OWNED)["passed"])

    def test_unjudged_owned_screens_are_named_as_failures(self):
        v = _decide(results=[{"name": "fyp_feed", "advisory": False, "passed": True}],
                    owned=OWNED)
        self.assertEqual(sorted(v["unjudged"]), ["login_modal", "signup"])
        self.assertFalse(v["passed"])

    def test_remediation_says_author_the_page(self):
        v = _decide(results=[], owned=OWNED)
        self.assertIn("author", v["reason"].lower())


class AFullyJudgedMilestoneStillPasses(unittest.TestCase):

    def test_all_owned_judged_and_passing(self):
        results = [{"name": n, "advisory": False, "passed": True} for n in OWNED]
        v = _decide(results=results, owned=OWNED)
        self.assertTrue(v["passed"])
        self.assertEqual(v["unjudged"], [])

    def test_one_owned_screen_below_threshold_still_blocks(self):
        results = [{"name": n, "advisory": False, "passed": n != "signup"} for n in OWNED]
        self.assertFalse(_decide(results=results, owned=OWNED)["passed"])

    def test_a_screen_outside_the_owned_set_does_not_block(self):
        """A later milestone's page must not fail THIS milestone."""
        results = [{"name": n, "advisory": False, "passed": True} for n in OWNED]
        results.append({"name": "explore", "advisory": False, "passed": False})
        self.assertTrue(_decide(results=results, owned=OWNED)["passed"])


class AdvisoryScreensCannotCarryTheVerdict(unittest.TestCase):

    def test_only_advisory_judgments_do_not_satisfy_an_owned_set(self):
        results = [{"name": n, "advisory": True, "passed": True} for n in OWNED]
        self.assertFalse(_decide(results=results, owned=OWNED)["passed"])


class NothingDeclaredYetIsLeftAlone(unittest.TestCase):
    """Pre-kickoff ticks must not be wedged by a gate with nothing to judge."""

    def test_empty_owned_preserves_the_old_verdict_true(self):
        self.assertTrue(_decide(results=[], owned=[])["passed"])

    def test_empty_owned_still_fails_on_a_real_blocking_failure(self):
        v = _decide(results=[{"name": "x", "advisory": False, "passed": False}], owned=[])
        self.assertFalse(v["passed"])

    def test_owned_none_behaves_like_empty(self):
        self.assertTrue(_decide(results=[], owned=None)["passed"])


if __name__ == "__main__":
    unittest.main()
