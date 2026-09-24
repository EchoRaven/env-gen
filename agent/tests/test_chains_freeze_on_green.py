"""Freeze verification chains once business_chain is GREEN (outlook run-25, 2026-07-01).

run-25 converged the backend (api_smoke passed) but then OSCILLATED at delivery: the verifier
re-authored a passing chain into a broken one (GET /api/messages/${messageId} → 422), the
regression guard restored the last-passing snapshot, the verifier re-broke it → 75-min no-
convergence abort. The regression guard only reverts AFTER the fact; it doesn't PREVENT the re-
break. Fix: once business_chain is green, register_verification_chain treats a RE-AUTHOR of an
EXISTING chain (same contract) as a no-op — the passing chain is kept. NEW chain names + a changed
contract (next milestone) are unaffected; the framework's coverage-completion + regression-guard
restore write the store directly (not via this method) so neither is blocked. ENV-AGNOSTIC +
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.framework_validation import snapshot_passing_chains  # noqa: E402


def _rh(tmp_path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in [("POST", "/auth/register"), ("POST", "/api/messages"),
                 ("GET", "/api/messages")]:
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    return hr, rh


_GOOD = [{"method": "POST", "path": "/api/messages", "expect": [201]},
         {"method": "GET", "path": "/api/messages", "expect": [200]}]


def test_freeze_blocks_reauthor_of_existing_chain_keeps_passing_one(tmp_path):
    hr, rh = _rh(tmp_path)
    res = rh.register_verification_chain("flow", steps=list(_GOOD), agent="verifier")
    assert "error" not in res and not res.get("frozen"), res           # initial author OK
    rh._chains_frozen_eps = set((rh.get_endpoints() or {}).keys())      # business_chain went green
    # verifier tries to RE-AUTHOR the same chain into a (broken) 1-step version
    res2 = rh.register_verification_chain("flow", steps=[
        {"method": "GET", "path": "/api/messages", "expect": [200]}], agent="verifier")
    assert res2.get("frozen") is True, res2
    kept = (rh.get_verification_chains() or {})["flow"]
    # the ORIGINAL (passing) chain is kept — it still has the POST create the broken
    # re-author (a GET-only chain) would have dropped (robust to the auto-prepended /auth step)
    assert any(s.get("method") == "POST" and s.get("path") == "/api/messages"
               for s in kept["steps"]), kept["steps"]


def test_freeze_allows_a_new_chain_name(tmp_path):
    hr, rh = _rh(tmp_path)
    rh.register_verification_chain("flow", steps=list(_GOOD), agent="verifier")
    rh._chains_frozen_eps = set((rh.get_endpoints() or {}).keys())
    res = rh.register_verification_chain("extra_flow", steps=[
        {"method": "GET", "path": "/api/messages", "expect": [200]}], agent="verifier")
    assert not res.get("frozen"), res                                   # NEW name → allowed
    assert "error" not in res
    assert "extra_flow" in (rh.get_verification_chains() or {})


def test_contract_change_lifts_the_freeze(tmp_path):
    hr, rh = _rh(tmp_path)
    rh.register_verification_chain("flow", steps=list(_GOOD), agent="verifier")
    rh._chains_frozen_eps = set((rh.get_endpoints() or {}).keys())
    # a new milestone registers a new endpoint → eps changes → auto-unfrozen
    rh.register_endpoint("GET", "/api/messages/{messageId}", agent="backend", status="implemented")
    res = rh.register_verification_chain("flow", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages/${messageId}", "expect": [200]}], agent="verifier")
    assert not res.get("frozen"), res                                   # contract changed → re-author allowed
    assert "error" not in res, res


def test_not_frozen_reauthor_works_normally(tmp_path):
    hr, rh = _rh(tmp_path)
    rh.register_verification_chain("flow", steps=list(_GOOD), agent="verifier")
    # no freeze set → re-author proceeds normally
    res = rh.register_verification_chain("flow", steps=[
        {"method": "GET", "path": "/api/messages", "expect": [200]}], agent="verifier")
    assert not res.get("frozen"), res
    # re-author (a GET-only chain) OVERWROTE the original → the POST create is gone
    steps = (rh.get_verification_chains() or {})["flow"]["steps"]
    assert not any(s.get("method") == "POST" and s.get("path") == "/api/messages"
                   for s in steps), steps


def test_snapshot_passing_chains_sets_the_freeze(tmp_path):
    hr, rh = _rh(tmp_path)

    class _Orch:
        def __init__(self, hubs):
            self.hubs = hubs
            import logging
            self._logger = logging.getLogger("t")
    orch = _Orch(hr)
    snapshot_passing_chains(orch)
    assert getattr(rh, "_chains_frozen_eps", None) == set((rh.get_endpoints() or {}).keys())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
