"""chain_executor: guarantee a working register->login auth round-trip even when
the verifier mis-authors it (observed live on smoke-notes, 2026-06-20).

Two real slips from the run, both → POST /auth/login 401 "invalid credentials" →
business_chain fails 6/6 → milestone never delivers:
  1. The chain registers via /oauth/register — RFC-7591 OAuth CLIENT registration
     (needs redirect_uris, returns client_id, creates NO user) — not the user
     endpoint /auth/register. The user never exists, so login 401s.
  2. The chain authored POST /auth/login BEFORE the register step. The old
     auth-first reorder gave register and login the SAME sort key, so a stable
     sort preserved the login-first order.

normalize_steps now (a) repoints an /oauth/register step carrying user creds to
/auth/register, (b) strictly orders register before login, and (c) synthesizes a
register (with the login's own creds) when a login step has none.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402


def _paths(steps):
    return [s["path"].rstrip("/") for s in steps]


def test_oauth_register_with_user_creds_is_repointed_to_auth_register():
    steps, errs = normalize_steps([
        {"method": "POST", "path": "/auth/login",
         "body": {"email": "test_${rand}@example.com", "password": "password123"},
         "save": {"token": "access_token"}, "expect": [200]},
        {"method": "POST", "path": "/oauth/register",
         "body": {"name": "Test", "email": "test_${rand}@example.com",
                  "password": "password123"}, "expect": [200, 201]},
    ])
    assert errs == [], errs
    # /oauth/register repointed to /auth/register AND ordered first.
    assert _paths(steps) == ["/auth/register", "/auth/login"]
    # the synthesized/repointed register carries the login's exact creds
    reg = steps[0]
    assert reg["body"]["email"] == "test_${rand}@example.com"
    assert reg["body"]["password"] == "password123"


def test_login_before_register_is_reordered_register_first():
    # both are real /auth/* endpoints but authored login-first.
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/login",
         "body": {"email": "u${rand}@x.com", "password": "pw"}, "expect": [200]},
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u${rand}@x.com", "password": "pw"}, "expect": [201]},
    ])
    assert _paths(steps) == ["/auth/register", "/auth/login"]


def test_login_with_no_register_synthesizes_one_with_login_creds():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/login",
         "body": {"email": "solo_${rand}@x.com", "password": "secret"},
         "expect": [200]},
    ])
    assert _paths(steps) == ["/auth/register", "/auth/login"]
    assert steps[0]["body"]["email"] == "solo_${rand}@x.com"
    assert steps[0]["body"]["password"] == "secret"
    assert steps[0]["save"].get("token") == "access_token"


def test_real_oauth_client_registration_is_not_repointed():
    # a genuine OAuth client registration (redirect_uris, no user creds) must be
    # left alone — it is NOT user registration.
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/oauth/register",
         "body": {"client_name": "app", "redirect_uris": ["http://x/cb"]},
         "expect": [201]},
    ])
    assert _paths(steps) == ["/oauth/register"]


def test_register_then_login_order_preserved_when_already_correct():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "a${rand}@x.com", "password": "pw"}, "expect": [201]},
        {"method": "POST", "path": "/auth/login",
         "body": {"email": "a${rand}@x.com", "password": "pw"}, "expect": [200]},
        {"method": "GET", "path": "/api/notes", "expect": [200], "auth": "token"},
    ])
    assert _paths(steps) == ["/auth/register", "/auth/login", "/api/notes"]


def test_api_steps_stay_after_auth_in_authored_order():
    # manage_notes shape: login, oauth/register(user creds), then API steps.
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/login",
         "body": {"email": "n${rand}@x.com", "password": "pw"}, "expect": [200]},
        {"method": "POST", "path": "/oauth/register",
         "body": {"email": "n${rand}@x.com", "password": "pw"}, "expect": [201]},
        {"method": "POST", "path": "/api/notes", "body": {"title": "t"},
         "expect": [201], "save": {"note_id": "id"}, "auth": "token"},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [200],
         "auth": "token"},
    ])
    # #192a may APPEND a framework isolation probe (+ its intruder register) —
    # the guarantee here is the RELATIVE ORDER of the authored steps, so assert
    # the expected sequence as a subsequence of the normalized paths.
    expected = ["/auth/register", "/auth/login",
                "/api/notes", "/api/notes/${note_id}"]
    got = _paths(steps)
    it = iter(got)
    assert all(p in it for p in expected), f"order broken: {got}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
