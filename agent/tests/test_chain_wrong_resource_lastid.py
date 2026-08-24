"""Fix #66 — an unresolved by-id path var must recover on ITS collection, never
fall to a cross-resource global last_id (outlook run-51, live 2026-07-03).

The verifier's auth_and_inbox_flow: register -> GET /api/auth/me -> GET
/api/folders -> GET /api/messages (save items.0.id) -> GET
/api/messages/{message_id} (expect 200). A FRESH chain user owns no messages, so
the list is empty (owner-scoped) and items.0.id never binds. The old resolution
order (same-resource -> GLOBAL last_id -> recovery) then used the global last_id
— the USER id from /auth/me or a FOLDER id from /folders — so the read hit
/api/messages/<user-or-folder-id> -> 404 -> business_chain wedged 7 cycles on a
CORRECT app. The fix moves collection-targeted recovery BEFORE the global
last_id, and a denial step never falls to the global last_id (false-leak guard).
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def _server():
    """Owner-scoped fake: users via register; messages owned by creator; a seed
    folder (id 500) + a /auth/me user id (id 900). Records calls."""
    state = {"next_user": 900, "msgs": {}}   # user ids start high to be distinct
    calls = []

    def http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, token))
        tail = url.split("/api", 1)[-1] if "/api" in url else url
        if "/auth/register" in url and method == "POST":
            tok = f"tok{state['next_user']}"
            state["next_user"] += 1
            return {"status": 201, "body_text": '{"access_token":"%s"}' % tok}
        if tail == "/auth/me" and method == "GET":
            return {"status": 200, "body_text": '{"item":{"id":900,"email":"u@x.com"}}'}
        if tail == "/folders" and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":500,"name":"Inbox"}]}'}
        if tail == "/messages" and method == "GET":
            mine = [{"id": k} for k, o in state["msgs"].items() if o == token]
            return {"status": 200, "body_text": '{"items":%s}'
                    % str(mine).replace("'", '"')}
        if tail == "/messages" and method == "POST":
            mid = 1000 + len(state["msgs"])
            state["msgs"][mid] = token
            return {"status": 201, "body_text": '{"item":{"id":%d}}' % mid}
        if tail.startswith("/messages/") and method == "GET":
            mid = tail.rsplit("/", 1)[-1]
            try:
                mid = int(mid)
            except ValueError:
                return {"status": 422, "body_text": '{"detail":"bad id"}'}
            owner = state["msgs"].get(mid)
            if owner is None or owner != token:
                return {"status": 404, "body_text": '{"detail":"Message not found"}'}
            return {"status": 200, "body_text": '{"item":{"id":%d}}' % mid}
        return {"status": 404, "body_text": "{}"}
    return http, calls, state


_RUN51_CHAIN = {"name": "auth_and_inbox_flow", "steps": [
    {"method": "POST", "path": "/auth/register",
     "body": {"email": "test${rand}@x.com", "password": "p", "name": "T"},
     "save": {"auth": "access_token", "token": "access_token"},
     "expect": [200, 201, 409]},
    {"method": "GET", "path": "/api/auth/me", "auth": "auth", "expect": [200]},
    {"method": "GET", "path": "/api/folders", "auth": "auth", "expect": [200]},
    {"method": "GET", "path": "/api/messages", "auth": "auth",
     "save": {"message_id": "items.0.id"}, "expect": [200]},
    {"method": "GET", "path": "/api/messages/{message_id}", "auth": "auth",
     "expect": [200]},
]}


def test_run51_chain_passes_via_collection_recovery(monkeypatch):
    """The fresh user's message list is empty, so message_id never binds; the
    read must recover a MESSAGE (create one), NOT read /api/messages/<user-id
    or folder-id> from the global last_id."""
    http, calls, state = _server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", _RUN51_CHAIN)
    assert out["broken"] == [], out["broken"]
    # it must NOT have read a message by the user id (900) or folder id (500)
    read_ids = [u.rsplit("/", 1)[-1] for m, u, _t in calls
                if "/messages/" in u and m == "GET"]
    assert "900" not in read_ids and "500" not in read_ids, read_ids
    # it recovered by CREATING a message (id >= 1000) as the chain user
    assert any(m == "POST" and u.endswith("/api/messages") for m, u, _t in calls)


def test_same_resource_id_still_wins(monkeypatch):
    """A chain that DID create the resource resolves to the created id (no
    recovery, no global-lastid) — the #10 same-resource path is unchanged."""
    http, calls, state = _server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "a@x.com", "password": "p", "name": "A"},
         "save": {"auth": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/api/messages", "auth": "auth",
         "body": {"subject": "hi"}, "save": {"mid": "item.id"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "auth",
         "expect": [200]}]})
    assert out["broken"] == [], out["broken"]
    # exactly one message created (no extra recovery create)
    assert sum(1 for m, u, _t in calls
               if m == "POST" and u.endswith("/api/messages")) == 1


def test_denial_step_no_global_lastid_when_no_same_resource(monkeypatch):
    """A denial read whose var is unresolved AND with no same-resource id must
    NOT fall to the cross-resource global last_id (a folder/user id from an
    earlier step); #66 skips the global last_id for denial steps. With no
    non-prober token, recovery is skipped too (#59b), so the literal survives —
    the point is it NEVER borrows an unrelated prior id."""
    http, calls, state = _server()
    monkeypatch.setattr(ce, "_http", http)
    ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "i@x.com", "password": "p", "name": "I"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "GET", "path": "/api/folders", "auth": "token", "expect": [200]},
        # denial read, no message ever created → no same-resource id; must not
        # borrow the folder id (500) via the global last_id
        {"method": "GET", "path": "/api/messages/${other_id}", "auth": "token",
         "expect": [404, 403]}]})
    read_500 = [u for m, u, _t in calls
                if "/messages/" in u and m == "GET" and u.rsplit("/", 1)[-1] == "500"]
    assert read_500 == [], "denial borrowed the folder id via global last_id"


def test_denial_with_intruder_token_recovers_owner_row(monkeypatch):
    """The REAL two-user denial: an intruder reads an owner's message by id via
    recovery on the owner's token -> 404 (isolation). #59b path, unaffected by
    #66's reorder (recovery already ran before the removed global-lastid)."""
    http, calls, state = _server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "owner@x.com", "password": "p", "name": "O"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "intruder@x.com", "password": "p", "name": "I"},
         "save": {"token_2": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/api/messages", "auth": "token",
         "body": {"subject": "owner-msg"}, "save": {"mid": "item.id"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "token_2",
         "expect": [404, 403]}]})
    assert out["broken"] == [], out["broken"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
