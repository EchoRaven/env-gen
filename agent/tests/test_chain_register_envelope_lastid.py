"""FIX #114 — the register envelope's nested user id feeds the global last_id rung
(instagram-core-di run-30, 2026-07-08 13:47 STUCK, live-replayed 100% reproducible).

The verifier authored `post_interaction_flow`: register → POST /api/posts/{id}/like →
POST /api/posts/{id}/repost, with NO post-source step. EVERY ladder rung starved:
  * same-resource: nothing captured a post id;
  * list/create recovery: this app has NO bare /api/posts collection (GET/POST both
    404 — feed/explore serve the content; run-3's exact topology);
  * aux-user rung: resource is "post", not "user";
  * GLOBAL last_id: the register response is the platform envelope
    ``{"access_token": ..., "user": {"id": N}}`` — no top-level id/item/items —
    so ``_extract_resource_id`` returned None and last_id NEVER got set.
The literal ``{id}`` reached the int path param → 422 (not in expect [200,201,404])
→ business_chain wedged 7 post-cap cycles → STUCK abort at 2331s, pre-M1.

Fix: ``_extract_resource_id`` also accepts the id of a nested one-level dict when the
payload contains EXACTLY ONE such dict (unambiguous — the register/login envelope's
``user``). The global rung then substitutes a real id; /api/posts/<uid>/like → 404,
which the expect family tolerates → converges instead of wedging. Same-resource ids,
explicit saves, and the denial-step guard (#59b) all stay authoritative above it.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def test_extract_id_from_single_nested_dict():
    # the platform register/login envelope (run-30's exact shape)
    assert ce._extract_resource_id(
        {"access_token": "x", "token_type": "Bearer", "expires_in": 3600,
         "user": {"id": 22, "email": "a@b.c"}}) == 22


def test_extract_id_existing_shapes_win():
    # canonical envelopes keep their precedence — nested rule is a last resort
    assert ce._extract_resource_id({"item": {"id": 1}, "user": {"id": 9}}) == 1
    assert ce._extract_resource_id({"id": 2, "user": {"id": 9}}) == 2
    assert ce._extract_resource_id({"items": [{"id": 3}], "user": {"id": 9}}) == 3


def test_extract_id_ambiguous_nested_returns_none():
    # TWO nested id-dicts → ambiguous → refuse to guess
    assert ce._extract_resource_id(
        {"user": {"id": 9}, "profile": {"id": 4}}) is None
    assert ce._extract_resource_id({"ok": True}) is None
    assert ce._extract_resource_id("not a mapping") is None


def test_run30_chain_shape_converges(monkeypatch):
    """the EXACT run-30 wedge: register (envelope, nested user id) → like/repost on
    literal {id}; no posts collection anywhere. The global rung must substitute the
    captured user id → 404 → tolerated by the expect family → chain passes."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text":
                    '{"access_token":"tok1","token_type":"Bearer","expires_in":3600,'
                    '"user":{"id":22,"email":"probe@t.com"}}'}
        if "/api/posts/22/" in url and method == "POST":
            return {"status": 404, "body_text": '{"detail":"post not found"}'}
        if url.endswith("/api/posts"):
            return {"status": 404, "body_text": "{}"}     # no bare collection (live)
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    steps, errs = ce.normalize_steps([
        {"method": "POST", "path": "/auth/register",
         "body": {"username": "u", "email": "u@t.com", "password": "Passw0rd!123"},
         "expect": [200, 201, 409]},
        {"method": "POST", "path": "/api/posts/{id}/like", "auth": "token",
         "expect": [200, 201, 404]},
        {"method": "POST", "path": "/api/posts/{id}/repost", "auth": "token",
         "expect": [200, 201, 404]},
    ])
    assert not errs
    out = ce.execute_chain("http://x", {"name": "post_interaction_flow", "steps": steps})
    assert out["broken"] == []                       # the run-30 wedge, gone
    # the literal placeholder must never reach the server
    assert not any("{id}" in u for _, u in calls)
    # and the resolved id is the register-captured user id
    assert any("/api/posts/22/like" in u for _, u in calls)


def test_denial_steps_still_never_use_global_lastid(monkeypatch):
    """#59b guard intact: a cross-user denial step must NOT resolve via the prober's
    own captured id (a 200 on your own row is a FALSE leak) — literal stays."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text":
                    '{"access_token":"tok1","user":{"id":22}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    steps, _ = ce.normalize_steps([
        {"method": "POST", "path": "/auth/register",
         "body": {"username": "u", "email": "u@t.com", "password": "Passw0rd!123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/posts/${other_user_post_id}",
         "auth": "token", "expect": [401, 403, 404],
         "description": "cross-user isolation: another user's post must be denied"},
    ])
    out = ce.execute_chain("http://x", {"name": "iso", "steps": steps})
    assert out["broken"] == []
    assert not any("/api/posts/22" in u for m, u in calls if m == "GET")
