"""FIX #81 — ACTION-SUFFIX by-id paths are invisible to the placeholder-resolution ladder
(instagram-core-di run, 2026-07-05 live).

The verifier authored `POST /api/posts/${post_id}/like` / `POST /api/users/${author_id}/follow`
with no capture. `_collection_path_of` only strips a TRAILING placeholder segment, so for a
mid-path placeholder the collection stays parametrised → list/create recovery is guard-skipped →
the step falls to the GLOBAL last_id (the chain user's OWN id from /auth/register → follow
YOURSELF → 400 "cannot follow yourself") or, when register 409'd (no capture), the LITERAL
`${post_id}` reaches the int path param → 422 int_parsing. business_chain wedged ~25 min live on
a functionally-correct app. Fixes: (A) truncate the collection path at the FIRST placeholder
segment (also fixes nested collections `/api/events/${event_id}/attendees`); (B) list recovery
takes `avoid` = the chain user's own registered id so a users-collection action never targets
SELF when another row exists. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def test_collection_path_truncates_at_first_placeholder():
    # action-suffix shape (the live wedge)
    assert ce._collection_path_of("/api/posts/${post_id}/like") == "/api/posts"
    assert ce._collection_path_of("/api/users/${author_id}/follow") == "/api/users"
    # nested-collection shape (same class)
    assert ce._collection_path_of("/api/events/${event_id}/attendees") == "/api/events"
    # trailing shapes unchanged
    assert ce._collection_path_of("/api/messages/${message_id}") == "/api/messages"
    assert ce._collection_path_of("/api/messages/{id}") == "/api/messages"
    assert ce._collection_path_of("/api/messages/:id") == "/api/messages"
    # no placeholder → untouched
    assert ce._collection_path_of("/api/messages/search") == "/api/messages/search"
    assert ce._collection_path_of("/api/messages") == "/api/messages"


def test_action_step_placeholder_recovers_via_collection_list(monkeypatch):
    """live symptom 2: register 409s (nothing captured) → ${post_id} must recover from the
    posts list, NOT reach the URL as a literal (422) and NOT abort the chain."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 409, "body_text": '{"detail":"exists"}'}   # no id captured
        if url.endswith("/api/posts") and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":7,"caption":"seed"}]}'}
        if url.endswith("/api/posts/7/like") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":70}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "POST", "path": "/api/posts/${post_id}/like", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert not any("${post_id}" in u for (_m, u) in calls)     # literal never sent
    assert any(u.endswith("/api/posts/7/like") for (_m, u) in calls)


def test_users_action_avoids_the_chain_users_own_id(monkeypatch):
    """live symptom 1: ${author_id} resolved to the caller's OWN registered id →
    400 'You cannot follow yourself'. Recovery must prefer a row that is NOT the chain user."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text": '{"id":24,"token":"t"}'}   # own id = 24
        if url.endswith("/api/users") and method == "GET":
            # the chain user is FIRST in the list — naive first-row pick would self-follow
            return {"status": 200, "body_text": '{"items":[{"id":24},{"id":3}]}'}
        if url.endswith("/api/users/3/follow") and method == "POST":
            return {"status": 201, "body_text": '{"ok":true}'}
        if url.endswith("/api/users/24/follow") and method == "POST":
            return {"status": 400, "body_text": '{"detail":"You cannot follow yourself"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "POST", "path": "/api/users/${author_id}/follow", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert any(u.endswith("/api/users/3/follow") for (_m, u) in calls)      # not self
    assert not any(u.endswith("/api/users/24/follow") for (_m, u) in calls)


def test_recover_id_via_list_avoid_falls_back_to_only_row(monkeypatch):
    """avoid must not turn a single-row collection into a None (a self-row beats a literal)."""
    monkeypatch.setattr(ce, "_http",
                        lambda *a, **k: {"status": 200, "body_text": '{"items":[{"id":24}]}'})
    assert ce._recover_id_via_list("http://x", "/api/users", "tok", avoid=24) == 24


def test_empty_brace_placeholder_recovers_via_list(monkeypatch):
    """FIX #89 (run-8 live): the verifier authored /api/posts/{}/like — python-format
    EMPTY braces. _UNRESOLVED_PLACEHOLDER required an alpha first char, so the whole
    recovery ladder was BLIND to {} and the literal hit the int param → 422 → 7-cycle
    wedge → STUCK at 06:06. {} and {0}-style digit placeholders must enter the ladder."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 409, "body_text": '{"detail":"exists"}'}
        if url.endswith("/api/posts") and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":7}]}'}
        if url.endswith("/api/posts/7/like") and method == "POST":
            return {"status": 201, "body_text": '{"ok":true}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "POST", "path": "/api/posts/{}/like", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert not any("/{}/" in u for (_m, u) in calls)
    assert any(u.endswith("/api/posts/7/like") for (_m, u) in calls)


def test_digit_brace_placeholder_also_recovers():
    assert ce._UNRESOLVED_PLACEHOLDER.search("/api/posts/{0}/like")
    assert ce._UNRESOLVED_PLACEHOLDER.search("/api/posts/{}")
    assert ce._collection_path_of("/api/posts/{}/like") == "/api/posts"


def test_pure_401_probe_strips_contradictory_auth(monkeypatch):
    """FIX #91 (run-11 live): the verifier authored an UNAUTHENTICATED-DENIAL probe
    (GET /api/feed expect [401]) WITH auth:'token' — self-contradictory: a valid token
    defeats its own expectation, the correct backend returns 200, and the chain wedges
    forever. A step expecting EXACTLY {401} is tokenless by definition → strip auth.
    (Cross-user denial probes expect 403/404 and keep their intruder token.)"""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, token))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text": '{"id":1,"access_token":"tok123"}'}
        if url.endswith("/api/feed") and method == "GET":
            if token:
                return {"status": 200, "body_text": '{"items":[{"id":1}]}'}
            return {"status": 401, "body_text": '{"detail":"missing or invalid token"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409], "save": {"token": "access_token"}},
        {"method": "GET", "path": "/api/feed", "auth": "token", "expect": [200]},
        {"method": "GET", "path": "/api/feed", "auth": "token", "expect": [401]}]})
    assert out["broken"] == [], out["broken"]
    feed_calls = [(u, t) for (m, u, t) in calls if u.endswith("/api/feed")]
    assert feed_calls[0][1] == "tok123"       # authed read keeps its token
    assert feed_calls[1][1] is None           # 401-probe sent WITHOUT the token


def _jwt_with_sub(sub):
    import base64, json as _j
    seg = lambda d: base64.urlsafe_b64encode(_j.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg':'RS256'})}.{seg({'sub': str(sub), 'aud': ['app-api']})}.sig"


def test_users_placeholder_last_resort_registers_aux_user(monkeypatch):
    """FIX #100 (run-18 live): register 409'd (no id), login carried no user object,
    NO /api/users collection exists, and the chain had no list step — every ladder rung
    legitimately starved → literal {} → 422 wedge. The platform AS is the one id source
    that exists BY CONSTRUCTION: mint an AUXILIARY user and take its id from the response
    or from its token's JWT sub claim (the AS mints sub=<user id>)."""
    calls = []
    aux_tok = _jwt_with_sub(57)

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, body))
        if url.endswith("/auth/register") and method == "POST":
            if body and str(body.get("email", "")).startswith("aux_"):
                return {"status": 201, "body_text": '{"access_token":"%s"}' % aux_tok}
            return {"status": 409, "body_text": '{"detail":"exists"}'}     # chain user: no id
        if url.endswith("/auth/login") and method == "POST":
            return {"status": 200, "body_text": '{"access_token":"%s"}' % _jwt_with_sub(12)}
        if url.endswith("/api/users/57/follow") and method == "POST":
            return {"status": 201, "body_text": '{"ok":true}'}
        return {"status": 404, "body_text": '{"detail":"Not Found"}'}       # incl. /api/users

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register", "expect": [200, 201, 409],
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "save": {"token": "access_token"}},
        {"method": "POST", "path": "/auth/login", "expect": [200],
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "save": {"token": "access_token"}},
        {"method": "POST", "path": "/api/users/{}/follow", "auth": "token", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert not any("{}" in u for (_m, u, _b) in calls)
    assert any(u.endswith("/api/users/57/follow") for (_m, u, _b) in calls)


def test_login_creds_carryforward_includes_tenant_id(monkeypatch):
    """FIX #101 (run-19 live): the verifier authored ${rand} in BOTH register and login
    (per-step rand → different emails AND different tenant_ids) → login 401 guaranteed.
    The carry-forward retried with the register's email/password but NOT its tenant_id →
    the multi-tenant AS still rejected → 7-cycle wedge. Carry tenant_id too."""
    calls = []
    reg = {}

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, body))
        if url.endswith("/auth/register") and method == "POST":
            reg.update(body or {})
            return {"status": 201, "body_text": '{"access_token":"t1"}'}
        if url.endswith("/auth/login") and method == "POST":
            b = body or {}
            if (b.get("email") == reg.get("email")
                    and b.get("password") == reg.get("password")
                    and b.get("tenant_id") == reg.get("tenant_id")):
                return {"status": 200, "body_text": '{"access_token":"t2"}'}
            return {"status": 401, "body_text": '{"detail":"invalid credentials"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register", "expect": [200, 201, 409],
         "body": {"email": "u_${rand}@example.com", "password": "password123",
                  "tenant_id": "tenant_${rand}"},
         "save": {"token": "access_token"}},
        {"method": "POST", "path": "/auth/login", "expect": [200],
         "body": {"email": "u_${rand}@example.com", "password": "password123",
                  "tenant_id": "tenant_${rand}"},
         "save": {"token": "access_token"}}]})
    assert out["broken"] == [], out["broken"]
