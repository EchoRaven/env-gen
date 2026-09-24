"""Delivery stuck-abort GRACE (smoke-notes exp11). The deliver-stuck abort latches at
the deliver-check but is consumed at the run-loop top of the NEXT iteration — so an
in-flight remediation that lands in the gap (the verifier (re-)registers a verification
chain that only needs one run_validation to pass) is killed before it runs. The grace
defers the abort ONE cycle WHEN forward progress (source/contract/chain change) happened
since the latch — keyed on the stable progress signature, capped so a genuine wedge still
fails fast, and ONLY for deliver-stuck aborts (never the framework-validation / Site A path).
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.orchestrator import _abort_grace_should_defer, FWVAL_ABORT_GRACE_MAX  # noqa: E402

_S0 = ("srchash", (("ep", 3),), 5)          # a progress signature at latch
_S1 = ("srchash", (("ep", 3),), 6)          # chain version bumped → progress since latch


class AbortGraceTests(unittest.TestCase):
    def test_defers_when_progress_since_latch(self):
        # THE exp11 case: a chain was (re-)registered after the abort latched → defer once.
        self.assertTrue(_abort_grace_should_defer(True, 0, _S0, _S1))

    def test_aborts_when_no_progress(self):
        # genuine wedge: nothing changed since latch → fail fast (no defer).
        self.assertFalse(_abort_grace_should_defer(True, 0, _S0, _S0))

    def test_never_defers_a_non_deliver_stuck_abort(self):
        # Site A (framework-validation) abort → no deliver-stuck flag → must NOT defer here.
        self.assertFalse(_abort_grace_should_defer(False, 0, _S0, _S1))

    def test_respects_grace_cap(self):
        self.assertFalse(_abort_grace_should_defer(True, FWVAL_ABORT_GRACE_MAX, _S0, _S1))
        # one below the cap still defers
        if FWVAL_ABORT_GRACE_MAX >= 1:
            self.assertTrue(_abort_grace_should_defer(True, FWVAL_ABORT_GRACE_MAX - 1, _S0, _S1))

    def test_no_progress_signal_aborts(self):
        # a missing signature (computation failed) is treated as 'no progress' → abort.
        self.assertFalse(_abort_grace_should_defer(True, 0, None, _S1))
        self.assertFalse(_abort_grace_should_defer(True, 0, _S0, None))

    def test_cap_is_bounded(self):
        # the grace is finite — a persistently-progressing-but-never-delivering run can
        # only defer FWVAL_ABORT_GRACE_MAX times before fail-fast (time backstop also bounds).
        self.assertGreaterEqual(FWVAL_ABORT_GRACE_MAX, 0)
        self.assertFalse(_abort_grace_should_defer(True, FWVAL_ABORT_GRACE_MAX + 5, _S0, _S1))


if __name__ == "__main__":
    unittest.main()
