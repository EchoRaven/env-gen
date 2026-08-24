"""Chain-executor list-GET recovery for an unresolvable path var (outlook run-22, 2026-07-01).

The verifier LLM routinely authors a chain that GETs/updates/deletes a resource by id WITHOUT a
prior POST to capture that id — e.g. GET /api/messages/${message_id} with no earlier create. The
prior fallback only substituted `last_id` (the most recent captured id) and did NOTHING when
`last_id is None`, so the LITERAL "${message_id}" reached the URL → 404 → business_chain wedged
forever on a functionally-correct, SEEDED app (run-22 died exactly here). The executor now RECOVERS:
resolve the placeholder same-resource → last_id → a live LIST GET on the collection (seed data
populates it) taking a real row's id. This lifts every run's business_chain pass rate (the #1
remaining chain-authoring-variance wedge). ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def test_collection_path_of():
    assert ce._collection_path_of("/api/messages/${message_id}") == "/api/messages"
    assert ce._collection_path_of("/api/messages/{id}") == "/api/messages"
    assert ce._collection_path_of("/api/messages/:id") == "/api/messages"
    assert ce._collection_path_of("/api/messages/search") == "/api/messages/search"  # not a placeholder
    assert ce._collection_path_of("/api/messages") == "/api/messages"


def test_unresolved_path_var_recovers_via_list_get(monkeypatch):
    """No prior create → ${message_id} unresolvable from captures → LIST GET recovers a seeded id."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/api/messages") and method == "GET":       # the seed-data list
            return {"status": 200, "body_text": '{"items":[{"id":77,"subject":"seed"}],"total":1}'}
        if "/api/messages/77" in url and method == "GET":           # by-id with the recovered id
            return {"status": 200, "body_text": '{"item":{"id":77}}'}
        return {"status": 404, "body_text": '{"detail":"Message not found"}'}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"action": "get", "method": "GET", "path": "/api/messages/${message_id}", "expect": [200]}]})
    assert out["broken"] == [], out["broken"]                        # recovered → 200, not 404 on the literal
    assert ("GET", "http://x/api/messages") in calls                 # did the recovery list-GET
    assert any("/api/messages/77" in u for (_m, u) in calls)         # then the by-id GET with id 77
    assert not any("${message_id}" in u for (_m, u) in calls)        # literal never sent


def test_prior_create_captured_id_wins_over_list(monkeypatch):
    """A captured same-resource id is used directly — no list-GET, and NOT some other row's id."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/api/messages") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":5}}'}          # captures message id 5
        if "/api/messages/5" in url and method == "GET":
            return {"status": 200, "body_text": '{"item":{"id":5}}'}
        if url.endswith("/api/messages") and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":99}]}'}       # list would give 99 — must NOT win
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/api/messages", "body": {"subject": "hi"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "expect": [200]}]})
    assert out["broken"] == [], out["broken"]
    assert any("/api/messages/5" in u for (_m, u) in calls)          # used the CAPTURED id 5, not list's 99


def test_correctly_wired_saved_var_untouched(monkeypatch):
    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/messages") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":8}}'}
        if "/api/messages/8" in url:
            return {"status": 200, "body_text": '{"item":{"id":8}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/api/messages", "save": {"mid": "item.id"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${mid}", "expect": [200]}]})
    assert out["broken"] == []


def test_empty_collection_is_graceful(monkeypatch):
    # recovery finds no row → the literal survives → the step 404s, but NO crash
    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/widgets") and method == "GET":
            return {"status": 200, "body_text": '{"items":[],"total":0}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "w", "steps": [
        {"method": "GET", "path": "/api/widgets/${widget_id}", "expect": [200]}]})
    assert isinstance(out["broken"], list)                          # graceful, no exception


def test_recover_helper_skips_parametrised_collection(monkeypatch):
    # a nested collection whose parent is still a placeholder must NOT be GET'd
    monkeypatch.setattr(ce, "_http", lambda *a, **k: {"status": 200, "body_text": '{"items":[{"id":1}]}'})
    assert ce._recover_id_via_list("http://x", "/api/events/${event_id}/attendees", "tok") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
