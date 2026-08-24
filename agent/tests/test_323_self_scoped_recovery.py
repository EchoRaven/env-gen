"""#323 part B — owner-scoped self-view recovery (r92 M3 NO-CONVERGENCE, 75min abort).

The verifier authored ``GET /api/users/Owner/favorites`` (and .../liked) as a stand-in for
"the current user's list". The contract declares ``/api/users/{username}/favorites`` and the
generated handler is OWNER-ONLY:

  * 404 "user not found"  when the path value is not a real user  ("Owner")
  * 403 "not authorized"  when the caller != the profile owner    (any OTHER user)
  * 200                    only when the caller IS the owner        (SELF)

#245's recovery picked a DIFFERENT user (``avoid=own_user_id``) → 403 forever → business_chain
never went green → api_smoke validation never recorded → run aborted. Both blockers
(business_chain_failing + validation_api_smoke_missing) were this ONE step.

Part A (test_323_middle_param_recovery) fixed the MIDDLE-segment template match. Part B makes
the recovery target the chain user's OWN identity for a self-alias literal, and keep SELF as a
fallback whenever a recovered other-user 403s an owner-scoped resource. ENV-AGNOSTIC.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402

EPS = [
    {"path": "/auth/register"},
    {"path": "/api/users/{username}"},
    {"path": "/api/users/{username}/favorites"},
    {"path": "/api/users/{username}/liked"},
]


# ---- unit: helpers ----

def test_self_alias_set_covers_owner_and_me():
    for a in ("owner", "Owner", "ME", "self", "current_user"):
        assert a.strip().lower() in ce._SELF_ALIAS


def test_extract_own_username_toplevel_and_nested():
    assert ce._extract_own_username({"id": 1, "username": "alice"}) == "alice"
    assert ce._extract_own_username({"user": {"handle": "bob"}}) == "bob"
    assert ce._extract_own_username({"id": 1}) is None


# ---- integration: the live r92 wedge ----

def _owner_scoped_server(calls, own_username):
    """favorites is owner-only: 404 unknown user, 403 non-owner, 200 self."""
    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201,
                    "body_text": '{"id":24,"username":"%s","access_token":"t"}' % own_username}
        if url.endswith("/api/users") and method == "GET":
            # a DIFFERENT real user exists (mallory) — #245 would pick this and 403
            return {"status": 200,
                    "body_text": '{"items":[{"username":"mallory"},{"username":"%s"}]}' % own_username}
        if method == "GET" and "/favorites" in url:
            seg = url.split("?", 1)[0].split("/")
            who = seg[seg.index("users") + 1]
            if who not in ("mallory", own_username):
                return {"status": 404, "body_text": '{"detail":"user not found"}'}
            if who != own_username:
                return {"status": 403, "body_text": '{"detail":"not authorized to view this list"}'}
            return {"status": 200, "body_text": '{"items":[],"total":0,"next_cursor":null}'}
        return {"status": 404, "body_text": "{}"}
    return fake_http


def test_owner_literal_recovers_to_self_not_another_user(monkeypatch):
    calls = []
    monkeypatch.setattr(ce, "_http", _owner_scoped_server(calls, "chainuser42"))
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/users/Owner/favorites?sort=latest&cursor=0&limit=10",
         "auth": "token", "expect": [200]}]}, endpoints=EPS)
    assert out["broken"] == [], out["broken"]
    # recovered to SELF, and the querystring is preserved
    assert any(u.endswith("/api/users/chainuser42/favorites?sort=latest&cursor=0&limit=10")
               for (_m, u) in calls), calls
    # the invented literal never counts as a pass
    assert not any("/users/Owner/" in u for (_m, u) in calls
                   if u.endswith("/favorites"))


def test_non_alias_literal_falls_back_to_self_after_403(monkeypatch):
    """A non-obvious literal ("ProfileOwner") isn't in _SELF_ALIAS, so recovery tries the
    OTHER real user first (mallory) → 403 owner-scoped → must then retry SELF → 200."""
    calls = []
    monkeypatch.setattr(ce, "_http", _owner_scoped_server(calls, "chainuser42"))
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/users/ProfileOwner/liked",
         "auth": "token", "expect": [200]}]}, endpoints=EPS)
    assert out["broken"] == [], out["broken"]
    assert any(u.endswith("/api/users/chainuser42/liked") for (_m, u) in calls), calls


def test_public_profile_prefers_a_real_other_user(monkeypatch):
    """A PUBLIC by-username GET (not owner-scoped) must still recover a real OTHER user —
    the self-first behaviour is reserved for self-alias literals, so ordinary bad usernames
    keep resolving to real collection rows (the #245 win, unregressed)."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text": '{"id":24,"username":"chainuser42","access_token":"t"}'}
        if url.endswith("/api/users") and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"username":"mallory"}]}'}
        if url.endswith("/api/users/mallory") and method == "GET":
            return {"status": 200, "body_text": '{"username":"mallory","bio":"hi"}'}
        return {"status": 404, "body_text": '{"detail":"user not found"}'}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/users/Ghost", "auth": "token", "expect": [200]}]},
        endpoints=[{"path": "/auth/register"}, {"path": "/api/users/{username}"}])
    assert out["broken"] == [], out["broken"]
    assert any(u.endswith("/api/users/mallory") for (_m, u) in calls), calls
