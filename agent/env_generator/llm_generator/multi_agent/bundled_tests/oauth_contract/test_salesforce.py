"""Minimum 8-test OAuth contract for the Salesforce sandbox env.

Spec: `.claude/skills/env-oauth-blueprint/SKILL.md`. Adapted for the
bridge topology — salesforce_auth sits in front of SuiteCRM, owns no
users, and has no /auth/register surface.

Run:
    docker compose up -d   (from src/envs/salesforce_crm)
    SALESFORCE_AUTH_URL=http://localhost:8036 \
    SALESFORCE_USERNAME=admin SALESFORCE_PASSWORD=password \
    python3 tests/oauth/test_salesforce.py
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

AUTH = os.getenv("SALESFORCE_AUTH_URL", "http://localhost:8036")
SF_USERNAME = os.getenv("SALESFORCE_USERNAME", "admin")
SF_PASSWORD = os.getenv("SALESFORCE_PASSWORD", "password")
EXPECTED_AUDIENCE = os.getenv("SALESFORCE_EXPECTED_AUDIENCE", "salesforce-api")


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


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _login_jwt() -> str:
    """JSON shortcut: /auth/login → JWT."""
    r = requests.post(
        f"{AUTH}/auth/login",
        json={"email": SF_USERNAME, "password": SF_PASSWORD, "tenant_id": "default"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_and_discovery() -> None:
    h = requests.get(f"{AUTH}/health")
    _assert(h.status_code == 200, f"/health {h.status_code}")
    d = requests.get(f"{AUTH}/.well-known/oauth-authorization-server")
    _assert(d.status_code == 200, f"discovery {d.status_code}")
    body = d.json()
    _assert("salesforce.read" in body["scopes_supported"], "scopes_supported missing salesforce.read")
    _assert("salesforce.write" in body["scopes_supported"], "scopes_supported missing salesforce.write")
    _assert(body["code_challenge_methods_supported"] == ["S256"], "PKCE S256 advertised")
    _assert(body["id_token_signing_alg_values_supported"] == ["RS256"], "RS256 advertised")
    _record("health + discovery", True)


def test_auth_login_returns_jwt() -> None:
    """Blueprint /auth/login JSON shortcut returns a properly shaped JWT."""
    r = requests.post(
        f"{AUTH}/auth/login",
        json={"email": SF_USERNAME, "password": SF_PASSWORD, "tenant_id": "default"},
    )
    _assert(r.status_code == 200, f"login {r.status_code}: {r.text[:200]}")
    body = r.json()
    _assert(body["token_type"] == "Bearer", "token_type")
    _assert(body.get("access_token"), "missing access_token")

    claims = _jwt_claims(body["access_token"])
    _assert(claims["tenant_id"] == "default", "tenant_id claim")
    _assert(claims["email"] == SF_USERNAME, "email claim")
    _assert(EXPECTED_AUDIENCE in claims["aud"], f"aud includes {EXPECTED_AUDIENCE}")
    _assert(isinstance(claims["aud"], list), "aud is array (blueprint)")
    _assert("salesforce.read" in claims["scope"].split(), "scope includes salesforce.read")
    _assert(claims.get("jti"), "jti present")
    _assert(claims.get("sf_token"), "sf_token claim present (bridge wraps SuiteCRM token)")
    _record("/auth/login → blueprint JWT", True)


def test_oauth_dance_end_to_end() -> None:
    """Full DCR → /authorize → /token (PKCE + resource indicator)."""
    md = requests.get(f"{AUTH}/.well-known/oauth-authorization-server").json()

    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "test-suite", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]

    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(8)
    form = {
        "client_id": client_id,
        "redirect_uri": "http://localhost:0/cb",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "salesforce.read salesforce.write",
        "username": SF_USERNAME,
        "password": SF_PASSWORD,
    }
    r = requests.post(md["authorization_endpoint"], data=form, allow_redirects=False)
    _assert(r.status_code == 303, f"/oauth/authorize → {r.status_code}: {r.text[:200]}")
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
    _assert(claims["client_id"] == client_id, "client_id claim")
    _assert(claims.get("sf_token"), "sf_token claim wraps SuiteCRM token")
    _record("OAuth dance (DCR + /authorize + /token + PKCE)", True)


def test_login_wrong_password_rejected() -> None:
    r = requests.post(
        f"{AUTH}/auth/login",
        json={"email": SF_USERNAME, "password": "wrong-bad-password", "tenant_id": "default"},
    )
    _assert(r.status_code == 401, f"wrong password: {r.status_code}")
    _record("/auth/login wrong password → 401", True)


def test_authorize_pkce_required() -> None:
    """Blueprint hard-requires S256 PKCE — anything else must 400."""
    md = requests.get(f"{AUTH}/.well-known/oauth-authorization-server").json()
    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "pkce-test", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]
    r = requests.get(
        md["authorization_endpoint"],
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://localhost:0/cb",
            # no code_challenge
        },
    )
    _assert(r.status_code == 400, f"missing PKCE: {r.status_code}")
    _record("missing PKCE → 400", True)


def test_authorize_invalid_redirect_rejected() -> None:
    md = requests.get(f"{AUTH}/.well-known/oauth-authorization-server").json()
    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "redir-test", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]
    _, challenge = _pkce()
    r = requests.get(
        md["authorization_endpoint"],
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://evil.example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    _assert(r.status_code == 400, f"invalid redirect: {r.status_code}")
    _record("invalid redirect_uri → 400", True)


def test_authorization_code_single_use() -> None:
    """A successfully consumed code must not be reusable."""
    md = requests.get(f"{AUTH}/.well-known/oauth-authorization-server").json()
    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "single-use", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]

    verifier, challenge = _pkce()
    r = requests.post(
        md["authorization_endpoint"],
        data={
            "client_id": client_id,
            "redirect_uri": "http://localhost:0/cb",
            "state": "x",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "salesforce.read",
            "username": SF_USERNAME,
            "password": SF_PASSWORD,
        },
        allow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://localhost:0/cb",
        "client_id": client_id,
        "code_verifier": verifier,
    }
    first = requests.post(md["token_endpoint"], data=body).json()
    _assert(first.get("access_token"), f"first exchange: {first}")
    second = requests.post(md["token_endpoint"], data=body)
    _assert(second.status_code == 400, f"reuse: {second.status_code}")
    _assert(second.json().get("error") == "invalid_grant", "error code on reuse")
    _record("auth code single-use", True)


def test_pkce_wrong_verifier_rejected() -> None:
    md = requests.get(f"{AUTH}/.well-known/oauth-authorization-server").json()
    reg = requests.post(
        md["registration_endpoint"],
        json={"client_name": "pkce-wrong", "redirect_uris": ["http://localhost:0/cb"]},
    ).json()
    client_id = reg["client_id"]

    verifier, challenge = _pkce()
    r = requests.post(
        md["authorization_endpoint"],
        data={
            "client_id": client_id,
            "redirect_uri": "http://localhost:0/cb",
            "state": "x",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "salesforce.read",
            "username": SF_USERNAME,
            "password": SF_PASSWORD,
        },
        allow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    r = requests.post(
        md["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:0/cb",
            "client_id": client_id,
            "code_verifier": verifier + "tampered",
        },
    )
    _assert(r.status_code == 400, f"wrong verifier: {r.status_code}")
    _assert(r.json().get("error") == "invalid_grant", "error code on bad PKCE")
    _record("wrong PKCE verifier → invalid_grant", True)


def test_jwks_exposes_signing_key() -> None:
    j = requests.get(f"{AUTH}/.well-known/jwks.json").json()
    _assert(len(j.get("keys", [])) >= 1, "jwks has at least one key")
    k = j["keys"][0]
    _assert(k["alg"] == "RS256", "alg=RS256")
    _assert(k["kty"] == "RSA", "kty=RSA")
    _assert(k.get("kid"), "kid present")
    _record("JWKS exposes RS256 key", True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_health_and_discovery,
    test_jwks_exposes_signing_key,
    test_auth_login_returns_jwt,
    test_login_wrong_password_rejected,
    test_authorize_pkce_required,
    test_authorize_invalid_redirect_rejected,
    test_oauth_dance_end_to_end,
    test_authorization_code_single_use,
    test_pkce_wrong_verifier_rejected,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except AssertionError as e:
            RESULTS.append(Result(fn.__name__, False, str(e)))
        except Exception as e:
            RESULTS.append(Result(fn.__name__, False, f"{type(e).__name__}: {e}"))

    if not RESULTS:
        print("no tests ran")
        return 1
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
