"""Guard: FIX #186 — the framework-validation stuck ladder must not abort a run
whose lanes are ACTIVELY EDITING the app source (tiktok-r2: STUCK-ABORT fired
~20s before the backend lane landed its /auth/login fix — the ladder keyed only
on (failure_set, chain_sig) and was blind to source edits).

Mirror of the #71 chain-authoring grace: a changed app-source signature grants a
BOUNDED stuck-counter reset (churn-capped so an r3-style forever-thrash still
aborts — no livelock). The delivery-gate ladder already has this via
_deliver_progress_sig; this closes the same gap in the api_smoke ladder.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _fwval_is_source_edit_progress,
)
from multi_agent.orchestrator import FWVAL_SOURCE_CHURN_CAP  # noqa: E402


class SourceEditProgressTests(unittest.TestCase):
    def test_changed_signature_below_cap_is_progress(self):
        self.assertTrue(_fwval_is_source_edit_progress("sigA", "sigB", 0, 8))

    def test_unchanged_signature_is_not_progress(self):
        # Idempotent framework heals leave the sig unchanged — must NOT reset
        # the ladder (that would disable the abort entirely).
        self.assertFalse(_fwval_is_source_edit_progress("sigA", "sigA", 0, 8))

    def test_first_observation_prev_none_is_not_progress(self):
        self.assertFalse(_fwval_is_source_edit_progress("sigA", None, 0, 8))

    def test_compute_error_now_none_is_not_progress(self):
        # _compute_app_source_signature returns None on error → no grace
        # (can't confirm progress).
        self.assertFalse(_fwval_is_source_edit_progress(None, "sigB", 0, 8))
        self.assertFalse(_fwval_is_source_edit_progress(None, None, 0, 8))

    def test_churn_cap_bounds_the_grace(self):
        # r3-class forever-thrash: sig flips every cycle but the failure set
        # never clears — after cap grace resets the ladder must resume.
        self.assertTrue(_fwval_is_source_edit_progress("a", "b", 7, 8))
        self.assertFalse(_fwval_is_source_edit_progress("a", "b", 8, 8))
        self.assertFalse(_fwval_is_source_edit_progress("a", "b", 99, 8))

    def test_never_raises_on_weird_inputs(self):
        self.assertFalse(_fwval_is_source_edit_progress("a", "b", None, None))
        self.assertFalse(_fwval_is_source_edit_progress(object(), object(), "x", "y"))

    def test_cap_constant_sane(self):
        # min 2, mirroring FWVAL_CHAIN_CHURN_CAP's floor — a cap of 0/1 would
        # effectively disable the grace.
        self.assertGreaterEqual(FWVAL_SOURCE_CHURN_CAP, 2)


if __name__ == "__main__":
    unittest.main()
