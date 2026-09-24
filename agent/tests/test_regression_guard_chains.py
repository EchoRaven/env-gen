"""Regression guard: once business_chain passes, a snapshot of the verification
chains is taken; if a later validation regresses business_chain WHILE the
contract (endpoint set) is unchanged, the last-passing chains are restored.

Observed live (smoke run #9): the app reached 1 check from delivery (business_chain
PASSING), then the verifier re-authored a chain into a broken state (register
tenant_id='tenant_1' but login omitted tenant_id -> backend looked up the user in
tenant 'default' -> 401) and the app churned back to broken. The guard reverts the
re-authoring deterministically so a validated-good state can't be silently lost.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.framework_validation import (  # noqa: E402
    snapshot_passing_chains, restore_regressed_chains)
from multi_agent.runtime.json_store import JsonStore  # noqa: E402


_GOOD = {"steps": [{"method": "POST", "path": "/auth/register",
                    "body": {"email": "u${rand}@x.com", "password": "pw", "tenant_id": "t1"}},
                   {"method": "POST", "path": "/auth/login",
                    "body": {"email": "u${rand}@x.com", "password": "pw", "tenant_id": "t1"}}]}
_BROKEN = {"steps": [{"method": "POST", "path": "/auth/register",
                      "body": {"email": "u${rand}@x.com", "password": "pw", "tenant_id": "t1"}},
                     {"method": "POST", "path": "/auth/login",
                      "body": {"email": "u${rand}@x.com", "password": "pw"}}]}  # tenant dropped


def _orch(tmp, endpoints):
    chains = JsonStore(Path(tmp) / "registryhub_verification_chains.json")
    rh = types.SimpleNamespace(
        _verification_chains=chains,
        get_endpoints=lambda: dict(endpoints))
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(registryhub=rh),
        _logger=types.SimpleNamespace(warning=lambda *a, **k: None,
                                      info=lambda *a, **k: None),
        _framework_validation_attempts=5), chains


class RegressionGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.eps = {"POST:/api/notes": {}, "GET:/api/notes": {}}

    def _snapshot_green(self, orch, chains):
        chains.set("flow", _GOOD)
        snapshot_passing_chains(orch)

    def test_snapshot_records_chains_and_high_water(self):
        orch, chains = _orch(self._tmp, self.eps)
        self._snapshot_green(orch, chains)
        self.assertEqual(orch._chains_snapshot["flow"], _GOOD)
        self.assertIn("business_chain", orch._fwval_green_high_water)
        self.assertEqual(orch._chains_snapshot_endpoints, set(self.eps))

    def test_restore_reverts_reauthored_chain_when_contract_unchanged(self):
        orch, chains = _orch(self._tmp, self.eps)
        self._snapshot_green(orch, chains)
        # an agent re-authors the chain into a broken state
        chains.set("flow", _BROKEN)
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        # store restored to the passing version, business_chain dropped from fset,
        # attempts reset so the next tick re-validates on the good chains
        self.assertEqual(chains.value()["flow"], _GOOD)
        self.assertNotIn("business_chain", fset)
        self.assertEqual(orch._framework_validation_attempts, 0)

    def test_restore_drops_a_new_broken_chain_full_replace(self):
        orch, chains = _orch(self._tmp, self.eps)
        self._snapshot_green(orch, chains)
        # a NEW broken chain is added (not a re-author of the snapshotted one)
        chains.set("flow2", _BROKEN)
        restore_regressed_chains(orch, frozenset({"business_chain"}))
        # full replace removes the new broken chain entirely
        self.assertNotIn("flow2", chains.value())
        self.assertEqual(set(chains.value()), {"flow"})

    def test_no_restore_when_contract_changed(self):
        # endpoints changed since the snapshot → legitimate contract evolution,
        # NOT a regression — leave the (re-authored) chains alone.
        orch, chains = _orch(self._tmp, self.eps)
        self._snapshot_green(orch, chains)
        orch.hubs.registryhub.get_endpoints = lambda: {"POST:/api/notes": {},
                                                       "GET:/api/notes": {},
                                                       "DELETE:/api/notes/{id}": {}}
        chains.set("flow", _BROKEN)
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(chains.value()["flow"], _BROKEN)  # NOT restored
        self.assertIn("business_chain", fset)

    def test_no_restore_when_never_passed(self):
        # business_chain never green (no high-water) → ongoing fixing, not a
        # regression — never revert.
        orch, chains = _orch(self._tmp, self.eps)
        chains.set("flow", _BROKEN)
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(chains.value()["flow"], _BROKEN)
        self.assertIn("business_chain", fset)

    def test_no_restore_when_app_broke_chains_unchanged(self):
        # business_chain red but the chains EQUAL the snapshot → the app itself
        # broke (a real defect), not a chain re-author. Do not mask it.
        orch, chains = _orch(self._tmp, self.eps)
        self._snapshot_green(orch, chains)  # chains == snapshot, still _GOOD
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertIn("business_chain", fset)  # left for normal feedback
        self.assertEqual(orch._framework_validation_attempts, 5)  # not reset


if __name__ == "__main__":
    unittest.main()
