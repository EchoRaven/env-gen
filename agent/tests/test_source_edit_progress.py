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
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _fwval_is_source_edit_progress,
)
from multi_agent.orchestrator import FWVAL_SOURCE_CHURN_CAP  # noqa: E402
from multi_agent import orchestrator as O_1046  # noqa: E402
from multi_agent.runtime import validation_runner as VR_1046  # noqa: E402


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


# --- #1203pg: every term of the delivery progress signature, driven ------------------------------
#
# This file's own docstring says "the delivery-gate ladder already has this via
# `_deliver_progress_sig`", and that signature's newest term had no test at all. #1046 added a
# completed container REBUILD to it, because every other term is SOURCE-side: a route already
# written to main.py but only now built into the image moves none of them, and building it is the
# only event that can flip the "route 404s" evidence the gate is failing on. r177 aborted 17
# SECONDS after the rebuild that fixed its terminal blocker, grace denied because nothing
# source-side had changed.
#
# Found by asking which framework ticket markers no test names -- #1046 was one of 27 out of
# 1934. The one test that touches the signature stubs it as a THREE-tuple while production
# returns four, which is how the fourth term stayed unverified.

class DeliverProgressSignatureTerms(unittest.TestCase):
    """Each term must move the signature, and nothing else must."""

    def _stub(self, source="src-A", versions=None, chains=3):
        return types.SimpleNamespace(
            hubs=types.SimpleNamespace(registryhub=types.SimpleNamespace(
                get_versions=lambda: dict(versions or {"ep": 1}),
                _verification_chains=types.SimpleNamespace(get_version=lambda: chains))),
            _compute_app_source_signature=lambda: source)

    def _sig(self, stub, builds=0):
        old = VR_1046._BUILDS_OK_1046
        VR_1046._BUILDS_OK_1046 = builds
        try:
            return O_1046.Orchestrator._deliver_progress_sig(stub)
        finally:
            VR_1046._BUILDS_OK_1046 = old

    def test_an_unchanged_world_gives_an_unchanged_signature(self):
        """Non-vacuity: a signature that moved every call would pass every test below."""
        s = self._stub()
        self.assertEqual(self._sig(s), self._sig(s))

    def test_a_completed_rebuild_moves_it(self):
        """r177's case. Without this term the only event that can clear a 404 is invisible."""
        s = self._stub()
        self.assertNotEqual(self._sig(s, builds=0), self._sig(s, builds=1))

    def test_a_source_edit_moves_it(self):
        self.assertNotEqual(self._sig(self._stub(source="src-A")),
                            self._sig(self._stub(source="src-B")))

    def test_a_contract_registration_moves_it(self):
        self.assertNotEqual(self._sig(self._stub(versions={"ep": 1})),
                            self._sig(self._stub(versions={"ep": 2})))

    def test_a_chain_registration_moves_it(self):
        self.assertNotEqual(self._sig(self._stub(chains=3)), self._sig(self._stub(chains=4)))

    def test_the_rebuild_count_is_the_LAST_term_and_the_others_survive_without_it(self):
        """The except arm defaults the count to 0; it must not cost the other three terms,
        because then a hiccup reading the build count would look like a total loss of signal."""
        s = self._stub(source="src-A", versions={"ep": 7}, chains=9)
        sig = self._sig(s, builds=0)
        self.assertEqual(sig[0], "src-A")
        self.assertEqual(sig[1], (("ep", 7),))
        self.assertEqual(sig[2], 9)
        self.assertEqual(sig[3], 0)

    def test_a_broken_registryhub_still_yields_a_signature(self):
        """`None` means "no progress signal" to the caller, so losing the whole signature on a
        hub hiccup would deny the abort-grace outright -- the r177 outcome by another route."""
        broken = types.SimpleNamespace(
            hubs=types.SimpleNamespace(registryhub=None),
            _compute_app_source_signature=lambda: "src-A")
        self.assertIsNotNone(self._sig(broken, builds=2))
