"""#327 — the regression-guard LIVELOCK (verifier + cross-run trajectory reviewers, both #1).

The guard restores the last-passing chain snapshot on a business_chain regression. But a
snapshot that went green ONCE via a transient/non-deterministic recovery (r92: the "Owner"
literal that only 404s once a real username is needed) is NOT idempotent: the restored chains
fail again → business_chain re-enters the failure set → the verifier is re-dispatched →
re-authors → the guard restores … forever. r92 did this 38× (68% of the run) before
NO-CONVERGENCE ABORT, and freeze-on-green never fired (frozen:true=0), so nothing broke the
loop at the source.

Fix: count restores of the SAME snapshot; once it has been restored more than the budget
WITHOUT sticking, POISON it — stop restoring, drop the snapshot, clear the green-high-water +
the freeze, and route the failing step back to the verifier (keep business_chain in fset) so
it actually gets fixed instead of looping.
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

_GOOD = {"steps": [{"method": "GET", "path": "/api/users/${uname}/favorites"}]}
_BROKEN = {"steps": [{"method": "GET", "path": "/api/users/Owner/favorites"}]}   # 404 forever


def _orch(tmp, endpoints):
    chains = JsonStore(Path(tmp) / "registryhub_verification_chains.json")
    rh = types.SimpleNamespace(
        _verification_chains=chains,
        get_endpoints=lambda: dict(endpoints))
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(registryhub=rh),
        _logger=types.SimpleNamespace(warning=lambda *a, **k: None,
                                      info=lambda *a, **k: None),
        _framework_validation_attempts=5), chains, rh


class PoisonedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.eps = {"GET:/api/users/{username}/favorites": {}}

    def _green(self, orch, chains):
        chains.set("fav", _GOOD)
        snapshot_passing_chains(orch)

    def _regress(self, orch, chains):
        """simulate the verifier re-authoring the chain into the broken shape, then validate."""
        chains.set("fav", _BROKEN)
        return restore_regressed_chains(orch, frozenset({"business_chain"}))

    def test_default_budget_is_two(self):
        # ENVGEN_MAX_CHAIN_RESTORES default = 2 → poison on the 3rd non-sticking restore
        from multi_agent.runtime.framework_validation import _max_chain_restores
        self.assertEqual(_max_chain_restores(), 2)

    def test_poisons_after_budget_and_routes_to_verifier(self):
        orch, chains, rh = _orch(self._tmp, self.eps)
        self._green(orch, chains)
        self.assertEqual(set(rh._chains_frozen_eps), set(self.eps))   # frozen on green

        # restores 1 and 2 revert + drop business_chain (the old, correct behaviour)
        f1 = self._regress(orch, chains)
        self.assertNotIn("business_chain", f1)
        self.assertEqual(chains.value()["fav"], _GOOD)   # restored
        f2 = self._regress(orch, chains)
        self.assertNotIn("business_chain", f2)

        # 3rd time the snapshot is proven non-idempotent → POISON
        f3 = self._regress(orch, chains)
        self.assertIn("business_chain", f3, "poisoned guard must route the step to the verifier")
        self.assertIsNone(orch._chains_snapshot, "snapshot dropped")
        self.assertNotIn("business_chain", orch._fwval_green_high_water, "high-water cleared")
        self.assertEqual(set(rh._chains_frozen_eps), set(), "freeze lifted so verifier can re-author")
        self.assertEqual(chains.value()["fav"], _BROKEN, "not restored — left for the verifier to fix")

    def test_genuine_green_resets_the_counter(self):
        orch, chains, rh = _orch(self._tmp, self.eps)
        self._green(orch, chains)
        self._regress(orch, chains)          # count = 1
        self.assertEqual(orch._chains_restore_count, 1)
        self._green(orch, chains)            # a real green re-snapshot resets it
        self.assertEqual(orch._chains_restore_count, 0)

    def test_single_transient_reauthor_is_not_poisoned(self):
        # one re-author, then it stays good → never poisons (regression guard still protects)
        orch, chains, rh = _orch(self._tmp, self.eps)
        self._green(orch, chains)
        f = self._regress(orch, chains)
        self.assertNotIn("business_chain", f)
        self.assertIsNotNone(orch._chains_snapshot)   # snapshot intact
        self.assertEqual(chains.value()["fav"], _GOOD)


if __name__ == "__main__":
    unittest.main()
