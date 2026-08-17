"""#486 — delivery gate must not block on INFRA-only verification chains (task#47,
netflix r58 live). The verifier voluntarily authors chains for framework control-surface
endpoints (`/api/v1/tenants`, `/api/v1/reset`, `/api/v1/admin/init-tenant`) that are NOT
app business flows. r58: `tenant_admin_coverage` POSTs `/api/v1/tenants` with only a
`name` (the framework endpoint requires a client-supplied `id`) → 400 → the chain is
`failing` → `business_chain_failing` BLOCKS an app that is otherwise 27/27 business-green.
A chain that touches ZERO business endpoints verifies nothing about the app, so its
pass/fail must not gate business delivery. This mirrors the existing kind="coverage"
exclusion and reuses the SAME is_business() classification the coverage check trusts —
excluding an infra-only chain can never hide a business bug (it touches no business
endpoint), and the full business surface stays enforced by _uncovered_business_endpoints."""
import re

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    business_chain_blockers, _business_endpoint_ids, _chain_touches_business)


class _FakeRH:
    def __init__(self, endpoints, chains):
        self._eps = endpoints
        self._chains = chains

    def get_endpoints(self):
        return dict(self._eps)

    def get_verification_chains(self):
        return dict(self._chains)

    def endpoint_id(self, m, p):
        p = re.sub(r"\$\{[^}]+\}", "{x}", p)
        p = re.sub(r"\{[^}]+\}", "{x}", p)
        return f"{(m or 'GET').upper()} {p.rstrip('/') or '/'}"

    # complete_coverage_chain may try to persist; make them safe no-ops
    def register_verification_chain(self, *a, **k):
        return None

    def update_verification_chain(self, *a, **k):
        return None


class _FakeHubs:
    def __init__(self, rh):
        self.registryhub = rh


_ENDPOINTS = {
    "e1": {"method": "GET", "path": "/api/titles"},
    "e2": {"method": "GET", "path": "/api/titles/{title_id}"},
    "e3": {"method": "GET", "path": "/api/profiles"},
    # framework control-surface (is_business == False)
    "e4": {"method": "GET", "path": "/api/v1/tenants"},
    "e5": {"method": "POST", "path": "/api/v1/tenants"},
}


def _title_flow(status="passing"):
    rec = {
        "name": "title_browse", "steps": [
            {"method": "GET", "path": "/api/titles"},
            {"method": "GET", "path": "/api/titles/${id}"},
            {"method": "GET", "path": "/api/profiles"},
        ], "status": status,
    }
    if status != "passing":
        rec["last_result"] = {"broken": ["GET /api/titles/${id} -> 500"]}
    return rec


def _tenant_infra(status="failing"):
    rec = {
        "name": "tenant_admin_coverage", "steps": [
            {"method": "POST", "path": "/auth/register"},
            {"method": "POST", "path": "/api/v1/tenants", "body": {"name": "t"}},
        ], "status": status,
    }
    if status != "passing":
        rec["last_result"] = {"broken": ["POST /api/v1/tenants -> 400"]}
    return rec


def test_business_endpoint_ids_excludes_control_surface():
    rh = _FakeRH(_ENDPOINTS, {})
    ids = _business_endpoint_ids(rh)
    assert rh.endpoint_id("GET", "/api/titles") in ids
    assert rh.endpoint_id("GET", "/api/profiles") in ids
    # /api/v1/tenants is control-surface → NOT a business endpoint
    assert rh.endpoint_id("GET", "/api/v1/tenants") not in ids
    assert rh.endpoint_id("POST", "/api/v1/tenants") not in ids


def test_chain_touches_business_classification():
    rh = _FakeRH(_ENDPOINTS, {})
    ids = _business_endpoint_ids(rh)
    assert _chain_touches_business(rh, _title_flow(), ids) is True
    # tenant chain: /auth/register + /api/v1/tenants → NO business endpoint
    assert _chain_touches_business(rh, _tenant_infra(), ids) is False


def test_infra_only_failing_chain_does_NOT_block_delivery():
    """The r58 wedge: business chain passes + covers everything, ONLY the infra
    tenant chain is failing → gate must be SATISFIED (returns {})."""
    chains = {"title_browse": _title_flow("passing"),
              "tenant_admin_coverage": _tenant_infra("failing")}
    gate = business_chain_blockers(_FakeHubs(_FakeRH(_ENDPOINTS, chains)))
    assert gate == {} or gate.get("reason") != "business_chain_failing", \
        f"#486: an infra-only failing chain must not cause business_chain_failing; got {gate}"


def test_real_business_failing_chain_STILL_blocks():
    """A failing chain that DOES touch a business endpoint must still block —
    the fix only excludes infra-only chains, never real business ones."""
    chains = {"title_browse": _title_flow("failing"),
              "tenant_admin_coverage": _tenant_infra("failing")}
    gate = business_chain_blockers(_FakeHubs(_FakeRH(_ENDPOINTS, chains)))
    assert gate.get("reason") == "business_chain_failing", \
        f"#486: a failing BUSINESS chain must still block delivery; got {gate}"
    assert "title_browse" in (gate.get("chains") or []), gate


def test_only_infra_chains_authored_reports_missing_not_failing():
    """If the verifier authored ONLY infra chains (no business-flow chain at all),
    the correct blocker is business_chain_missing (author a real chain), not _failing."""
    chains = {"tenant_admin_coverage": _tenant_infra("failing"),
              "tenant_admin_v2": _tenant_infra("passing")}
    gate = business_chain_blockers(_FakeHubs(_FakeRH(_ENDPOINTS, chains)))
    assert gate.get("reason") == "business_chain_missing", gate


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
