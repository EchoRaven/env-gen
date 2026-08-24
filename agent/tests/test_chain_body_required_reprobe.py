"""Fix #70 — a write that 422s 'body required' (no body sent) re-probes with {}
to surface the field-level 422, then auto-fills (outlook run-58, live).

run-58 STUCK-ABORT: business_chain POST /api/events/{id}/rsvp -> 422
{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}.
The lane's rsvp handler needs {"response": "..."}; the chain sent NO body, so
FastAPI reports loc:["body"] (the WHOLE body missing) with NO field name -> the
missing-field auto-repair had nothing to fill -> wedge 7 cycles on a correct
endpoint (live: null->422, {}->422 loc:["body","response"], {"response":..}->200).
The executor now re-probes with {} when a write 422s with no body, surfacing the
field-level 422 whose field names the fill uses. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def test_missing_required_fields_skips_whole_body_loc():
    """loc:["body"] (whole body missing) yields NO field name — filling a field
    literally called 'body' would be wrong."""
    bt = '{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}'
    body, query = ce._missing_required_fields(bt, "POST")
    assert body == [] and query == []


def test_missing_required_fields_extracts_field_level():
    bt = '{"detail":[{"type":"missing","loc":["body","response"],"msg":"Field required"}]}'
    body, query = ce._missing_required_fields(bt, "POST")
    assert body == ["response"]


def test_rsvp_reprobe_then_fill(monkeypatch):
    """The run-58 rsvp shape: null body -> loc:["body"]; {} -> loc:["body",
    "response"]; {"response":..} -> 201. The executor re-probes with {} then
    fills 'response'."""
    calls = []

    def http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, body))
        if "/auth/register" in url:
            return {"status": 201, "body_text": '{"access_token":"t"}'}
        if url.endswith("/rsvp") and method == "POST":
            if body is None:
                return {"status": 422, "body_text":
                        '{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}'}
            if not body.get("response"):
                return {"status": 422, "body_text":
                        '{"detail":[{"type":"missing","loc":["body","response"],"msg":"Field required"}]}'}
            return {"status": 201, "body_text": '{"item":{"id":1}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "a@x.com", "password": "p", "name": "A"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/api/events/e1/rsvp", "auth": "token",
         "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    rsvp = [s for s in out["steps"] if s.get("path", "").endswith("/rsvp")][0]
    assert rsvp["status"] in (200, 201)
    assert "response" in (rsvp.get("autofilled") or [])
    # a {} re-probe happened before the filled retry
    rsvp_bodies = [b for m, u, b in calls if u.endswith("/rsvp")]
    assert {} in rsvp_bodies or any(b == {} for b in rsvp_bodies)
    assert any(isinstance(b, dict) and b.get("response") for b in rsvp_bodies)


def test_bodyless_endpoint_unaffected(monkeypatch):
    """A POST action that genuinely needs no body (200 on null) is not disturbed
    by the re-probe path (it only runs on a 4xx)."""
    def http(method, url, token=None, body=None, **_kw):
        if "/auth/register" in url:
            return {"status": 201, "body_text": '{"access_token":"t"}'}
        if url.endswith("/publish"):
            return {"status": 200, "body_text": '{"ok":true}'}
        return {"status": 404, "body_text": "{}"}
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "a@x.com", "password": "p", "name": "A"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/api/posts/1/publish", "auth": "token",
         "expect": [200]}]})
    assert out["broken"] == [], out["broken"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
