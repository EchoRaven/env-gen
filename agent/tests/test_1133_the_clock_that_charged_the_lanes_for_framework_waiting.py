"""#1133: the no-convergence abort billed the lanes for time the FRAMEWORK spent deferring.

`_fwdeliver_first_decline_ts` is stamped at the first gate decline and never reset — by
design, so an oscillating run cannot keep resetting it. But the clock it starts is read as
LANE non-convergence ("the lanes are active but not converging on a clean gate"), and the
framework's own delivery deferrals run on that same clock.

netflix-local-r2: the delivery gate went FULLY GREEN five times (17:34:02, 18:21:04,
18:31:28, 18:40:06, 18:49:20) and the run was aborted at 18:53:18 for "has not gone green in
79min". Its one `deliver_project` call (18:32:49, right after a green gate) returned
"deferred by the hard final VISUAL fidelity gate: frontend is still inside the bounded
remediation window". That window ran 3964s — 66 minutes, 88% of the 4500s budget — and the
tick it released (18:46:25) the test-user squad deferred delivery once more. The abort fired
seven minutes later.

The credit is CAPPED at one full budget on purpose: a deferral that never ends must not turn
a 75-minute fail-fast into a 6-hour wall-clock grind, which is the reason this clock exists.
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


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(str(fmt) % a if a else str(fmt))

    error = info = debug = warning


def _orch(first_decline_ts=1000.0):
    """A bare Orchestrator carrying only what the credit helper reads."""
    o = object.__new__(orch_mod.Orchestrator)
    o._logger = _Log()
    o._fwdeliver_first_decline_ts = first_decline_ts
    return o


class TheFrameworksOwnWaitIsGivenBack(unittest.TestCase):

    def test_a_deferral_moves_the_deadline_by_its_own_length(self):
        o = _orch()
        o._credit_framework_deferral_1133(3964, "visual (escape)")
        self.assertEqual(o._fwdeliver_first_decline_ts, 1000.0 + 3964)
        self.assertEqual(o._fwdeliver_deferral_credit_1133, 3964)

    def test_the_r2_case_would_no_longer_abort(self):
        """r2's numbers: 79min elapsed, 66min of it the visual remediation window."""
        elapsed = 79 * 60
        o = _orch(first_decline_ts=0.0 + 1.0)
        o._credit_framework_deferral_1133(3964, "visual (escape)")
        lane_time = elapsed - (o._fwdeliver_first_decline_ts - 1.0)
        self.assertLess(lane_time, BUDGET,
                        "with the framework's own 66min credited back, the lane time left "
                        "is inside the budget and the run gets to finish")

    def test_credits_accumulate_across_several_deferrals(self):
        o = _orch()
        o._credit_framework_deferral_1133(600, "page-build")
        o._credit_framework_deferral_1133(900, "visual (fast-release)")
        self.assertEqual(o._fwdeliver_deferral_credit_1133, 1500)
        self.assertEqual(o._fwdeliver_first_decline_ts, 1000.0 + 1500)


class TheBackstopStaysArmed(unittest.TestCase):
    """A fix that lets a stuck deferral run to the 6h wall-clock would be worse than the bug."""

    def test_total_credit_never_exceeds_one_budget(self):
        o = _orch()
        for _ in range(10):
            o._credit_framework_deferral_1133(BUDGET, "visual (escape)")
        self.assertEqual(o._fwdeliver_deferral_credit_1133, BUDGET)
        self.assertEqual(o._fwdeliver_first_decline_ts, 1000.0 + BUDGET)

    def test_a_single_oversized_deferral_is_clamped(self):
        o = _orch()
        o._credit_framework_deferral_1133(BUDGET * 5, "visual (escape)")
        self.assertEqual(o._fwdeliver_deferral_credit_1133, BUDGET)

    def test_refusal_past_the_cap_is_logged(self):
        o = _orch()
        o._credit_framework_deferral_1133(BUDGET, "visual (escape)")
        o._credit_framework_deferral_1133(60, "page-build")
        self.assertTrue([l for l in o._logger.lines if "CAP reached" in l])

    def test_nothing_is_credited_before_the_clock_starts(self):
        """No first decline yet → there is no deadline to move."""
        o = _orch(first_decline_ts=0.0)
        o._credit_framework_deferral_1133(3964, "visual (escape)")
        self.assertEqual(o._fwdeliver_first_decline_ts, 0.0)

    def test_junk_and_zero_spans_are_ignored(self):
        o = _orch()
        for bad in (0, -5, None, "abc"):
            o._credit_framework_deferral_1133(bad, "visual (escape)")
        self.assertEqual(o._fwdeliver_first_decline_ts, 1000.0)


class ItIsActuallyWiredIn(unittest.TestCase):
    """A helper nobody calls credits nothing."""

    def test_every_deferral_release_site_credits(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("_credit_framework_deferral_1133"), 4,
                         "expected 1 definition + 3 release sites")
        for label in ("page-build", "visual (fast-release)", "visual (escape)"):
            self.assertIn(f'_credit_framework_deferral_1133(_now - ', src)
            self.assertIn(f'"{label}")', src)

    def test_the_abort_no_longer_claims_the_gate_never_went_green(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        self.assertNotIn('f"delivery gate has not gone green in "', src)
        self.assertIn('delivery never SUCCEEDED in', src)


if __name__ == "__main__":
    unittest.main()
