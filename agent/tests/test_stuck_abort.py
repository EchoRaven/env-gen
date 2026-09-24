"""Guard: the framework-validation stuck ladder fails fast on an unrecoverable bug
(PROPOSAL #5). The ladder escalates on a STABLE failure set with no lane progress:
  wait → redispatch@2 → terminal@4 (surface root) → abort@7 (fail fast).
The abort rung is what stops an unrecoverable framework-generation bug (run #16's
regenerated-every-cycle broken DDL) from limping to the wall-clock cap.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.orchestrator import (  # noqa: E402
    _fwval_stuck_decision, _fwval_failure_set,
    FWVAL_STUCK_REDISPATCH_AFTER, FWVAL_STUCK_TERMINAL_AFTER, FWVAL_STUCK_ABORT_AFTER,
)


class StuckLadderTests(unittest.TestCase):
    def test_rung_boundaries(self):
        self.assertEqual(_fwval_stuck_decision(0), "wait")
        self.assertEqual(_fwval_stuck_decision(1), "wait")
        self.assertEqual(_fwval_stuck_decision(2), "redispatch")   # FWVAL_STUCK_REDISPATCH_AFTER
        self.assertEqual(_fwval_stuck_decision(3), "redispatch")
        self.assertEqual(_fwval_stuck_decision(4), "terminal")     # FWVAL_STUCK_TERMINAL_AFTER
        self.assertEqual(_fwval_stuck_decision(5), "terminal")
        self.assertEqual(_fwval_stuck_decision(6), "terminal")
        self.assertEqual(_fwval_stuck_decision(7), "abort")        # FWVAL_STUCK_ABORT_AFTER
        self.assertEqual(_fwval_stuck_decision(99), "abort")

    def test_constants_are_strictly_increasing(self):
        # abort must come AFTER terminal AFTER redispatch, or the ladder is broken.
        self.assertLess(FWVAL_STUCK_REDISPATCH_AFTER, FWVAL_STUCK_TERMINAL_AFTER)
        self.assertLess(FWVAL_STUCK_TERMINAL_AFTER, FWVAL_STUCK_ABORT_AFTER)

    def test_reset_to_zero_means_wait_not_abort(self):
        # The impl-count-rise / failure-set-change reset sets stuck_count=0 → the
        # ladder must drop back to "wait" (real progress never triggers the abort).
        self.assertEqual(_fwval_stuck_decision(0), "wait")

    def test_custom_thresholds(self):
        self.assertEqual(_fwval_stuck_decision(3, abort_after=3), "abort")
        self.assertEqual(
            _fwval_stuck_decision(2, redispatch_after=1, terminal_after=2, abort_after=5),
            "terminal")


class FailureSetStableSignalTests(unittest.TestCase):
    """_fwval_failure_set is the STABLE signal the ladder keys on (failing-check
    NAMES), not the flapping file-content hash — so the abort actually fires."""

    def test_failing_check_names_only(self):
        data = {"checks": [
            {"name": "docker_up", "status": "fail", "detail": "postgres exit 3 ..."},
            {"name": "api_smoke", "status": "fail"},
            {"name": "build", "status": "pass"},
        ]}
        self.assertEqual(_fwval_failure_set(data), frozenset({"docker_up", "api_smoke"}))

    def test_detail_churn_does_not_change_the_set(self):
        # Same failing checks, different transient detail → SAME stable set (so the
        # stuck counter keeps climbing toward abort instead of resetting on noise).
        a = {"checks": [{"name": "docker_up", "status": "fail", "detail": "boot t=1"}]}
        b = {"checks": [{"name": "docker_up", "status": "fail", "detail": "boot t=2"}]}
        self.assertEqual(_fwval_failure_set(a), _fwval_failure_set(b))

    def test_empty_or_none(self):
        self.assertEqual(_fwval_failure_set(None), frozenset())
        self.assertEqual(_fwval_failure_set({"checks": []}), frozenset())


if __name__ == "__main__":
    unittest.main()
