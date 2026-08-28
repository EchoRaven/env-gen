"""#1133c: a deferral that never RELEASES was billed to the lanes in full.

#1133 credits a framework deferral at its release site. A deferral still in flight is blocking
delivery right now and is billed to the lanes the whole time — and the no-convergence abort can
fire BEFORE the visual gate's own escape does, so the credit never happens at all.

netflix-local-r6 is that run, on the DEFAULT 75-minute budget:

    04:42 → 05:09   five visual judgements, scores climbing
                    (browse_by_languages 0.56→0.58, games 0.42→0.62), never reaching 0.65
    (no "deferral RELEASED" line anywhere — #1133 credited 0)
    13 of 47 gate evaluations FULLY GREEN; deliver_project called twice
    05:31   ABORT: "delivery never SUCCEEDED in 75min of lane time"

Compare netflix-local-r5, where the same deferral escaped at 4830s, was credited, and the run
DELIVERED 1.0.0.
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

from multi_agent import orchestrator as orch_mod  # noqa: E402

BUDGET = orch_mod.FWVAL_NO_DELIVER_ABORT_S


class _Gate:
    def __init__(self, deferred_since=None, released=False):
        self.deferred_since = deferred_since
        self.released = released


def _orch(gate=None, already_credited=0.0):
    """`_vf_gate` is a lazily-created PROPERTY; inject through its backing slot."""
    o = object.__new__(orch_mod.Orchestrator)
    o.__dict__["_vf_gate_instance"] = gate if gate is not None else _Gate()
    o._fwdeliver_deferral_credit_1133 = already_credited
    return o


class TimeStillBeingWaitedOnIsNotLaneTime(unittest.TestCase):

    def test_an_unreleased_deferral_is_credited_live(self):
        o = _orch(_Gate(deferred_since=1000.0, released=False))
        self.assertEqual(o._live_deferral_credit_1133c(1000.0 + 900), 900)

    def test_the_r6_shape(self):
        """~50 minutes deferred and still going, against a 75-minute budget."""
        o = _orch(_Gate(deferred_since=0.0 + 1.0, released=False))
        live = o._live_deferral_credit_1133c(1.0 + 50 * 60)
        self.assertEqual(live, 50 * 60)
        self.assertLess((99 * 60) - live, BUDGET,
                        "with the in-flight wait removed, r6's window is inside the budget")


class ItDoesNotDoubleCount(unittest.TestCase):

    def test_a_released_deferral_credits_nothing_here(self):
        """#1133 already credited it at the release site."""
        o = _orch(_Gate(deferred_since=1000.0, released=True))
        self.assertEqual(o._live_deferral_credit_1133c(1000.0 + 900), 0.0)

    def test_a_gate_that_never_deferred_credits_nothing(self):
        o = _orch(_Gate(deferred_since=None))
        self.assertEqual(o._live_deferral_credit_1133c(9999.0), 0.0)


class TheBackstopStaysArmed(unittest.TestCase):
    """A never-ending deferral must not convert a 75-minute fail-fast into a wall-clock grind."""

    def test_live_credit_shares_the_one_budget_cap(self):
        o = _orch(_Gate(deferred_since=0.0 + 1.0, released=False))
        self.assertEqual(o._live_deferral_credit_1133c(1.0 + BUDGET * 5), BUDGET)

    def test_already_credited_time_reduces_the_room(self):
        o = _orch(_Gate(deferred_since=0.0 + 1.0, released=False), already_credited=BUDGET - 60)
        self.assertEqual(o._live_deferral_credit_1133c(1.0 + BUDGET), 60)

    def test_no_room_left_credits_nothing(self):
        o = _orch(_Gate(deferred_since=0.0 + 1.0, released=False), already_credited=BUDGET)
        self.assertEqual(o._live_deferral_credit_1133c(1.0 + 900), 0.0)


class ItNeverRaises(unittest.TestCase):

    def test_missing_or_junk_state_returns_zero(self):
        for gate in (_Gate(), _Gate("abc"), object()):
            self.assertEqual(_orch(gate)._live_deferral_credit_1133c(1000.0), 0.0)

    def test_a_clock_that_went_backwards_credits_nothing(self):
        o = _orch(_Gate(deferred_since=5000.0, released=False))
        self.assertEqual(o._live_deferral_credit_1133c(1000.0), 0.0)

    def test_only_the_visual_gate_is_consulted(self):
        """The other anchors are not cleared on release, so they cannot say 'still deferring'."""
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        i = src.index("def _live_deferral_credit_1133c")
        whole = src[i:src.index("\n    def ", i + 10)]
        # the other anchors ARE named in the docstring (that is where the reason lives);
        # what matters is that no CODE reads them.
        code = whole[whole.index('"""', whole.index('"""') + 3) + 3:]
        self.assertIn("_vf_gate", code)
        self.assertNotIn("_tu_squad_deferred_since", code)
        self.assertNotIn("_pages_gate_deferred_since", code)


if __name__ == "__main__":
    unittest.main()
