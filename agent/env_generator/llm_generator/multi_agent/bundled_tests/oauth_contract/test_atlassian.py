"""Minimum 8-test OAuth contract for the Atlassian sandbox env.

Spec: `.claude/skills/env-oauth-blueprint/SKILL.md`. Run against a live
atlassian-api stack:

    docker compose up -d   (from src/envs/atlassian)
    ATLASSIAN_API_URL=http://localhost:8040 python3 tests/oauth/test_atlassian.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests

API = os.getenv("ATLASSIAN_API_URL", "http://localhost:8040")
EXPECTED_AUDIENCE = os.getenv("ATLASSIAN_EXPECTED_AUDIENCE", "atlassian-api")


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


RESULTS: list[Result] = []


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(Result(name, ok, detail))


def _jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode())


def _unique(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _setup_tenant_user(tenant_id: str, email: str, password: str = "pw") -> dict:
    r = requests.post(
        f"{API}/api/auth/register",
        json={
            "email": email,
            "name": email.split("@")[0].title(),
            "password": password,
        },
        headers={"X-Tenant-ID": tenant_id},
    )
    r.raise_for_status()
    return r.json()


def _login(email: str, password: str, tenant_id: str = "default") -> str:
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-Tenant-ID": tenant_id},
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_and_discovery() -> None:
    h = requests.get(f"{API}/health")
    _assert(h.status_code == 200, f"/health {h.status_code}")
    d = requests.get(f"{API}/.well-known/oauth-authorization-server")
    _assert(d.status_code == 200, f"discovery {d.status_code}")
    body = d.json()
    _assert("atlassian.read" in body["scopes_supported"], "scopes_supported missing atlassian.read")
    _assert("atlassian.write" in body["scopes_supported"], "scopes_supported missing atlassian.write")
    _assert(body["code_challenge_methods_supported"] == ["S256"], "PKCE S256 advertised")
    _record("health + discovery", True)


def test_jwks_exposes_signing_key() -> None:
    j = requests.get(f"{API}/.well-known/jwks.json").json()
    _assert(len(j.get("keys", [])) >= 1, "jwks has at least one key")
    k = j["keys"][0]
    _assert(k["alg"] == "RS256", "alg=RS256")
    _assert(k["kty"] == "RSA", "kty=RSA")
    _assert(k.get("kid"), "kid present")
    _record("JWKS exposes RS256 key", True)


def test_register_and_login_returns_jwt() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)

    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": email, "password": "pw"},
        headers={"X-Tenant-ID": tid},
    )
    _assert(r.status_code == 200, f"login {r.status_code}: {r.text[:200]}")
    body = r.json()
    _assert(body["token_type"] == "Bearer", "token_type")
    _assert(body.get("access_token"), "missing access_token")

    claims = _jwt_claims(body["access_token"])
    _assert(claims["tenant_id"] == tid, "tenant_id claim")
    _assert(claims["email"] == email, "email claim")
    _assert(claims["name"] == email.split("@")[0].title(), "name claim")
    _assert(EXPECTED_AUDIENCE in claims["aud"], f"aud includes {EXPECTED_AUDIENCE}")
    _assert(isinstance(claims["aud"], list), "aud is array (blueprint)")
    _assert("atlassian.read" in claims["scope"].split(), "scope includes atlassian.read")
    _assert(claims.get("jti"), "jti present")
    _record("register + login → blueprint JWT", True)


def test_duplicate_register_rejected() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    r = requests.post(
        f"{API}/api/auth/register",
        json={"email": email, "name": "Dup", "password": "pw"},
        headers={"X-Tenant-ID": tid},
    )
    _assert(r.status_code == 400, f"duplicate register {r.status_code}")
    _record("duplicate register → 400", True)


def test_multitenant_same_email_distinct() -> None:
    email = _unique("u") + "@test.com"
    t1 = _unique("t")
    t2 = _unique("t")
    _setup_tenant_user(t1, email)
    _setup_tenant_user(t2, email)
    tok1 = _login(email, "pw", tenant_id=t1)
    tok2 = _login(email, "pw", tenant_id=t2)
    c1, c2 = _jwt_claims(tok1), _jwt_claims(tok2)
    _assert(c1["sub"] != c2["sub"], "different sub across tenants")
    _assert(c1["tenant_id"] == t1 and c2["tenant_id"] == t2, "tenant_id per-tenant")
    _record("multitenant same email → distinct users", True)


def test_jwt_works_against_auth_me() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    token = _login(email, "pw", tenant_id=tid)
    r = requests.get(f"{API}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    _assert(r.status_code == 200, f"/api/auth/me {r.status_code} {r.text[:200]}")
    body = r.json()
    _assert(body["email"] == email, "me.email")
    _assert(body["tenantId"] == tid, "me.tenantId")
    _record("UI JWT → /api/auth/me", True)


def test_garbage_token_rejected() -> None:
    r = requests.get(f"{API}/api/auth/me", headers={"Authorization": "Bearer notajwt"})
    _assert(r.status_code == 401, f"garbage token {r.status_code}")
    _record("garbage token → 401", True)


def test_no_token_rejected() -> None:
    r = requests.get(f"{API}/api/auth/me")
    _assert(r.status_code == 401, f"no token {r.status_code}")
    _record("no token → 401", True)


def test_tampered_token_rejected() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    good = _login(email, "pw", tenant_id=tid)
    header_b64, payload_b64, sig_b64 = good.split(".")
    payload = _jwt_claims(good)
    payload["exp"] = int(time.time()) - 60
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    tampered = f"{header_b64}.{tampered_payload}.{sig_b64}"
    r = requests.get(f"{API}/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    _assert(r.status_code == 401, f"tampered token {r.status_code}")
    _record("tampered/expired token → 401", True)


def test_login_wrong_password_rejected() -> None:
    """Pre-existing bug fixed in this refactor: /api/auth/login now actually
    checks the password against password_hash."""
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": email, "password": "wrong"},
        headers={"X-Tenant-ID": tid},
    )
    _assert(r.status_code == 401, f"wrong password {r.status_code}")
    _record("wrong password → 401", True)


def test_seeded_user_can_login() -> None:
    """alice@example.com / 'password' was seeded by seed.sql; login should
    work end-to-end against the seeded sha256+salt password_hash."""
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": "alice@example.com", "password": "password"},
    )
    _assert(r.status_code == 200, f"alice login {r.status_code}: {r.text[:200]}")
    body = r.json()
    _assert(body.get("access_token"), "alice JWT issued")
    claims = _jwt_claims(body["access_token"])
    _assert("atlassian.admin" in claims["scope"].split(), "alice admin scope (system_admin role)")
    _record("seeded admin login + admin scope", True)


def test_oauth_dance_end_to_end() -> None:
    """Full DCR → /authorize → /token (PKCE + resource indicator)."""
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)

    md = requests.get(f"{API}/.well-known/oauth-authorization-server").json()
    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "test-suite", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(8)
    form = {
        "client_id": client_id,
        "redirect_uri": "http://localhost:0/cb",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "atlassian.read atlassian.write",
        "tenant_id": tid,
        "email": email,
        "password": "pw",
    }
    r = requests.post(md["authorization_endpoint"], data=form, allow_redirects=False)
    _assert(r.status_code == 303, f"/oauth/authorize {r.status_code}: {r.text[:200]}")
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    custom_aud = "test-resource-aud"
    tok = requests.post(
        md["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:0/cb",
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": custom_aud,
        },
    ).json()
    _assert(tok.get("access_token"), f"/oauth/token: {tok}")

    claims = _jwt_claims(tok["access_token"])
    _assert(custom_aud in claims["aud"], "aud reflects RFC 8707 resource indicator")
    _assert(claims["tenant_id"] == tid, "tenant_id from authorize step survives")
    _assert(claims["client_id"] == client_id, "client_id claim")
    _record("OAuth dance (DCR + /authorize + /token + PKCE)", True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_health_and_discovery,
    test_jwks_exposes_signing_key,
    test_register_and_login_returns_jwt,
    test_duplicate_register_rejected,
    test_multitenant_same_email_distinct,
    test_jwt_works_against_auth_me,
    test_garbage_token_rejected,
    test_no_token_rejected,
    test_tampered_token_rejected,
    test_login_wrong_password_rejected,
    test_seeded_user_can_login,
    test_oauth_dance_end_to_end,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except AssertionError as e:
            RESULTS.append(Result(fn.__name__, False, str(e)))
        except Exception as e:
            RESULTS.append(Result(fn.__name__, False, f"{type(e).__name__}: {e}"))

    width = max(len(r.name) for r in RESULTS) + 2
    for r in RESULTS:
        flag = "PASS" if r.ok else "FAIL"
        print(f"{r.name:<{width}} {flag}")
        if not r.ok and r.detail:
            print(f"    -> {r.detail}")
    fails = sum(1 for r in RESULTS if not r.ok)
    print(f"\n{len(RESULTS) - fails}/{len(RESULTS)} passed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
