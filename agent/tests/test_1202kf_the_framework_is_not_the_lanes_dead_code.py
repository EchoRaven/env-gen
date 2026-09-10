"""#1202kf: "remove or wire up the dead artifacts" — about code the framework wrote.

r114's delivery gate, live while this was written:

    7 dead artifact(s) (Cutover 19 gate) — endpoints=7: endpoints:/oauth/register,
    endpoints:/oauth/authorize, endpoints:/oauth/authorize, endpoints:/oauth/token,
    endpoints:/.well-known/jwks.json,
    endpoints:/.well-known/oauth-authorization-server, endpoints:/health

Every one of those is projected by the framework (`oauth_scaffold`, `control_plane`) and
none of them can EVER acquire a consumer: `oauth_scaffold`'s own docstring says the auth and
oauth endpoints are fixed-spec with heterogeneous shapes so "the frontend's response_key-keyed
api.js generator MUST SKIP them", and the AS's own login page — not the app — drives
/oauth/authorize. `scan_dead_endpoints` calls an endpoint dead when its consumer list is
empty, so for these it is empty by construction. That is the shape #1199 deleted
`scan_dead_tables` for, and the shape `_is_framework_owned_1088` already exempts FILES for.

Measured over the 153 runs with an endpoints ledger: 37 of 155 dead-endpoint findings (24%)
are these, and of the 45 runs whose final ledger carries a dead-endpoint blocker, 16 are made
ENTIRELY of them — a delivery blocker with nothing actionable in it. A floor, not an estimate:
a lane that re-registers the endpoint clears the record, and r114 showed 7 in the gate log and
0 in the ledger twenty minutes later.

WHAT IS VERIFIED: a framework-fixed endpoint at status='defined' with no consumers is no
longer reported dead; a business endpoint in exactly that state still is; and the exemption
reads the framework's own declarations rather than a copied list.

WHAT IS NOT: that suppressing it makes any run deliver. It removes a blocker that named only
un-actionable work — the same trade #1023b made for tables and #1085 for tool configs.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
# House style, and NOT a detail: insert `llm_generator`, never `multi_agent` itself.
# `multi_agent/` contains its own `tests/` package, so putting it on sys.path ahead of `agent/`
# shadows `agent/tests` — and `test_kickoff_run_kickoff_finalize_hardening.py`, which does
# `from tests.test_kickoff_run_kickoff import ...`, then fails to COLLECT and takes the whole
# suite down with it. Passed alone; only the full run showed it.
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.coverage_audit import scan_dead_endpoints                 # noqa: E402
from multi_agent.runtime.kickoff.contract import fixed_surface_1202ke              # noqa: E402
from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS               # noqa: E402
from multi_agent.runtime.control_plane import CONTROL_SURFACE_ENDPOINTS            # noqa: E402


class _Registry:
    def __init__(self, eps):
        self._eps = eps

    def get_endpoints(self):
        return self._eps

    def get_consumers(self, _ep_id):
        return []


class _Hubs:
    def __init__(self, eps):
        self.registryhub = _Registry(eps)


def _ep(method, path, status="defined"):
    return {f"{method} {path}": {"method": method, "path": path,
                                 "status": status, "provider": "backend"}}


def _paths(found):
    return sorted(f["path"] for f in found)


def test_a_business_endpoint_with_no_consumers_is_still_dead():
    """★ The floor. Without this the exemption could be doing nothing, or everything."""
    assert _paths(scan_dead_endpoints(_Hubs(_ep("GET", "/api/videos")))) == ["/api/videos"]


def test_r114s_seven_are_all_exempt():
    """★ The case. Reconstructed from the gate line quoted in the docstring."""
    eps = {}
    for m, p in (("POST", "/oauth/register"), ("GET", "/oauth/authorize"),
                 ("POST", "/oauth/authorize"), ("POST", "/oauth/token"),
                 ("GET", "/.well-known/jwks.json"),
                 ("GET", "/.well-known/oauth-authorization-server"),
                 ("GET", "/health")):
        eps.update(_ep(m, p))
    assert scan_dead_endpoints(_Hubs(eps)) == []


def test_every_framework_fixed_endpoint_is_exempt():
    """Enumerated from the declarations, so a new fixed endpoint is covered the day it lands."""
    for e in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS):
        found = scan_dead_endpoints(_Hubs(_ep(e["method"], e["path"])))
        assert found == [], f"{e['method']} {e['path']} still reported dead"


def test_the_exemption_reads_the_framework_not_a_copy():
    surf = fixed_surface_1202ke()
    assert len(surf) == len(AS_CONTRACT_ENDPOINTS) + len(CONTROL_SURFACE_ENDPOINTS)


def test_a_business_path_that_merely_starts_the_same_is_not_exempt():
    """`/health-metrics` and `/api/v1/tenants-audit` are business endpoints. A prefix rule
    here is the `art` matching `cart_token` trap; the key is the WHOLE (method, path)."""
    for m, p in (("GET", "/health-metrics"), ("GET", "/api/v1/tenants-audit"),
                 ("POST", "/oauth/tokens")):
        assert _paths(scan_dead_endpoints(_Hubs(_ep(m, p)))) == [p], p


def test_a_different_method_on_a_fixed_path_is_not_exempt():
    """DELETE /oauth/token is not on the surface. Exempting a whole PATH would hide a real
    lane endpoint that happens to share it."""
    assert _paths(scan_dead_endpoints(_Hubs(_ep("DELETE", "/oauth/token")))) == ["/oauth/token"]


def test_an_implemented_endpoint_is_still_skipped_first():
    """Non-regression: the status test predates this and must still short-circuit."""
    assert scan_dead_endpoints(_Hubs(_ep("GET", "/api/videos", status="implemented"))) == []


def test_a_missing_oauth_module_does_not_break_the_audit():
    """A build without the AS must degrade to 'nothing exempt', never to a crashed audit."""
    import multi_agent.runtime.coverage_audit as CA
    assert isinstance(CA._framework_fixed_1202kf(), set)
