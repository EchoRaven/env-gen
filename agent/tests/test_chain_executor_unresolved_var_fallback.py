"""A chain step that references a path var the verifier never saved (outlook run #6:
GET /api/messages/${msg_id}) used to send the literal "${msg_id}" → 422 int_parsing →
business_chain failed FOREVER on a functionally-correct app, blocking delivery. The
executor now falls back to the most recent resource id captured from a prior step.
LOCAL-ONLY (agent/tests/ gitignored)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def test_unresolved_path_var_falls_back_to_captured_id(monkeypatch):
    seen_paths = []

    def fake_http(method, url, token=None, body=None, **_kw):
        seen_paths.append(url)
        if url.endswith("/api/messages") and method == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":42,"subject":"hi"}],"total":1}'}
        # the get-by-id step: only 200 if a REAL numeric id was substituted (not the literal var)
        if "/api/messages/42" in url:
            return {"status": 200, "body_text": '{"item":{"id":42,"subject":"hi"}}'}
        return {"status": 422, "body_text": '{"detail":[{"type":"int_parsing"}]}'}

    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "messages", "steps": [
        {"action": "list", "method": "GET", "path": "/api/messages"},          # captures id 42
        {"action": "get", "method": "GET", "path": "/api/messages/${msg_id}"},  # msg_id never saved
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == [], out["broken"]                 # fallback rescued the get-by-id
    assert "/api/messages/42" in seen_paths[-1]               # literal ${msg_id} was replaced by 42
    assert "${msg_id}" not in seen_paths[-1]


def test_correctly_wired_chain_is_untouched(monkeypatch):
    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/messages"):
            return {"status": 201, "body_text": '{"item":{"id":7}}'}
        if "/api/messages/7" in url:
            return {"status": 200, "body_text": '{"item":{"id":7}}'}
        return {"status": 404, "body_text": "{}"}
    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "m", "steps": [
        {"action": "create", "method": "POST", "path": "/api/messages", "save": {"mid": "item.id"}},
        {"action": "get", "method": "GET", "path": "/api/messages/${mid}"},  # correctly saved
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == []


def test_no_prior_id_leaves_placeholder_step_failing_gracefully(monkeypatch):
    # first step references an unsaved var with NO prior id → can't rescue, but must not crash
    monkeypatch.setattr(ce, "_http", lambda *a, **k: {"status": 422, "body_text": "{}"})
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"action": "get", "method": "GET", "path": "/api/messages/${msg_id}"}]})
    assert isinstance(out["broken"], list)  # graceful, no exception


def test_unresolved_body_fk_falls_back_to_captured_id(monkeypatch):
    """outlook 2026-06-30: POST /api/events with body {"calendar_id": "${calendar_id}"}
    that the chain never saved sent the LITERAL token to the int column → 500 →
    business_chain wedged forever. The body fallback now resolves it to the most recent
    captured resource id (the calendar created the prior step), preserving int type."""
    seen_bodies = []

    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/calendars") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":5,"name":"Work"}}'}  # captures id 5
        if url.endswith("/api/events") and method == "POST":
            seen_bodies.append(body)
            cid = (body or {}).get("calendar_id")
            # the real app rejects the literal token; only a real numeric id succeeds
            if isinstance(cid, int) or (isinstance(cid, str) and cid.isdigit()):
                return {"status": 201, "body_text": '{"item":{"id":99}}'}
            return {"status": 500, "body_text": '{"detail":"invalid input syntax for type integer"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "calendar_events", "steps": [
        {"action": "create_cal", "method": "POST", "path": "/api/calendars",
         "body": {"name": "Work"}, "expect": [201]},                      # captures id 5
        {"action": "create_event", "method": "POST", "path": "/api/events",
         "body": {"calendar_id": "${calendar_id}", "title": "Sync"},      # calendar_id never saved
         "expect": [201]},
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == [], out["broken"]                  # fallback rescued the FK
    assert seen_bodies[-1]["calendar_id"] == 5                  # literal token → captured id (int)
    assert seen_bodies[-1]["calendar_id"] != "${calendar_id}"
    assert seen_bodies[-1]["title"] == "Sync"                  # other fields untouched


def test_saved_body_var_is_not_overridden_by_fallback(monkeypatch):
    """A correctly-wired body var (saved by a prior step) must use the SAVED value,
    never the last_id fallback — the fallback only rescues UNSAVED tokens."""
    seen = []

    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/calendars") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":11}}'}
        if url.endswith("/api/folders") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":77}}'}  # later create → last_id=77
        if url.endswith("/api/events") and method == "POST":
            seen.append(body)
            return {"status": 201, "body_text": '{"item":{"id":1}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "c", "steps": [
        {"method": "POST", "path": "/api/calendars", "body": {"name": "W"},
         "save": {"calendar_id": "item.id"}, "expect": [201]},   # saves calendar_id=11
        {"method": "POST", "path": "/api/folders", "body": {"name": "F"}, "expect": [201]},  # last_id=77
        {"method": "POST", "path": "/api/events",
         "body": {"calendar_id": "${calendar_id}"}, "expect": [201]},
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == []
    # SAVED value 11 wins, NOT the more-recent last_id 77
    assert str(seen[-1]["calendar_id"]) == "11"


def test_unsaved_fk_resolves_to_the_RIGHT_resource_not_global_last_id(monkeypatch):
    """outlook run-8: a chain creates a calendar, then a MESSAGE, then an event with an
    UNSAVED {"calendar_id":"${calendar_id}"}. The global-last_id fallback would resolve it
    to the MESSAGE id (created last) -> events_calendar_id_fkey VIOLATION. Fix #10 resolves
    `${calendar_id}` to the last CALENDAR id (by resource), not whatever was most recent."""
    seen = []

    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/calendars") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":10}}'}        # calendar id 10
        if url.endswith("/api/messages") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":20}}'}        # message id 20 (global last_id)
        if url.endswith("/api/events") and method == "POST":
            seen.append(body)
            cid = (body or {}).get("calendar_id")
            if cid == 10:                                                    # only the REAL calendar id passes
                return {"status": 201, "body_text": '{"item":{"id":99}}'}
            return {"status": 500, "body_text": '{"detail":"ForeignKeyViolation events_calendar_id_fkey"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "cal_msg_event", "steps": [
        {"method": "POST", "path": "/api/calendars", "body": {"name": "W"}, "expect": [201]},   # id 10
        {"method": "POST", "path": "/api/messages", "body": {"subject": "x"}, "expect": [201]},  # id 20 (interloper)
        {"method": "POST", "path": "/api/events",
         "body": {"calendar_id": "${calendar_id}", "title": "Sync"}, "expect": [201]},           # unsaved FK
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == [], out["broken"]
    assert seen[-1]["calendar_id"] == 10        # the CALENDAR id, not the message id (20)


def test_bare_brace_fk_placeholder_in_body_resolves(monkeypatch):
    """outlook run-11 M3: the verifier authored a BARE {folder_id} (not ${folder_id}) in a
    POST body → the literal reached the int column → 500. A whole-value {name_id} is an
    unambiguous FK ref and must resolve to the right resource id like ${name_id}."""
    seen = []

    def fake_http(method, url, token=None, body=None, **_kw):
        if url.endswith("/api/folders") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":7}}'}
        if url.endswith("/api/messages") and method == "POST":
            seen.append(body)
            fid = (body or {}).get("folder_id")
            if fid == 7:
                return {"status": 201, "body_text": '{"item":{"id":1}}'}
            return {"status": 500, "body_text": '{"detail":"invalid input syntax for type integer"}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "folder_msg", "steps": [
        {"method": "POST", "path": "/api/folders", "body": {"name": "F"}, "expect": [201]},   # folder id 7
        {"method": "POST", "path": "/api/messages",
         "body": {"folder_id": "{folder_id}", "subject": "x"}, "expect": [201]},               # BARE brace FK
    ]}
    out = ce.execute_chain("http://x", chain)
    assert out["broken"] == [], out["broken"]
    assert seen[-1]["folder_id"] == 7          # bare {folder_id} → the folder's id (not the literal)


def test_bare_non_fk_literal_is_left_alone():
    # a bare {status} (not _id) / {rand} whole-value is NOT an FK token → left as-is (literal-safe)
    r = ce._resolve_unresolved_dollar_vars({"note": "{status}", "x": "{rand}"}, 9, {})
    assert r == {"note": "{status}", "x": "{rand}"}


def test_resource_from_path():
    assert ce._resource_from_path("/api/calendars") == "calendar"
    assert ce._resource_from_path("/api/events") == "event"
    assert ce._resource_from_path("/api/messages?folder=1") == "message"
    assert ce._resource_from_path("/api/calendars/5") is None        # by-id, not a collection
    assert ce._resource_from_path("/api/events/${id}") is None       # path param
    assert ce._resource_from_path("/api/events/{id}") is None
    assert ce._resource_from_path("/auth/login") == "login"          # non-FK, harmless


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
