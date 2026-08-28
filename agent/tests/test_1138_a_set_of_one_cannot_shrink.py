"""#1138: a failing set of size ONE cannot shrink, so #228's grace never fired for r7.

`convergence_grace` (#228) grants extra time when the failing set is small and RECENTLY SHRANK
— "visible convergence, not livelock". The orchestrator records a shrink only when the failing
CHECK SET is a strict subset of the previous tick's.

A run held by `validation_ui_evidence_failed` alone has a set of size one. It can never be a
strict subset of itself, so no shrink is ever recorded, so no grace is ever granted — however
much the evidence INSIDE that check converges.

netflix-local-r7: 98 of 99 gate evaluations were that check alone, and it was aborted at 83min
of lane time holding **24 passing UI records and ONE failing flow**
(`open_title_detail_and_play`). Across this session the failing count came down 7 (r3) → 2
(r4) → 1 (r5, r6, r7), and r5 DELIVERED from exactly this position once its last flow was
fixed.
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
from multi_agent.runtime.delivery_gate import convergence_grace  # noqa: E402


class _Log:
    def info(self, *a, **k): pass
    warning = error = debug = info


def _orch():
    o = object.__new__(orch_mod.Orchestrator)
    o._logger = _Log()
    return o


class DepthCountsAsProgress(unittest.TestCase):

    def test_fewer_failing_flows_is_a_shrink(self):
        o = _orch()
        self.assertFalse(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 7}))  # 1st
        self.assertTrue(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 2}))
        self.assertTrue(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 1}))

    def test_the_r7_endgame(self):
        """2 → 1 is the tick that should have bought r7 its grace."""
        o = _orch()
        o._ui_depth_shrank_1138({"ui_evidence_failed_records": 2})
        self.assertTrue(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 1}))

    def test_reaching_zero_counts_too(self):
        o = _orch()
        o._ui_depth_shrank_1138({"ui_evidence_failed_records": 1})
        self.assertTrue(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 0}))


class StandingStillIsNotProgress(unittest.TestCase):

    def test_an_unchanged_count_is_not_a_shrink(self):
        o = _orch()
        o._ui_depth_shrank_1138({"ui_evidence_failed_records": 3})
        self.assertFalse(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 3}))

    def test_a_growing_count_is_not_a_shrink(self):
        o = _orch()
        o._ui_depth_shrank_1138({"ui_evidence_failed_records": 1})
        self.assertFalse(o._ui_depth_shrank_1138({"ui_evidence_failed_records": 4}))

    def test_the_first_observation_is_never_a_shrink(self):
        self.assertFalse(_orch()._ui_depth_shrank_1138({"ui_evidence_failed_records": 1}))

    def test_junk_and_missing_fields_are_not_a_shrink(self):
        o = _orch()
        o._ui_depth_shrank_1138({"ui_evidence_failed_records": 5})
        for bad in ({}, None, {"ui_evidence_failed_records": "x"}, "nope"):
            self.assertFalse(o._ui_depth_shrank_1138(bad), bad)


class TheGraceKeepsItsOwnBounds(unittest.TestCase):
    """#1138 only supplies a shrink SIGNAL — every #228 bound still applies."""

    def test_a_stale_shrink_still_earns_nothing(self):
        self.assertEqual(
            convergence_grace(failed_count=1, last_shrink_age_s=1e9, grace_used=0), 0.0)

    def test_a_large_failing_set_still_earns_nothing(self):
        self.assertEqual(
            convergence_grace(failed_count=99, last_shrink_age_s=1.0, grace_used=0), 0.0)

    def test_the_extensions_are_still_capped(self):
        self.assertEqual(
            convergence_grace(failed_count=1, last_shrink_age_s=1.0, grace_used=99), 0.0)

    def test_a_fresh_small_shrink_does_earn_time(self):
        self.assertGreater(
            convergence_grace(failed_count=1, last_shrink_age_s=1.0, grace_used=0), 0.0)


class TheGateCarriesTheCount(unittest.TestCase):

    def test_the_count_is_exported(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
               / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn('"ui_evidence_failed_records"', src)

    def test_the_orchestrator_consults_it(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("_ui_depth_shrank_1138(gate)", src)


if __name__ == "__main__":
    unittest.main()
