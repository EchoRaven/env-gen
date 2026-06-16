# Cutover 32: Global SSE + Agent List Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Two concrete polish items from Cutover 31's Known Limits.

1. **Homepage cross-project SSE:** `homepage.jsx` still polls `/api/projects` every 5s because Cutover 31's SSE is per-project. Add a workspaces-root-scoped `_GlobalSSEHub` + `GET /api/events` so the homepage learns about project create/delete/status changes (and any hub event in any project) in real time.
2. **Agent list service:** `chat_panel.jsx` has a hardcoded `KNOWN_AGENTS = ["orchestrator", "design", ...]` list. Add `GET /api/projects/<id>/agents` that reads `agents_config.yaml` profiles, so the chat dropdown reflects the real agent registry.

**Architecture:**
- Add a module-level `_GLOBAL_SSE_HUB: _SSEHub` singleton in `live_monitor_server.py`. Project lifecycle helpers (`create_project_call`, `set_project_status_call`, `delete_project_call`) explicitly publish a synthetic event to it.
- Add a per-project "forwarder bridge" that copies every per-project EventHub event into the global hub (so the homepage sees activity-induced lifecycle changes too). This bridge is attached once when a HubRegistry is cached.
- New `GET /api/events` endpoint mirrors `_stream_sse` but reads from `_GLOBAL_SSE_HUB`.
- New `_load_agent_profiles()` helper reads YAML; `GET /api/projects/<id>/agents` returns `{agents: [{id, name, description}]}`.
- Frontend: `homepage.jsx` subscribes to `/api/events`, refreshes on every event (cheap; the list is small). Polling fallback slows from 5s to 30s when SSE is connected. `chat_panel.jsx` fetches `/api/projects/<id>/agents` on mount and uses the result instead of `KNOWN_AGENTS`.

**Tech Stack:** PyYAML (already in env), no new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/`. sys.path boilerplate at top. Imports: `from live_monitor_server import _GLOBAL_SSE_HUB, _load_agent_profiles, ...` after the boilerplate. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. No `Co-Authored-By: Claude` trailer.

---

## File Structure

**Create:** `docs/superpowers/migration-logs/32-global-sse-agents.md`, `agent/tests/test_global_sse_and_agents.py`

**Modify:** `agent/env_generator/llm_generator/live_monitor_server.py`, `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`, `agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx`

---

## Task 1: Pre-flight baseline

- [ ] **Step 1: Regressions** — expect 7 OK
- [ ] **Step 2: Pytest collect** — expect 1057 (Cutover 31 baseline)
- [ ] **Step 3: Migration log stub** at `docs/superpowers/migration-logs/32-global-sse-agents.md`:
  ```markdown
  # Cutover 32: Global SSE + Agent List Service

  **Branch:** `haibotong-cutover-32-global-sse-agents`
  **Date:** 2026-05-26
  **Status:** in-progress

  ## Pre-flight baseline
  - Regressions: 7 OK
  - Pytest collected: 1057
  ```
- [ ] **Step 4: Commit + stage plan**: `Cutover 32: record pre-flight baseline`

---

## Task 2: Backend — `_GLOBAL_SSE_HUB` + GET /api/events + lifecycle events

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Create: `agent/tests/test_global_sse_and_agents.py`

### TDD Step 1: write failing tests

```python
# agent/tests/test_global_sse_and_agents.py
import sys
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestGlobalSSEHub(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _GLOBAL_SSE_HUB, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _GLOBAL_SSE_HUB._clients.clear()  # type: ignore[attr-defined]
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _GLOBAL_SSE_HUB, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _GLOBAL_SSE_HUB._clients.clear()  # type: ignore[attr-defined]
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_create_project_broadcasts_global_event(self):
        from live_monitor_server import _GLOBAL_SSE_HUB, create_project_call
        q = _GLOBAL_SSE_HUB.register("test_client")
        result = create_project_call(self.root, {"name": "demo"})
        self.assertNotIn("error", result, result)
        event = q.get(timeout=2.0)
        self.assertEqual(event.get("event_type"), "project_created")
        self.assertEqual(event.get("project_id"), result["id"])

    def test_set_project_status_broadcasts_global_event(self):
        from live_monitor_server import _GLOBAL_SSE_HUB, create_project_call, set_project_status_call
        result = create_project_call(self.root, {"name": "demo"})
        q = _GLOBAL_SSE_HUB.register("test_client")
        set_project_status_call(self.root, result["id"], {"status": "paused"})
        event = q.get(timeout=2.0)
        self.assertEqual(event.get("event_type"), "project_status_changed")
        self.assertEqual(event.get("payload", {}).get("status"), "paused")

    def test_delete_project_broadcasts_global_event(self):
        from live_monitor_server import _GLOBAL_SSE_HUB, create_project_call, delete_project_call
        result = create_project_call(self.root, {"name": "demo"})
        q = _GLOBAL_SSE_HUB.register("test_client")
        delete_project_call(self.root, result["id"], {"confirm": True})
        event = q.get(timeout=2.0)
        self.assertEqual(event.get("event_type"), "project_deleted")
        self.assertEqual(event.get("project_id"), result["id"])

    def test_per_project_event_forwards_to_global(self):
        """Any EventHub publish on a project should also reach the global bus."""
        from live_monitor_server import _GLOBAL_SSE_HUB, create_project_call, _resolve_hubs
        result = create_project_call(self.root, {"name": "demo"})
        pid = result["id"]
        # Drain the project_created event from setup
        q = _GLOBAL_SSE_HUB.register("test_client")
        reg, _ = _resolve_hubs(self.root, pid)
        reg.eventhub.publish_event(source_hub="workhub", event_type="task_created",
                                   payload={"title": "x"}, recipients=["alpha"])
        # First event in queue might be lingering; allow ourselves up to 3 reads
        found = False
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                event = q.get(timeout=0.5)
            except Exception:
                continue
            if event.get("event_type") == "task_created":
                self.assertEqual(event.get("project_id"), pid)
                found = True
                break
        self.assertTrue(found, "task_created event should have reached the global hub")


class TestGlobalEventsEndpoint(unittest.TestCase):
    def test_global_events_endpoint_streams(self):
        import http.server
        from functools import partial
        from http.client import HTTPConnection
        from live_monitor_server import MonitorHandler, _GLOBAL_SSE_HUB, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE, create_project_call

        _GLOBAL_SSE_HUB._clients.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=root)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                received = []
                def reader():
                    conn = HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request("GET", "/api/events")
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 200)
                    self.assertIn("text/event-stream", resp.getheader("Content-Type", ""))
                    deadline = time.time() + 1.5
                    while time.time() < deadline:
                        chunk = resp.fp.read1(256)
                        if not chunk:
                            break
                        received.append(chunk)
                    conn.close()

                rt = threading.Thread(target=reader, daemon=True); rt.start()
                time.sleep(0.3)
                create_project_call(root, {"name": "via_global_sse"})
                rt.join(timeout=2.0)
                blob = b"".join(received).decode("utf-8", errors="replace")
                self.assertIn("data:", blob)
                self.assertIn("project_created", blob)
            finally:
                server.shutdown()
                server.server_close()
```

Run — expect AttributeError on `_GLOBAL_SSE_HUB` etc.

### TDD Step 2: implement

Edit `agent/env_generator/llm_generator/live_monitor_server.py`:

1. After the existing `_SSE_HUB_CACHE` block, add a module-level global SSE hub:

```python
# Cutover 32: workspaces-root-scoped SSE hub for project lifecycle + cross-project events.
_GLOBAL_SSE_HUB = _SSEHub()


def _publish_global(event_type: str, project_id: str, payload: dict, source_hub: str = "ui") -> None:
    """Push a project-lifecycle event into the global SSE stream.

    Used by create_project_call / set_project_status_call / delete_project_call
    so the homepage receives push updates without polling.
    """
    import time as _time
    _GLOBAL_SSE_HUB.broadcast({
        "id": f"evt_global_{int(_time.time() * 1000)}",
        "event_type": event_type,
        "source_hub": source_hub,
        "project_id": project_id,
        "payload": payload or {},
        "created_at": _time.time(),
    })


class _ForwardToGlobalBridge:
    """EventHub bridge that re-broadcasts per-project events onto the global hub.

    Attached once per HubRegistry (when first cached) so any hub mutation
    is visible to the homepage SSE client.
    """
    def __init__(self, project_id: str):
        self._project_id = project_id

    def deliver(self, event: dict) -> None:
        try:
            _GLOBAL_SSE_HUB.broadcast({
                **event,
                "project_id": self._project_id,
            })
        except Exception:
            pass
```

2. Modify `_resolve_hubs` so that when a HubRegistry is newly cached, we also attach a `_ForwardToGlobalBridge` to its EventHub. Replace the `if reg is None:` branch:

```python
        if reg is None:
            reg = HubRegistry(workspace)
            reg.eventhub.add_bridge(_ForwardToGlobalBridge(project_id))
            _HUB_REGISTRY_CACHE[key] = reg
```

3. Modify the lifecycle helpers to publish lifecycle events. In `create_project_call`, immediately before `return {...}` (the final success return), add:

```python
    _publish_global("project_created", reg.project_metadata.id,
                    {"name": reg.project_metadata.name, "status": reg.project_metadata.status})
```

(Capture `reg` from wherever the helper holds the registry. If the helper builds via the constructor, just use the returned project_id and resolve again — `_resolve_hubs(workspaces_root, project_id)` is cheap on cache hit.)

In `set_project_status_call`, after the successful status update, before return:

```python
    _publish_global("project_status_changed", project_id,
                    {"status": body.get("status")})
```

In `delete_project_call`, after the successful rmtree + cache eviction, before return:

```python
    _publish_global("project_deleted", project_id, {})
```

4. Add `_stream_global_sse` method to `MonitorHandler` (next to `_stream_sse`):

```python
def _stream_global_sse(self) -> None:
    """Stream global SSE events (project lifecycle + all per-project events)."""
    import uuid as _uuid
    if self._workspaces_root is None:
        self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
        return

    client_id = f"sse_global_{_uuid.uuid4().hex[:12]}"
    q = _GLOBAL_SSE_HUB.register(client_id)
    try:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.write(b": connected\n\n")
        self.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        _GLOBAL_SSE_HUB.unregister(client_id)
        return

    try:
        while True:
            try:
                event = q.get(timeout=15.0)
            except queue.Empty:
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            slim = {
                "id": event.get("id"),
                "event_type": event.get("event_type"),
                "source_hub": event.get("source_hub"),
                "project_id": event.get("project_id"),
                "thread_id": event.get("thread_id"),
                "created_at": event.get("created_at"),
                "payload": event.get("payload"),
            }
            try:
                data = json.dumps(slim, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
    finally:
        _GLOBAL_SSE_HUB.unregister(client_id)
```

5. In `do_GET`, add the `/api/events` route. Place it BEFORE the existing per-project `/api/projects/<id>/events` route (more-specific paths should match first, but this is exact-match vs prefix, so order doesn't actually matter — pick whichever reads cleaner):

```python
if parsed.path == "/api/events":
    self._stream_global_sse()
    return
```

Run tests — expect 5 PASS (4 unit + 1 smoke).

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_global_sse_and_agents.py
git commit -m "Cutover 32: _GLOBAL_SSE_HUB + GET /api/events + project lifecycle events"
```

---

## Task 3: Backend — GET /api/projects/<id>/agents

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Modify: `agent/tests/test_global_sse_and_agents.py` (append)

### TDD Step 1: append failing test

```python
class TestAgentsEndpoint(unittest.TestCase):
    def test_load_agent_profiles_returns_known_agents(self):
        from live_monitor_server import _load_agent_profiles
        profiles = _load_agent_profiles()
        # Should be a non-empty list, each entry has id + name
        self.assertGreater(len(profiles), 5)
        sample = profiles[0]
        self.assertIn("id", sample)
        self.assertIn("name", sample)

    def test_load_agent_profiles_includes_orchestrator(self):
        from live_monitor_server import _load_agent_profiles
        profiles = _load_agent_profiles()
        ids = {p["id"] for p in profiles}
        self.assertIn("orchestrator", ids)

    def test_agents_endpoint_returns_payload(self):
        from live_monitor_server import build_agents_list, create_project_call
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from live_monitor_server import _GLOBAL_SSE_HUB, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
            _GLOBAL_SSE_HUB._clients.clear(); _HUB_REGISTRY_CACHE.clear(); _SSE_HUB_CACHE.clear()
            result = create_project_call(root, {"name": "demo"})
            payload = build_agents_list(root, result["id"])
            self.assertIn("agents", payload)
            self.assertGreater(len(payload["agents"]), 5)

    def test_agents_endpoint_unknown_project_returns_error(self):
        from live_monitor_server import build_agents_list
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_agents_list(Path(tmp), "nope")
            self.assertIn("error", payload)
```

Run — expect `_load_agent_profiles` not defined.

### TDD Step 2: implement

In `live_monitor_server.py`, add near the other helpers (e.g., next to `build_conversations_list`):

```python
# Cutover 32: cache parsed agents_config.yaml profiles.
_AGENT_PROFILES_CACHE: Optional[List[dict]] = None


def _load_agent_profiles() -> List[dict]:
    """Return a list of {id, name, description} dicts from agents_config.yaml.

    Cached after first read so repeated UI fetches don't re-parse YAML each
    time. Returns an empty list if the file is missing or malformed.
    """
    global _AGENT_PROFILES_CACHE
    if _AGENT_PROFILES_CACHE is not None:
        return _AGENT_PROFILES_CACHE
    try:
        import yaml  # PyYAML — already a project dep
    except ImportError:
        _AGENT_PROFILES_CACHE = []
        return _AGENT_PROFILES_CACHE
    config_path = (
        Path(__file__).parent
        / "multi_agent" / "agents" / "agents_config.yaml"
    )
    if not config_path.exists():
        _AGENT_PROFILES_CACHE = []
        return _AGENT_PROFILES_CACHE
    try:
        with config_path.open("r") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        _AGENT_PROFILES_CACHE = []
        return _AGENT_PROFILES_CACHE

    profiles = []
    for agent_id, info in (data.get("profiles") or {}).items():
        if not isinstance(info, dict):
            continue
        profiles.append({
            "id": agent_id,
            "name": info.get("name", agent_id),
            "description": info.get("description", ""),
            "can_deliver": bool((info.get("flags") or {}).get("can_deliver", False)),
            "team_lead": bool((info.get("flags") or {}).get("team_lead", False)),
        })
    # Sort: team leads first, then alphabetical
    profiles.sort(key=lambda p: (not p["team_lead"], not p["can_deliver"], p["id"]))
    _AGENT_PROFILES_CACHE = profiles
    return profiles


def build_agents_list(workspaces_root: Path, project_id: str) -> dict:
    """`GET /api/projects/<id>/agents` payload."""
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err
    return {"agents": _load_agent_profiles()}
```

Then add the GET route in `do_GET` (next to existing `/api/projects/<id>/conversations` route):

```python
if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/agents"):
    if self._workspaces_root is None:
        self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
        return
    pid = parsed.path[len("/api/projects/"):-len("/agents")]
    self._write_json(build_agents_list(self._workspaces_root, pid))
    return
```

Run tests — expect PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_global_sse_and_agents.py
git commit -m "Cutover 32: GET /api/projects/<id>/agents + _load_agent_profiles helper"
```

---

## Task 4: Frontend — homepage SSE + dynamic chat agent list

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`
- Modify: `agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx`

### Step 1: homepage SSE

Edit `homepage.jsx`. After the existing `useEffect` that runs `refresh()` + `setInterval(refresh, 5000)`, slow the fallback poll to 30s when SSE is connected, and subscribe via MonitorSSE to `/api/events`:

Find the existing useEffect (which calls `refresh()` then `setInterval(refresh, 5000)`) and modify the interval pattern:

```jsx
useEffect(() => {
  refresh();
  // Cutover 32: keep a slow fallback poll while SSE is connected; otherwise 5s.
  let pollMs = 5000;
  function pickInterval() {
    return window.MonitorSSE && window.MonitorSSE.isConnected() ? 30000 : 5000;
  }
  let timer = window.setInterval(function tick() {
    refresh();
    const next = pickInterval();
    if (next !== pollMs) {
      window.clearInterval(timer);
      pollMs = next;
      timer = window.setInterval(tick, pollMs);
    }
  }, pollMs);
  return () => window.clearInterval(timer);
}, []);

// Cutover 32: subscribe to global SSE so project create/delete/status push instantly.
window.MonitorSSE && window.MonitorSSE.useSSE("__global__", (event) => {
  // useSSE expects a projectId; we pass "__global__" as a sentinel and
  // open the global endpoint manually below if MonitorSSE doesn't route it.
});
```

That `__global__` sentinel approach is fragile. Cleaner: open EventSource directly in homepage.jsx (don't reuse the per-project `useSSE` hook). Replace the SSE block with an inline subscription:

```jsx
useEffect(() => {
  let es = null, reconnectTimer = null, backoffMs = 500, closed = false;
  function open() {
    if (closed) return;
    try { es = new EventSource("/api/events"); } catch (e) { return; }
    es.onopen = () => { backoffMs = 500; };
    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        const t = event.event_type;
        // Refresh on lifecycle + any cross-project event
        if (t === "project_created" || t === "project_deleted" || t === "project_status_changed" ||
            event.project_id /* per-project activity bumps last_active */) {
          refresh();
        }
      } catch (_) {}
    };
    es.onerror = () => {
      if (es) { try { es.close(); } catch (_) {} es = null; }
      if (closed) return;
      reconnectTimer = window.setTimeout(open, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 30000);
    };
  }
  open();
  return () => {
    closed = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    if (es) { try { es.close(); } catch (_) {} }
  };
}, []);
```

Read the current `homepage.jsx` first to find where `refresh` is defined and add these blocks correctly.

### Step 2: chat panel agent list

Edit `chat_panel.jsx`. Replace the hardcoded `KNOWN_AGENTS = [...]` constant with a state value populated from `/api/projects/<id>/agents`. Add at the top of the `ChatPanel` component (after existing state hooks):

```jsx
const [knownAgents, setKnownAgents] = useState([]);

useEffect(() => {
  if (!projectId) return;
  fetch(`/api/projects/${encodeURIComponent(projectId)}/agents`)
    .then(r => r.json())
    .then(data => {
      if (data && Array.isArray(data.agents)) {
        // Skip the human_user pseudo-id if present.
        const agents = data.agents.filter(a => a.id !== "human_user").map(a => a.id);
        setKnownAgents(agents);
      }
    })
    .catch(() => {});
}, [projectId]);
```

Then in the JSX where `KNOWN_AGENTS.map(...)` appears, replace it with `knownAgents.map(...)`. Remove the top-level `const KNOWN_AGENTS = [...]` constant entirely.

### Step 3: manual smoke

```bash
mkdir -p /tmp/cutover32_smoke_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/cutover32_smoke_ws --port 4395 &
SERVER_PID=$!
sleep 1
PID=$(curl -s -X POST http://127.0.0.1:4395/api/projects -H "Content-Type: application/json" -d '{"name":"smoke"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")

# Test agents endpoint
curl -s http://127.0.0.1:4395/api/projects/$PID/agents | python -m json.tool | head -20

# Test global SSE
curl -s -N http://127.0.0.1:4395/api/events > /tmp/global-sse.txt &
CURL_PID=$!
sleep 0.5
curl -s -X POST http://127.0.0.1:4395/api/projects -H "Content-Type: application/json" -d '{"name":"second"}'
sleep 1
kill $CURL_PID 2>/dev/null
kill $SERVER_PID 2>/dev/null
grep -E "^data:" /tmp/global-sse.txt | head -5
```

Expected: agents endpoint returns a list with `orchestrator` etc.; global SSE shows a `project_created` event for "second".

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/src/chat_panel.jsx
git commit -m "Cutover 32: homepage global SSE + chat panel dynamic agent list"
```

---

## Task 5: Final sweep + migration log + push

- [ ] **Step 1: Verify all new tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_global_sse_and_agents.py -v
```

Expected: 4 + 1 + 4 = 9 tests pass (lifecycle + smoke + agent endpoint tests).

- [ ] **Step 2: Regressions + endpoint regression spot-check**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py agent/tests/test_live_monitor_sse.py agent/tests/test_eventhub_completeness.py -q 2>&1 | tail -5
```

- [ ] **Step 3: Migration log full version**

Replace `docs/superpowers/migration-logs/32-global-sse-agents.md` with:

```markdown
# Cutover 32: Global SSE + Agent List Service

**Branch:** `haibotong-cutover-32-global-sse-agents`
**Date:** 2026-05-26

## What

Two polish items from Cutover 31's Known Limits.

1. **Global SSE for homepage:** new `_GLOBAL_SSE_HUB` + `GET /api/events`
   carries project lifecycle events (`project_created`/`_status_changed`/`_deleted`)
   and forwards every per-project hub event onto the same stream (via a
   `_ForwardToGlobalBridge` attached to each cached HubRegistry's EventHub).
   Homepage subscribes via `EventSource` and refreshes on demand; the 5s
   fallback poll slows to 30s while SSE is connected.

2. **Agent list service:** new `GET /api/projects/<id>/agents` reads
   `agents_config.yaml` profiles, sorts by team-lead → can-deliver →
   alphabetic, and returns `{agents: [{id, name, description, can_deliver, team_lead}]}`.
   `chat_panel.jsx` fetches this on mount and uses it instead of the
   hardcoded `KNOWN_AGENTS = [...]` constant.

## Commits

- (fill in baseline SHA) Cutover 32: record pre-flight baseline
- (fill in) Cutover 32: _GLOBAL_SSE_HUB + GET /api/events + project lifecycle events
- (fill in) Cutover 32: GET /api/projects/<id>/agents + _load_agent_profiles helper
- (fill in) Cutover 32: homepage global SSE + chat panel dynamic agent list
- (this commit) Cutover 32: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collected: 1057 → ~1066 (+9 new tests in `test_global_sse_and_agents.py`)

## New surfaces

### Backend
- `_GLOBAL_SSE_HUB: _SSEHub` — module-level singleton for cross-project events
- `_publish_global(event_type, project_id, payload, source_hub="ui")` — lifecycle events
- `_ForwardToGlobalBridge` — per-project bridge that copies events onto the global hub
- `MonitorHandler._stream_global_sse` + `GET /api/events`
- `_load_agent_profiles()` — cached YAML reader returning `[{id, name, description, can_deliver, team_lead}]`
- `build_agents_list(workspaces_root, project_id)` + `GET /api/projects/<id>/agents`

### Frontend
- `homepage.jsx`: inline EventSource on `/api/events`; refresh on lifecycle events; fallback poll 30s while SSE up
- `chat_panel.jsx`: `useState<knownAgents>` + `useEffect` fetch on mount; `KNOWN_AGENTS` constant removed

## Architecture notes

- `_ForwardToGlobalBridge` is attached once per HubRegistry (when cached).
  Since Cutover 31's cache means at-most one HubRegistry per project, we
  also attach at-most one forwarder per project — no duplicate events.
- The global hub uses the same `_SSEHub` class (queue overflow drops
  silently); UI re-syncs from `/api/projects` on any received event.
- Agent profiles are cached after first parse; module-restart picks up
  any yaml edits. Adequate for the local-only deployment.

## Known limits

- Forwarded events carry the full per-project payload — slight bandwidth
  cost for chatty projects. UI just triggers `refresh()` on receipt; it
  doesn't actually read the event body.
- `_AGENT_PROFILES_CACHE` invalidates only on server restart. If
  `agents_config.yaml` is hot-edited, restart to pick up changes.
- Agent list filtering skips only `human_user` — future cutover may add
  per-project agent visibility flags (e.g., bug_triage_orchestrator
  hidden in projects that don't have failing tests).
```

(Fill in actual SHAs from `git log --oneline -10`.)

- [ ] **Step 4: Commit migration log**

```bash
git add docs/superpowers/migration-logs/32-global-sse-agents.md
git commit -m "Cutover 32: migration log"
```

- [ ] **Step 5: Push + ff-merge**

```bash
git push -u red-env-gen haibotong-cutover-32-global-sse-agents 2>&1 | tail -5
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-32-global-sse-agents
git merge --ff-only haibotong-cutover-32-global-sse-agents
git push red-env-gen haibotong-0521-pipeline-web-tools 2>&1 | tail -3
```
