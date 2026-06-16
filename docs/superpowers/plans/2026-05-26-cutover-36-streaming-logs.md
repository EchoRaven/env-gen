# Cutover 36: Streaming Log View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Replace Cutover 34's 4KB `log_tail` polling with a true SSE log stream. When the UI opens a run, it sees every new log line in real time. When the run finishes, a final `_end` event closes the stream.

**Architecture:** Add `GET /api/runs/<run_id>/log/stream` SSE endpoint. The handler:
1. Looks up the run in `_RUN_REGISTRY`.
2. Sends SSE headers + initial snapshot (last 64KB of the log so users joining mid-run see context).
3. Then tails the log file: opens at EOF, polls every 200ms for new bytes, writes each chunk as `data: {"chunk": "..."}\n\n`.
4. Stops when `_RUN_REGISTRY[run_id]["state"]` is no longer `running`. Sends `data: {"_end": true, "returncode": ...}\n\n`, then closes.
5. Heartbeats `: heartbeat\n\n` every 15s during quiet periods.

Frontend: new `<RunLogStream>` component (`run_log_stream.jsx`) that takes `runId` + `onClose`. Renders a fixed-height scrollable `<pre>` with auto-scroll-to-bottom. Add a "View Logs" button next to each run row + a `<RunLogModal>` overlay.

Wire into `views.jsx` — show "View Logs" button when a run is associated with the current project (via `_RUN_REGISTRY` cross-reference exposed in `/api/projects/<id>/state` as new `active_runs` field).

**Tech Stack:** stdlib only.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. NO `Co-Authored-By: Claude` trailer.

**Auth note:** With Cutover 35, tests that hit HTTP endpoints must set `ENVGEN_AUTH_TOKEN=""` (or leave it unset) so auth is off, OR perform a login + use the cookie. Easier: leave auth off in test setUp.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/36-streaming-logs.md`
- `agent/tests/test_run_log_stream.py`
- `agent/env_generator/llm_generator/live_monitor/src/run_log_stream.jsx`
- `agent/env_generator/llm_generator/live_monitor/styles/run_log.css`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (new SSE endpoint + `active_runs` in build_project_state)
- `agent/env_generator/llm_generator/live_monitor/src/views.jsx` (View Logs button + modal mount)
- `agent/env_generator/llm_generator/live_monitor/index.html` (load run_log_stream.jsx + run_log.css)

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1108
- [ ] Migration log stub at `docs/superpowers/migration-logs/36-streaming-logs.md`
- [ ] Stage plan
- [ ] Commit: `Cutover 36: record pre-flight baseline`

---

## Task 2: Backend — log stream SSE endpoint

**Files:**
- Modify: `live_monitor_server.py`
- Create: `agent/tests/test_run_log_stream.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_run_log_stream.py
import http.server
import os
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.client import HTTPConnection
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class _FakeFinishingPopen:
    """A Popen mock that becomes `done` (returncode=0) on the Nth poll call."""
    def __init__(self, finish_after_polls: int = 999):
        self.pid = 12345
        self._finish_after = finish_after_polls
        self._polls = 0
        self._returncode = None
    def poll(self):
        self._polls += 1
        if self._polls >= self._finish_after:
            self._returncode = 0
        return self._returncode
    @property
    def returncode(self):
        return self._returncode
    def terminate(self): self._returncode = -15
    def kill(self): self._returncode = -9
    def wait(self, timeout=None): return self._returncode or 0


class TestLogStream(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE, _SESSIONS
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        _SESSIONS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "demo"
        self.workspace.mkdir()
        (self.workspace / "logs").mkdir()
        self.log_path = self.workspace / "logs" / "generation.log"
        self.log_path.write_text("initial log line 1\ninitial log line 2\n")
        # Register a fake run
        self.run_id = "run_test_001"
        from live_monitor_server import _RUN_REGISTRY
        _RUN_REGISTRY[self.run_id] = {
            "run_id": self.run_id,
            "project_id": "demo",
            "started_at": time.time(),
            "command": ["fake"],
            "log_path": str(self.log_path),
            "popen": _FakeFinishingPopen(),
            "state": "running",
            "returncode": None,
        }

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY
        _RUN_REGISTRY.clear()
        self._tmp.cleanup()

    def test_log_stream_endpoint_sends_initial_snapshot(self):
        """SSE handler sends the existing log content as a first chunk."""
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received = []
            def reader():
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", f"/api/runs/{self.run_id}/log/stream")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                self.assertIn("text/event-stream", resp.getheader("Content-Type", ""))
                deadline = time.time() + 1.5
                while time.time() < deadline:
                    chunk = resp.fp.read1(512)
                    if not chunk: break
                    received.append(chunk)
                conn.close()
            rt = threading.Thread(target=reader, daemon=True); rt.start()
            rt.join(timeout=2.5)
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn("data:", blob)
            self.assertIn("initial log line 1", blob)
            self.assertIn("initial log line 2", blob)
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_tails_new_lines(self):
        """Lines written after the connection opens must be streamed."""
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received = []
            def reader():
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", f"/api/runs/{self.run_id}/log/stream")
                resp = conn.getresponse()
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    chunk = resp.fp.read1(512)
                    if not chunk: break
                    received.append(chunk)
                conn.close()
            rt = threading.Thread(target=reader, daemon=True); rt.start()
            # Append after a brief delay so the stream is open
            time.sleep(0.5)
            with self.log_path.open("ab") as f:
                f.write(b"NEW LINE AFTER CONNECT\n")
                f.flush()
            rt.join(timeout=3.0)
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn("NEW LINE AFTER CONNECT", blob)
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_unknown_run_returns_404(self):
        from live_monitor_server import MonitorHandler
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/runs/does_not_exist/log/stream")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            conn.close()
        finally:
            server.shutdown(); server.server_close()

    def test_log_stream_emits_end_event_when_run_completes(self):
        """When the underlying Popen finishes, the stream emits _end + closes."""
        from live_monitor_server import MonitorHandler, _RUN_REGISTRY
        # Force the fake to finish after ~3 polls
        _RUN_REGISTRY[self.run_id]["popen"] = _FakeFinishingPopen(finish_after_polls=3)
        handler = partial(MonitorHandler, directory=".", project_dir=None, workspaces_root=self.root)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        try:
            received = []
            def reader():
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", f"/api/runs/{self.run_id}/log/stream")
                resp = conn.getresponse()
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    chunk = resp.fp.read1(512)
                    if not chunk: break
                    received.append(chunk)
                conn.close()
            rt = threading.Thread(target=reader, daemon=True); rt.start()
            rt.join(timeout=3.5)
            blob = b"".join(received).decode("utf-8", errors="replace")
            self.assertIn('"_end": true', blob)
            self.assertIn('"returncode": 0', blob)
        finally:
            server.shutdown(); server.server_close()
```

Run → expect failures (endpoint not yet wired).

### TDD Step 2: implement

In `live_monitor_server.py`, add a streamer method to `MonitorHandler`:

```python
def _stream_run_log(self, run_id: str) -> None:
    """SSE stream of a run's generation.log: initial snapshot + tail until run finishes."""
    with _RUN_REGISTRY_LOCK:
        handle = _RUN_REGISTRY.get(run_id)
    if handle is None:
        self._write_json({"error": f"run not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
        return

    log_path = Path(handle["log_path"])

    # Send SSE preamble
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
        return

    def emit(payload: dict) -> bool:
        try:
            data = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # Step 1: send the initial snapshot (last 64KB).
    SNAPSHOT_MAX = 64 * 1024
    initial_bytes = b""
    pos = 0
    if log_path.exists():
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as f:
                if size > SNAPSHOT_MAX:
                    f.seek(size - SNAPSHOT_MAX, 0)
                    # Skip partial first line so the snapshot is clean
                    f.readline()
                initial_bytes = f.read()
                pos = f.tell()
        except Exception:
            initial_bytes = b""
            pos = 0
    if initial_bytes:
        text = initial_bytes.decode("utf-8", errors="replace")
        if not emit({"chunk": text, "initial": True}):
            return

    # Step 2: tail loop.
    HEARTBEAT_INTERVAL = 15.0
    POLL_INTERVAL = 0.2
    last_heartbeat = time.time()
    while True:
        # Check if run is finished
        with _RUN_REGISTRY_LOCK:
            cur_handle = _RUN_REGISTRY.get(run_id)
        if cur_handle is None:
            break
        popen = cur_handle["popen"]
        rc = popen.poll()
        # Read any new bytes
        new_text = ""
        if log_path.exists():
            try:
                cur_size = log_path.stat().st_size
                if cur_size > pos:
                    with log_path.open("rb") as f:
                        f.seek(pos, 0)
                        chunk = f.read(cur_size - pos)
                        pos = f.tell()
                    if chunk:
                        new_text = chunk.decode("utf-8", errors="replace")
                elif cur_size < pos:
                    # File rotated / truncated; reset
                    pos = 0
            except Exception:
                pass

        if new_text:
            if not emit({"chunk": new_text}):
                return
            last_heartbeat = time.time()

        if rc is not None:
            # One last read in case the process flushed after our seek
            try:
                if log_path.exists():
                    cur_size = log_path.stat().st_size
                    if cur_size > pos:
                        with log_path.open("rb") as f:
                            f.seek(pos, 0)
                            chunk = f.read(cur_size - pos)
                        if chunk:
                            emit({"chunk": chunk.decode("utf-8", errors="replace")})
            except Exception:
                pass
            emit({"_end": True, "returncode": rc})
            return

        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                last_heartbeat = time.time()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        time.sleep(POLL_INTERVAL)
```

In `do_GET`, add the route (near the existing `/api/runs/<id>/status` route):

```python
if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/log/stream"):
    run_id = parsed.path[len("/api/runs/"):-len("/log/stream")]
    self._stream_run_log(run_id)
    return
```

### Also: expose `active_runs` in build_project_state

In `live_monitor_server.py`, find `build_project_state(workspaces_root, project_id)`. After the existing payload assembly, add:

```python
# Cutover 36: include runs whose project_id matches so the UI can show "View Logs" buttons.
with _RUN_REGISTRY_LOCK:
    project_runs = [
        {
            "run_id": h["run_id"],
            "state": h["state"],
            "started_at": h["started_at"],
            "returncode": h.get("returncode"),
        }
        for h in _RUN_REGISTRY.values()
        if h.get("project_id") == project_id
    ]
state["active_runs"] = sorted(project_runs, key=lambda r: r["started_at"], reverse=True)
```

(Replace `state` with whatever variable name the function uses for its return dict — check the source.)

Run tests → expect 4 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_run_log_stream.py
git commit -m "Cutover 36: GET /api/runs/<id>/log/stream SSE endpoint + active_runs in project state"
```

---

## Task 3: Frontend — RunLogStream component + View Logs button

**Files:**
- Create: `live_monitor/src/run_log_stream.jsx`
- Create: `live_monitor/styles/run_log.css`
- Modify: `live_monitor/src/views.jsx`
- Modify: `live_monitor/index.html`

### Step 1: RunLogStream component

Create `live_monitor/src/run_log_stream.jsx`:

```jsx
window.RunLogStream = (function () {
  const { useState, useEffect, useRef } = React;

  function RunLogStream({ runId, onClose }) {
    const [lines, setLines] = useState("");
    const [finished, setFinished] = useState(false);
    const [returncode, setReturncode] = useState(null);
    const [error, setError] = useState("");
    const preRef = useRef(null);
    const followRef = useRef(true);  // auto-scroll while user is at the bottom

    useEffect(() => {
      if (!runId) return undefined;
      let es = null, reconnectTimer = null, backoffMs = 500, closed = false;

      function open() {
        if (closed) return;
        try {
          es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/log/stream`, { withCredentials: true });
        } catch (e) {
          setError(String(e));
          return;
        }
        es.onopen = () => { backoffMs = 500; };
        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (event._end) {
              setFinished(true);
              setReturncode(event.returncode);
              if (es) { try { es.close(); } catch (_) {} es = null; }
              return;
            }
            if (event.chunk) {
              setLines(prev => prev + event.chunk);
            }
          } catch (_) {}
        };
        es.onerror = () => {
          if (es) { try { es.close(); } catch (_) {} es = null; }
          if (closed || finished) return;
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
    }, [runId]);

    // Auto-scroll to bottom whenever new content arrives (unless user scrolled up)
    useEffect(() => {
      const el = preRef.current;
      if (el && followRef.current) {
        el.scrollTop = el.scrollHeight;
      }
    }, [lines]);

    function onScroll() {
      const el = preRef.current;
      if (!el) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      followRef.current = atBottom;
    }

    return (
      <div className="run-log-modal-backdrop" onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}>
        <div className="run-log-modal">
          <div className="run-log-header">
            <span className="run-log-title">Run {runId}</span>
            <span className={"run-log-state state-" + (finished ? (returncode === 0 ? "ok" : "fail") : "running")}>
              {finished
                ? (returncode === 0 ? "Completed" : `Failed (rc=${returncode})`)
                : "Running…"}
            </span>
            <button className="run-log-close" onClick={() => onClose?.()}>Close</button>
          </div>
          {error && <div className="run-log-error">{error}</div>}
          <pre ref={preRef} onScroll={onScroll} className="run-log-pre">{lines || "(waiting for output…)"}</pre>
        </div>
      </div>
    );
  }

  return RunLogStream;
})();
```

### Step 2: run_log.css

```css
.run-log-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.run-log-modal {
  width: 80vw; max-width: 1200px;
  height: 70vh;
  background: #0e1626; border: 1px solid #2d3a4d;
  border-radius: 8px;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.run-log-header {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: #1a2538; border-bottom: 1px solid #2d3a4d;
}
.run-log-title { font-family: monospace; color: #ddd; font-size: 13px; }
.run-log-state { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.run-log-state.state-running { background: #1a3a5a; color: #6cc; }
.run-log-state.state-ok { background: #1a3a1a; color: #8e8; }
.run-log-state.state-fail { background: #3a1a1a; color: #faa; }
.run-log-close {
  margin-left: auto;
  background: transparent; color: #aab;
  border: 1px solid #354054; border-radius: 4px;
  padding: 4px 12px; font-size: 11px;
  cursor: pointer;
}
.run-log-close:hover { color: #fff; border-color: #4070d0; }
.run-log-error {
  background: #4a1f1f; color: #ffaaaa;
  padding: 6px 14px; font-size: 12px;
}
.run-log-pre {
  flex: 1; margin: 0;
  background: #0a1018; color: #cdd;
  font-family: monospace; font-size: 11px;
  line-height: 1.4;
  padding: 12px;
  overflow-y: scroll;
  white-space: pre-wrap; word-break: break-all;
}
```

### Step 3: View Logs button in views.jsx

Read `views.jsx`. Find a sensible mount point for an "Active runs" pill cluster — likely near the project header (next to DeliverButton from Cutover 34). Read `state?.active_runs` and render one `<button>` per active run: "View Logs: run_abc123 (running)" → opens the modal.

State for the modal:

```jsx
const [openRunLog, setOpenRunLog] = useState(null);

// In the project header render:
{state?.active_runs && state.active_runs.length > 0 && (
  <div className="active-runs">
    {state.active_runs.map(r => (
      <button key={r.run_id}
              className={"run-pill state-" + r.state}
              onClick={() => setOpenRunLog(r.run_id)}>
        {r.run_id.substr(0, 10)}… ({r.state})
      </button>
    ))}
  </div>
)}

{openRunLog && (
  <window.RunLogStream runId={openRunLog} onClose={() => setOpenRunLog(null)} />
)}
```

Add `.active-runs` + `.run-pill` styles to `v0-workspace.css`:

```css
.active-runs { display: flex; gap: 6px; }
.run-pill {
  background: #1a2538;
  border: 1px solid #354054;
  border-radius: 999px;
  color: #aab; font-size: 11px;
  padding: 3px 10px;
  cursor: pointer; font-family: monospace;
}
.run-pill:hover { color: #fff; border-color: #4070d0; }
.run-pill.state-running { color: #6cc; border-color: #1a3a5a; }
.run-pill.state-completed { color: #8e8; border-color: #1a3a1a; }
.run-pill.state-failed { color: #faa; border-color: #3a1a1a; }
.run-pill.state-stopped { color: #ddd; border-color: #4a3a1a; }
```

### Step 4: index.html

Add `<link rel="stylesheet" href="styles/run_log.css">` in `<head>` and `<script type="text/babel" src="src/run_log_stream.jsx"></script>` BEFORE `views.jsx`.

### Step 5: Manual smoke

```bash
mkdir -p /tmp/c36_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/c36_ws --port 4400 &
SERVER_PID=$!
sleep 1
# Create a project
PID=$(curl -sS -X POST http://127.0.0.1:4400/api/projects -H "Content-Type: application/json" -d '{"name":"log-test"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
# Manually add a fake run to the registry via python
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys, time, threading
sys.path.insert(0, 'agent'); sys.path.insert(0, 'agent/env_generator/llm_generator')
import live_monitor_server as lms
# Write some initial log
log = '/tmp/c36_ws/$PID/logs/generation.log'
import os; os.makedirs(os.path.dirname(log), exist_ok=True)
open(log, 'w').write('startup line 1\nstartup line 2\n')
# Stub a run
class FakePopen:
    def poll(self): return None
lms._RUN_REGISTRY['run_smoke_001'] = {
    'run_id': 'run_smoke_001', 'project_id': '$PID', 'started_at': time.time(),
    'command': ['fake'], 'log_path': log, 'popen': FakePopen(),
    'state': 'running', 'returncode': None,
}
print('seeded')
"
# Now curl the SSE log stream for 2 seconds while appending to the log
(sleep 0.5 && echo "TAILED LINE A" >> /tmp/c36_ws/$PID/logs/generation.log) &
curl -sS -N --max-time 2 http://127.0.0.1:4400/api/runs/run_smoke_001/log/stream | head -20
kill $SERVER_PID 2>/dev/null
```

Note: since the fake run lives in the server's `_RUN_REGISTRY` dict, we can't easily seed it from a separate process. Skip this smoke test if it's too complex; rely on the pytest tests instead.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/run_log_stream.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/run_log.css \
        agent/env_generator/llm_generator/live_monitor/src/views.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/v0-workspace.css \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 36: RunLogStream component + View Logs button in project view"
```

---

## Task 4: Migration log + push + ff-merge

### Step 1: full sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_run_log_stream.py -q 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_control.py agent/tests/test_live_monitor_endpoints.py agent/tests/test_live_monitor_sse.py agent/tests/test_global_sse_and_agents.py agent/tests/test_auth.py -q 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expect: 4 log-stream + ~120 collateral + 7 regressions OK.

### Step 2: Migration log

Overwrite `docs/superpowers/migration-logs/36-streaming-logs.md`:

```markdown
# Cutover 36: Streaming Log View

**Branch:** `haibotong-cutover-36-streaming-logs`
**Date:** 2026-05-26

## What

Replaces Cutover 34's 4KB `log_tail` polling with a real SSE stream of
generation logs. UI opens `EventSource(/api/runs/<id>/log/stream)` and
receives the live log as `data: {chunk}\n\n` events. On run completion,
a final `data: {_end: true, returncode: N}` event closes the stream.

## Commits

- (SHA) Cutover 36: record pre-flight baseline
- (SHA) Cutover 36: GET /api/runs/<id>/log/stream SSE endpoint + active_runs in project state
- (SHA) Cutover 36: RunLogStream component + View Logs button
- (this) Cutover 36: migration log

## New surfaces

### Backend
- `MonitorHandler._stream_run_log(run_id)` — initial 64KB snapshot + 200ms tail poll loop with heartbeat
- `GET /api/runs/<run_id>/log/stream` SSE endpoint
- `build_project_state` adds `active_runs: [{run_id, state, started_at, returncode}]` (per-project run handles)

### Frontend
- `src/run_log_stream.jsx` — modal log viewer with auto-scroll
- `styles/run_log.css`
- `views.jsx` — per-project "Active runs" pills + log modal
- Auto-follow toggle: user scrolling up freezes auto-scroll; scrolling back to bottom re-enables

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1108 → ~1112 (+4 log-stream tests)

## Architecture notes

- The stream polls every 200ms — adequate for ~5 lines/sec output rate
  without burning CPU.
- Initial snapshot trims to last 64KB so users joining mid-run see
  recent context without flooding the channel.
- Stream auto-closes on run completion (`_end` event); UI receives
  returncode and shows "Completed" or "Failed (rc=N)" pill.
- File rotation/truncation detection: if `cur_size < pos`, the stream
  resets to position 0.
- Heartbeat (`: heartbeat\n\n`) every 15s during quiet periods so
  proxies don't drop the connection.

## Known limits

- Log files are read from disk; if the file is deleted mid-stream, the
  next read returns empty and the stream sits idle until the run
  finishes (then emits `_end`).
- No log filtering or grep — just the raw stream. Future: client-side
  text filter in the modal.
- Modal blocks the rest of the UI while open. Future: dockable side
  panel.
- One stream per run. Multiple browsers viewing the same run each open
  their own file handle.
- Sessions and cookies are forwarded via `withCredentials: true` on
  EventSource so auth (Cutover 35) works.
```

### Step 3: commit migration log + plan + push + ff-merge

```bash
git add docs/superpowers/migration-logs/36-streaming-logs.md docs/superpowers/plans/2026-05-26-cutover-36-streaming-logs.md
git commit -m "Cutover 36: migration log"
git push -u red-env-gen haibotong-cutover-36-streaming-logs
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-36-streaming-logs
git merge --ff-only haibotong-cutover-36-streaming-logs
git push red-env-gen haibotong-0521-pipeline-web-tools
```
