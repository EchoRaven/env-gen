"""FIX #83 — harvest resource ids from step RESPONSE BODIES (instagram run-3, 2026-07-06).

The verifier's business_chain was wired exactly as a human would: GET /api/feed, then
POST /api/posts/${post_id}/like — take the post id FROM the feed. But the executor only
captured ids from the canonical envelope keyed by the PATH's resource ('feed'), so
${post_id} stayed unresolved; and this app has NO bare /api/posts collection (feed/explore
serve content) → list recovery 404'd, create recovery 404'd → the LITERAL ${post_id}
reached the int path param → 422 → wedge → STUCK (run-3, 1650s). Harvest ids from every
successful response: each top-level key whose value is a list of dicts with an id →
last_id_by_resource[singular(key)] (setdefault — never clobbers an id captured from an
explicit create); one level of nested dicts too ({"posts":[{"user":{"id":42}}]} → user).
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

_FEED = ('{"posts":[{"id":10,"user_id":10,"caption":"hi",'
         '"user":{"id":42,"username":"seed_user"}}],"pagination":{"current_page":1}}')


def test_like_step_resolves_post_id_from_prior_feed_response(monkeypatch):
    """run-3 live symptom: no /api/posts collection exists — the feed body is the only
    source of a post id, and the chain reads the feed first. Must never send the literal."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 409, "body_text": '{"detail":"exists"}'}
        if url.endswith("/api/feed") and method == "GET":
            return {"status": 200, "body_text": _FEED}
        if url.endswith("/api/posts/10/like") and method == "POST":
            return {"status": 201, "body_text": '{"ok":true}'}
        return {"status": 404, "body_text": '{"detail":"Not Found"}'}   # incl. /api/posts

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/feed", "expect": [200]},
        {"method": "POST", "path": "/api/posts/${post_id}/like", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert not any("${post_id}" in u for (_m, u) in calls)
    assert any(u.endswith("/api/posts/10/like") for (_m, u) in calls)


def test_follow_resolves_user_id_from_nested_feed_row(monkeypatch):
    """no /api/users collection either — the seeded feed rows carry {"user":{"id":42}};
    one level of nested-dict harvesting must satisfy /api/users/${user_id}/follow."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/auth/register") and method == "POST":
            return {"status": 201, "body_text": '{"id":7,"token":"t"}'}   # own id 7
        if url.endswith("/api/feed") and method == "GET":
            return {"status": 200, "body_text": _FEED}
        if url.endswith("/api/users/42/follow") and method == "POST":
            return {"status": 201, "body_text": '{"ok":true}'}
        return {"status": 404, "body_text": '{"detail":"Not Found"}'}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "u_${rand}@example.com", "password": "password123"},
         "expect": [200, 201, 409]},
        {"method": "GET", "path": "/api/feed", "expect": [200]},
        {"method": "POST", "path": "/api/users/${user_id}/follow", "expect": [200, 201]}]})
    assert out["broken"] == [], out["broken"]
    assert any(u.endswith("/api/users/42/follow") for (_m, u) in calls)
    assert not any(u.endswith("/api/users/7/follow") for (_m, u) in calls)   # never self


def test_harvest_never_clobbers_an_explicitly_created_id(monkeypatch):
    """an id captured from the chain's own CREATE stays authoritative over list rows."""
    calls = []

    def fake_http(method, url, token=None, body=None, **_kw):
        calls.append((method, url))
        if url.endswith("/api/messages") and method == "POST":
            return {"status": 201, "body_text": '{"item":{"id":5}}'}     # created → id 5
        if url.endswith("/api/inbox") and method == "GET":               # a list naming messages
            return {"status": 200, "body_text": '{"messages":[{"id":99}]}'}
        if url.endswith("/api/messages/5") and method == "GET":
            return {"status": 200, "body_text": '{"item":{"id":5}}'}
        return {"status": 404, "body_text": "{}"}

    monkeypatch.setattr(ce, "_http", fake_http)
    out = ce.execute_chain("http://x", {"name": "c", "steps": [
        {"method": "POST", "path": "/api/messages", "body": {"subject": "hi"}, "expect": [201]},
        {"method": "GET", "path": "/api/inbox", "expect": [200]},
        {"method": "GET", "path": "/api/messages/${message_id}", "expect": [200]}]})
    assert out["broken"] == [], out["broken"]
    assert any(u.endswith("/api/messages/5") for (_m, u) in calls)       # created id wins
    assert not any(u.endswith("/api/messages/99") for (_m, u) in calls)


def test_http_reads_large_list_bodies_completely():
    """FIX #98 (run-16 live): _http read only 2048 bytes — after #74/#84 made seeds
    DENSE, list responses (explore ≈2.5KB+) got TRUNCATED mid-JSON → json.loads failed
    silently in BOTH the save-dig and the auto-capture/harvest → last_id never set →
    literal ${post_id} → 422 wedge. The verifier's wiring (save: posts.0.id) was
    perfect; the transport ate the body. _http must return the full JSON for bodies
    well past 2KB."""
    import http.server, threading, json as _json
    from multi_agent.runtime.validation_runner import _http

    rows = [{"id": i, "caption": "x" * 120} for i in range(1, 60)]   # ~8KB payload
    payload = _json.dumps({"items": rows}).encode()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        res = _http("GET", f"http://127.0.0.1:{srv.server_port}/api/items")
        assert res["status"] == 200
        parsed = _json.loads(res["body_text"])          # must NOT be truncated
        assert len(parsed["items"]) == 59
    finally:
        srv.shutdown()
