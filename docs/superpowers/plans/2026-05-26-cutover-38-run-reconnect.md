# Cutover 38: Run Reconnect on Server Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Cutover 34's `_RUN_REGISTRY` is in-memory only. Server restart drops handle tracking — the subprocess keeps running (it was spawned with `start_new_session=True`) but the UI loses visibility. Fix: persist the registry to disk at `<workspaces_root>/.runs.json`, reload on startup, and substitute a `_AttachedRunHandle` (Popen-API-compatible shim using `os.kill(pid, 0)` for liveness) so the rest of the code works unchanged.

**Architecture:**
- `_save_registry(workspaces_root)` — serialize the registry to JSON (drop the `popen` field; keep `pid`, `state`, etc.).
- `_load_registry(workspaces_root)` — read the JSON, for each entry call `os.kill(pid, 0)` to test liveness. Live → mint an `_AttachedRunHandle(pid)`. Dead → state="completed", returncode=None, note in metadata.
- `_AttachedRunHandle`: tiny class with `.pid`, `.poll()` (returns None if alive via `os.kill(pid, 0)`, else 0), `.returncode`, `.terminate()` (SIGTERM via `os.kill`), `.kill()` (SIGKILL).
- Save triggers: every `start_run_call` (after register), every `stop_run_call`, and inside `get_run_status` / `list_runs` whenever a state transition is detected. Also on `atexit` for clean shutdown.
- Load trigger: lazy on first call to a workspaces-root helper. Track per-workspaces-root via a `_LOADED_ROOTS: Set[Path]` set so we don't re-load on every request.

**Tech Stack:** stdlib `os`, `signal`. No new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/`. sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. NO `Co-Authored-By: Claude` trailer.

For tests involving real PIDs, use the **current Python PID** (`os.getpid()`) for "alive" cases — it's always alive during the test run — and a guaranteed-dead PID (allocate one by spawning a quick subprocess that exits, then read its already-reaped pid).

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/38-run-reconnect.md`
- `agent/tests/test_run_reconnect.py`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (persistence + reconnect + `_AttachedRunHandle`)

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1118
- [ ] Migration log stub
- [ ] Stage plan
- [ ] Commit: `Cutover 38: record pre-flight baseline`

---

## Task 2: Implementation

**Files:**
- Modify: `live_monitor_server.py`
- Create: `agent/tests/test_run_reconnect.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_run_reconnect.py
import json
import os
import signal
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _dead_pid() -> int:
    """Return a pid that has already exited (so os.kill(pid, 0) raises)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class TestAttachedRunHandle(unittest.TestCase):
    def test_poll_returns_none_when_pid_alive(self):
        from live_monitor_server import _AttachedRunHandle
        h = _AttachedRunHandle(pid=os.getpid())
        self.assertIsNone(h.poll())
        self.assertIsNone(h.returncode)

    def test_poll_returns_zero_when_pid_dead(self):
        from live_monitor_server import _AttachedRunHandle
        h = _AttachedRunHandle(pid=_dead_pid())
        # Allow a brief moment for the OS to reap, then poll
        time.sleep(0.05)
        rc = h.poll()
        self.assertIsNotNone(rc)


class TestRegistryPersistence(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        os.environ.pop("ENVGEN_AUTH_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        self._tmp.cleanup()

    def test_save_registry_writes_runs_json(self):
        from live_monitor_server import _RUN_REGISTRY, _save_registry
        _RUN_REGISTRY["run_test"] = {
            "run_id": "run_test",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["python", "main.py"],
            "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": 12345, "poll": lambda self: None, "returncode": None})(),
            "state": "running",
            "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        runs_file = self.root / ".runs.json"
        self.assertTrue(runs_file.exists())
        data = json.loads(runs_file.read_text())
        self.assertIn("run_test", data)
        self.assertEqual(data["run_test"]["pid"], 12345)
        # popen object must not be persisted
        self.assertNotIn("popen", data["run_test"])

    def test_load_registry_creates_attached_handles_for_alive_pids(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY, _AttachedRunHandle
        # Use our own pid as a "still alive" fake run
        _RUN_REGISTRY["run_alive"] = {
            "run_id": "run_alive",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["python", "main.py"],
            "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": os.getpid(), "poll": lambda self: None, "returncode": None})(),
            "state": "running",
            "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        _load_registry(self.root)
        self.assertIn("run_alive", _RUN_REGISTRY)
        reloaded = _RUN_REGISTRY["run_alive"]
        self.assertEqual(reloaded["state"], "running")
        self.assertIsInstance(reloaded["popen"], _AttachedRunHandle)
        self.assertIsNone(reloaded["popen"].poll())  # still alive

    def test_load_registry_marks_dead_pids_as_completed(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY
        dead = _dead_pid()
        _RUN_REGISTRY["run_dead"] = {
            "run_id": "run_dead",
            "project_id": "p1",
            "started_at": 1000.0,
            "command": ["x"], "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": dead, "poll": lambda self: None, "returncode": None})(),
            "state": "running", "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        time.sleep(0.05)  # ensure os has reaped
        _load_registry(self.root)
        self.assertIn("run_dead", _RUN_REGISTRY)
        self.assertEqual(_RUN_REGISTRY["run_dead"]["state"], "completed")

    def test_load_registry_idempotent_on_repeated_calls(self):
        from live_monitor_server import _save_registry, _load_registry, _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY["run_x"] = {
            "run_id": "run_x", "project_id": "p", "started_at": 1.0,
            "command": ["x"], "log_path": "/tmp/x.log",
            "popen": type("Fake", (), {"pid": os.getpid(), "poll": lambda self: None, "returncode": None})(),
            "state": "running", "returncode": None,
            "workspaces_root": str(self.root),
        }
        _save_registry(self.root)
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        _load_registry(self.root)
        first_handle = _RUN_REGISTRY["run_x"]["popen"]
        _load_registry(self.root)
        second_handle = _RUN_REGISTRY["run_x"]["popen"]
        # Should NOT re-mint a new handle (idempotent)
        self.assertIs(first_handle, second_handle)

    def test_missing_runs_file_is_silent(self):
        from live_monitor_server import _load_registry, _RUN_REGISTRY
        _load_registry(self.root)
        # No file → no entries added; no exception
        self.assertEqual(len(_RUN_REGISTRY), 0)


class TestStartRunSavesRegistry(unittest.TestCase):
    """start_run_call must save the registry after registering the new handle."""
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        os.environ.setdefault("OPENAI_API_KEY", "test")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _LOADED_ROOTS
        _RUN_REGISTRY.clear()
        _LOADED_ROOTS.clear()
        self._tmp.cleanup()

    def test_start_run_persists_to_disk(self):
        from live_monitor_server import start_run_call
        # FakePopen-style mock at module level
        class FakePopen:
            def __init__(self, *a, **kw):
                self.pid = 99999
                self._rc = None
            def poll(self): return self._rc
            @property
            def returncode(self): return self._rc
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "persist-demo"})
        self.assertNotIn("error", result)
        runs_file = self.root / ".runs.json"
        self.assertTrue(runs_file.exists())
        data = json.loads(runs_file.read_text())
        self.assertIn(result["run_id"], data)
        self.assertEqual(data[result["run_id"]]["pid"], 99999)
```

Run → expect failures.

### TDD Step 2: implement

Edit `live_monitor_server.py`. Add a section after `_RUN_REGISTRY` and its helpers:

```python
# ---------------------------------------------------------------------------
# Cutover 38: Persistence + reconnect across server restarts
# ---------------------------------------------------------------------------

_LOADED_ROOTS: Set[str] = set()
_LOADED_ROOTS_LOCK = threading.Lock()


class _AttachedRunHandle:
    """Popen-API-compatible shim for a process we no longer own.

    After server restart, our orchestrator subprocesses (started with
    start_new_session=True) survive. We can no longer waitpid on them
    (we're not the parent), but we CAN signal them and check liveness
    via os.kill(pid, 0). `poll()` returns None while alive and 0 when
    the OS reports the pid is gone. The true exit status is unknown
    (so `returncode` stays None even after death).
    """

    def __init__(self, pid: int):
        self.pid = pid
        self._returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self._returncode is not None:
            return self._returncode
        try:
            os.kill(self.pid, 0)
            return None  # still alive
        except ProcessLookupError:
            self._returncode = 0  # we don't know real rc; assume clean
            return 0
        except PermissionError:
            return None  # alive, just not signal-able
        except Exception:
            self._returncode = 0
            return 0

    @property
    def returncode(self) -> Optional[int]:
        return self._returncode

    def terminate(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except Exception:
            pass

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except Exception:
            pass

    def wait(self, timeout: Optional[float] = None) -> int:
        # Poll until dead or timeout
        deadline = time.time() + (timeout if timeout is not None else 30.0)
        while time.time() < deadline:
            if self.poll() is not None:
                return self._returncode or 0
            time.sleep(0.1)
        return self._returncode or 0


def _registry_file(workspaces_root: Path) -> Path:
    return Path(workspaces_root) / ".runs.json"


def _save_registry(workspaces_root: Path) -> None:
    """Persist the in-memory registry (filtered to this workspaces_root) to disk."""
    try:
        Path(workspaces_root).mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    out: Dict[str, dict] = {}
    with _RUN_REGISTRY_LOCK:
        for run_id, h in _RUN_REGISTRY.items():
            if h.get("workspaces_root") and str(h["workspaces_root"]) != str(workspaces_root):
                continue
            popen = h.get("popen")
            pid = getattr(popen, "pid", None) if popen else h.get("pid")
            entry = {k: v for k, v in h.items() if k != "popen"}
            entry["pid"] = pid
            out[run_id] = entry
    tmp_path = _registry_file(workspaces_root).with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(out, indent=2, default=str))
        os.replace(tmp_path, _registry_file(workspaces_root))
    except Exception:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def _load_registry(workspaces_root: Path) -> None:
    """Load persisted registry entries from disk; attach _AttachedRunHandle to live pids.

    Idempotent — a second call for the same workspaces_root is a no-op.
    """
    key = str(Path(workspaces_root).resolve())
    with _LOADED_ROOTS_LOCK:
        if key in _LOADED_ROOTS:
            return
        _LOADED_ROOTS.add(key)
    runs_file = _registry_file(workspaces_root)
    if not runs_file.exists():
        return
    try:
        data = json.loads(runs_file.read_text())
    except Exception:
        return
    with _RUN_REGISTRY_LOCK:
        for run_id, entry in (data or {}).items():
            if run_id in _RUN_REGISTRY:
                continue  # already in memory, prefer it
            pid = entry.get("pid")
            attached = None
            state = entry.get("state", "running")
            returncode = entry.get("returncode")
            if pid:
                attached = _AttachedRunHandle(pid=int(pid))
                if attached.poll() is not None and state == "running":
                    state = "completed"
            _RUN_REGISTRY[run_id] = {
                **entry,
                "popen": attached,
                "state": state,
                "returncode": returncode,
                "workspaces_root": entry.get("workspaces_root") or str(workspaces_root),
            }
```

Add `import signal` to the top imports if missing. Same for `Set`.

Modify `start_run_call` to:
1. Capture `workspaces_root` in the handle so `_save_registry` can filter by it.
2. Call `_save_registry(workspaces_root)` after registering.

Find the existing `start_run_call`, in the handle-creation block, add `"workspaces_root": str(workspaces_root)`. Then at the very end (just before `return`), add:

```python
_save_registry(workspaces_root)
```

Modify `stop_run_call` to save after the state transition:

```python
# (inside stop_run_call, after handle["state"] is updated, BEFORE return)
ws = handle.get("workspaces_root")
if ws:
    _save_registry(Path(ws))
```

Modify `get_run_status` to save when it observes a state transition:

```python
# inside get_run_status, after handle["state"] is updated from running to completed/failed:
ws = handle.get("workspaces_root")
if ws:
    _save_registry(Path(ws))
```

Add `_load_registry(workspaces_root)` call lazily to `_resolve_hubs` (it's called on every workspace request):

```python
def _resolve_hubs(workspaces_root: Path, project_id: str):
    _load_registry(workspaces_root)  # Cutover 38: idempotent reattach
    ...
```

Run tests → expect 9 PASS (2 attached-handle + 5 registry persistence + 1 idempotent + 1 start_run-persists; plus the `test_missing_runs_file_is_silent`).

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_run_reconnect.py
git commit -m "Cutover 38: persist _RUN_REGISTRY to .runs.json + _AttachedRunHandle for restart reconnect"
```

---

## Task 3: Migration log + push + ff-merge

### Step 1: sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_run_reconnect.py -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_control.py agent/tests/test_live_monitor_endpoints.py agent/tests/test_auth.py agent/tests/test_run_log_stream.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

### Step 2: Migration log

```markdown
# Cutover 38: Run Reconnect on Server Restart

**Branch:** `haibotong-cutover-38-run-reconnect`
**Date:** 2026-05-26

## What

Persist Cutover 34's `_RUN_REGISTRY` to disk so the live monitor can
re-attach to live orchestrator subprocesses across a server restart.

- `_save_registry(workspaces_root)` → writes `<workspaces_root>/.runs.json`
  (excludes the Popen handle; keeps pid + state + returncode + metadata)
- `_load_registry(workspaces_root)` → reads the file, mints an
  `_AttachedRunHandle(pid)` for each live pid (verified via
  `os.kill(pid, 0)`), marks dead pids as `state="completed"`.
- Triggers: `start_run_call`, `stop_run_call`, `get_run_status` (on
  state transition). Load is lazy + idempotent via `_LOADED_ROOTS`,
  called inside `_resolve_hubs`.

`_AttachedRunHandle` mimics the Popen surface (`pid`, `poll()`,
`returncode`, `terminate()`, `kill()`, `wait()`) using `os.kill` for
liveness + signaling. Real exit status is unknown for non-child
processes, so `returncode` reports `0` on detected death (best-effort).

## Commits

- (SHA) Cutover 38: record pre-flight baseline
- (SHA) Cutover 38: persist _RUN_REGISTRY to .runs.json + _AttachedRunHandle for restart reconnect
- (this) Cutover 38: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1118 → ~1126 (+8 reconnect tests)

## Architecture notes

- Persistence file location: `<workspaces_root>/.runs.json` — alongside
  per-project `<project_id>/project.json` records (Cutover 26).
- File writes use atomic `os.replace(tmp, final)` to avoid partial reads.
- After restart, the SSE log stream (Cutover 36) still works because
  `_AttachedRunHandle.poll()` follows the same contract as Popen.
- The DeliverButton (Cutover 34) doesn't care about run handles — it
  checks `compute_deliverability` directly.
- Project lifecycle SSE events (Cutover 32) `project_run_started` /
  `project_run_finished` are NOT replayed on reconnect (they're event-
  sourced and ephemeral). The UI sees the run in `active_runs` on next
  state refresh.

## Known limits

- Real exit status (returncode) is unknown for non-child reattached
  processes. The handle reports `0` once the pid disappears. If the
  orchestrator failed and you need the true return code, check the
  log file at `<workspace>/logs/generation.log`.
- `_LOADED_ROOTS` is per process. If you point a single server at
  multiple workspaces-roots over its lifetime (uncommon), each gets
  loaded the first time it's resolved.
- No file lock on `.runs.json`. If two live-monitor processes share a
  workspaces-root (also uncommon), concurrent saves could clobber.
  Add file locking in a future cutover if multi-server becomes a thing.
- Stale entries in `.runs.json` accumulate. Future cutover may add an
  "archive completed runs older than N days" cleanup.
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/38-run-reconnect.md docs/superpowers/plans/2026-05-26-cutover-38-run-reconnect.md
git commit -m "Cutover 38: migration log"
git push -u red-env-gen haibotong-cutover-38-run-reconnect
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-38-run-reconnect
git merge --ff-only haibotong-cutover-38-run-reconnect
git push red-env-gen haibotong-0521-pipeline-web-tools
```
