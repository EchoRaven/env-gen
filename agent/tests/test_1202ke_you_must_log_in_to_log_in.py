"""#1202ke: the contract said you need a token to get a token.

r114's kickoff log, live while this was written:

    KICKOFF RECONCILE (escalate): ... normalized 31 endpoint-shape issue(s)
    ['defaulted auth_required=True for POST /auth/register', ...,
     'defaulted auth_required=True for POST /auth/login', ...]

and the registration that landed in `registryhub_endpoints.json` carried
`metadata.auth_required: true` beside a `summary` and a request/response copied VERBATIM out
of `oauth_scaffold.AS_CONTRACT_ENDPOINTS` -- whose own record for that same path says
`auth_required: False`, and which `scaffolder.register_fixed_contract_surface` had already
registered correctly. `register_endpoint` is a merge-upsert on (method, path), so the later,
wrong write won.

The mechanism: the backend draft re-declares the auth surface it was shown in the prompt and
omits the flag; `_normalize_backend_endpoints_for_reconcile`'s rule -- "the LLM only omits it,
never means public" -- is right for a business endpoint and inverts the framework's own answer
for this one.

Measured over the 153 generated runs carrying an endpoints ledger: 15 state that a public auth
endpoint requires auth, and they are the CURRENT era, not history -- tiktok r96/r97/r99/r103/
r104/r106/r107, netflix-local r9/r27/r31/r35/r41, and r114 (which also flipped /oauth/register
and /oauth/token).

WHAT IS VERIFIED here: the framework's value now wins in both places a kickoff endpoint can
reach the ledger, over an omission and over an explicit contradiction alike; business
endpoints keep the fail-closed default; and the fixed surface is read from the framework's own
declarations rather than a copied literal.

WHAT IS NOT: that this changed any run's outcome. `oauth_routes.py` is projected and never
enforced the auth the ledger claimed, so nothing 401'd because of it -- what it produced is a
contract that lies about framework code no lane can edit, which is the #919 oscillation shape.
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

import pytest                                                          # noqa: E402

from multi_agent.runtime.kickoff.contract import (                                 # noqa: E402
    fixed_surface_1202ke,
    normalize_to_registryhub_endpoint,
)
from multi_agent.runtime.kickoff.run_kickoff import (                              # noqa: E402
    _normalize_backend_endpoints_for_reconcile as _norm,
)
from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS               # noqa: E402
from multi_agent.runtime.control_plane import CONTROL_SURFACE_ENDPOINTS            # noqa: E402


def _ke(method, path, auth, rk="data"):
    return {"method": method, "path": path, "response_key": rk,
            "auth_required": auth, "request": {}, "response": {}}


# --- the surface itself ---------------------------------------------------------------------

def test_the_surface_is_read_from_the_framework_not_copied():
    """A literal copy is how a fixed list silently stops matching the code it describes."""
    surf = fixed_surface_1202ke()
    assert len(surf) == len(AS_CONTRACT_ENDPOINTS) + len(CONTROL_SURFACE_ENDPOINTS)
    for ep in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS):
        assert (ep["method"].upper(), ep["path"]) in surf


def test_every_fixed_endpoint_is_public():
    """The premise. If the framework ever fixes an endpoint that DOES need auth, this fix
    still does the right thing (it copies the value) -- but the test below that asserts
    'login is public' would be asserting the wrong thing, so pin the premise explicitly."""
    for ep in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS):
        assert ep.get("auth_required") is False, ep["path"]


# --- the funnel: normalize_to_registryhub_endpoint -------------------------------------------

@pytest.mark.parametrize("path", ["/auth/login", "/auth/register", "/oauth/token"])
def test_an_explicit_true_on_a_fixed_endpoint_is_overruled(path):
    """★ The half the reconcile normalizer cannot reach: a draft that STATES auth_required
    true is valid to roadmap_validator, never escalates, and used to sail straight through."""
    assert normalize_to_registryhub_endpoint(_ke("POST", path, True))["auth_required"] is False


def test_a_trailing_slash_does_not_smuggle_it_past():
    assert normalize_to_registryhub_endpoint(
        _ke("POST", "/auth/login/", True))["auth_required"] is False


def test_a_lowercase_method_does_not_smuggle_it_past():
    assert normalize_to_registryhub_endpoint(
        _ke("post", "/auth/login", True))["auth_required"] is False


def test_a_business_endpoint_keeps_its_declared_auth():
    """★ Scope, both directions: the fix must not reach past the fixed surface."""
    assert normalize_to_registryhub_endpoint(
        _ke("GET", "/api/videos", True))["auth_required"] is True
    assert normalize_to_registryhub_endpoint(
        _ke("POST", "/api/videos", False))["auth_required"] is False


def test_a_business_path_that_merely_contains_login_is_untouched():
    """`/api/login-history` is a business endpoint. A substring rule here is exactly the
    `art` matching `cart_token` trap; the surface is keyed on the WHOLE (method, path)."""
    assert normalize_to_registryhub_endpoint(
        _ke("GET", "/api/login-history", True))["auth_required"] is True


# --- the draft: _normalize_backend_endpoints_for_reconcile -----------------------------------

def test_the_reconcile_normalizer_no_longer_invents_auth_for_the_fixed_surface():
    """★ r114's exact input: the draft re-declares /auth/login and omits the flag."""
    out, notes = _norm({"backend": {"api_endpoints": [
        {"method": "POST", "path": "/auth/login", "summary": "First-party login"},
    ]}})
    ep = out["backend"]["api_endpoints"][0]
    assert ep["auth_required"] is False
    assert not any("defaulted auth_required=True for POST /auth/login" in n for n in notes)
    assert any("#1202ke" in n for n in notes), f"the change must be reported: {notes}"


def test_the_reconcile_normalizer_still_fails_closed_for_business():
    """Non-regression: #20's rule is right for the surface it was written for."""
    out, notes = _norm({"backend": {"api_endpoints": [
        {"method": "GET", "path": "/api/videos"},
    ]}})
    assert out["backend"]["api_endpoints"][0]["auth_required"] is True
    assert any("defaulted auth_required=True for GET /api/videos" in n for n in notes)


def test_a_response_key_is_still_derived_for_a_fixed_endpoint():
    """★ The fix stays narrow to `auth_required`, and this pins WHY.

    The first draft of #1202ke also skipped the response_key derivation for a fixed endpoint,
    reasoning that kind auth/oauth/infra is fixed-spec with heterogeneous shapes the
    response_key-keyed api.js generator must skip. That would have been a RUN-KILLER:
    `roadmap_validator` requires `endpoint.response_key` to be a non-empty string, and this
    normalizer is the LAST RESORT before `validation_failed` aborts the run -- so an absent key
    trades a contract that lies for a run that dies. Assert the key survives, and assert the
    validator's rule directly so the two can never drift apart."""
    out, _ = _norm({"backend": {"api_endpoints": [
        {"method": "POST", "path": "/auth/register"},
    ]}})
    ep = out["backend"]["api_endpoints"][0]
    assert isinstance(ep.get("response_key"), str) and ep["response_key"].strip()

    from multi_agent.runtime.kickoff.roadmap_validator import validate_roadmap  # noqa: F401
    import inspect as _i
    from multi_agent.runtime.kickoff import roadmap_validator as _rv
    assert "endpoint.response_key MUST be a non-empty string" in _i.getsource(_rv)


def test_a_fixed_endpoint_already_correct_produces_no_1202ke_note():
    """Idempotence: re-running must not churn a #1202ke note, which is how #1202jn read as
    motion. (A response_key note may still appear the first time -- see the test above for why
    that derivation deliberately stays.)"""
    out, notes = _norm({"backend": {"api_endpoints": [
        {"method": "POST", "path": "/auth/login",
         "auth_required": False, "response_key": "access_token"},
    ]}})
    assert out["backend"]["api_endpoints"][0]["auth_required"] is False
    assert not notes


# --- one rule, one implementation ------------------------------------------------------------

def test_both_call_sites_share_the_one_helper():
    """#1202gt/gu/gw were all 'one fact, two implementations'. Both must route through
    `fixed_surface_1202ke`, so neither can drift from the framework's declarations."""
    import inspect
    from multi_agent.runtime.kickoff import run_kickoff as RK
    from multi_agent.runtime.kickoff import contract as C
    assert "fixed_surface_1202ke()" in inspect.getsource(
        RK._normalize_backend_endpoints_for_reconcile)
    assert "fixed_surface_1202ke()" in inspect.getsource(
        C.normalize_to_registryhub_endpoint)
