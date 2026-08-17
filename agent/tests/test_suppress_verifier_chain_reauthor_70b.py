"""#70(b) (netflix r76, 2026-08-05) — deliver-tail business_chain NON-convergence. r76
converged the gate 17→2, then business_chain went green→REGRESSED→restored while the verifier
kept authoring NEW never-run chains (11 piled up) FASTER than #475's deterministic re-run could
settle them → run_chains never caught up → 0 delivery. Root: the framework armed a chain re-run
(#475) AND, in parallel, the remediation dispatcher told the verifier "URGENT: business_chain_failing"
→ it authored more unrun chains.

FIX: when #475 armed a re-run THIS tick (orch._chain_rerun_armed), SKIP the verifier RE-AUTHOR
dispatch for business_chain_failing — let run_chains settle the existing batch. This tests the
extracted decision predicate; the dispatch loop calls it to `continue` past the verifier dispatch."""
from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    suppress_verifier_chain_reauthor as S)


def test_suppress_when_rerun_armed_and_verifier_owned():
    # the r76 wedge state: framework is re-running chains → don't spawn more via the verifier
    assert S("business_chain_failing", "verifier", True) is True


def test_dispatch_when_rerun_not_armed():
    # #475 spent / a broken chain (no-op) → flag False → verifier IS dispatched to fix it
    assert S("business_chain_failing", "verifier", False) is False


def test_dispatch_when_rerouted_to_backend():
    # the #148 action-404 re-route flipped owner→backend (a REAL missing endpoint) — that is a
    # genuine backend fix and must STILL dispatch even while a re-run is armed
    assert S("business_chain_failing", "backend", True) is False


def test_only_business_chain_failing_is_suppressed():
    # other gate blockers are never suppressed by the chain-rerun flag
    for other in ("business_chain_api_coverage", "business_chain_coverage",
                  "business_chain_missing", "deliverability_ui_flow_missing",
                  "verification_checklist_not_ready", "database_sql_missing"):
        assert S(other, "verifier", True) is False, other


def test_falsey_armed_values_never_suppress():
    for armed in (False, None, 0, ""):
        assert S("business_chain_failing", "verifier", armed) is False, armed


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
