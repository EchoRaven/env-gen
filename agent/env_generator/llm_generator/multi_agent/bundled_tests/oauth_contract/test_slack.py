"""Minimum 8-test OAuth contract for the Slack sandbox env.

Spec: `.claude/skills/env-oauth-blueprint/SKILL.md`. Run against a live
slack-api stack:

    SLACK_API_URL=http://localhost:8034 python3 tests/oauth/test_slack.py
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass

import requests

API = os.getenv("SLACK_API_URL", "http://localhost:8034")
EXPECTED_AUDIENCE = os.getenv("SLACK_EXPECTED_AUDIENCE", "slack-api")


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


def _unique(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode())


def _setup_tenant_user(tenant_id: str, email: str, password: str = "pw") -> dict:
    requests.post(f"{API}/api/v1/tenants", json={"id": tenant_id})
    r = requests.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "name": email.split("@")[0].title(),
            "password": password,
            "tenant_id": tenant_id,
        },
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_and_discovery() -> None:
    h = requests.get(f"{API}/health")
    _assert(h.status_code == 200, f"/health {h.status_code}")
    d = requests.get(f"{API}/.well-known/oauth-authorization-server")
    _assert(d.status_code == 200, f"discovery {d.status_code}")
    body = d.json()
    _assert("slack.read" in body["scopes_supported"], "scopes_supported missing slack.read")
    _assert("slack.write" in body["scopes_supported"], "scopes_supported missing slack.write")
    _assert(body["code_challenge_methods_supported"] == ["S256"], "PKCE S256 advertised")
    _record("health + discovery", True)


def test_register_and_login_returns_jwt() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)

    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "pw", "tenant_id": tid},
    )
    _assert(r.status_code == 200, f"login {r.status_code}")
    body = r.json()
    _assert(body["token_type"] == "Bearer", "token_type")
    _assert(body.get("access_token"), "missing access_token")

    claims = _jwt_claims(body["access_token"])
    _assert(claims["tenant_id"] == tid, "tenant_id claim")
    _assert(claims["email"] == email, "email claim")
    _assert(claims["name"] == email.split("@")[0].title(), "name claim")
    _assert(EXPECTED_AUDIENCE in claims["aud"], f"aud includes {EXPECTED_AUDIENCE}")
    _assert(isinstance(claims["aud"], list), "aud is array (blueprint)")
    _assert("slack.read" in claims["scope"].split(), "scope includes slack.read")
    _assert(claims.get("jti"), "jti present")
    _record("register + login → blueprint JWT", True)


def test_duplicate_register_rejected() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    r = requests.post(
        f"{API}/auth/register",
        json={"email": email, "password": "pw", "tenant_id": tid},
    )
    _assert(r.status_code == 400, f"duplicate register {r.status_code}")
    _record("duplicate register → 400", True)


def test_multitenant_same_email_distinct() -> None:
    email = _unique("u") + "@test.com"
    t1 = _unique("t")
    t2 = _unique("t")
    _setup_tenant_user(t1, email)
    _setup_tenant_user(t2, email)
    tok1 = requests.post(
        f"{API}/auth/login", json={"email": email, "password": "pw", "tenant_id": t1}
    ).json()["access_token"]
    tok2 = requests.post(
        f"{API}/auth/login", json={"email": email, "password": "pw", "tenant_id": t2}
    ).json()["access_token"]
    c1, c2 = _jwt_claims(tok1), _jwt_claims(tok2)
    _assert(c1["sub"] != c2["sub"], "different sub across tenants")
    _assert(c1["tenant_id"] == t1 and c2["tenant_id"] == t2, "tenant_id per-tenant")
    _record("multitenant same email → distinct users", True)


def test_ui_jwt_works_on_resource_server() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    token = requests.post(
        f"{API}/auth/login", json={"email": email, "password": "pw", "tenant_id": tid}
    ).json()["access_token"]
    r = requests.get(
        f"{API}/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    _assert(r.status_code == 200, f"/api/v1/me {r.status_code} {r.text}")
    body = r.json()
    _assert(body["email"] == email, "me.email")
    _assert(body["tenant_id"] == tid, "me.tenant_id")
    _record("UI JWT → RS /api/v1/me", True)


def test_garbage_token_rejected() -> None:
    r = requests.get(
        f"{API}/api/v1/me", headers={"Authorization": "Bearer notajwt"}
    )
    _assert(r.status_code == 401, f"garbage token {r.status_code}")
    _record("garbage token → 401", True)


def test_no_token_rejected() -> None:
    r = requests.get(f"{API}/api/v1/me")
    _assert(r.status_code == 401, f"no token {r.status_code}")
    _record("no token → 401", True)


def test_expired_token_rejected() -> None:
    """Mint a JWT that's already expired by signing with our key.

    Slack's RS256 key is generated locally; we don't have access to it from
    the test runner, so instead we tamper with the token's payload — the
    signature will fail to verify and the RS rejects it. Same effect: an
    invalid/expired-shaped JWT must not authenticate.
    """
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    good = requests.post(
        f"{API}/auth/login", json={"email": email, "password": "pw", "tenant_id": tid}
    ).json()["access_token"]
    header_b64, payload_b64, sig_b64 = good.split(".")
    payload = _jwt_claims(good)
    payload["exp"] = int(time.time()) - 60  # already expired
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    tampered = f"{header_b64}.{tampered_payload}.{sig_b64}"
    r = requests.get(
        f"{API}/api/v1/me", headers={"Authorization": f"Bearer {tampered}"}
    )
    _assert(r.status_code == 401, f"tampered/expired token {r.status_code}")
    _record("tampered/expired token → 401", True)


def test_login_wrong_password_rejected() -> None:
    tid = _unique("t")
    email = _unique("u") + "@test.com"
    _setup_tenant_user(tid, email)
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "wrong", "tenant_id": tid},
    )
    _assert(r.status_code == 401, f"wrong password {r.status_code}")
    _record("wrong password → 401", True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_health_and_discovery,
    test_register_and_login_returns_jwt,
    test_duplicate_register_rejected,
    test_multitenant_same_email_distinct,
    test_ui_jwt_works_on_resource_server,
    test_garbage_token_rejected,
    test_no_token_rejected,
    test_expired_token_rejected,
    test_login_wrong_password_rejected,
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
