"""#1140: an early escape shipped an app where not one screen reached the bar.

`_visual_release_decision`'s escapes answer "have we waited long enough". #750 drew the line
this extends — *"an escape answers 'have we waited long enough', and no amount of waiting
makes a blank page a delivery"*. Waiting-is-futile and good-enough-to-ship are different
questions, and every escape except the wall-clock was answering the first while deciding the
second.

netflix-local-r8: 9 consecutive no-improvement judgements tripped #519's HARD plateau, which
by design has NO time floor, and it released at 1395s with blocking_average 0.4412 and ZERO
of 11 screens at the 0.65 bar. It then delivered release 1.0.0.

Measured over the nine runs carrying a visual verdict, "not one screen reached the bar"
separates the bottom three exactly — r8 (0/11), r9 (0/11), r1 (0/10) — from every run that
escaped legitimately: r3 (8/12, soft plateau), r5 (5/11, wall-clock), r2 (3/11, wall-clock).
No threshold to calibrate, which is why the floor is this and not a number. r6 (11/12,
passed=True) proves the bar is reachable.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.orchestrator import (  # noqa: E402
    _visual_release_decision, _any_blocking_screen_at_bar_1140,
    VISUAL_PLATEAU_HARD_ROUNDS, VISUAL_PLATEAU_ROUNDS, VISUAL_PLATEAU_MIN_S,
    VISUAL_DEFERRAL_ESCAPE_S,
)

T0 = 1_000_000.0


def _decide(**kw):
    base = dict(deferred_since=T0, attempts=1, total_judgments=5, now=T0 + 100.0)
    base.update(kw)
    now = base.pop("now")
    return _visual_release_decision(
        base.pop("deferred_since"), base.pop("attempts"), base.pop("total_judgments"),
        now, **base)


class TheR8Shape(unittest.TestCase):
    """9 plateau rounds, 1395s deferred, zero screens at the bar."""

    def test_the_hard_plateau_no_longer_ships_it(self):
        self.assertEqual(
            _decide(now=T0 + 1395.0, plateau_rounds=9, any_screen_at_bar=False), "defer")

    def test_the_same_state_ships_once_one_screen_reaches_the_bar(self):
        self.assertEqual(
            _decide(now=T0 + 1395.0, plateau_rounds=9, any_screen_at_bar=True), "release")

    def test_it_still_ships_when_the_wall_clock_runs_out(self):
        """The floor delays an early exit; it never creates a deadlock."""
        self.assertEqual(
            _decide(now=T0 + VISUAL_DEFERRAL_ESCAPE_S + 1, plateau_rounds=9,
                    any_screen_at_bar=False), "release")


class TheEscapesThatWereLegitimate(unittest.TestCase):

    def test_r5_and_r2_wall_clock_are_untouched(self):
        for deferred in (4830.0, 3964.0):
            self.assertEqual(
                _decide(now=T0 + deferred, any_screen_at_bar=False), "release",
                f"wall-clock at {deferred}s must remain unconditional")

    def test_r3_soft_plateau_with_screens_at_the_bar_still_releases(self):
        self.assertEqual(
            _decide(now=T0 + 1941.0, plateau_rounds=VISUAL_PLATEAU_ROUNDS,
                    any_screen_at_bar=True), "release")

    def test_the_other_early_escapes_are_floored_too(self):
        """attempt cap, judgment cap and idle answer the same 'waiting won't help'."""
        self.assertEqual(_decide(attempts=99, any_screen_at_bar=False), "defer")
        self.assertEqual(_decide(total_judgments=999, any_screen_at_bar=False), "defer")
        self.assertEqual(
            _decide(now=T0 + VISUAL_PLATEAU_MIN_S + 10, last_judgment_at=T0,
                    any_screen_at_bar=False), "defer")


class ThePrecedenceIsUnchanged(unittest.TestCase):

    def test_app_dead_still_dominates(self):
        self.assertEqual(
            _decide(now=T0 + 9999.0, app_dead=True, any_screen_at_bar=True), "defer")

    def test_fast_release_is_unaffected(self):
        self.assertEqual(
            _decide(blocking_average=0.80, avg_min=0.65, avg_stable_rounds=2,
                    coverage_ok=True, any_screen_at_bar=False), "fast_release")

    def test_the_default_keeps_every_caller_byte_identical(self):
        """No caller that omits the flag may change behaviour (#558's discipline)."""
        self.assertEqual(_decide(plateau_rounds=VISUAL_PLATEAU_HARD_ROUNDS), "release")
        self.assertEqual(_decide(attempts=99), "release")


class UnknownIsNeverAFloor(unittest.TestCase):
    """It may only tighten a state it can actually see."""

    def test_no_judgement_yet_reads_as_permissive(self):
        self.assertTrue(_any_blocking_screen_at_bar_1140({}))
        self.assertTrue(_any_blocking_screen_at_bar_1140({"screens": []}))
        self.assertTrue(_any_blocking_screen_at_bar_1140(None))

    def test_an_advisory_only_exam_is_permissive(self):
        self.assertTrue(_any_blocking_screen_at_bar_1140(
            {"screens": [{"name": "hover", "advisory": True, "passed": False}]}))

    def test_malformed_records_are_permissive(self):
        self.assertTrue(_any_blocking_screen_at_bar_1140({"screens": "nope"}))
        self.assertTrue(_any_blocking_screen_at_bar_1140({"screens": [None, 7]}))

    def test_it_sees_the_r8_and_r5_shapes(self):
        r8 = {"screens": [{"name": f"s{i}", "passed": False} for i in range(11)]}
        self.assertFalse(_any_blocking_screen_at_bar_1140(r8))
        r5 = {"screens": [{"name": "player", "passed": True}]
                         + [{"name": f"s{i}", "passed": False} for i in range(10)]}
        self.assertTrue(_any_blocking_screen_at_bar_1140(r5))

    def test_an_advisory_pass_does_not_count(self):
        """One passing OVERLAY screen must not certify the blocking exam."""
        self.assertFalse(_any_blocking_screen_at_bar_1140(
            {"screens": [{"name": "hover", "advisory": True, "passed": True},
                         {"name": "browse", "passed": False}]}))


if __name__ == "__main__":
    unittest.main()
