"""run-29 M3 STUCK-ABORT forensics → 3 executor fixes (#32/#33/#34, 2026-07-01).

run-29 M3 wedged with 6/6 validation failures on a WORKING backend. The persisted chain
records showed three distinct executor gaps:
- #32: owner-scoped reads + a FRESH chain user own nothing → ``save: items.0.id`` on an
  empty list fails AND the list recovery sees the same empty list → literal ``{message_id}``
  → 422 (3 of 6 chains). Fix: last-resort ``_recover_id_via_create`` — POST a minimal row
  (auto-filling server-named required fields) and use its id.
- #33: verifier-authored query with a raw SPACE (``search?q=Test Message``) → urllib
  ``InvalidURL`` → step status None forever. Fix: ``_safe_url`` percent-encodes what urllib
  refuses, leaving valid URLs byte-identical.
- #34: steps missing their ``auth`` ref hit endpoints unauthenticated → 401 despite a
  saved token. Fix: on 401/403 without an auth ref, retry once with the saved token; adopt
  only if the authored expectation passes (isolation probes undisturbed).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as ce  # noqa: E402
from multi_agent.runtime.validation_runner import _safe_url  # noqa: E402


# ---------- #33 _safe_url ----------

def test_safe_url_encodes_space_and_nonascii():
    assert _safe_url("http://h:1/api/messages/search?q=Test Message") == \
        "http://h:1/api/messages/search?q=Test%20Message"
    assert "%E6" in _safe_url("http://h:1/api/search?q=测试")


def test_safe_url_leaves_valid_urls_identical():
    for u in ("http://h:1/api/messages?folder=inbox&focused=true",
              "http://h:1/api/events/9c-4e/rsvp",
              "http://h:1/api/x?q=a%20b"):          # already-encoded stays put
        assert _safe_url(u) == u


# ---------- #32 _recover_id_via_create ----------

def _resp(status, body=""):
    return {"status": status, "body_text": body, "error": None}


def test_recover_via_create_plain_post(monkeypatch):
    calls = []
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        calls.append((method, url, body))
        return _resp(201, '{"item": {"id": 42}}')
    monkeypatch.setattr(ce, "_http", fake_http)
    assert ce._recover_id_via_create("http://h", "/api/messages", "tok") == 42
    assert calls[0][0] == "POST"


def test_recover_via_create_fills_required_fields(monkeypatch):
    calls = []
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        calls.append(body)
        if not body:
            return _resp(422, '{"detail":[{"type":"missing","loc":["body","subject"],"msg":"Field required"}]}')
        return _resp(201, '{"item": {"id": "m-7"}}')
    monkeypatch.setattr(ce, "_http", fake_http)
    assert ce._recover_id_via_create("http://h", "/api/messages", "tok") == "m-7"
    assert calls[1] == {"subject": "chain-recover"}


def test_recover_via_create_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(ce, "_http", lambda *a, **k: _resp(500, "boom"))
    assert ce._recover_id_via_create("http://h", "/api/messages", "tok") is None
    # parametrised / empty path → refuse
    assert ce._recover_id_via_create("http://h", "/api/x/{id}", "t") is None
    assert ce._recover_id_via_create("http://h", "", "t") is None


def test_run29_class_a_end_to_end(monkeypatch):
    """The exact run-29 shape: register → empty list (save fails) → by-id step recovers
    via CREATE instead of sending the literal ``{message_id}``."""
    state = {"created": False}
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        if url.endswith("/auth/register"):
            return _resp(201, '{"access_token": "T"}')
        if method == "GET" and url.endswith("/api/messages"):
            return _resp(200, '{"items": []}')                  # owner-scoped: EMPTY
        if method == "POST" and url.endswith("/api/messages"):
            state["created"] = True
            return _resp(201, '{"item": {"id": 5}}')
        if method == "GET" and url.endswith("/api/messages/5"):
            return _resp(200, '{"item": {"id": 5}}')
        return _resp(404, '{"detail": "Not Found"}')
    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://h", {"name": "read_message", "steps": [
        {"method": "POST", "path": "/auth/register", "expect": [201],
         "save": {"token": "access_token"},
         "body": {"email": "u_${rand}@e.io", "password": "p", "name": "U"}},
        {"method": "GET", "path": "/api/messages", "expect": [200], "auth": "token",
         "save": {"message_id": "items.0.id"}},
        {"method": "GET", "path": "/api/messages/${message_id}", "expect": [200],
         "auth": "token"},
    ]})
    assert state["created"], "create-recovery did not fire"
    assert not out.get("broken"), out.get("broken")


# ---------- #34 auth auto-attach ----------

def test_auth_auto_attach_retries_with_saved_token(monkeypatch):
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        if url.endswith("/auth/register"):
            return _resp(201, '{"access_token": "T"}')
        if method == "POST" and url.endswith("/api/messages"):
            if token == "T":
                return _resp(201, '{"item": {"id": 9}}')
            return _resp(401, '{"detail": "missing or invalid token"}')
        return _resp(404, '{"detail": "Not Found"}')
    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://h", {"name": "core_flow", "steps": [
        {"method": "POST", "path": "/auth/register", "expect": [201],
         "save": {"token": "access_token"},
         "body": {"email": "u_${rand}@e.io", "password": "p", "name": "U"}},
        # the run-29 bug shape: NO "auth" ref on the write
        {"method": "POST", "path": "/api/messages", "expect": [201],
         "body": {"subject": "hi", "body": "b"}},
    ]})
    assert not out.get("broken"), out.get("broken")
    assert any("auth<-saved-token" in (s.get("autofilled") or [])
               for s in out.get("steps") or []), out.get("steps")


def test_isolation_probe_expecting_denial_is_untouched(monkeypatch):
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        if url.endswith("/auth/register"):
            return _resp(201, '{"access_token": "T"}')
        return _resp(401, '{"detail": "unauthorized"}')          # denial IS the expectation
    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://h", {"name": "iso", "steps": [
        {"method": "POST", "path": "/auth/register", "expect": [201],
         "save": {"token": "access_token"},
         "body": {"email": "u_${rand}@e.io", "password": "p", "name": "U"}},
        {"method": "GET", "path": "/api/messages", "expect": [401]},   # expected denial
    ]})
    assert not out.get("broken"), out.get("broken")               # 401 ∈ expect → ok, no retry


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
