"""#478 — the r52 convergence churn (never delivered). register_verification_chain reset
EVERY re-registration to status='registered' (unrun) + last_result=None, so the verifier's
repeated re-registration (r52: 12× per run) kept flipping already-PASSING chains back to
unrun → business_chain_failing → delivery-gate churn → 0 release (all other gates green).

FIX: idempotent re-registration — when the STEPS are UNCHANGED and the chain was
passing/framework_blocked, PRESERVE its status + last_result; only a NEW or step-CHANGED
chain resets to 'registered'. Safe: run_chains re-executes all chains each validation, so a
preserved status is re-validated (an app regression on unchanged steps is still caught);
and a FAILING chain is NOT preserved (re-run needed). Generalizable to every env."""
from pathlib import Path
from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _rh(tmp_path):
    rh = RegistryHub(Path(tmp_path))
    # chain normalization prepends auth steps → register them so the chain isn't rejected
    rh.register_endpoint("POST", "/auth/register", status="implemented")
    rh.register_endpoint("POST", "/auth/login", status="implemented")
    rh.register_endpoint("GET", "/api/items", status="implemented")
    rh.register_endpoint("POST", "/api/items", status="implemented")
    return rh


def _status(rh, name):
    return (rh.get_verification_chains().get(name) or {}).get("status")


def test_reregister_same_steps_preserves_passing(tmp_path):
    rh = _rh(tmp_path)
    steps = [{"method": "GET", "path": "/api/items"}]
    assert "error" not in rh.register_verification_chain("c1", steps), "chain should register"
    assert _status(rh, "c1") == "registered"
    rh.record_chain_result("c1", {"broken": [], "steps": steps})
    assert _status(rh, "c1") == "passing"
    # #478: re-register IDENTICAL steps → status PRESERVED (the churn-breaker)
    rh.register_verification_chain("c1", steps)
    assert _status(rh, "c1") == "passing", \
        "#478: unchanged re-register must KEEP passing (else the verifier churns it to unrun)"
    assert (rh.get_verification_chains()["c1"].get("last_result")) is not None, \
        "#478: last_result preserved on unchanged re-register"


def test_reregister_changed_steps_resets_to_unrun(tmp_path):
    rh = _rh(tmp_path)
    steps = [{"method": "GET", "path": "/api/items"}]
    rh.register_verification_chain("c1", steps)
    rh.record_chain_result("c1", {"broken": [], "steps": steps})
    assert _status(rh, "c1") == "passing"
    steps2 = steps + [{"method": "POST", "path": "/api/items"}]  # genuinely different
    rh.register_verification_chain("c1", steps2)
    assert _status(rh, "c1") == "registered", \
        "#478: step-CHANGED chain correctly resets to unrun (must be re-run)"


def test_reregister_failing_chain_not_preserved(tmp_path):
    # only passing/framework_blocked are preserved; a FAILING chain re-registers as unrun
    rh = _rh(tmp_path)
    steps = [{"method": "GET", "path": "/api/items"}]
    rh.register_verification_chain("c1", steps)
    rh.record_chain_result("c1", {"broken": ["step 1: 500"], "steps": steps})
    assert _status(rh, "c1") == "failing"
    rh.register_verification_chain("c1", steps)
    assert _status(rh, "c1") == "registered", \
        "#478: a failing chain re-registers as unrun so it gets re-run (never preserves failing)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
