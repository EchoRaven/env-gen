"""FIX #136 — a NON-denial by-id step whose AUTHORED path carries a LITERAL numeric id
retries ONCE with a recovered real id when it 404s.

3rd occurrence of the class (run-52 UUID ids, run-58 repost 2/3, run-60 repost 4):
the verifier hand-writes `POST /api/posts/4/repost` but the seed only reaches id 2 —
the ${placeholder} recovery ladder never fires for literals, so the authored id goes
out verbatim -> 404 -> business_chain wedges 7 post-cap cycles on a correct app
(run-60: the backend "fixed" the live DB but not seed_data.json, so every clean-boot
regressed it and the run STUCK-downshifted to its budget death).

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as ce  # noqa: E402


def _resp(status, body=""):
    return {"status": status, "body_text": body, "error": None}


def _run(chain, fake_http, monkeypatch):
    monkeypatch.setattr(ce, "_http", fake_http)
    return ce.execute_chain("http://h", chain)


def test_literal_id_404_recovers_via_list(monkeypatch):
    """POST /api/posts/4/repost 404s (seed has 1-2); the retry lists /api/posts,
    takes a real id, and the step passes."""
    calls = []
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        calls.append((method, url))
        if url.endswith("/api/posts/4/repost"):
            return _resp(404, '{"detail":"Post not found"}')
        if method == "GET" and url.endswith("/api/posts"):
            return _resp(200, '{"items":[{"id": 2}, {"id": 1}]}')
        if url.endswith("/api/posts/2/repost"):
            return _resp(201, '{"item":{"id": 9}}')
        return _resp(200, '{"items":[]}')
    out = _run({"name": "c", "steps": [
        {"action": "repost", "method": "POST", "path": "/api/posts/4/repost",
         "expect": [200, 201]}]}, fake_http, monkeypatch)
    assert out["broken"] == [], out
    st = out["steps"][0]
    assert st["ok"] and st["status"] == 201
    assert any("/api/posts/2/repost" in u for _, u in calls), calls


def test_denial_probe_keeps_its_404(monkeypatch):
    """A cross-user denial probe EXPECTS 404 — it passes as-is and must never be
    'recovered' into a 200 leak."""
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        return _resp(404, '{"detail":"not found"}')
    out = _run({"name": "c", "steps": [
        {"action": "cross-user read denied", "method": "GET",
         "path": "/api/messages/7", "expect": [403, 404]}]}, fake_http, monkeypatch)
    assert out["broken"] == []
    assert out["steps"][0]["ok"] and out["steps"][0]["status"] == 404


def test_genuinely_broken_endpoint_still_fails(monkeypatch):
    """The retry with a REAL id also 404s -> the failure is honest and recorded."""
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        if method == "GET" and url.endswith("/api/posts"):
            return _resp(200, '{"items":[{"id": 1}]}')
        return _resp(404, '{"detail":"Post not found"}')
    out = _run({"name": "c", "steps": [
        {"action": "repost", "method": "POST", "path": "/api/posts/4/repost",
         "expect": [200, 201]}]}, fake_http, monkeypatch)
    assert out["broken"], "a broken endpoint must still surface"


def test_substituted_id_is_not_retried(monkeypatch):
    """An id that came from a ${var} substitution was REALLY captured — its 404 is a
    genuine failure and must not be masked by a literal-id retry (the authored path
    carries the placeholder, not a literal digit)."""
    calls = []
    def fake_http(method, url, *, token=None, body=None, timeout=10, **_kw):
        calls.append((method, url))
        if method == "POST" and url.endswith("/api/posts"):
            return _resp(201, '{"item":{"id": 5}}')
        return _resp(404, '{"detail":"gone"}')
    out = _run({"name": "c", "steps": [
        {"action": "create", "method": "POST", "path": "/api/posts",
         "expect": [201], "save": {"post_id": "id"}},
        {"action": "read back", "method": "GET", "path": "/api/posts/${post_id}",
         "expect": [200]}]}, fake_http, monkeypatch)
    assert out["broken"], "captured-id 404 must fail honestly"
    # no extra GET /api/posts list-recovery for the substituted step
    gets = [u for m, u in calls if m == "GET" and u.endswith("/api/posts")]
    assert not gets, f"substituted-id step must not literal-retry, calls={calls}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
