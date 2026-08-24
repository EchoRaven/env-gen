"""FIX #78 — robust cross-user denial probe (outlook run-64 + smoke-feed, both live-diagnosed).

A cross-user DENIAL step (expect 403/404) that gets a 2xx is normally a real leak. But TWICE
now a run aborted (7-cycle stuck) on such a 2xx that was NOT a real leak — the backend was
live-confirmed CORRECT (a genuine different user IS denied), so the probe had run as the
resource's OWNER via a stale/owner-colliding/empty intruder token → the op legitimately
succeeded → false "leak/hack". #78: before failing the gate on a denial 2xx, RE-VERIFY with a
GUARANTEED-fresh intruder. If they are denied, the 2xx was a probe artifact (not broken). This
CANNOT mask a real leak: a genuine leak → the fresh intruder ALSO succeeds → stays broken.
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


# ── the helper: the core decision ────────────────────────────────────────────
def test_fresh_intruder_denied_means_NOT_a_real_leak(monkeypatch):
    def http(method, url, token=None, body=None, **_kw):
        if "/auth/register" in url:
            assert body and "reverify_" in body["email"]  # a FRESH, unique intruder
            return {"status": 201, "body_text": '{"access_token":"FRESH_TOK"}'}
        assert token == "FRESH_TOK"  # the re-run uses the fresh token, not the original
        return {"status": 404, "body_text": '{"detail":"not found"}'}  # DENIED
    monkeypatch.setattr(ce, "_http", http)
    assert ce._reverify_denial_via_fresh_intruder(
        "http://x", "PUT", "/api/posts/1", {"text": "x"}, [403, 404]) is False


def test_fresh_intruder_succeeds_IS_a_real_leak(monkeypatch):
    def http(method, url, token=None, body=None, **_kw):
        if "/auth/register" in url:
            return {"status": 201, "body_text": '{"access_token":"FRESH"}'}
        return {"status": 200, "body_text": '{"item":{}}'}  # fresh intruder ALSO edits → REAL leak
    monkeypatch.setattr(ce, "_http", http)
    assert ce._reverify_denial_via_fresh_intruder(
        "http://x", "DELETE", "/api/posts/1", None, [403, 404]) is True


def test_no_fresh_token_is_conservative(monkeypatch):
    """If a fresh intruder can't be registered, we CANNOT disprove the leak → keep the leak
    verdict (never silently pass a possible leak)."""
    def http(method, url, token=None, body=None, **_kw):
        return {"status": 500, "body_text": "{}"}  # register failed → no token
    monkeypatch.setattr(ce, "_http", http)
    assert ce._reverify_denial_via_fresh_intruder(
        "http://x", "PUT", "/api/posts/1", {}, [403, 404]) is True


def test_helper_never_raises(monkeypatch):
    def http(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(ce, "_http", http)
    assert ce._reverify_denial_via_fresh_intruder("http://x", "PUT", "/p", {}, [404]) is True


# ── integration: a false-positive denial 2xx is downgraded, a real leak stays broken ─────
def _run(monkeypatch, put_status_for_original, fresh_denied):
    """Owner creates a post; the cross-user denial PUT gets ``put_status_for_original`` (the
    intruder swap collided to the owner ⇒ 200); the reverify FRESH intruder is denied/allowed
    per ``fresh_denied``."""
    def http(method, url, token=None, body=None, **_kw):
        if "/auth/register" in url:
            if body and "reverify_" in (body.get("email") or ""):
                return {"status": 201, "body_text": '{"access_token":"FRESH"}'}
            return {"status": 201, "body_text": '{"access_token":"OWNER"}'}  # chain register
        if url.endswith("/api/posts") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":"p1"}}'}
        if "/api/posts/" in url and method in ("PUT", "PATCH", "DELETE"):
            if token == "FRESH":
                return ({"status": 404, "body_text": '{"detail":"not found"}'} if fresh_denied
                        else {"status": 200, "body_text": '{"item":{}}'})
            return {"status": put_status_for_original, "body_text": '{"item":{"id":"p1"}}'}
        if method == "GET":
            return {"status": 200, "body_text": '{"item":{"id":"p1"}}'}
        return {"status": 200, "body_text": "{}"}
    monkeypatch.setattr(ce, "_http", http)
    chain = {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register", "save": {"token": "access_token"}, "expect": [200, 201]},
        {"method": "POST", "path": "/api/posts", "auth": "token", "body": {"text": "x"},
         "save": {"pid": "item.id"}, "expect": [201]},
        {"method": "PUT", "path": "/api/posts/${pid}", "auth": "token",
         "body": {"text": "hack"}, "expect": [403, 404]},  # cross-user denial (auth swapped by normalize)
    ]}
    return ce.execute_chain("http://x", chain)


def test_false_positive_denial_2xx_is_not_broken(monkeypatch):
    # original denial PUT → 200 (owner-colliding token), but the FRESH intruder is DENIED
    out = _run(monkeypatch, put_status_for_original=200, fresh_denied=True)
    assert out["broken"] == [], out["broken"]
    put = [s for s in out["steps"] if s["method"] == "PUT"][0]
    assert put["kind"] == "skipped"


def test_real_leak_stays_broken(monkeypatch):
    # original denial PUT → 200 AND the FRESH intruder ALSO succeeds → a genuine leak
    out = _run(monkeypatch, put_status_for_original=200, fresh_denied=False)
    assert any("/api/posts/" in b and "PUT" in b for b in out["broken"]), out["broken"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
