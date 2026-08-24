"""Fix #67 — an unsatisfiable-by-data by-id READ is skipped, not a false wedge
(outlook run-53, live 2026-07-03, STUCK-ABORT).

The verifier's read_email chain: register user_a -> register user_b -> GET
/api/messages (save items.0.id) -> GET /api/messages/${message_id_a} (x2). A
FRESH user owns no messages (owner-scoped empty list) so message_id_a never
binds; and THIS run's agent registered only GET /api/messages (no POST), so
create-recovery POSTed -> 405 Method Not Allowed -> could not create one either.
The literal ${message_id_a} then reached the URL -> 404 -> business_chain wedged
7 cycles on a functionally-correct app (the endpoint IS reachable — api_smoke
proved it — and correctly 404s a non-existent id; the chain just has no data to
read). The executor now SKIPS such a positive by-id GET (recorded, not broken).
Denial steps still send the literal (their 404 is the desired pass); non-GET
writes still run. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def _server(*, allow_post=True):
    """Owner-scoped fake. allow_post=False models run-53's contract (only GET
    /api/messages registered -> POST returns 405)."""
    state = {"next_user": 700, "msgs": {}}
    calls = []

    def http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, token))
        tail = url.split("/api", 1)[-1] if "/api" in url else url
        if "/auth/register" in url and method == "POST":
            tok = f"tok{state['next_user']}"
            state["next_user"] += 1
            return {"status": 201, "body_text": '{"access_token":"%s"}' % tok}
        if tail == "/messages" and method == "GET":
            mine = [{"id": k} for k, o in state["msgs"].items() if o == token]
            return {"status": 200, "body_text": '{"items":%s}'
                    % str(mine).replace("'", '"')}
        if tail == "/messages" and method == "POST":
            if not allow_post:
                return {"status": 405, "body_text": '{"detail":"Method Not Allowed"}'}
            mid = 1000 + len(state["msgs"])
            state["msgs"][mid] = token
            return {"status": 201, "body_text": '{"item":{"id":%d}}' % mid}
        if tail.startswith("/messages/") and method == "GET":
            raw = tail.rsplit("/", 1)[-1]
            # model run-53's TEXT/UUID-id backend: any unknown id (incl. a
            # surviving literal ${x}) is simply not found -> 404 (not a 422).
            try:
                mid = int(raw)
            except ValueError:
                return {"status": 404, "body_text": '{"detail":"Message not found"}'}
            owner = state["msgs"].get(mid)
            if owner is None or owner != token:
                return {"status": 404, "body_text": '{"detail":"Message not found"}'}
            return {"status": 200, "body_text": '{"item":{"id":%d}}' % mid}
        return {"status": 404, "body_text": "{}"}
    return http, calls, state


_READ_EMAIL = {"name": "read_email", "steps": [
    {"method": "POST", "path": "/auth/register",
     "body": {"email": "a${rand}@x.com", "password": "p", "name": "A"},
     "save": {"token_a": "access_token", "token": "access_token"}, "expect": [201]},
    {"method": "POST", "path": "/auth/register",
     "body": {"email": "b${rand}@x.com", "password": "p", "name": "B"},
     "save": {"token_b": "access_token"}, "expect": [201]},
    {"method": "GET", "path": "/api/messages", "auth": "token_a",
     "save": {"message_id_a": "items.0.id"}, "expect": [200]},
    {"method": "GET", "path": "/api/messages/${message_id_a}", "auth": "token_a",
     "expect": [200]},
    {"method": "GET", "path": "/api/messages/${message_id_a}", "auth": "token_a",
     "expect": [200]},
]}


def test_run53_no_post_read_is_skipped_not_broken(monkeypatch):
    """POST unavailable (405) + empty owner-scoped list -> the by-id reads are
    unsatisfiable by data -> skipped, chain passes (no false wedge)."""
    http, calls, state = _server(allow_post=False)
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", _READ_EMAIL)
    assert out["broken"] == [], out["broken"]
    skipped = [s for s in out["steps"] if s.get("kind") == "skipped"]
    assert skipped, "the unsatisfiable read should be skipped"
    assert any("unsatisfiable by data" in s.get("note", "") for s in skipped)
    # the literal ${message_id_a} must NEVER have been sent
    assert not any("${message_id_a}" in u for _m, u, _t in calls)


def test_create_recovery_still_used_when_post_available(monkeypatch):
    """When POST works, the read is SATISFIED via create-recovery (not skipped)
    — #67 only skips when there is genuinely no data path."""
    http, calls, state = _server(allow_post=True)
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", _READ_EMAIL)
    assert out["broken"] == [], out["broken"]
    assert not [s for s in out["steps"] if s.get("kind") == "skipped"]
    assert any(m == "POST" and u.endswith("/api/messages") for m, u, _t in calls)


def test_denial_read_still_sends_literal_not_skipped(monkeypatch):
    """A denial by-id read with an unresolvable var must NOT be skipped — it
    sends the literal so its 404 is the desired isolation pass (#59b)."""
    http, calls, state = _server(allow_post=False)
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "i@x.com", "password": "p", "name": "I"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${nope_id}", "auth": "token",
         "expect": [404, 403]}]})
    assert out["broken"] == [], out["broken"]
    # NOT skipped — the denial step ran and its 404 satisfied [404,403]
    assert not [s for s in out["steps"] if s.get("kind") == "skipped"]


def test_satisfiable_read_not_skipped(monkeypatch):
    """A chain that DID create the resource resolves + reads it (never skipped)."""
    http, calls, state = _server(allow_post=True)
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "o@x.com", "password": "p", "name": "O"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/api/messages", "auth": "token",
         "body": {"subject": "hi"}, "save": {"mid": "item.id"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "token",
         "expect": [200]}]})
    assert out["broken"] == [], out["broken"]
    assert not [s for s in out["steps"] if s.get("kind") == "skipped"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
