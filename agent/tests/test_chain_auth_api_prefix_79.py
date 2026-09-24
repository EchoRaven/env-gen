"""FIX #79 — /api-prefixed auth steps must get the same auth coercions as un-prefixed ones.

instagram-core opt6 aborted (75-min NO-CONVERGENCE, business_chain_failing): the registered
`auth_and_profile` chain had a body-less `POST /api/auth/register` step (body=null). The
framework register (mounted at BOTH `/` and `/api`) 422'd "email and password are required" →
login 401 → users/me 404 → the chain failed every cycle. EVERY auth invariant in normalize_steps
(canonical-save, expect-union, body-default, ensure-user, auth-first reorder) keyed ONLY on the
un-prefixed `/auth/register|login`, so an `/api/`-prefixed auth step bypassed ALL of them — most
damagingly the body-default, leaving a body-less register that 422'd forever. #79 collapses
`/api/auth/register|login` → the canonical `/auth/*` form (same handler, mounted at both) so
every invariant applies uniformly. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402


def _auth_steps(steps, kind):  # kind in {"register","login"}
    return [s for s in steps
            if str(s.get("path") or "").rstrip("/").endswith("/auth/" + kind)]


def test_api_prefixed_bodyless_register_is_coerced():
    # the exact opt6 killer: POST /api/auth/register with no body
    steps, errors = normalize_steps([{"method": "POST", "path": "/api/auth/register"}])
    assert errors == []
    regs = _auth_steps(steps, "register")
    assert regs, steps
    r = regs[0]
    assert str(r["path"]).rstrip("/") == "/auth/register"          # collapsed to canonical
    assert r["body"].get("email") and r["body"].get("password")    # body-default fired
    assert 201 in r["expect"]                                      # expect-union fired
    assert (r.get("save") or {}).get("token") == "access_token"    # canonical-save fired
    # INVARIANT: no auth step is left body-less (what caused the 422)
    for s in steps:
        p = str(s.get("path") or "").rstrip("/")
        if p.endswith("/auth/register") or p.endswith("/auth/login"):
            assert s.get("body"), s


def test_api_prefixed_bodyless_login_is_coerced():
    steps, _ = normalize_steps([{"method": "POST", "path": "/api/auth/login"}])
    logins = _auth_steps(steps, "login")
    assert logins
    lb = logins[0]["body"]
    assert lb.get("email") and lb.get("password") and "name" not in lb  # login body carries no name
    # ensure-user-before-login synthesizes a register ahead of the login
    regs = _auth_steps(steps, "register")
    assert regs and steps.index(regs[0]) < steps.index(logins[0])


def test_api_prefixed_authored_body_not_clobbered():
    steps, _ = normalize_steps([{"method": "POST", "path": "/api/auth/register",
                                 "body": {"email": "a@b.io", "password": "p"}}])
    r = _auth_steps(steps, "register")[0]
    assert r["body"] == {"email": "a@b.io", "password": "p"}        # authored body preserved


def test_unprefixed_register_still_works():  # regression
    steps, _ = normalize_steps([{"method": "POST", "path": "/auth/register"}])
    r = _auth_steps(steps, "register")[0]
    assert r["body"].get("email") and 201 in r["expect"]


def test_plain_api_resource_step_gets_no_auth_body():
    steps, _ = normalize_steps([{"method": "GET", "path": "/api/posts"}])
    gets = [s for s in steps if s.get("method") == "GET" and "/api/posts" in s.get("path", "")]
    assert gets and not gets[0].get("body")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
