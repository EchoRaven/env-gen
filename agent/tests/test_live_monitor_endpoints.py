"""Cutover 28: live monitor endpoint contracts.

These tests invoke handler helpers directly (no real socket) to avoid port
flakiness in CI. The HTTP wiring is exercised once in test_e2e_http_smoke.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry


def _seed_project(root: Path, pid: str, name: str):
    ws = root / pid
    HubRegistry(ws, project_id=pid, project_name=name, human_user_id="test_user")
    return ws


def test_list_projects_endpoint_returns_empty(tmp_path):
    from live_monitor_server import build_projects_list
    payload = build_projects_list(tmp_path)
    assert payload == {"projects": []}


def test_list_projects_endpoint_returns_seeded_projects(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    _seed_project(tmp_path, "proj_b", "Beta")
    from live_monitor_server import build_projects_list
    payload = build_projects_list(tmp_path)
    ids = sorted(p["id"] for p in payload["projects"])
    assert ids == ["proj_a", "proj_b"]
    sample = payload["projects"][0]
    for field in ("id", "name", "status", "created_at", "last_active_at", "workspace_path"):
        assert field in sample


def test_list_projects_endpoint_handles_missing_root(tmp_path):
    from live_monitor_server import build_projects_list
    payload = build_projects_list(tmp_path / "does_not_exist")
    assert payload == {"projects": []}


def test_per_project_state_includes_hub_snapshots(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import build_project_state
    payload = build_project_state(tmp_path, "proj_a")
    assert payload["projectId"] == "proj_a"
    assert payload["projectName"] == "Alpha"
    assert "hubs" in payload
    for hub_name in ("codehub", "registryhub", "workhub", "eventhub", "runhub"):
        assert hub_name in payload["hubs"], f"missing hub: {hub_name}"


def test_per_project_state_unknown_project_returns_error(tmp_path):
    from live_monitor_server import build_project_state
    payload = build_project_state(tmp_path, "nope")
    assert payload.get("error")


def test_per_project_state_reuses_existing_build_state(tmp_path):
    """Existing per-project fields (recentEvents, agentCounts, etc.) still present."""
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import build_project_state
    payload = build_project_state(tmp_path, "proj_a")
    # build_state contract from pre-Cutover 28 must survive
    for key in ("projectName", "status", "agentCounts"):
        assert key in payload


def test_list_conversations_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    # Seed a conversation
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a", human_user_id="test_user")
    reg.human_console.start_conversation(target_agents=["backend"], text="hello world")
    del reg

    from live_monitor_server import build_conversations_list
    payload = build_conversations_list(tmp_path, "proj_a")
    assert "conversations" in payload
    assert len(payload["conversations"]) == 1
    convo = payload["conversations"][0]
    assert convo["last_message_text"] == "hello world"


def test_list_messages_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a", human_user_id="test_user")
    c = reg.human_console.start_conversation(target_agents=["backend"], text="msg1")
    reg.eventhub.publish_agent_reply(thread_id=c["thread_id"], agent="backend", text="reply1")
    tid = c["thread_id"]
    del reg

    from live_monitor_server import build_messages_list
    payload = build_messages_list(tmp_path, "proj_a", tid)
    assert "messages" in payload
    texts = [m["text"] for m in payload["messages"]]
    assert texts == ["msg1", "reply1"]


def test_start_conversation_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import start_conversation_call
    result = start_conversation_call(
        tmp_path, "proj_a",
        body={"target_agents": ["backend"], "text": "please scaffold", "from_user": "test_user"},
    )
    assert "thread_id" in result
    assert result["first_message_text"] == "please scaffold"


def test_send_message_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import (
        start_conversation_call,
        send_message_call,
    )
    initial = start_conversation_call(
        tmp_path, "proj_a",
        body={"target_agents": ["backend"], "text": "first", "from_user": "test_user"},
    )
    result = send_message_call(
        tmp_path, "proj_a", initial["thread_id"],
        body={"text": "second", "from_user": "test_user"},
    )
    assert result.get("ok") is True

    from live_monitor_server import build_messages_list
    msgs = build_messages_list(tmp_path, "proj_a", initial["thread_id"])
    texts = [m["text"] for m in msgs["messages"]]
    assert texts == ["first", "second"]


def test_start_conversation_validates_input(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import start_conversation_call
    result = start_conversation_call(tmp_path, "proj_a", body={"target_agents": [], "text": "x"})
    assert "error" in result
    result = start_conversation_call(tmp_path, "proj_a", body={"target_agents": ["backend"], "text": ""})
    assert "error" in result


def test_e2e_http_smoke_lists_projects_then_starts_conversation(tmp_path):
    import json
    import threading
    import time
    import urllib.request
    from functools import partial
    from http.server import ThreadingHTTPServer

    from live_monitor_server import APP_DIR, MonitorHandler

    _seed_project(tmp_path, "proj_a", "Alpha")

    handler = partial(MonitorHandler, directory=str(APP_DIR), workspaces_root=tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        # GET /api/projects
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects") as r:
            data = json.loads(r.read())
        assert len(data["projects"]) == 1

        # POST a conversation
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects/proj_a/conversations",
            data=json.dumps({"target_agents": ["backend"], "text": "smoke", "from_user": "test_user"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            convo = json.loads(r.read())
        assert "thread_id" in convo

        # GET conversations
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects/proj_a/conversations") as r:
            convos = json.loads(r.read())
        assert len(convos["conversations"]) == 1
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Cutover 30: project lifecycle endpoints
# ---------------------------------------------------------------------------


def test_create_project_endpoint(tmp_path):
    from live_monitor_server import create_project_call
    result = create_project_call(tmp_path, body={"name": "Gamma", "description": "g"})
    assert result.get("id", "").startswith("proj_")
    assert result["name"] == "Gamma"
    assert (tmp_path / result["id"] / "project.json").exists()


def test_create_project_validates_name(tmp_path):
    from live_monitor_server import create_project_call
    result = create_project_call(tmp_path, body={"name": ""})
    assert "error" in result


def test_set_project_status_endpoint(tmp_path):
    from live_monitor_server import create_project_call, set_project_status_call
    p = create_project_call(tmp_path, body={"name": "X"})
    result = set_project_status_call(tmp_path, p["id"], body={"status": "archived"})
    assert result.get("status") == "archived"


def test_set_project_status_rejects_unknown(tmp_path):
    from live_monitor_server import create_project_call, set_project_status_call
    p = create_project_call(tmp_path, body={"name": "X"})
    result = set_project_status_call(tmp_path, p["id"], body={"status": "neon"})
    assert "error" in result


def test_delete_project_requires_confirm(tmp_path):
    from live_monitor_server import create_project_call, delete_project_call
    p = create_project_call(tmp_path, body={"name": "X"})
    no_confirm = delete_project_call(tmp_path, p["id"], body={})
    assert "error" in no_confirm
    yes = delete_project_call(tmp_path, p["id"], body={"confirm": True, "confirm_name": "X"})
    assert yes.get("ok") is True
    assert not (tmp_path / p["id"]).exists()


def test_delete_project_rejects_name_mismatch(tmp_path):
    """confirm_name must match stored project name when provided."""
    from live_monitor_server import create_project_call, delete_project_call
    p = create_project_call(tmp_path, body={"name": "X"})
    result = delete_project_call(
        tmp_path, p["id"], body={"confirm": True, "confirm_name": "WRONG"}
    )
    assert "error" in result
    assert (tmp_path / p["id"]).exists()


def test_delete_project_rejects_path_traversal(tmp_path):
    """delete_project_call must refuse paths outside workspaces_root."""
    from live_monitor_server import delete_project_call
    # Build a fake workspace OUTSIDE workspaces_root and try to wipe it via the helper.
    outside = tmp_path.parent / "outside_workspace"
    outside.mkdir(exist_ok=True)
    sentinel = outside / "keep.txt"
    sentinel.write_text("must survive")
    # The id-resolver normally never returns an outside path, but defense-in-depth
    # check: even if a hostile id resolves outside, we must refuse.
    result = delete_project_call(tmp_path, "../outside_workspace", body={"confirm": True})
    assert "error" in result
    assert sentinel.exists()
    # Cleanup
    sentinel.unlink()
    outside.rmdir()


def test_e2e_http_delete_project(tmp_path):
    """End-to-end HTTP smoke for DELETE /api/projects/<id>."""
    import json
    import threading
    import urllib.request
    from functools import partial
    from http.server import ThreadingHTTPServer

    from live_monitor_server import APP_DIR, MonitorHandler, create_project_call

    created = create_project_call(tmp_path, body={"name": "Zeta"})
    pid = created["id"]

    handler = partial(MonitorHandler, directory=str(APP_DIR), workspaces_root=tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects/{pid}",
            data=json.dumps({"confirm": True, "confirm_name": "Zeta"}).encode(),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        assert data.get("ok") is True
        assert not (tmp_path / pid).exists()
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Cutover 30 Task 3: WorkHub operation endpoints
# ---------------------------------------------------------------------------


def test_workhub_create_task(tmp_path):
    from live_monitor_server import workhub_create_task_call
    _seed_project(tmp_path, "p", "P")
    result = workhub_create_task_call(
        tmp_path,
        "p",
        body={"title": "Wire login", "assignee": "backend", "priority": "P1"},
    )
    assert result.get("id", "").startswith("task_")
    assert result["title"] == "Wire login"
    assert result["metadata"]["priority"] == "P1"


def test_workhub_create_task_requires_title(tmp_path):
    from live_monitor_server import workhub_create_task_call
    _seed_project(tmp_path, "p", "P")
    result = workhub_create_task_call(tmp_path, "p", body={"title": ""})
    assert "error" in result


def test_workhub_create_task_unknown_project(tmp_path):
    from live_monitor_server import workhub_create_task_call
    result = workhub_create_task_call(tmp_path, "ghost", body={"title": "x"})
    assert "error" in result
    assert "ghost" in result["error"]


def test_workhub_set_priority(tmp_path):
    from live_monitor_server import workhub_create_task_call, workhub_set_priority_call
    _seed_project(tmp_path, "p", "P")
    created = workhub_create_task_call(tmp_path, "p", body={"title": "T"})
    assert "id" in created
    result = workhub_set_priority_call(
        tmp_path, "p", created["id"], body={"priority": "P0"}
    )
    assert result.get("metadata", {}).get("priority") == "P0"


def test_workhub_set_priority_rejects_invalid(tmp_path):
    from live_monitor_server import workhub_create_task_call, workhub_set_priority_call
    _seed_project(tmp_path, "p", "P")
    created = workhub_create_task_call(tmp_path, "p", body={"title": "T"})
    result = workhub_set_priority_call(
        tmp_path, "p", created["id"], body={"priority": "URGENT"}
    )
    assert "error" in result


def test_workhub_create_page(tmp_path):
    from live_monitor_server import workhub_create_document_call
    _seed_project(tmp_path, "p", "P")
    result = workhub_create_document_call(
        tmp_path, "p", body={"title": "Design draft", "kind": "design"}
    )
    assert result.get("id", "").startswith("doc_")
    assert result["kind"] == "design"


def test_workhub_mark_intentionally_dead(tmp_path):
    from live_monitor_server import workhub_mark_intentionally_dead_call
    _seed_project(tmp_path, "p", "P")
    result = workhub_mark_intentionally_dead_call(
        tmp_path,
        "p",
        body={"path": "src/foo.py", "reason": "demo-only utility"},
    )
    assert result.get("path") == "src/foo.py"
    assert result.get("reason") == "demo-only utility"


def test_workhub_mark_intentionally_dead_requires_fields(tmp_path):
    from live_monitor_server import workhub_mark_intentionally_dead_call
    _seed_project(tmp_path, "p", "P")
    result = workhub_mark_intentionally_dead_call(
        tmp_path, "p", body={"path": "", "reason": "x"}
    )
    assert "error" in result


# --- Cutover 30 Task 4: CodeHub operation endpoints -------------------------


def _seed_pr(ws: Path, pr_id: str, *, merge_state: str = "review") -> "tuple":
    """Seed a project workspace with a fake-PR record so we can exercise
    review/merge/check helpers without standing up a real .git tree.
    """
    reg = HubRegistry(ws, project_id=ws.name, project_name=ws.name, human_user_id="test_user")
    reg.workhub.create_task(title="seed task", agent="backend", task_id="task_seed")
    pr = {
        "id": pr_id,
        "repo_id": "main",
        "title": f"PR {pr_id}",
        "source_branch": "feat/x",
        "target_branch": "main",
        "author": "backend",
        "status": "open",
        "reviewers": ["alice", "bob"],
        "linked_tasks": ["task_seed"],
        "linked_apis": [],
        "linked_pages": [],
        "linked_consumers": [],
        "head": None,
        "checks": [],
        "reviews": [],
        "merge_state": merge_state,
    }
    reg.codehub.stores.pull_requests.update(
        lambda m: m.set(pr_id, pr, "backend"),
        change_info={"agent": "backend"},
    )
    return reg, pr


def test_codehub_open_pr_unknown_project(tmp_path):
    from live_monitor_server import codehub_open_pr_call
    result = codehub_open_pr_call(
        tmp_path,
        "ghost",
        body={"branch": "feat/x", "linked_tasks": ["task_seed"], "reviewers": ["a", "b"]},
    )
    assert "error" in result
    assert "ghost" in result["error"]


def test_codehub_open_pr_requires_branch(tmp_path):
    from live_monitor_server import codehub_open_pr_call
    _seed_project(tmp_path, "p", "P")
    result = codehub_open_pr_call(
        tmp_path,
        "p",
        body={"branch": "", "linked_tasks": ["task_seed"], "reviewers": ["a", "b"]},
    )
    assert result.get("error") == "branch is required"


def test_codehub_open_pr_requires_linked_task(tmp_path):
    from live_monitor_server import codehub_open_pr_call
    _seed_project(tmp_path, "p", "P")
    result = codehub_open_pr_call(
        tmp_path,
        "p",
        body={"branch": "feat/x", "reviewers": ["a", "b"], "author": "backend", "linked_tasks": []},
    )
    assert result.get("error") == "linked_tasks_required"


def test_codehub_submit_review_records_comment(tmp_path):
    from live_monitor_server import codehub_submit_review_call
    ws = tmp_path / "p"
    _seed_pr(ws, "pr_review")
    result = codehub_submit_review_call(
        tmp_path,
        "p",
        "pr_review",
        body={"reviewer": "alice", "state": "comment", "comments": [{"body": "nit"}]},
    )
    assert result.get("state") == "comment"
    assert result.get("reviewer") == "alice"
    assert result.get("pr_id") == "pr_review"


def test_codehub_submit_review_unknown_pr(tmp_path):
    from live_monitor_server import codehub_submit_review_call
    _seed_project(tmp_path, "p", "P")
    result = codehub_submit_review_call(
        tmp_path,
        "p",
        "pr_missing",
        body={"reviewer": "alice", "state": "comment"},
    )
    assert "error" in result
    assert "pr_missing" in result["error"]


def test_codehub_merge_pr_requires_ready_state(tmp_path):
    from live_monitor_server import codehub_merge_pr_call
    ws = tmp_path / "p"
    _seed_pr(ws, "pr_merge", merge_state="blocked")
    result = codehub_merge_pr_call(
        tmp_path, "p", "pr_merge", body={"strategy": "squash"},
    )
    # CodeHub guards merge_state != "ready"
    assert result.get("error") == "PR is not ready to merge"
    assert result.get("merge_state") == "blocked"


def test_codehub_force_merge_requires_force_flag(tmp_path):
    """UI safety gate: force_merge requires explicit body.force=True."""
    from live_monitor_server import codehub_force_merge_pr_call
    ws = tmp_path / "p"
    _seed_pr(ws, "pr_force")
    result = codehub_force_merge_pr_call(
        tmp_path,
        "p",
        "pr_force",
        body={"reason": "extensive infra rollback after audit"},
    )
    assert result.get("error") == "force_required"
    assert "force=true" in (result.get("hint") or "").lower()


def test_codehub_force_merge_rejects_short_reason(tmp_path):
    from live_monitor_server import codehub_force_merge_pr_call
    ws = tmp_path / "p"
    _seed_pr(ws, "pr_force2")
    result = codehub_force_merge_pr_call(
        tmp_path,
        "p",
        "pr_force2",
        body={"reason": "short", "force": True},
    )
    assert result.get("error") == "force_merge_reason_too_short"


def test_codehub_force_merge_publishes_audit_event(tmp_path):
    """Destructive op must publish an audit-trail event from source_hub='ui'."""
    from live_monitor_server import codehub_force_merge_pr_call
    ws = tmp_path / "p"
    reg, _ = _seed_pr(ws, "pr_audit")
    reason = "post-incident rollback approved by SRE lead"
    result = codehub_force_merge_pr_call(
        tmp_path,
        "p",
        "pr_audit",
        body={"reason": reason, "force": True, "agent": "ui_user"},
    )
    assert result.get("force_merged") is True
    assert result.get("force_reason") == reason

    # Re-resolve registry to read the persisted EventHub state
    from multi_agent.runtime.hub_registry import HubRegistry as _HR
    reg2 = _HR(ws)
    events = list(reg2.eventhub._events.value().values())
    audit = [e for e in events if e.get("source_hub") == "ui" and e.get("event_type") == "force_merge_pr"]
    assert audit, f"expected ui audit event, got: {[(e.get('source_hub'), e.get('event_type')) for e in events]}"
    payload = audit[-1].get("payload") or {}
    assert payload.get("pr_id") == "pr_audit"
    assert payload.get("agent") == "ui_user"
    assert payload.get("reason") == reason


def test_codehub_record_check(tmp_path):
    from live_monitor_server import codehub_record_check_call
    ws = tmp_path / "p"
    _seed_pr(ws, "pr_check")
    result = codehub_record_check_call(
        tmp_path,
        "p",
        "pr_check",
        body={"name": "lint", "status": "passed", "evidence": {"runner": "ruff"}},
    )
    assert result.get("name") == "lint"
    assert result.get("status") == "passed"
    assert result.get("id") == "check_pr_check_lint"


def test_codehub_record_check_unknown_project(tmp_path):
    from live_monitor_server import codehub_record_check_call
    result = codehub_record_check_call(
        tmp_path, "ghost", "pr_x", body={"name": "lint", "status": "passed"},
    )
    assert "error" in result


# --- Cutover 30 Task 5: RegistryHub / EventHub / RunHub operation endpoints ------


def test_registryhub_register_endpoint(tmp_path):
    from live_monitor_server import registryhub_register_endpoint_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_endpoint_call(
        tmp_path, "p",
        body={"method": "GET", "path": "/users", "provider": "backend"},
    )
    assert result.get("id") == "GET /users"
    assert result.get("method") == "GET"
    assert result.get("path") == "/users"
    assert result.get("provider") == "backend"


def test_registryhub_register_endpoint_requires_method_and_path(tmp_path):
    from live_monitor_server import registryhub_register_endpoint_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_endpoint_call(tmp_path, "p", body={"method": "GET"})
    assert "error" in result


def test_registryhub_register_table(tmp_path):
    from live_monitor_server import registryhub_register_table_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_table_call(
        tmp_path, "p",
        body={"name": "users", "schema": {"id": "int"}, "provider": "backend", "agent": "backend"},
    )
    assert result.get("name") == "users"
    # The write boundary normalizes the flat-map contract-tool schema
    # (``{col: "type string"}``) to the ONE canonical ``{"columns":[…]}`` shape
    # the projector understands, so every column survives re-registration
    # (previously a flat-map table collapsed to id-only ORM/DDL).
    assert result.get("schema") == {"columns": [{"name": "id", "type": "int"}]}
    assert result.get("provider") == "backend"


def test_registryhub_register_table_requires_name(tmp_path):
    from live_monitor_server import registryhub_register_table_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_table_call(tmp_path, "p", body={"schema": {}})
    assert "error" in result


def test_registryhub_register_consumer(tmp_path):
    from live_monitor_server import (
        registryhub_register_endpoint_call,
        registryhub_register_consumer_call,
    )
    _seed_project(tmp_path, "p", "P")
    # Need an endpoint first (L1 gate).
    registryhub_register_endpoint_call(
        tmp_path, "p", body={"method": "GET", "path": "/items"},
    )
    result = registryhub_register_consumer_call(
        tmp_path, "p",
        body={
            "endpoint_id": "GET /items",
            "file_path": "src/feed.py",
            "agent": "backend",
        },
    )
    assert result.get("endpoint_id") == "GET /items"
    assert result.get("file_path") == "src/feed.py"


def test_registryhub_register_consumer_unknown_endpoint(tmp_path):
    from live_monitor_server import registryhub_register_consumer_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_consumer_call(
        tmp_path, "p",
        body={
            "endpoint_id": "GET /ghost",
            "file_path": "src/x.py",
            "agent": "backend",
        },
    )
    assert result.get("error") == "endpoint_not_registered"


def test_registryhub_register_mcp_server(tmp_path):
    from live_monitor_server import registryhub_register_mcp_server_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_mcp_server_call(
        tmp_path, "p",
        body={
            "name": "github",
            "transport": "stdio",
            "endpoint": "/usr/bin/gh-mcp",
            "provider": "backend",
        },
    )
    assert result.get("name") == "github"
    assert result.get("transport") == "stdio"


def test_registryhub_register_mcp_server_rejects_invalid_transport(tmp_path):
    from live_monitor_server import registryhub_register_mcp_server_call
    _seed_project(tmp_path, "p", "P")
    result = registryhub_register_mcp_server_call(
        tmp_path, "p",
        body={"name": "x", "transport": "carrier-pigeon", "endpoint": ""},
    )
    assert "error" in result


def test_eventhub_mark_read(tmp_path):
    from live_monitor_server import eventhub_mark_read_call
    ws = tmp_path / "p"
    reg = HubRegistry(ws, project_id="p", project_name="P", human_user_id="test_user")
    ev = reg.eventhub.publish_event(
        source_hub="test", event_type="ping", payload={}, recipients=["backend"],
    )
    result = eventhub_mark_read_call(
        tmp_path, "p", "backend", body={"event_id": ev["id"]},
    )
    assert result.get("read") is True


def test_eventhub_mark_read_unknown_event(tmp_path):
    from live_monitor_server import eventhub_mark_read_call
    _seed_project(tmp_path, "p", "P")
    result = eventhub_mark_read_call(
        tmp_path, "p", "backend", body={"event_id": "evt_does_not_exist"},
    )
    assert "error" in result


def test_eventhub_mark_all_read(tmp_path):
    from live_monitor_server import eventhub_mark_all_read_call
    ws = tmp_path / "p"
    reg = HubRegistry(ws, project_id="p", project_name="P", human_user_id="test_user")
    reg.eventhub.publish_event(
        source_hub="test", event_type="ping", payload={}, recipients=["backend"],
    )
    reg.eventhub.publish_event(
        source_hub="test", event_type="ping", payload={}, recipients=["backend"],
    )
    result = eventhub_mark_all_read_call(tmp_path, "p", "backend", body={})
    assert result.get("marked_count") == 2


def test_eventhub_subscribe(tmp_path):
    from live_monitor_server import eventhub_subscribe_call
    _seed_project(tmp_path, "p", "P")
    result = eventhub_subscribe_call(
        tmp_path, "p",
        body={
            "agent": "backend",
            "source_hub": "codehub",
            "event_type": "pr_opened",
            "priority_floor": "normal",
        },
    )
    assert result.get("agent") == "backend"
    assert result.get("source_hub") == "codehub"
    assert result.get("event_type") == "pr_opened"
    assert result.get("priority_floor") == "normal"


def test_eventhub_subscribe_defaults_to_wildcards(tmp_path):
    from live_monitor_server import eventhub_subscribe_call
    _seed_project(tmp_path, "p", "P")
    result = eventhub_subscribe_call(
        tmp_path, "p",
        body={"agent": "backend"},
    )
    assert result.get("source_hub") == "*"
    assert result.get("event_type") == "*"


def test_runhub_record_run(tmp_path):
    from live_monitor_server import runhub_record_run_call
    _seed_project(tmp_path, "p", "P")
    result = runhub_record_run_call(
        tmp_path, "p",
        body={"branch": "main", "generated_dir": "/tmp/x"},
    )
    assert result.get("id", "").startswith("run_")
    assert result.get("branch") == "main"
    assert result.get("status") == "starting"


def test_runhub_record_run_unknown_project(tmp_path):
    from live_monitor_server import runhub_record_run_call
    result = runhub_record_run_call(
        tmp_path, "ghost",
        body={"branch": "main", "generated_dir": "/tmp/x"},
    )
    assert "error" in result


def test_runhub_update_run_status(tmp_path):
    from live_monitor_server import runhub_record_run_call, runhub_update_run_status_call
    _seed_project(tmp_path, "p", "P")
    run = runhub_record_run_call(
        tmp_path, "p",
        body={"branch": "main", "generated_dir": "/tmp/x"},
    )
    result = runhub_update_run_status_call(
        tmp_path, "p", run["id"],
        body={"status": "completed", "fail_count": 0},
    )
    assert result.get("status") == "completed"
    assert result.get("fail_count") == 0
    assert result.get("finished_at") is not None


def test_runhub_update_run_status_rejects_invalid_status(tmp_path):
    from live_monitor_server import runhub_record_run_call, runhub_update_run_status_call
    _seed_project(tmp_path, "p", "P")
    run = runhub_record_run_call(
        tmp_path, "p",
        body={"branch": "main", "generated_dir": "/tmp/x"},
    )
    result = runhub_update_run_status_call(
        tmp_path, "p", run["id"], body={"status": "vibing"},
    )
    assert "error" in result


# --- HTTP route wiring spot-checks for the new endpoints --------------------


def test_route_registryhub_register_endpoint_via_post(tmp_path):
    """Spot-check the do_POST dispatch path for the registryhub branch."""
    import threading
    from contextlib import closing
    import socket
    import urllib.request
    import json as _json
    from functools import partial
    from http.server import ThreadingHTTPServer

    from live_monitor_server import APP_DIR, MonitorHandler

    _seed_project(tmp_path, "p", "P")

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = partial(
        MonitorHandler,
        directory=str(APP_DIR),
        project_dir=None,
        workspaces_root=tmp_path,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects/p/registryhub/endpoints",
            data=_json.dumps({"method": "POST", "path": "/login"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert payload.get("id") == "POST /login"


def test_route_runhub_record_run_via_post(tmp_path):
    """Spot-check the do_POST dispatch path for the runhub branch."""
    import threading
    from contextlib import closing
    import socket
    import urllib.request
    import json as _json
    from functools import partial
    from http.server import ThreadingHTTPServer

    from live_monitor_server import APP_DIR, MonitorHandler

    _seed_project(tmp_path, "p", "P")

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = partial(
        MonitorHandler,
        directory=str(APP_DIR),
        project_dir=None,
        workspaces_root=tmp_path,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects/p/runhub/runs",
            data=_json.dumps({"branch": "main", "generated_dir": "/tmp/x"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert payload.get("id", "").startswith("run_")


# ---------------------------------------------------------------------------
# Cutover 32: GET /api/projects/<id>/agents (agents_config.yaml profiles)
# ---------------------------------------------------------------------------


def test_agents_endpoint_returns_known_agents(tmp_path):
    """``build_agents_list`` returns the parsed profiles from
    ``multi_agent/agents/agents_config.yaml``, keyed by agent id, including
    well-known core profiles (``orchestrator`` at minimum).
    """
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import build_agents_list
    payload = build_agents_list(tmp_path, "proj_a")
    assert "agents" in payload, payload
    agents = payload["agents"]
    assert isinstance(agents, list)
    assert len(agents) > 5, f"expected >5 agent profiles, got {len(agents)}"
    sample = agents[0]
    assert "id" in sample
    assert "name" in sample
    ids = {a["id"] for a in agents}
    assert "orchestrator" in ids


def test_agents_endpoint_unknown_project_returns_error(tmp_path):
    """``build_agents_list`` returns an ``error`` payload (not a list) when
    the project id does not resolve to a workspace.
    """
    from live_monitor_server import build_agents_list
    payload = build_agents_list(tmp_path, "does-not-exist")
    assert "error" in payload, payload
    assert "agents" not in payload


# ---------------------------------------------------------------------------
# Cutover 33 Task 2: WorkHub task lifecycle endpoints
# ---------------------------------------------------------------------------


def test_claim_task(tmp_path):
    _seed_project(tmp_path, "proj_t1", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_claim_task_call
    t = workhub_create_task_call(
        tmp_path, "proj_t1",
        {"title": "do x", "description": "", "agent": "orchestrator", "priority": "P1"},
    )
    result = workhub_claim_task_call(tmp_path, "proj_t1", t["id"], {"agent": "backend"})
    assert result.get("status") == "in_progress" or "claimed_by" in result, result


def test_fail_task_requires_reason(tmp_path):
    _seed_project(tmp_path, "proj_t2", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_fail_task_call
    t = workhub_create_task_call(
        tmp_path, "proj_t2",
        {"title": "x", "description": "", "agent": "o", "priority": "P1"},
    )
    result = workhub_fail_task_call(tmp_path, "proj_t2", t["id"], {"reason": "", "agent": "o"})
    assert "error" in result


def test_complete_task(tmp_path):
    _seed_project(tmp_path, "proj_t3", "Tasks")
    from live_monitor_server import (
        workhub_create_task_call,
        workhub_claim_task_call,
        workhub_complete_task_call,
    )
    t = workhub_create_task_call(
        tmp_path, "proj_t3",
        {"title": "x", "description": "", "agent": "o", "priority": "P1"},
    )
    workhub_claim_task_call(tmp_path, "proj_t3", t["id"], {"agent": "backend"})
    result = workhub_complete_task_call(
        tmp_path, "proj_t3", t["id"],
        {"agent": "backend", "result": {"ok": True}},
    )
    assert "error" not in result, result


def test_cancel_task(tmp_path):
    _seed_project(tmp_path, "proj_t4", "Tasks")
    from live_monitor_server import workhub_create_task_call, workhub_cancel_task_call
    t = workhub_create_task_call(
        tmp_path, "proj_t4",
        {"title": "x", "description": "", "agent": "o", "priority": "P1"},
    )
    result = workhub_cancel_task_call(tmp_path, "proj_t4", t["id"], {"agent": "o"})
    assert "error" not in result, result


# ---------------------------------------------------------------------------
# Cutover 33 Task 3: WorkHub comments + decisions + plans endpoints
# ---------------------------------------------------------------------------


def test_comment_on_task(tmp_path):
    _seed_project(tmp_path, "proj_c1", "Comments")
    from live_monitor_server import workhub_create_task_call, workhub_comment_call
    t = workhub_create_task_call(
        tmp_path, "proj_c1",
        {"title": "x", "description": "", "agent": "o", "priority": "P1"},
    )
    result = workhub_comment_call(
        tmp_path, "proj_c1", t["id"],
        {"body": "looks good to me", "agent": "reviewer"},
    )
    assert "error" not in result, result


def test_record_decision_requires_fields(tmp_path):
    _seed_project(tmp_path, "proj_d1", "Decisions")
    from live_monitor_server import workhub_record_decision_call
    reg = HubRegistry(tmp_path / "proj_d1", human_user_id="test_user")
    page = reg.workhub.create_document(title="Design", agent="design", kind="design")
    page_id = page.get("page_id") or page.get("id")
    result = workhub_record_decision_call(
        tmp_path, "proj_d1", page_id,
        {"title": "", "options": [], "chosen": "", "reason": ""},
    )
    assert "error" in result
    result2 = workhub_record_decision_call(
        tmp_path, "proj_d1", page_id,
        {
            "title": "DB choice",
            "options": ["postgres", "mysql"],
            "chosen": "postgres",
            "reason": "better json support",
            "agent": "architect",
        },
    )
    assert "error" not in result2, result2


# Tier A retirement (docs/plan_task_stage_review_2026_06_03.md):
# ``test_create_plan`` deleted along with the retired
# ``workhub_create_plan_call`` HTTP handler. No UI/JSX client called
# the POST /api/projects/<id>/workhub/plans route; the underlying
# ``WorkHub.create_plan`` method retired in the same pass.


# --- Cutover 33 Task 4: RegistryHub schema refinements -------------------------


def test_registryhub_update_endpoint_schema(tmp_path):
    _seed_project(tmp_path, "proj_a1", "ApiUpdate")
    reg = HubRegistry(tmp_path / "proj_a1", human_user_id="test_user")
    ep = reg.registryhub.register_endpoint("GET", "/users", schema={}, provider="backend", agent="backend")
    # register_endpoint returns the endpoint dict; its identifier lives in "id".
    eid = ep.get("id") or ep.get("endpoint_id")
    assert eid, ep
    from live_monitor_server import registryhub_update_endpoint_schema_call
    result = registryhub_update_endpoint_schema_call(
        tmp_path, "proj_a1", eid,
        {
            "request": {"query": {}},
            "response": {"200": {"users": "array"}},
            "agent": "backend",
        },
    )
    assert "error" not in result, result
    # The new schema should be reflected on the endpoint.
    assert (result.get("schema") or {}).get("response") == {"200": {"users": "array"}}, result


def test_registryhub_deprecate_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a2", "ApiDeprecate")
    reg = HubRegistry(tmp_path / "proj_a2", human_user_id="test_user")
    ep = reg.registryhub.register_endpoint("GET", "/old", schema={}, provider="backend", agent="backend")
    eid = ep.get("id") or ep.get("endpoint_id")
    assert eid, ep
    from live_monitor_server import registryhub_deprecate_endpoint_call
    result = registryhub_deprecate_endpoint_call(
        tmp_path, "proj_a2", eid,
        {"agent": "backend"},
    )
    assert "error" not in result, result
    assert result.get("status") == "deprecated", result


def test_registryhub_update_table_schema(tmp_path):
    _seed_project(tmp_path, "proj_a3", "TableUpdate")
    reg = HubRegistry(tmp_path / "proj_a3", human_user_id="test_user")
    reg.schema_hub.register_table(
        name="users", schema={"columns": ["id"]}, provider="backend", agent="backend",
    )
    from live_monitor_server import registryhub_update_table_schema_call
    result = registryhub_update_table_schema_call(
        tmp_path, "proj_a3", "users",
        {"schema": {"columns": ["id", "email"]}, "agent": "backend"},
    )
    assert "error" not in result, result
    assert (result.get("schema") or {}).get("columns") == ["id", "email"], result


# --- Cutover 33 Task 5: CodeHub review inline-comments support ------------


def test_submit_review_with_inline_comments(tmp_path):
    _seed_project(tmp_path, "proj_r1", "ReviewInline")
    reg = HubRegistry(tmp_path / "proj_r1", human_user_id="test_user")
    # PRs require >=1 linked task (Gate 1) and >=2 distinct reviewers (Gate 3).
    reg.workhub.create_task(
        task_id="task_1", title="t", description="", agent="o",
        domain="ui", priority="P1",
    )
    pr = reg.codehub.open_pull_request(
        branch="feat/x", author="dev", title="t",
        linked_tasks=["task_1"], reviewers=["reviewer1"],
    )
    pr_id = pr.get("id") or pr.get("pr_id")
    assert pr_id, pr
    from live_monitor_server import codehub_submit_review_call
    result = codehub_submit_review_call(
        tmp_path, "proj_r1", pr_id,
        {
            "reviewer": "reviewer1",
            "state": "comment",
            "comments": ["overall good"],
            "inline_comments": [{"file": "src/x.py", "line": 1, "body": "consider X"}],
        },
    )
    assert "error" not in result, result
    assert len(result.get("inline_comments") or []) == 1


def test_submit_review_approve_requires_inline(tmp_path):
    _seed_project(tmp_path, "proj_r2", "ReviewApprove")
    reg = HubRegistry(tmp_path / "proj_r2", human_user_id="test_user")
    reg.workhub.create_task(
        task_id="task_2", title="t", description="", agent="o",
        domain="ui", priority="P1",
    )
    pr = reg.codehub.open_pull_request(
        branch="feat/y", author="dev", title="t",
        linked_tasks=["task_2"], reviewers=["r"],
    )
    pr_id = pr.get("id") or pr.get("pr_id")
    assert pr_id, pr
    from live_monitor_server import codehub_submit_review_call
    # approve without inline_comments must fail (the underlying substantive-
    # approve gate complains; the wrapper surfaces the error).
    result = codehub_submit_review_call(
        tmp_path, "proj_r2", pr_id,
        {
            "reviewer": "r",
            "state": "approve",
            "reason": "this is a sufficiently long reason to pass the gate",
            "inline_comments": [],
        },
    )
    assert "error" in result, result


class TestBlockEditorEndpoints(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call, workhub_create_document_call
        result = create_project_call(self.root, {"name": "blocks-test"})
        self.project_id = result["id"]
        page_result = workhub_create_document_call(self.root, self.project_id, {
            "title": "Design Page",
            "agent": "test",
        })
        self.assertNotIn("error", page_result, page_result)
        self.page_id = page_result.get("id")

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_append_block_creates_block(self):
        from live_monitor_server import workhub_append_block_call, _resolve_hubs
        result = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "Hello world", "agent": "alice",
        })
        self.assertNotIn("error", result, result)
        self.assertIn("id", result)
        reg, _ = _resolve_hubs(self.root, self.project_id)
        blocks = reg.workhub.snapshot().get("blocks", {})
        self.assertEqual(len(blocks), 1)
        b = next(iter(blocks.values()))
        self.assertEqual(b["content"], "Hello world")
        self.assertEqual(b["type"], "text")
        self.assertEqual(b["page_id"], self.page_id)

    def test_append_block_unknown_page_returns_error(self):
        from live_monitor_server import workhub_append_block_call
        result = workhub_append_block_call(self.root, self.project_id, "page_nope", {
            "type": "text", "content": "x", "agent": "alice",
        })
        self.assertIn("error", result)

    def test_update_block_replaces_content(self):
        from live_monitor_server import workhub_append_block_call, workhub_update_block_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "before", "agent": "alice",
        })
        result = workhub_update_block_call(self.root, self.project_id, b1["id"], {
            "content": "after", "agent": "alice",
        })
        self.assertNotIn("error", result, result)
        self.assertEqual(result["content"], "after")

    def test_update_block_unknown_returns_error(self):
        from live_monitor_server import workhub_update_block_call
        result = workhub_update_block_call(self.root, self.project_id, "block_nope", {
            "content": "x", "agent": "alice",
        })
        self.assertIn("error", result)

    def test_insert_block_after_keeps_order(self):
        from live_monitor_server import workhub_append_block_call, workhub_insert_block_after_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "first", "agent": "alice",
        })
        b3 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "third", "agent": "alice",
        })
        b2 = workhub_insert_block_after_call(self.root, self.project_id, self.page_id, b1["id"], {
            "type": "text", "content": "second", "agent": "alice",
        })
        self.assertNotIn("error", b2, b2)
        # b2's ord must be between b1 and b3
        self.assertLess(b1["ord"], b2["ord"])
        self.assertLess(b2["ord"], b3["ord"])

    def test_insert_block_unknown_after_appends_at_end(self):
        from live_monitor_server import workhub_append_block_call, workhub_insert_block_after_call, _resolve_hubs
        b1 = workhub_append_block_call(self.root, self.project_id, self.page_id, {
            "type": "text", "content": "first", "agent": "alice",
        })
        result = workhub_insert_block_after_call(self.root, self.project_id, self.page_id, "nope", {
            "type": "text", "content": "should-append", "agent": "alice",
        })
        # WorkHub's insert_block_after appends when after_block_id is unknown.
        self.assertNotIn("error", result, result)
        self.assertGreater(result["ord"], b1["ord"])
