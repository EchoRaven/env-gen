"""#1054 — the regression guard's "did an agent re-author?" test also answers YES
to a chain that merely RAN.

`restore_regressed_chains` decides an agent broke the chains by comparing the
whole store against the last-passing snapshot:

    if cur_eps == snap_eps and dict(rh._verification_chains.value() or {}) != snap:

But `chain_executor.run_chains` writes execution metadata back onto the SAME
records after every validation — same file, `shared/hubs/registryhub_verification
_chains.json`:

    rec = {**rec, "status": _status,
           "last_result": {...}, "last_run_at": time.time()}

`last_run_at` is a wall-clock float, so the raw dict compare differs after ANY
run, whether or not a single step was edited.

That breaks the guard's own stated safety property:

    "Self-correcting: if the app genuinely broke, the restored-correct chain
     still fails and (current == snapshot) so the restore is skipped and normal
     feedback proceeds — never masks a real defect."

`current == snapshot` never holds again once the chains have run. So a GENUINE
backend regression is misread as agent re-authoring: the guard restores, drops
business_chain from the failure set (nobody is dispatched to fix the real
break), and resets `_framework_validation_attempts`. It repeats until the #327
budget is spent, then poisons the snapshot — i.e. it burns its entire budget on
every real regression instead of never firing for one. r169: "fired twice while
still losing".

The framework already has the right predicate and uses it elsewhere —
`_fwval_chain_signature` hashes each chain's `steps` and documents that it
EXCLUDES "last_result / last_run_at / _updated_at / status", so "a CHANGED
signature ⇒ the verifier RE-AUTHORED a chain".
"""
from __future__ import annotations

import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.framework_validation import (  # noqa: E402
    snapshot_passing_chains, restore_regressed_chains)
from multi_agent.runtime.json_store import JsonStore  # noqa: E402

_GOOD = {"name": "flow", "steps": [
    {"method": "POST", "path": "/auth/register", "body": {"email": "u@x.com"}},
    {"method": "POST", "path": "/api/notes", "body": {"title": "t"}}]}
_REAUTHORED = {"name": "flow", "steps": [
    {"method": "POST", "path": "/auth/register", "body": {"email": "u@x.com"}},
    {"method": "POST", "path": "/api/notes", "body": {}}]}  # step edited


def _orch(tmp, endpoints):
    chains = JsonStore(Path(tmp) / "registryhub_verification_chains.json")
    rh = types.SimpleNamespace(_verification_chains=chains,
                               get_endpoints=lambda: dict(endpoints))
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(registryhub=rh),
        _logger=types.SimpleNamespace(warning=lambda *a, **k: None,
                                      info=lambda *a, **k: None),
        _framework_validation_attempts=1), chains


def _record_a_run(chains, *, passing: bool) -> None:
    """Exactly what chain_executor.run_chains writes back after executing."""
    cur = dict(chains.value() or {})
    rec = dict(cur["flow"])
    rec.update({"status": "passing" if passing else "failing",
                "last_result": {"broken": [] if passing else ["POST /api/notes -> 500"],
                                "steps": []},
                "last_run_at": time.time()})
    chains.update(lambda _v, _r=rec: {**cur, "flow": _r}, change_info={"agent": "x"})


class AChainThatOnlyRanIsNotAReauthoredChain(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.eps = {"POST:/api/notes": {}, "GET:/api/notes": {}}

    def _green(self):
        orch, chains = _orch(self._tmp, self.eps)
        chains.set("flow", dict(_GOOD))
        _record_a_run(chains, passing=True)      # green runs write metadata too
        snapshot_passing_chains(orch)
        return orch, chains

    def test_a_genuine_backend_break_is_not_restored(self):
        """The app broke; the chains were never edited. The guard must stand down."""
        orch, chains = self._green()
        _record_a_run(chains, passing=False)     # the regression: only metadata moved
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertIn("business_chain", fset,
                      "a real app break must stay in the failure set so its owner is dispatched")

    def test_the_run_result_is_not_reverted(self):
        orch, chains = self._green()
        _record_a_run(chains, passing=False)
        restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(dict(chains.value())["flow"]["status"], "failing",
                         "restoring the snapshot overwrites the result of the run that just ran")

    def test_the_attempt_ladder_is_not_reset(self):
        orch, chains = self._green()
        _record_a_run(chains, passing=False)
        restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(orch._framework_validation_attempts, 1)

    def test_the_restore_budget_is_not_spent(self):
        orch, chains = self._green()
        _record_a_run(chains, passing=False)
        restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(int(getattr(orch, "_chains_restore_count", 0) or 0), 0,
                         "#327's budget must be there for real re-authoring, not spent on runs")


class GenuineReauthoringStillRestores(unittest.TestCase):
    """The guard's actual job must keep working."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.eps = {"POST:/api/notes": {}, "GET:/api/notes": {}}

    def _green(self):
        orch, chains = _orch(self._tmp, self.eps)
        chains.set("flow", dict(_GOOD))
        _record_a_run(chains, passing=True)
        snapshot_passing_chains(orch)
        return orch, chains

    def test_an_edited_step_is_reverted(self):
        orch, chains = self._green()
        chains.set("flow", dict(_REAUTHORED))
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(dict(chains.value())["flow"]["steps"], _GOOD["steps"])
        self.assertNotIn("business_chain", fset)

    def test_a_new_broken_chain_is_dropped_full_replace(self):
        orch, chains = self._green()
        chains.set("flow2", dict(_REAUTHORED))
        restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertNotIn("flow2", dict(chains.value()))

    def test_reauthoring_after_a_run_is_still_caught(self):
        """Metadata drift must not MASK a real re-authoring either."""
        orch, chains = self._green()
        _record_a_run(chains, passing=False)
        chains.set("flow", dict(_REAUTHORED))
        fset = restore_regressed_chains(orch, frozenset({"business_chain"}))
        self.assertEqual(dict(chains.value())["flow"]["steps"], _GOOD["steps"])
        self.assertNotIn("business_chain", fset)


if __name__ == "__main__":
    unittest.main()
