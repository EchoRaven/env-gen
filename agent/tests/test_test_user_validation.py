"""Post-milestone TEST-USER validation — the automated hand-verification.

Simulates a real user's journey across the API (+ checks the MCP surface is complete)
and flags any broken step, so a milestone never ships a broken contract silently. The
journey is built to catch the exact route_projector defects found by hand on instagram
MM (2026-06-09): a created post with a null owner, and a 500 on /users/{username}/posts.
"""

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import test_user_validation as tuv  # noqa: E402

_ENDPOINTS = [
    {"method": "GET", "path": "/api/users/me"},
    {"method": "POST", "path": "/api/posts"},
    {"method": "GET", "path": "/api/feed"},
    {"method": "GET", "path": "/api/users/{username}/posts"},
    {"method": "POST", "path": "/api/users/{username}/follow"},
    {"method": "POST", "path": "/api/posts/{post_id}/comments"},
    {"method": "GET", "path": "/api/explore"},
]


def _fake_http(script):
    """Build a _http stand-in that returns scripted responses by (METHOD, path-suffix)."""
    def _h(method, url, *, token=None, body=None, timeout=10):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path
        for (m, suffix), resp in script.items():
            if method.upper() == m and path.endswith(suffix):
                return resp
        return {"status": 200, "body_text": "{}", "error": None}
    return _h


def _ok(body):
    return {"status": 200, "body_text": json.dumps(body), "error": None}


def _created(body):
    return {"status": 201, "body_text": json.dumps(body), "error": None}


def test_clean_journey_passes(tmp_path, monkeypatch):
    script = {
        ("POST", "/auth/register"): _created({"access_token": "tokA"}),
        ("GET", "/api/users/me"): _ok({"username": "alpha"}),
        ("POST", "/api/posts"): _created({"item": {"id": 7, "author_id": 1}}),
        ("GET", "/api/feed"): _ok({"items": []}),
        ("GET", "/api/users/alpha/posts"): _ok({"items": [{"id": 7}]}),
        ("POST", "/api/users/alpha/follow"): _created({"item": {"id": 1}}),
        ("POST", "/api/posts/7/comments"): _created({"item": {"id": 3}}),
        ("GET", "/api/explore"): _ok({"items": []}),
    }
    monkeypatch.setattr(tuv, "_http", _fake_http(script))
    rep = tuv.run_test_user_validation(tmp_path, _ENDPOINTS, version="1.0.0",
                                       base_url="http://x:3001")
    assert rep["summary"]["api_failed"] == 0
    assert rep["summary"]["api_passed"] == rep["summary"]["api_steps"]
    # report persisted
    assert (tmp_path / "test_user_reports" / "1.0.0.json").exists()


def test_null_owner_on_create_is_flagged(tmp_path, monkeypatch):
    script = {
        ("POST", "/auth/register"): _created({"access_token": "tokA"}),
        ("GET", "/api/users/me"): _ok({"username": "alpha"}),
        # 201 but author_id is null → the route_projector owner-injection bug
        ("POST", "/api/posts"): _created({"item": {"id": 7, "author_id": None}}),
        ("GET", "/api/users/alpha/posts"): _ok({"items": []}),
    }
    monkeypatch.setattr(tuv, "_http", _fake_http(script))
    rep = tuv.run_test_user_validation(tmp_path, _ENDPOINTS, base_url="http://x:3001")
    create = next(s for s in rep["api"]["steps"] if s["action"] == "create a post")
    assert create["ok"] is False
    assert "owner" in create["note"].lower()
    assert rep["summary"]["verdict"] == "ISSUES"


def test_missing_endpoint_is_partial_not_issues(tmp_path, monkeypatch):
    """A 404/405 (feature not implemented at this milestone) → PARTIAL, not ISSUES —
    distinct from a real defect. Only counts as 'missing', never 'broken'."""
    script = {
        ("POST", "/auth/register"): _created({"access_token": "tokA"}),
        ("GET", "/api/users/me"): _ok({"username": "alpha"}),
        ("POST", "/api/posts"): {"status": 404, "body_text": '{"detail":"Not Found"}', "error": None},
        ("GET", "/api/users/alpha/posts"): {"status": 404, "body_text": "{}", "error": None},
    }
    monkeypatch.setattr(tuv, "_http", _fake_http(script))
    rep = tuv.run_test_user_validation(tmp_path, _ENDPOINTS, base_url="http://x:3001")
    assert rep["summary"]["api_failed"] == 0          # nothing BROKEN
    assert rep["summary"]["api_missing"] >= 1          # but features missing
    assert rep["summary"]["verdict"] == "PARTIAL"
    create = next(s for s in rep["api"]["steps"] if s["action"] == "create a post")
    assert create["kind"] == "missing"


def test_nested_posts_500_is_flagged(tmp_path, monkeypatch):
    script = {
        ("POST", "/auth/register"): _created({"access_token": "tokA"}),
        ("GET", "/api/users/me"): _ok({"username": "alpha"}),
        ("POST", "/api/posts"): _created({"item": {"id": 7, "author_id": 1}}),
        ("GET", "/api/users/alpha/posts"): {"status": 500, "body_text": "Internal Server Error", "error": None},
    }
    monkeypatch.setattr(tuv, "_http", _fake_http(script))
    rep = tuv.run_test_user_validation(tmp_path, _ENDPOINTS, base_url="http://x:3001")
    view = next(s for s in rep["api"]["steps"] if s["action"] == "view my posts")
    assert view["ok"] is False and view["status"] == 500
    assert any("/api/users/{username}/posts" in b for b in rep["summary"]["broken"])


def test_auth_failure_short_circuits(tmp_path, monkeypatch):
    script = {("POST", "/auth/register"): {"status": 500, "body_text": "{}", "error": None},
              ("POST", "/auth/login"): {"status": 401, "body_text": "{}", "error": None}}
    monkeypatch.setattr(tuv, "_http", _fake_http(script))
    rep = tuv.run_test_user_validation(tmp_path, _ENDPOINTS, base_url="http://x:3001")
    assert rep["summary"]["verdict"] in ("ISSUES", "ERROR")
    assert rep["api"]["actor"] is None


def test_mcp_completeness_check(tmp_path):
    # a complete MCP server: one @mcp.tool per business endpoint
    srv = tmp_path / "mcp_server" / "app"
    srv.mkdir(parents=True)
    tools = "\n".join(f"@mcp.tool\nasync def tool_{i}():\n    pass\n" for i in range(len(_ENDPOINTS)))
    (srv / "main.py").write_text(tools, encoding="utf-8")
    res = tuv._mcp_test_user(tmp_path, _ENDPOINTS)
    assert res["server_found"] is True
    assert res["tools_found"] == len(_ENDPOINTS)
    assert res["complete"] is True


def test_mcp_incomplete_flagged(tmp_path):
    srv = tmp_path / "mcp_server" / "app"
    srv.mkdir(parents=True)
    (srv / "main.py").write_text("@mcp.tool\nasync def tool_0():\n    pass\n", encoding="utf-8")
    res = tuv._mcp_test_user(tmp_path, _ENDPOINTS)  # 1 tool, many endpoints
    assert res["complete"] is False
    assert "INCOMPLETE" in res["note"]


def test_missing_mcp_server(tmp_path):
    res = tuv._mcp_test_user(tmp_path, _ENDPOINTS)
    assert res["server_found"] is False
