"""#71 (netflix r75/r76, 2026-08-05) — deliver-tail chain-resubmission churn. The verifier
authored a chain step for an endpoint the contract never defined (PUT /api/profiles/{id}, a
hallucinated update-profile route ABSENT from reference_spec.json), got the "endpoints NOT
registered" reject, and RE-SUBMITTED it many times — burning deliver-tail cycles (防止浪费token)
while business_chain churned.

FIX (per-ENDPOINT counting): r76 proved a (chain-name, unregistered-set)-keyed counter never
escalated — the verifier re-submits the SAME missing endpoint under a VARYING chain name (and/or
a different companion endpoint) each time (PUT /api/profiles/{} rejected 6×, 0 escalations). So
count rejects PER unregistered ENDPOINT across ALL chains and ESCALATE the guidance once ANY
endpoint in a reject has been rejected >=2 times — robust to name/companion variation. Purely
additive: the FIRST reject of an endpoint is unchanged; happy path + chain content untouched;
self-invalidates once the endpoint is registered (drops out of `unregistered`). Generalizes."""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _rh(tmp_path):
    rh = RegistryHub(Path(tmp_path))
    # chain normalization prepends auth steps → register them so ONLY the hallucinated
    # PUT /api/profiles/{id} is unregistered.
    rh.register_endpoint("POST", "/auth/register", status="implemented")
    rh.register_endpoint("POST", "/auth/login", status="implemented")
    rh.register_endpoint("GET", "/api/profiles", status="implemented")
    rh.register_endpoint("POST", "/api/profiles", status="implemented")
    return rh


_HALLUCINATED = [{"method": "PUT", "path": "/api/profiles/{id}", "body": {"name": "x"}}]


def test_first_reject_is_plain_no_escalation(tmp_path):
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("update_profile", _HALLUCINATED)
    assert "error" in res
    assert "NOT registered in RegistryHub" in res["error"]
    # FIRST reject of this endpoint must be the unchanged base message — no escalation yet.
    assert "been rejected" not in res["error"]


def test_second_reject_same_name_escalates(tmp_path):
    rh = _rh(tmp_path)
    rh.register_verification_chain("update_profile", _HALLUCINATED)          # 1st
    res2 = rh.register_verification_chain("update_profile", _HALLUCINATED)   # 2nd
    assert "error" in res2
    assert "been rejected 2 times" in res2["error"], res2["error"]
    assert "PUT /api/profiles/{}" in res2["error"]
    assert "DROP those steps" in res2["error"]


def test_varying_chain_name_same_endpoint_still_escalates(tmp_path):
    # THE r76 BUG: the verifier re-submits the same missing endpoint under DIFFERENT chain
    # names. Per-endpoint counting must still escalate on the 2nd (name is irrelevant).
    rh = _rh(tmp_path)
    rh.register_verification_chain("update_profile_v1", _HALLUCINATED)       # 1st (name A)
    res = rh.register_verification_chain("edit_profile_flow", _HALLUCINATED)  # 2nd (name B)
    assert "error" in res
    assert "been rejected 2 times" in res["error"], res["error"]
    # count keeps rising across further varying-name resubmissions
    res3 = rh.register_verification_chain("profile_update_chain", _HALLUCINATED)  # 3rd (name C)
    assert "been rejected 3 times" in res3["error"], res3["error"]


def test_companion_endpoint_variation_still_escalates(tmp_path):
    # the missing endpoint paired with a DIFFERENT (also-missing) companion each time → the
    # (name,set) key would differ, but per-endpoint counting escalates on PUT /api/profiles.
    rh = _rh(tmp_path)
    c1 = _HALLUCINATED + [{"method": "DELETE", "path": "/api/nonexistent_a/{id}"}]
    c2 = _HALLUCINATED + [{"method": "DELETE", "path": "/api/nonexistent_b/{id}"}]
    rh.register_verification_chain("c1", c1)                                  # profiles: 1
    res = rh.register_verification_chain("c2", c2)                            # profiles: 2 → escalate
    assert "PUT /api/profiles/{}" in res["error"]
    assert "been rejected 2 times" in res["error"], res["error"]


def test_self_invalidates_when_endpoint_registered(tmp_path):
    # the dedup must NOT block a chain that becomes valid once the endpoint is registered.
    rh = _rh(tmp_path)
    rh.register_verification_chain("update_profile", _HALLUCINATED)          # rejected 1st
    rh.register_verification_chain("update_profile", _HALLUCINATED)          # rejected 2nd (escalated)
    rh.register_endpoint("PUT", "/api/profiles/{id}", status="implemented")  # now it exists
    res = rh.register_verification_chain("update_profile", _HALLUCINATED)
    assert "error" not in res, res   # the now-valid chain registers cleanly (no stale block)


def test_distinct_endpoint_has_own_counter(tmp_path):
    # per-endpoint: a DIFFERENT missing endpoint's FIRST reject is not escalated (no cross-count).
    rh = _rh(tmp_path)
    rh.register_verification_chain("update_profile", _HALLUCINATED)          # profiles: 1
    rh.register_verification_chain("update_profile", _HALLUCINATED)          # profiles: 2 (escalated)
    other = [{"method": "PUT", "path": "/api/my-list/{id}", "body": {"pos": 1}}]
    res = rh.register_verification_chain("update_mylist", other)             # my-list: 1
    assert "error" in res
    assert "been rejected" not in res["error"], "distinct endpoint must start its own count"


def test_valid_chain_still_registers_unaffected(tmp_path):
    # happy path untouched: a chain over registered endpoints registers with no error.
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("list_profiles", [{"method": "GET", "path": "/api/profiles"}])
    assert "error" not in res, res
    assert (rh.get_verification_chains().get("list_profiles") or {}).get("status") == "registered"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
