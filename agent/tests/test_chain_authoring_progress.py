"""Fix #71 — the stuck ladder gives a re-authoring verifier bounded convergence
room (outlook run-60, live 2026-07-03).

run-60 STUCK-ABORT on business_chain: the verifier authored a broken chain (a
/api/auth/me denial probe / wrong expect) then RE-AUTHORED it toward correct —
the unauth_access chain PASSES now — but the check-level failure set stayed
{"business_chain"} the whole window, so the 7-cycle stuck budget fired ONE cycle
before it went green. When business_chain is the only blocker AND the chains'
authored content signature changed (a re-authoring = real progress the failure
set can't see), the stuck counter resets — BOUNDED by FWVAL_CHAIN_CHURN_CAP so a
verifier that oscillates FOREVER still aborts (no livelock). LOCAL-ONLY
(agent/tests/ gitignored).
"""

import sys
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.framework_validation import (  # noqa: E402
    _fwval_chain_signature, _fwval_is_chain_authoring_progress)
from multi_agent.orchestrator import FWVAL_CHAIN_CHURN_CAP  # noqa: E402


def _orch(chains):
    rh = types.SimpleNamespace(
        _verification_chains=types.SimpleNamespace(value=lambda: chains))
    return types.SimpleNamespace(hubs=types.SimpleNamespace(registryhub=rh))


class SignatureTests(unittest.TestCase):
    def test_signature_excludes_execution_metadata(self):
        """Same authored steps, different last_result/last_run_at → SAME signature
        (a normal re-run must NOT read as re-authoring)."""
        a = {"c": {"name": "c", "steps": [{"m": "GET", "p": "/x"}],
                   "last_result": {"broken": ["e"]}, "last_run_at": 1, "status": "fail"}}
        b = {"c": {"name": "c", "steps": [{"m": "GET", "p": "/x"}],
                   "last_result": {"broken": []}, "last_run_at": 2, "status": "pass"}}
        self.assertEqual(_fwval_chain_signature(_orch(a)),
                         _fwval_chain_signature(_orch(b)))

    def test_signature_changes_on_reauthor(self):
        a = {"c": {"name": "c", "steps": [{"m": "GET", "p": "/x"}]}}
        b = {"c": {"name": "c", "steps": [{"m": "GET", "p": "/y"}]}}  # re-authored
        self.assertNotEqual(_fwval_chain_signature(_orch(a)),
                            _fwval_chain_signature(_orch(b)))

    def test_signature_ignores_underscore_chains(self):
        a = {"c": {"steps": [1]}, "_meta": {"x": 1}}
        b = {"c": {"steps": [1]}, "_meta": {"x": 999}}  # only _meta differs
        self.assertEqual(_fwval_chain_signature(_orch(a)),
                         _fwval_chain_signature(_orch(b)))

    def test_signature_none_on_error(self):
        self.assertIsNone(_fwval_chain_signature(types.SimpleNamespace(hubs=None)))


class ProgressDecisionTests(unittest.TestCase):
    CAP = FWVAL_CHAIN_CHURN_CAP

    def test_reauthoring_business_chain_is_progress(self):
        assert _fwval_is_chain_authoring_progress(
            {"business_chain"}, "sigB", "sigA", 0, self.CAP) is True

    def test_unchanged_chain_is_not_progress(self):
        """Verifier idle (sig unchanged) → NOT progress → the stuck counter advances
        to abort as before (the genuinely-stuck case is unchanged)."""
        assert _fwval_is_chain_authoring_progress(
            {"business_chain"}, "sigA", "sigA", 0, self.CAP) is False

    def test_other_blocker_present_is_not_progress(self):
        """If a NON-chain check also fails (docker_up, etc.), chain re-authoring is
        not the whole story → do not grant the bypass."""
        assert _fwval_is_chain_authoring_progress(
            {"business_chain", "docker_up"}, "sigB", "sigA", 0, self.CAP) is False

    def test_churn_cap_stops_forever_oscillation(self):
        """At the churn cap, re-authoring is NO LONGER progress → the run aborts
        (a verifier that oscillates forever cannot livelock)."""
        assert _fwval_is_chain_authoring_progress(
            {"business_chain"}, "sigB", "sigA", self.CAP, self.CAP) is False

    def test_none_signatures_are_not_progress(self):
        assert _fwval_is_chain_authoring_progress(
            {"business_chain"}, None, "sigA", 0, self.CAP) is False
        assert _fwval_is_chain_authoring_progress(
            {"business_chain"}, "sigB", None, 0, self.CAP) is False

    def test_bounded_total_cycles(self):
        """Simulate: each cycle the verifier re-authors (sig changes) but the chain
        stays broken. The counter resets each cycle UNTIL the churn cap, then the
        stuck counter advances to abort. Proves BOUNDED (no infinite livelock)."""
        churn, stuck, cycles = 0, 0, 0
        prev_sig = "sig0"
        for i in range(1, 200):   # a forever-oscillating verifier
            cycles += 1
            sig = f"sig{i}"       # re-authored every cycle
            if _fwval_is_chain_authoring_progress(
                    {"business_chain"}, sig, prev_sig, churn, self.CAP):
                churn += 1
                stuck = 0
            else:
                stuck += 1
            prev_sig = sig
            if stuck >= 7:        # FWVAL_STUCK_ABORT_AFTER
                break
        # bounded: churn cap (8) resets + then 7 stuck cycles → ~15, never infinite
        self.assertLessEqual(cycles, self.CAP + 8)
        self.assertGreaterEqual(stuck, 7)   # it DID reach abort


if __name__ == "__main__":
    unittest.main()
