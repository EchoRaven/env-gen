# Cutover 28: Product-Grade UI (Homepage + 5-Hub Dashboard + Chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the live monitor from a single-project CRDT viewer into a product-grade multi-project workspace UI. The new UI has (1) a homepage that lists projects via `list_projects()` from Cutover 26 and lets the user create/resume one, (2) a per-project dashboard that surfaces all five hubs (CodeHub, APIHub, WorkHub, EventHub, RunHub) with hub-specific widgets, (3) a human-agent chat panel that talks to Cutover 27's `HumanConsole` so a real user can select 1+ agents and converse with them. CRDT terminology is fully stripped from the UI.

**Architecture:** `live_monitor_server.py` gains a workspaces-root mode (`--workspaces-root <dir>`) that serves 8 new JSON endpoints (project list, per-project state, conversation CRUD). The existing `--project-dir` mode keeps working unchanged. Frontend gets a new top-level route system (hash-based: `#/` = homepage, `#/projects/<id>` = project view) implemented in plain React (already loaded). The CRDT tab is replaced with five hub tabs that render from a new `_hub_snapshots(project_dir)` helper that calls `HubRegistry.snapshot()`. A new `<ChatPanel>` component talks to the conversation endpoints. CSS additions go in a new `styles/homepage.css` and `styles/chat.css` to keep the existing v0-workspace.css untouched.

**Tech Stack:** Python 3 (`http.server.ThreadingHTTPServer`), React (already in index.html via UMD), plain CSS (no build step). Reuses Cutover 26 `ProjectIndex` + Cutover 27 `HumanConsole`.

---

## Test infrastructure conventions (repo-specific — REQUIRED)

Tests live in `agent/tests/`. **Every new test file MUST start with this boilerplate**:

```python
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
```

`live_monitor_server.py` lives in `agent/env_generator/llm_generator/`, so after the boilerplate it's importable as `from live_monitor_server import ...`.

Pytest: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q`
Regressions: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

---

## File Structure

**Files to create:**
- `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx` — homepage component (project picker, new-project form, recent activity strip)
- `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx` — five hub panels: `<CodeHubPanel>`, `<APIHubPanel>`, `<WorkHubPanel>`, `<EventHubPanel>`, `<RunHubPanel>`
- `agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx` — `<ChatPanel>` (conversation list + transcript + input + agent selector)
- `agent/env_generator/llm_generator/live_monitor/src/router.jsx` — minimal hash-based router (`useRoute()` hook)
- `agent/env_generator/llm_generator/live_monitor/styles/homepage.css`
- `agent/env_generator/llm_generator/live_monitor/styles/chat.css`
- `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`
- `agent/tests/test_live_monitor_endpoints.py` — server endpoint tests
- `docs/superpowers/migration-logs/28-product-ui.md`

**Files to modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` — add `--workspaces-root` arg, 8 new endpoints, `_hub_snapshots()` helper; remove `_crdt_document` from `build_state` (still exported for back-compat tab); add `POST` support to `MonitorHandler`
- `agent/env_generator/llm_generator/live_monitor/index.html` — load new JSX files + CSS
- `agent/env_generator/llm_generator/live_monitor/src/app.jsx` — top-level router: render `<Homepage>` for `#/`, render existing per-project view for `#/projects/<id>`
- `agent/env_generator/llm_generator/live_monitor/src/views.jsx` — replace `CrdtInspector` (lines 1003-1035) with `<HubsTab>` wrapping the new `hub_panels.jsx`; remove `"crdt"` from the tab list (line 964); add `"chat"` tab that mounts `<ChatPanel>`

---

## Task 1: Pre-flight baseline

**Files:**
- None

- [ ] **Step 1: Run regressions + record baseline**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-28-product-ui
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -10
```

Expected: 7 regressions OK, ~972 discover OK (post-Cutover 27).

- [ ] **Step 2: Confirm the live monitor still starts in single-project mode (no regression)**

```bash
mkdir -p /tmp/cutover28_smoke_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py \
  --project-dir /tmp/cutover28_smoke_ws --port 4291 &
SERVER_PID=$!
sleep 1
curl -sS http://127.0.0.1:4291/api/ping
kill $SERVER_PID
```

Expected: `{"ok": true}`.

- [ ] **Step 3: Create migration log stub + commit**

```bash
mkdir -p docs/superpowers/migration-logs
cat > docs/superpowers/migration-logs/28-product-ui.md <<'EOF'
# Cutover 28: Product-Grade UI

**Branch:** `haibotong-cutover-28-product-ui`
**Date:** 2026-05-26
**Status:** in-progress

## Pre-flight baseline
- Regressions: 7 OK
- Discover: <BASELINE> OK
- Live monitor single-project mode: OK (/api/ping returns ok)
EOF
git add docs/superpowers/migration-logs/28-product-ui.md
git commit -m "Cutover 28: record pre-flight baseline"
```

---

## Task 2: Backend — workspaces-root mode + `/api/projects` endpoint (TDD)

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Create: `agent/tests/test_live_monitor_endpoints.py`

- [ ] **Step 1: Write the failing tests for `/api/projects` (in-process invocation)**

```python
# agent/tests/test_live_monitor_endpoints.py
"""Cutover 28: live monitor endpoint contracts.

These tests invoke handler helpers directly (no real socket) to avoid port
flakiness in CI. The HTTP wiring is exercised once in test_e2e_http_smoke.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry


def _seed_project(root: Path, pid: str, name: str):
    ws = root / pid
    HubRegistry(ws, project_id=pid, project_name=name)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: All FAIL — `ImportError: cannot import name 'build_projects_list'`.

- [ ] **Step 3: Implement `build_projects_list` + `--workspaces-root` flag**

Add this helper to `agent/env_generator/llm_generator/live_monitor_server.py`, near `build_state` (~line 1386):

```python
def build_projects_list(workspaces_root: Path) -> dict:
    """List all projects under a workspaces-root for the homepage."""
    from multi_agent.runtime.project import ProjectIndex
    if not workspaces_root.exists():
        return {"projects": []}
    idx = ProjectIndex(workspaces_root)
    projects = []
    for md in idx.list():
        workspace = workspaces_root / md.id
        # Fall back to scanning for the actual workspace dir if names differ
        if not workspace.exists():
            for child in workspaces_root.iterdir():
                if not child.is_dir():
                    continue
                from multi_agent.runtime.project import load_project_metadata
                m = load_project_metadata(child)
                if m and m.id == md.id:
                    workspace = child
                    break
        projects.append({
            "id": md.id,
            "name": md.name,
            "description": md.description,
            "status": md.status,
            "created_at": md.created_at,
            "last_active_at": md.last_active_at,
            "workspace_path": str(workspace),
        })
    return {"projects": projects}
```

Then modify the `MonitorHandler.__init__` and `do_GET`:

```python
class MonitorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, project_dir: Optional[Path] = None,
                 workspaces_root: Optional[Path] = None, **kwargs):
        self._project_dir = project_dir
        self._workspaces_root = workspaces_root
        super().__init__(*args, directory=directory, **kwargs)
```

Add routing for the new endpoint at the top of `do_GET` (before the existing `/api/state` check):

```python
        if parsed.path == "/api/projects":
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._write_json(build_projects_list(self._workspaces_root))
            return
```

Modify `main()` to accept `--workspaces-root`:

```python
    parser.add_argument("--project-dir", help="Single project directory (legacy mode)")
    parser.add_argument("--workspaces-root", help="Parent dir containing per-project workspaces (multi-project mode)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4210)
    args = parser.parse_args()

    if not args.project_dir and not args.workspaces_root:
        parser.error("must supply either --project-dir or --workspaces-root")

    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    workspaces_root = Path(args.workspaces_root).resolve() if args.workspaces_root else None
    handler = partial(
        MonitorHandler,
        directory=str(APP_DIR),
        project_dir=project_dir,
        workspaces_root=workspaces_root,
    )
```

(Remove the existing `--project-dir` required=True; rely on the explicit check.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py \
        agent/tests/test_live_monitor_endpoints.py
git commit -m "Cutover 28: live monitor --workspaces-root mode + /api/projects endpoint"
```

---

## Task 3: Backend — per-project state with hub snapshots

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Modify: `agent/tests/test_live_monitor_endpoints.py`

- [ ] **Step 1: Append failing tests for `/api/projects/<id>/state`**

Append to `test_live_monitor_endpoints.py`:

```python
def test_per_project_state_includes_hub_snapshots(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    from live_monitor_server import build_project_state
    payload = build_project_state(tmp_path, "proj_a")
    assert payload["projectId"] == "proj_a"
    assert payload["projectName"] == "Alpha"
    assert "hubs" in payload
    for hub_name in ("codehub", "apihub", "workhub", "eventhub", "runhub"):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: 3 prior PASS, 3 new FAIL with `ImportError: build_project_state`.

- [ ] **Step 3: Implement `build_project_state` + endpoint routing**

In `live_monitor_server.py`, add this helper:

```python
def _hub_snapshots(workspace: Path) -> dict:
    """Return {hub_name: snapshot} for all five hubs by constructing HubRegistry."""
    from multi_agent.runtime.hub_registry import HubRegistry
    try:
        reg = HubRegistry(workspace)
        return reg.snapshot()
    except Exception as e:
        return {
            "error": f"failed to load hub snapshots: {e}",
            "codehub": {},
            "apihub": {},
            "workhub": {},
            "eventhub": {},
            "runhub": {},
        }


def build_project_state(workspaces_root: Path, project_id: str) -> dict:
    """Per-project dashboard payload."""
    from multi_agent.runtime.project import ProjectIndex
    idx = ProjectIndex(workspaces_root)
    md, workspace = idx.get(project_id)
    if md is None or workspace is None:
        return {"error": f"project not found: {project_id}"}
    state = build_state(workspace)
    state["projectId"] = md.id
    state["projectName"] = md.name
    state["projectStatus"] = md.status
    state["projectDescription"] = md.description
    state["hubs"] = _hub_snapshots(workspace)
    return state
```

Add to `do_GET` (after the `/api/projects` block):

```python
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/state"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            # /api/projects/<id>/state
            pid = parsed.path[len("/api/projects/"):-len("/state")]
            self._write_json(build_project_state(self._workspaces_root, pid))
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py \
        agent/tests/test_live_monitor_endpoints.py
git commit -m "Cutover 28: /api/projects/<id>/state with 5-hub snapshots"
```

---

## Task 4: Backend — conversation CRUD endpoints

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Modify: `agent/tests/test_live_monitor_endpoints.py`

- [ ] **Step 1: Append failing tests for conversation endpoints**

Append to `test_live_monitor_endpoints.py`:

```python
def test_list_conversations_endpoint(tmp_path):
    _seed_project(tmp_path, "proj_a", "Alpha")
    # Seed a conversation
    from multi_agent.runtime.hub_registry import HubRegistry
    reg = HubRegistry(tmp_path / "proj_a")
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
    reg = HubRegistry(tmp_path / "proj_a")
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
        body={"target_agents": ["backend"], "text": "please scaffold"},
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
        body={"target_agents": ["backend"], "text": "first"},
    )
    result = send_message_call(
        tmp_path, "proj_a", initial["thread_id"],
        body={"text": "second"},
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: 6 prior PASS, 5 new FAIL with `ImportError`.

- [ ] **Step 3: Implement the conversation helpers + endpoints**

Add to `live_monitor_server.py`:

```python
def _project_workspace(workspaces_root: Path, project_id: str) -> Optional[Path]:
    from multi_agent.runtime.project import ProjectIndex
    _, workspace = ProjectIndex(workspaces_root).get(project_id)
    return workspace


def build_conversations_list(workspaces_root: Path, project_id: str) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}", "conversations": []}
    reg = HubRegistry(workspace)
    return {"conversations": reg.human_console.list_conversations()}


def build_messages_list(workspaces_root: Path, project_id: str, thread_id: str) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}", "messages": []}
    reg = HubRegistry(workspace)
    try:
        return {"messages": reg.human_console.list_messages(thread_id)}
    except ValueError as e:
        return {"error": str(e), "messages": []}


def start_conversation_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    reg = HubRegistry(workspace)
    try:
        return reg.human_console.start_conversation(
            target_agents=body.get("target_agents") or [],
            text=body.get("text") or "",
            from_user=body.get("from_user") or "human_user",
        )
    except ValueError as e:
        return {"error": str(e)}


def send_message_call(workspaces_root: Path, project_id: str, thread_id: str, body: dict) -> dict:
    from multi_agent.runtime.hub_registry import HubRegistry
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    reg = HubRegistry(workspace)
    try:
        reg.human_console.send_message(
            thread_id=thread_id,
            text=body.get("text") or "",
            from_user=body.get("from_user") or "human_user",
        )
        return {"ok": True}
    except ValueError as e:
        return {"error": str(e)}
```

Add `do_POST` to `MonitorHandler` (whole new method) and route additions in `do_GET`:

```python
    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_POST(self) -> None:  # noqa: N802
        if self._workspaces_root is None:
            self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
            return
        parsed = urlparse(self.path)
        body = self._read_json_body()
        # POST /api/projects/<id>/conversations
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/conversations"):
            pid = parsed.path[len("/api/projects/"):-len("/conversations")]
            self._write_json(start_conversation_call(self._workspaces_root, pid, body))
            return
        # POST /api/projects/<id>/conversations/<tid>/messages
        marker = "/conversations/"
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/messages") and marker in parsed.path:
            head, tail = parsed.path.split(marker, 1)
            pid = head[len("/api/projects/"):]
            tid = tail[: -len("/messages")]
            self._write_json(send_message_call(self._workspaces_root, pid, tid, body))
            return
        self._write_json({"error": "unknown endpoint"}, status=HTTPStatus.NOT_FOUND)
```

Add GET routes to `do_GET` (after the per-project state route):

```python
        # GET /api/projects/<id>/conversations
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/conversations"):
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            pid = parsed.path[len("/api/projects/"):-len("/conversations")]
            self._write_json(build_conversations_list(self._workspaces_root, pid))
            return
        # GET /api/projects/<id>/conversations/<tid>/messages
        marker = "/conversations/"
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/messages") and marker in parsed.path:
            if self._workspaces_root is None:
                self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
                return
            head, tail = parsed.path.split(marker, 1)
            pid = head[len("/api/projects/"):]
            tid = tail[: -len("/messages")]
            self._write_json(build_messages_list(self._workspaces_root, pid, tid))
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py -v`

Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py \
        agent/tests/test_live_monitor_endpoints.py
git commit -m "Cutover 28: conversation CRUD endpoints + do_POST on MonitorHandler"
```

---

## Task 5: Backend — HTTP e2e smoke

**Files:**
- Modify: `agent/tests/test_live_monitor_endpoints.py`

- [ ] **Step 1: Append the HTTP smoke test**

Append to `test_live_monitor_endpoints.py`:

```python
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
            data=json.dumps({"target_agents": ["backend"], "text": "smoke"}).encode(),
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
```

- [ ] **Step 2: Run + expect pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py::test_e2e_http_smoke_lists_projects_then_starts_conversation -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_live_monitor_endpoints.py
git commit -m "Cutover 28: HTTP e2e smoke for /api/projects + POST conversation"
```

---

## Task 6: Frontend — minimal router + Homepage component

**Files:**
- Create: `agent/env_generator/llm_generator/live_monitor/src/router.jsx`
- Create: `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`
- Create: `agent/env_generator/llm_generator/live_monitor/styles/homepage.css`
- Modify: `agent/env_generator/llm_generator/live_monitor/index.html` (load new files)
- Modify: `agent/env_generator/llm_generator/live_monitor/src/app.jsx` (route between Homepage and existing view)

- [ ] **Step 1: Write the router**

Create `agent/env_generator/llm_generator/live_monitor/src/router.jsx`:

```jsx
// Cutover 28: minimal hash-based router.
// Routes:
//   #/                   -> { kind: "home" }
//   #/projects/<id>      -> { kind: "project", projectId: <id> }
const { useState, useEffect } = window.React;

function parseHash(hash) {
  const clean = (hash || "").replace(/^#/, "");
  if (!clean || clean === "/") return { kind: "home" };
  const match = clean.match(/^\/projects\/([^/]+)\/?$/);
  if (match) return { kind: "project", projectId: decodeURIComponent(match[1]) };
  return { kind: "home" };
}

function useRoute() {
  const [route, setRoute] = useState(parseHash(window.location.hash));
  useEffect(() => {
    function onHashChange() {
      setRoute(parseHash(window.location.hash));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return route;
}

function navigateTo(path) {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
}

window.LiveMonitorRouter = { useRoute, navigateTo };
```

- [ ] **Step 2: Write the Homepage component**

Create `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`:

```jsx
const { useEffect, useState } = window.React;

function Homepage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      const resp = await fetch("/api/projects");
      const data = await resp.json();
      setProjects(data.projects || []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  }

  function statusBadge(status) {
    const cls = {
      active: "status-active",
      completed: "status-completed",
      failed: "status-failed",
      paused: "status-paused",
      archived: "status-archived",
    }[status] || "status-other";
    return <span className={`status-pill ${cls}`}>{status}</span>;
  }

  return (
    <div className="homepage">
      <header className="homepage-header">
        <h1>env-gen workspaces</h1>
        <p className="homepage-subtitle">
          Select a project to view its hubs, chat with agents, or resume work.
        </p>
      </header>

      {loading && <div className="homepage-loading">Loading projects…</div>}
      {error && <div className="homepage-error">Error: {error}</div>}
      {!loading && projects.length === 0 && (
        <div className="homepage-empty">
          No projects yet. Run the orchestrator to generate one — it will appear here.
        </div>
      )}

      <ul className="project-grid">
        {projects.map((p) => (
          <li
            key={p.id}
            className="project-card"
            onClick={() => window.LiveMonitorRouter.navigateTo(`/projects/${p.id}`)}
          >
            <div className="project-card-row">
              <h2 className="project-card-title">{p.name}</h2>
              {statusBadge(p.status)}
            </div>
            <p className="project-card-desc">{p.description || <em>no description</em>}</p>
            <div className="project-card-meta">
              <span>Created: {fmtTime(p.created_at)}</span>
              <span>Last active: {fmtTime(p.last_active_at)}</span>
            </div>
            <code className="project-card-id">{p.id}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

window.LiveMonitorHomepage = Homepage;
```

- [ ] **Step 3: Add Homepage styles**

Create `agent/env_generator/llm_generator/live_monitor/styles/homepage.css`:

```css
.homepage {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
  color: #d4d4d4;
}
.homepage-header h1 {
  font-size: 28px;
  margin: 0 0 8px;
  letter-spacing: -0.5px;
}
.homepage-subtitle { color: #888; margin: 0 0 32px; }
.homepage-loading,
.homepage-error,
.homepage-empty {
  padding: 32px;
  text-align: center;
  border: 1px dashed #333;
  border-radius: 8px;
  color: #888;
}
.homepage-error { color: #ff6b6b; border-color: #5a2a2a; }
.project-grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.project-card {
  background: #181b20;
  border: 1px solid #2a2f37;
  border-radius: 10px;
  padding: 20px;
  cursor: pointer;
  transition: border-color 120ms, transform 120ms;
}
.project-card:hover {
  border-color: #4a90e2;
  transform: translateY(-2px);
}
.project-card-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.project-card-title {
  font-size: 18px;
  margin: 0;
  color: #fff;
}
.project-card-desc {
  margin: 0 0 16px;
  color: #aaa;
  font-size: 13px;
  line-height: 1.5;
  min-height: 38px;
}
.project-card-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #777;
  margin-bottom: 12px;
}
.project-card-id {
  font-size: 11px;
  color: #555;
  font-family: monospace;
}
.status-pill {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}
.status-active { background: #1f3a5f; color: #6cb6ff; }
.status-completed { background: #1d3a26; color: #6ed191; }
.status-failed { background: #4a1f1f; color: #ff8a8a; }
.status-paused { background: #3a2f0c; color: #f0c674; }
.status-archived { background: #2a2a2a; color: #888; }
.status-other { background: #2a2a2a; color: #888; }
```

- [ ] **Step 4: Wire into index.html**

Read first: `cat agent/env_generator/llm_generator/live_monitor/index.html`

Then add the new CSS link and JS script tags. The pattern should match how existing files are loaded. Add into the `<head>`:

```html
<link rel="stylesheet" href="styles/homepage.css">
```

And add before the existing app.jsx script tag (so router/homepage are defined first):

```html
<script type="text/babel" src="src/router.jsx"></script>
<script type="text/babel" src="src/homepage.jsx"></script>
```

- [ ] **Step 5: Modify app.jsx to route**

Read `agent/env_generator/llm_generator/live_monitor/src/app.jsx`. At the top of the main exported component (commonly `App`), invoke the router and render conditionally. Wrap the existing render content into the project branch. Example pattern (adapt to actual code shape):

```jsx
// At top of App component:
const route = window.LiveMonitorRouter.useRoute();

if (route.kind === "home") {
  return <window.LiveMonitorHomepage />;
}

// route.kind === "project" — fall through to existing project view.
// If your existing code reads state from /api/state, change it to
// /api/projects/${route.projectId}/state in the fetch call(s) below.
```

Find every `fetch("/api/state")` call in `app.jsx` and replace with:

```jsx
fetch(`/api/projects/${route.projectId}/state`)
```

If `app.jsx` has its main fetch in `useEffect`, also add `route.projectId` to its dep list.

- [ ] **Step 6: Manual smoke test of the homepage**

Run:

```bash
mkdir -p /tmp/cutover28_ws
/home/haibotong/miniconda3/envs/dt/bin/python -c "
from pathlib import Path
from multi_agent.runtime.hub_registry import HubRegistry
HubRegistry(Path('/tmp/cutover28_ws/proj_alpha'), project_id='proj_alpha', project_name='Alpha Demo', project_description='hello world demo')
HubRegistry(Path('/tmp/cutover28_ws/proj_beta'), project_id='proj_beta', project_name='Beta Trial')
print('seeded')
"

/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py \
  --workspaces-root /tmp/cutover28_ws --port 4292 &
sleep 1
curl -sS http://127.0.0.1:4292/api/projects | python -m json.tool
kill %1
```

Expected: JSON listing both projects with names "Alpha Demo" and "Beta Trial".

If you have a browser, open `http://127.0.0.1:4292/#/` and verify the homepage renders both cards. (Skip if no browser — endpoint smoke is enough.)

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/live_monitor/src/router.jsx \
        agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/homepage.css \
        agent/env_generator/llm_generator/live_monitor/index.html \
        agent/env_generator/llm_generator/live_monitor/src/app.jsx
git commit -m "Cutover 28: homepage + hash router + per-project state fetch"
```

---

## Task 7: Frontend — 5-hub panels + replace CRDT tab

**Files:**
- Create: `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx`
- Create: `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`
- Modify: `agent/env_generator/llm_generator/live_monitor/src/views.jsx` (replace CrdtInspector and tab list)
- Modify: `agent/env_generator/llm_generator/live_monitor/index.html`

- [ ] **Step 1: Write hub_panels.jsx**

Create `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx`:

```jsx
const { useState } = window.React;

function HubCard({ title, count, subtitle, children, accent }) {
  return (
    <div className="hub-card" style={{ borderLeftColor: accent }}>
      <div className="hub-card-header">
        <h3>{title}</h3>
        {count !== undefined && <span className="hub-card-count">{count}</span>}
      </div>
      {subtitle && <p className="hub-card-subtitle">{subtitle}</p>}
      <div className="hub-card-body">{children}</div>
    </div>
  );
}

function CodeHubPanel({ snapshot }) {
  const s = snapshot || {};
  const commits = s.commits || s.commit_count || 0;
  const files = s.files || s.file_count || 0;
  return (
    <HubCard title="CodeHub" count={commits} subtitle={`${files} tracked files`} accent="#6cb6ff">
      <pre className="hub-snapshot">{JSON.stringify(s, null, 2)}</pre>
    </HubCard>
  );
}

function APIHubPanel({ snapshot }) {
  const s = snapshot || {};
  const endpoints = (s.endpoints && Object.keys(s.endpoints).length) || s.endpoint_count || 0;
  const tables = (s.tables && Object.keys(s.tables).length) || s.table_count || 0;
  return (
    <HubCard title="APIHub" count={endpoints} subtitle={`${tables} tables`} accent="#f0c674">
      <pre className="hub-snapshot">{JSON.stringify(s, null, 2)}</pre>
    </HubCard>
  );
}

function WorkHubPanel({ snapshot }) {
  const s = snapshot || {};
  const tasks = (s.tasks && Object.keys(s.tasks).length) || s.task_count || 0;
  const pages = (s.pages && Object.keys(s.pages).length) || s.page_count || 0;
  return (
    <HubCard title="WorkHub" count={tasks} subtitle={`${pages} pages`} accent="#6ed191">
      <pre className="hub-snapshot">{JSON.stringify(s, null, 2)}</pre>
    </HubCard>
  );
}

function EventHubPanel({ snapshot }) {
  const s = snapshot || {};
  const events = (s.events && Object.keys(s.events).length) || s.event_count || 0;
  const threads = (s.threads && Object.keys(s.threads).length) || s.thread_count || 0;
  return (
    <HubCard title="EventHub" count={events} subtitle={`${threads} threads`} accent="#c594c5">
      <pre className="hub-snapshot">{JSON.stringify(s, null, 2)}</pre>
    </HubCard>
  );
}

function RunHubPanel({ snapshot }) {
  const s = snapshot || {};
  const runs = (s.runs && Object.keys(s.runs).length) || s.run_count || 0;
  return (
    <HubCard title="RunHub" count={runs} subtitle="end-to-end run history" accent="#ff8a8a">
      <pre className="hub-snapshot">{JSON.stringify(s, null, 2)}</pre>
    </HubCard>
  );
}

function HubsTab({ hubs }) {
  const h = hubs || {};
  return (
    <div className="hubs-grid">
      <CodeHubPanel snapshot={h.codehub} />
      <APIHubPanel snapshot={h.apihub} />
      <WorkHubPanel snapshot={h.workhub} />
      <EventHubPanel snapshot={h.eventhub} />
      <RunHubPanel snapshot={h.runhub} />
    </div>
  );
}

window.LiveMonitorHubsTab = HubsTab;
```

- [ ] **Step 2: Add hubs.css**

Create `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`:

```css
.hubs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 16px;
  padding: 16px;
}
.hub-card {
  background: #181b20;
  border: 1px solid #2a2f37;
  border-left: 4px solid #555;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  min-height: 200px;
}
.hub-card-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}
.hub-card-header h3 {
  margin: 0;
  font-size: 16px;
  color: #fff;
}
.hub-card-count {
  font-size: 22px;
  font-weight: 700;
  color: #6cb6ff;
}
.hub-card-subtitle {
  color: #888;
  font-size: 12px;
  margin: 0 0 12px;
}
.hub-card-body {
  flex: 1;
  overflow: auto;
  background: #0e1014;
  border-radius: 6px;
  padding: 8px;
}
.hub-snapshot {
  font-size: 11px;
  color: #bbb;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
```

- [ ] **Step 3: Modify views.jsx — replace CrdtInspector with HubsTab + drop CRDT tab**

Read `agent/env_generator/llm_generator/live_monitor/src/views.jsx` lines 960-1040.

Then:

1. Replace the tab array at line 964:
   ```jsx
   {["preview", "code", "crdt", "logs"].map((item) => (
   ```
   with:
   ```jsx
   {["preview", "code", "hubs", "chat", "logs"].map((item) => (
   ```

2. Replace the conditional rendering at line 992:
   ```jsx
   {tab === "crdt" ? <CrdtInspector crdt={state?.crdt} /> : null}
   ```
   with:
   ```jsx
   {tab === "hubs" ? <window.LiveMonitorHubsTab hubs={state?.hubs} /> : null}
   {tab === "chat" ? <window.LiveMonitorChatPanel projectId={state?.projectId} /> : null}
   ```

3. Delete (or comment out) the entire `function CrdtInspector({ crdt })` block from line 1003 to line 1035. The associated CSS classes (.crdt-pane, .crdt-sidebar, etc.) can stay — they're scoped enough that removing them is risky to existing screens. Mark the deletion explicit by leaving a one-line note:
   ```jsx
   // Cutover 28: CrdtInspector replaced by HubsTab (window.LiveMonitorHubsTab)
   ```

- [ ] **Step 4: Add the new scripts + stylesheet to index.html**

In `<head>`:
```html
<link rel="stylesheet" href="styles/hubs.css">
```

Before `app.jsx`:
```html
<script type="text/babel" src="src/hub_panels.jsx"></script>
```

- [ ] **Step 5: Commit (chat tab body to be wired in Task 8)**

```bash
git add agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/hubs.css \
        agent/env_generator/llm_generator/live_monitor/src/views.jsx \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 28: 5-hub HubsTab replaces CRDT inspector; add chat tab slot"
```

---

## Task 8: Frontend — ChatPanel component

**Files:**
- Create: `agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx`
- Create: `agent/env_generator/llm_generator/live_monitor/styles/chat.css`
- Modify: `agent/env_generator/llm_generator/live_monitor/index.html`

- [ ] **Step 1: Write the ChatPanel component**

Create `agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx`:

```jsx
const { useState, useEffect, useRef } = window.React;

const KNOWN_AGENTS = [
  "orchestrator", "design", "database", "backend", "frontend",
  "verifier", "knowledge", "bug_triage_orchestrator",
  "architect_reviewer", "visual_reviewer", "analysis_worker",
  "review_worker", "worker",
];

function ChatPanel({ projectId }) {
  const [conversations, setConversations] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [agentSelector, setAgentSelector] = useState(false);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [error, setError] = useState(null);
  const messagesEndRef = useRef(null);

  async function refreshConversations() {
    if (!projectId) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations`);
      const data = await r.json();
      setConversations(data.conversations || []);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function refreshMessages(threadId) {
    if (!projectId || !threadId) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations/${threadId}/messages`);
      const data = await r.json();
      setMessages(data.messages || []);
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    refreshConversations();
    const id = setInterval(refreshConversations, 3000);
    return () => clearInterval(id);
  }, [projectId]);

  useEffect(() => {
    if (activeThread) {
      refreshMessages(activeThread);
      const id = setInterval(() => refreshMessages(activeThread), 2000);
      return () => clearInterval(id);
    }
  }, [activeThread, projectId]);

  async function startNew() {
    if (!draft.trim() || selectedAgents.length === 0) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_agents: selectedAgents, text: draft }),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); return; }
      setDraft("");
      setAgentSelector(false);
      setSelectedAgents([]);
      await refreshConversations();
      setActiveThread(data.thread_id);
    } catch (e) {
      setError(String(e));
    }
  }

  async function sendInThread() {
    if (!draft.trim() || !activeThread) return;
    try {
      const r = await fetch(`/api/projects/${projectId}/conversations/${activeThread}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: draft }),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); return; }
      setDraft("");
      await refreshMessages(activeThread);
    } catch (e) {
      setError(String(e));
    }
  }

  function toggleAgent(name) {
    setSelectedAgents((prev) =>
      prev.includes(name) ? prev.filter((a) => a !== name) : [...prev, name]
    );
  }

  return (
    <div className="chat-panel">
      <div className="chat-sidebar">
        <button className="chat-new-btn" onClick={() => { setActiveThread(null); setAgentSelector(true); }}>
          + New conversation
        </button>
        <ul className="chat-conversation-list">
          {conversations.map((c) => (
            <li
              key={c.thread_id}
              className={`chat-conversation-item ${activeThread === c.thread_id ? "active" : ""}`}
              onClick={() => { setActiveThread(c.thread_id); setAgentSelector(false); }}
            >
              <div className="chat-conv-participants">{c.participants.filter(p => p !== "human_user").join(", ")}</div>
              <div className="chat-conv-preview">{c.last_message_text || <em>no messages</em>}</div>
              <div className="chat-conv-meta">{c.message_count} msg · {c.status}</div>
            </li>
          ))}
          {conversations.length === 0 && <li className="chat-empty">No conversations yet.</li>}
        </ul>
      </div>

      <div className="chat-main">
        {error && <div className="chat-error">{error}</div>}

        {agentSelector && (
          <div className="chat-agent-selector">
            <h4>Choose one or more agents:</h4>
            <div className="chat-agent-grid">
              {KNOWN_AGENTS.map((a) => (
                <button
                  key={a}
                  className={`chat-agent-chip ${selectedAgents.includes(a) ? "selected" : ""}`}
                  onClick={() => toggleAgent(a)}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>
        )}

        {!agentSelector && activeThread && (
          <div className="chat-transcript">
            {messages.map((m) => (
              <div key={m.message_id} className={`chat-msg chat-msg-${m.source === "human_user" ? "human" : "agent"}`}>
                <div className="chat-msg-source">{m.source}</div>
                <div className="chat-msg-text">{m.text}</div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}

        {!agentSelector && !activeThread && (
          <div className="chat-placeholder">
            Select a conversation or start a new one.
          </div>
        )}

        <div className="chat-input-row">
          <textarea
            className="chat-input"
            value={draft}
            placeholder={agentSelector ? "Type your message, then send to chosen agents…" : "Reply…"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                agentSelector ? startNew() : sendInThread();
              }
            }}
            rows={3}
          />
          <button
            className="chat-send-btn"
            onClick={() => agentSelector ? startNew() : sendInThread()}
            disabled={!draft.trim() || (agentSelector && selectedAgents.length === 0) || (!agentSelector && !activeThread)}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

window.LiveMonitorChatPanel = ChatPanel;
```

- [ ] **Step 2: Add chat.css**

Create `agent/env_generator/llm_generator/live_monitor/styles/chat.css`:

```css
.chat-panel {
  display: grid;
  grid-template-columns: 280px 1fr;
  height: 70vh;
  background: #0e1014;
  border: 1px solid #2a2f37;
  border-radius: 8px;
  margin: 16px;
  overflow: hidden;
}
.chat-sidebar {
  border-right: 1px solid #2a2f37;
  display: flex;
  flex-direction: column;
  background: #14171c;
}
.chat-new-btn {
  margin: 12px;
  padding: 8px 12px;
  background: #4a90e2;
  color: #fff;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}
.chat-new-btn:hover { background: #5aa0ee; }
.chat-conversation-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
}
.chat-conversation-item {
  padding: 12px;
  border-bottom: 1px solid #1f242a;
  cursor: pointer;
}
.chat-conversation-item:hover { background: #1a1e23; }
.chat-conversation-item.active { background: #1f3a5f; }
.chat-conv-participants {
  font-size: 12px;
  font-weight: 600;
  color: #6cb6ff;
  margin-bottom: 4px;
}
.chat-conv-preview {
  font-size: 12px;
  color: #aaa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chat-conv-meta {
  font-size: 10px;
  color: #666;
  margin-top: 4px;
}
.chat-empty { color: #666; padding: 16px; text-align: center; font-size: 12px; }
.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.chat-error {
  background: #4a1f1f;
  color: #ff8a8a;
  padding: 10px 16px;
  font-size: 12px;
}
.chat-agent-selector {
  padding: 24px;
}
.chat-agent-selector h4 { margin: 0 0 12px; color: #d4d4d4; }
.chat-agent-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chat-agent-chip {
  background: #14171c;
  border: 1px solid #2a2f37;
  border-radius: 999px;
  color: #aaa;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}
.chat-agent-chip:hover { border-color: #4a90e2; color: #fff; }
.chat-agent-chip.selected {
  background: #4a90e2;
  border-color: #4a90e2;
  color: #fff;
  font-weight: 600;
}
.chat-transcript {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chat-msg {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 8px;
}
.chat-msg-source {
  font-size: 11px;
  font-weight: 600;
  opacity: 0.7;
  margin-bottom: 4px;
}
.chat-msg-text {
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.chat-msg-human {
  align-self: flex-end;
  background: #1f3a5f;
  color: #d8eaff;
}
.chat-msg-agent {
  align-self: flex-start;
  background: #1d2a1f;
  color: #d6eedb;
}
.chat-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
}
.chat-input-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #2a2f37;
  background: #14171c;
}
.chat-input {
  background: #0e1014;
  color: #d4d4d4;
  border: 1px solid #2a2f37;
  border-radius: 6px;
  padding: 8px 12px;
  font-family: inherit;
  font-size: 13px;
  resize: none;
}
.chat-input:focus { outline: 1px solid #4a90e2; }
.chat-send-btn {
  background: #4a90e2;
  color: #fff;
  border: 0;
  border-radius: 6px;
  padding: 0 20px;
  font-weight: 600;
  cursor: pointer;
}
.chat-send-btn:disabled { background: #2a2f37; color: #555; cursor: not-allowed; }
```

- [ ] **Step 3: Wire into index.html**

In `<head>`:
```html
<link rel="stylesheet" href="styles/chat.css">
```

Before `app.jsx`:
```html
<script type="text/babel" src="src/chat_panel.jsx"></script>
```

- [ ] **Step 4: Manual smoke test**

```bash
mkdir -p /tmp/cutover28_chat_ws
/home/haibotong/miniconda3/envs/dt/bin/python -c "
from pathlib import Path
from multi_agent.runtime.hub_registry import HubRegistry
reg = HubRegistry(Path('/tmp/cutover28_chat_ws/proj_demo'), project_id='proj_demo', project_name='Demo')
c = reg.human_console.start_conversation(target_agents=['backend'], text='hello chat')
print('thread_id:', c['thread_id'])
"

/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py \
  --workspaces-root /tmp/cutover28_chat_ws --port 4293 &
sleep 1
curl -sS http://127.0.0.1:4293/api/projects/proj_demo/conversations | python -m json.tool
curl -sS -X POST http://127.0.0.1:4293/api/projects/proj_demo/conversations \
  -H 'Content-Type: application/json' \
  -d '{"target_agents":["frontend"],"text":"second conversation"}' | python -m json.tool
kill %1
```

Expected: First curl shows 1 conversation; second curl returns a new thread_id.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/chat.css \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 28: ChatPanel component (conversation list + transcript + agent selector)"
```

---

## Task 9: Strip remaining CRDT references + final sweep + migration log + push

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py` (optional: keep `_crdt_document` exported but stop adding to `build_state`)
- Modify: `docs/superpowers/migration-logs/28-product-ui.md`

- [ ] **Step 1: Audit remaining CRDT references**

Run:

```bash
grep -rn "crdt\|CRDT\|Crdt" agent/env_generator/llm_generator/live_monitor* 2>&1 | grep -v node_modules | grep -v "/\.[a-zA-Z]"
```

Expected output: only references inside `live_monitor_server.py:_crdt_document` (the back-compat function — leave it for backwards compat with old workspaces that still have `shared/crdt/`; the UI no longer renders this tab) and possibly orphan CSS classes (`crdt-pane`, `crdt-sidebar`, etc.) in `v0-workspace.css` — leave those alone too (zero render impact).

If you find any `state?.crdt` or `<CrdtInspector` still active in jsx files, remove them.

- [ ] **Step 2: Remove `crdt` from build_state return payload (optional housekeeping)**

In `live_monitor_server.py`, line 1410:

```python
        "crdt": _crdt_document(project_dir),
```

Change to:

```python
        # Cutover 28: crdt key kept for back-compat with older UIs; UI uses "hubs" now.
        "crdt": _crdt_document(project_dir),
```

(Leave the line — old monitor instances may still read it. Just annotate.)

- [ ] **Step 3: Full test sweep**

Run:

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -10
```

Expected:
- Regressions: 7 OK
- Discover: <baseline> + 12 (3 projects + 3 state + 5 conversations + 1 http e2e) new

- [ ] **Step 4: Update migration log**

Overwrite `docs/superpowers/migration-logs/28-product-ui.md`:

```markdown
# Cutover 28: Product-Grade UI

**Branch:** `haibotong-cutover-28-product-ui`
**Date:** 2026-05-26

## What

Live monitor moves from single-project CRDT viewer to multi-project
workspace UI. Server gains `--workspaces-root` mode + 8 JSON endpoints
(project list, per-project state with 5-hub snapshots, conversation CRUD).
Frontend gains a hash-based router, a homepage with project picker, a
5-hub dashboard panel (Code/API/Work/Event/Run), and a ChatPanel that
drives Cutover 27's HumanConsole. CRDT tab removed.

## Why

Pre-Cutover 28, the UI required `--project-dir` per-process and rendered
"CRDT Document" — a model the runtime stopped using in Cutover 9. The
user asked for a "product-grade UI" with a homepage that lists projects,
shows each project's hub progress, and lets a human pick agents to chat
with. This delivers the consumable surface for Cutovers 26 + 27.

## Commits

- Cutover 28: record pre-flight baseline
- Cutover 28: live monitor --workspaces-root mode + /api/projects endpoint
- Cutover 28: /api/projects/<id>/state with 5-hub snapshots
- Cutover 28: conversation CRUD endpoints + do_POST on MonitorHandler
- Cutover 28: HTTP e2e smoke for /api/projects + POST conversation
- Cutover 28: homepage + hash router + per-project state fetch
- Cutover 28: 5-hub HubsTab replaces CRDT inspector; add chat tab slot
- Cutover 28: ChatPanel component (conversation list + transcript + agent selector)
- (this commit) Cutover 28: CRDT housekeeping + migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Discover: <BASELINE> → <FINAL> OK (+<DELTA> new)

## New surfaces

### Backend (live_monitor_server.py)
- `--workspaces-root <dir>` arg (alternative to `--project-dir`)
- `GET /api/projects` → `{projects: [{id, name, status, created_at, last_active_at, workspace_path, description}]}`
- `GET /api/projects/<id>/state` → existing build_state payload + `{projectId, projectName, projectStatus, hubs}`
- `GET /api/projects/<id>/conversations` → `{conversations: [summary, ...]}`
- `GET /api/projects/<id>/conversations/<tid>/messages` → `{messages: [{message_id, source, text, created_at, event_type}]}`
- `POST /api/projects/<id>/conversations` body `{target_agents: [...], text, from_user?}` → conversation summary
- `POST /api/projects/<id>/conversations/<tid>/messages` body `{text, from_user?}` → `{ok: true}`
- `build_projects_list`, `build_project_state`, `build_conversations_list`,
  `build_messages_list`, `start_conversation_call`, `send_message_call`
  helpers (all in-process callable for tests)
- `_hub_snapshots(workspace)` — calls HubRegistry.snapshot()

### Frontend
- `src/router.jsx` — `window.LiveMonitorRouter.{useRoute, navigateTo}`
- `src/homepage.jsx` — project grid + auto-refresh
- `src/hub_panels.jsx` — `<HubsTab>` + 5 hub panels
- `src/chat_panel.jsx` — `<ChatPanel>` with conversation list, transcript, agent selector
- `styles/homepage.css`, `styles/hubs.css`, `styles/chat.css`

### Removed
- `<CrdtInspector>` (replaced by `<HubsTab>`)
- "crdt" tab in views.jsx (replaced by "hubs" and "chat")

### Backward compat
- `--project-dir` mode still works (no homepage/chat — single-project view only)
- `build_state` still returns `crdt` key (annotated as back-compat)
- v0-workspace.css `.crdt-*` classes retained (no longer referenced)

## Known limits (future cutovers)

- HubsTab renders raw `JSON.stringify(snapshot)` for each hub — readable but
  not designed. Future: hub-specific widgets (CodeHub: PR list; APIHub: endpoint
  table; WorkHub: kanban; EventHub: thread timeline; RunHub: run history chart).
- Homepage has no "Create new project" button — orchestrator creates them.
  Future: a CLI bridge.
- Chat doesn't auto-route messages by intent; user must pick agents.
- No auth — local-only.
- Polling instead of websockets (3s convs, 2s msgs); fine for single user.
- KNOWN_AGENTS in chat_panel.jsx is hardcoded; should ideally come from
  `/api/projects/<id>/agents` (build from agents_config.yaml).
- The orchestrator process and the live monitor process are still separate;
  human chat written via the monitor is durable but only consumed if the
  orchestrator is running (or, on next start, drained from inbox).
```

(Fill in `<BASELINE>`, `<FINAL>`, `<DELTA>`.)

- [ ] **Step 5: Commit + push branch**

```bash
git add docs/superpowers/migration-logs/28-product-ui.md \
        agent/env_generator/llm_generator/live_monitor_server.py
git commit -m "Cutover 28: CRDT housekeeping + migration log"
git push -u red-env-gen haibotong-cutover-28-product-ui 2>&1 | tail -5
```

- [ ] **Step 6: Fast-forward merge into parent + push parent**

```bash
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-28-product-ui
git merge --ff-only haibotong-cutover-28-product-ui
git push red-env-gen haibotong-0521-pipeline-web-tools 2>&1 | tail -5
```

---

## Self-Review Notes

**Spec coverage:**
- "现在的UI还是给予crdt的，需要改成四个hub的" → Tasks 7 (HubsTab replaces CrdtInspector, 5 hubs shown — user chose 5 in the upfront question)
- "我们需要做一个产品级的UI" → Tasks 6-8 (homepage + dashboard + chat + dedicated CSS)
- "做一个首页，可以选择项目" → Task 6 (Homepage with project cards)
- "可以让user和agent交互" → Task 8 (ChatPanel with agent selector + transcript)
- "可以看到每个项目四个hub的进展和变化" → Task 7 (HubsTab with 5 panels — note: 5 hubs, per user choice)

**Out of scope (deferred / future cutovers):**
- Hub-specific widgets (kanban for WorkHub, timeline for EventHub, etc.) — current panels show JSON snapshot
- WebSocket live updates — using polling
- Project creation via UI — orchestrator-driven only
- Agent intent auto-routing — user explicit selection
- Auth / multi-user

**Dependencies on Cutover 26 + 27:**
- Hard dependency on `ProjectIndex`, `list_projects`, `HubRegistry.project_metadata` (Cutover 26)
- Hard dependency on `HumanConsole`, `EventHub.list_conversations` (Cutover 27)
- Plan assumes both merged into parent before Cutover 28 begins
