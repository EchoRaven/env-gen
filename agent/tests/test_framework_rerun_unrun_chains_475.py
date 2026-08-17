"""#475 — the LAST Part-B convergence blocker (r50, 2026-08-04). After #473 cleared the
seed blocker, r50 reached seed✓/functional✓/visual✓/ui_flow✓/16-endpoints✓ but still
churned to 0 release (14 DELIVER_PROJECT) on business_chain_failing — caused by ONE
never-run ('?') chain while 29/31 passed. business_chain_blockers lumps NEVER-RUN chains
with FAILED ones; the gate then re-dispatches the verifier to RE-AUTHOR, which registers
more unrun chains → churn.

FIX: maybe_rerun_unrun_chains — when the ONLY business_chain blockers are unrun chains
(status unset, no broken last_result), reset the api_smoke attempt counter (bounded per
milestone, mirrors FIX #120) so run_chains re-executes ALL chains and records real status.
SAFETY (the crux): it NEVER acts when any chain has a BROKEN last_result — a real failure
stays a verifier fix and is never masked by a re-run."""
import types
from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    maybe_rerun_unrun_chains)


def _orch(chains: dict):
    rh = types.SimpleNamespace(get_verification_chains=lambda: chains)
    hubs = types.SimpleNamespace(registryhub=rh)
    logger = types.SimpleNamespace(warning=lambda *a, **k: None)
    return types.SimpleNamespace(
        hubs=hubs, _logger=logger, _current_milestone_version="1.0.0",
        _framework_validation_attempts=5)


_PASS = {"steps": [{"x": 1}], "status": "passing"}
_UNRUN = {"steps": [{"x": 1}], "status": "?"}          # registered, never executed
_UNRUN2 = {"steps": [{"x": 1}]}                          # no status key at all
_BROKEN = {"steps": [{"x": 1}], "status": "failing",
           "last_result": {"broken": ["step 2: 500"]}}
_COVERAGE = {"steps": [{"x": 1}], "status": "?", "kind": "coverage"}


def test_unrun_only_arms_rerun():
    orch = _orch({"a": _PASS, "b": _UNRUN, "c": _UNRUN2, "_meta": {}})
    assert maybe_rerun_unrun_chains(orch, ["business_chain_failing"]) is True
    assert orch._framework_validation_attempts == 0, "#475: reset api_smoke attempts → run_chains re-runs"
    assert orch._unrun_chain_rerun_by_ms["1.0.0"] == 1


def test_broken_chain_never_masked():
    # a chain with a BROKEN last_result is a REAL failure → do NOT re-run/mask it
    orch = _orch({"a": _PASS, "b": _BROKEN, "c": _UNRUN, "_meta": {}})
    assert maybe_rerun_unrun_chains(orch, ["business_chain_failing"]) is False
    assert orch._framework_validation_attempts == 5, "must NOT reset when a real failure exists"


def test_no_business_chain_blocker_noop():
    orch = _orch({"a": _PASS, "b": _UNRUN})
    assert maybe_rerun_unrun_chains(orch, ["deliverability_ui_flow_missing"]) is False
    assert orch._framework_validation_attempts == 5


def test_all_passing_noop():
    orch = _orch({"a": _PASS, "b": _PASS, "_meta": {}})
    assert maybe_rerun_unrun_chains(orch, ["business_chain_failing"]) is False


def test_coverage_chain_excluded():
    # a kind='coverage' chain is never executed and must NOT count as a blocker
    orch = _orch({"a": _PASS, "cov": _COVERAGE, "_meta": {}})
    assert maybe_rerun_unrun_chains(orch, ["business_chain_failing"]) is False


def test_budget_bounded_per_milestone():
    orch = _orch({"a": _PASS, "b": _UNRUN, "_meta": {}})
    fired = 0
    for _ in range(6):
        orch._framework_validation_attempts = 5
        if maybe_rerun_unrun_chains(orch, ["business_chain_failing"]):
            fired += 1
    assert fired == 4, "#475: bounded to 4 re-runs per milestone (no infinite loop)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
