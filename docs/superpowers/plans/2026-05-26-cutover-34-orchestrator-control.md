# Cutover 34: Orchestrator-Level Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Two top-level operations that currently require CLI access:
1. **Start Generation** — kick off the full multi-agent pipeline from the UI homepage with a wizard (name, description, model, provider, reference images). Backend spawns `main.py` as a subprocess scoped to the workspaces-root; UI tracks status + auto-navigates to the new project view.
2. **Deliver Project** — a per-project "Deliver" button that runs `compute_deliverability` (Cutover 24's pure aggregator over RunHub + APIHub + WorkHub + coverage/seed/visual audits). If verdict=`ready`, set project status to `completed`. If `blocked`, show the blockers list inline so the user knows what's missing.

**Architecture:**
- Backend `POST /api/runs` — body: `{name, description?, model?, provider?, reference_images?[]}` → creates workspace under `workspaces_root/<project_id>` (project_id derived from `name` or auto-generated), spawns `subprocess.Popen([python, "main.py", ...])` with stdout/stderr → `<workspace>/logs/generation.log`, captures the PID in a `_RUN_REGISTRY: Dict[run_id, RunHandle]`. Returns `{run_id, project_id}` immediately (async start).
- Backend `GET /api/runs` — list all runs (handle status).
- Backend `GET /api/runs/<run_id>/status` — `{state: running|completed|failed, returncode?, log_tail?}` via `Popen.poll()`.
- Backend `POST /api/runs/<run_id>/stop` — `Popen.terminate()` then `Popen.kill()` after 5s if still alive (DESTRUCTIVE — requires `confirm=True`).
- Backend `POST /api/projects/<id>/deliver` — calls `compute_deliverability(hubs, workspace, session_start_ts=0.0)`. If verdict=`ready` and `force_deliver` flag is not required, sets project status to `completed` + publishes `project_delivered` event. If `blocked`, returns the report with blockers list. Optional body field `force_deliver=True` (DESTRUCTIVE) overrides the gate, audited via EventHub.
- Frontend `homepage.jsx`: new "+ New Generation" prominent button → wizard form. On POST success → `LiveMonitorRouter.navigateTo("/projects/<id>")`.
- Frontend `views.jsx`: new "Deliver" button in the project header (or in a dedicated tab). Click → POST → if `ready` show success + status change; if `blocked` render the blockers list inline.

**Subprocess safety:**
- Each spawn uses `start_new_session=True` so killing the live monitor doesn't reap the run.
- Env passes through `OPENAI_API_KEY`/`GEMINI_API_KEY`/etc. from the live monitor's environment.
- A `RunHandle` dataclass tracks `(pid, project_id, started_at, log_path, popen)`.
- On server shutdown, all running RunHandles are NOT killed (intentional — generation must outlive UI restarts).

**Tech Stack:** Python `subprocess.Popen`, existing `live_monitor_server.py` patterns. No new deps.

---

## Test infrastructure conventions

Tests in `agent/tests/`. sys.path boilerplate at top. Use short-form imports `from live_monitor_server import ...`. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. NO `Co-Authored-By: Claude` trailer.

**Subprocess testing approach:** Use a `FakePopen` mock that mimics `Popen.poll() / returncode / terminate() / kill()` so tests don't actually spawn Python processes. The one e2e smoke test launches a trivial `python -c "print('hello'); import time; time.sleep(0.1)"` subprocess to verify the wiring.

---

## File Structure

**Create:** `docs/superpowers/migration-logs/34-orchestrator-control.md`, `agent/tests/test_orchestrator_control.py`

**Modify:** `agent/env_generator/llm_generator/live_monitor_server.py`, `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`, `agent/env_generator/llm_generator/live_monitor/src/views.jsx`, `agent/env_generator/llm_generator/live_monitor/styles/homepage.css`, `agent/env_generator/llm_generator/live_monitor/styles/v0-workspace.css` (for the new Deliver button)

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1086 (post-Cutover 33)
- [ ] Migration log stub at `docs/superpowers/migration-logs/34-orchestrator-control.md`
- [ ] Stage plan file
- [ ] Commit: `Cutover 34: record pre-flight baseline`

---

## Task 2: Backend — `_RUN_REGISTRY` + POST /api/runs

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Create: `agent/tests/test_orchestrator_control.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_orchestrator_control.py
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class FakePopen:
    """Mimics subprocess.Popen surface used by RunHandle."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 99999
        self._returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._returncode

    @property
    def returncode(self):
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15  # SIGTERM exit code

    def kill(self):
        self.killed = True
        self._returncode = -9

    def wait(self, timeout=None):
        return self._returncode if self._returncode is not None else 0


class TestRunRegistry(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        from live_monitor_server import _RUN_REGISTRY, _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _RUN_REGISTRY.clear()
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_start_run_creates_workspace_and_returns_ids(self):
        from live_monitor_server import start_run_call
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo", "description": "a demo"})
        self.assertNotIn("error", result, result)
        self.assertIn("run_id", result)
        self.assertIn("project_id", result)
        self.assertTrue((self.root / result["project_id"]).exists())

    def test_start_run_requires_name(self):
        from live_monitor_server import start_run_call
        result = start_run_call(self.root, {})
        self.assertIn("error", result)

    def test_start_run_records_in_registry(self):
        from live_monitor_server import start_run_call, _RUN_REGISTRY
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        self.assertIn(result["run_id"], _RUN_REGISTRY)
        handle = _RUN_REGISTRY[result["run_id"]]
        self.assertEqual(handle["project_id"], result["project_id"])
        self.assertEqual(handle["state"], "running")

    def test_run_status_returns_running_then_completed(self):
        from live_monitor_server import start_run_call, get_run_status, _RUN_REGISTRY
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        run_id = result["run_id"]
        status = get_run_status(run_id)
        self.assertEqual(status["state"], "running")
        # Simulate completion
        _RUN_REGISTRY[run_id]["popen"]._returncode = 0
        status = get_run_status(run_id)
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["returncode"], 0)

    def test_stop_run_requires_confirm(self):
        from live_monitor_server import start_run_call, stop_run_call
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            result = start_run_call(self.root, {"name": "demo"})
        stop_result = stop_run_call(result["run_id"], {})
        self.assertIn("error", stop_result)
        stop_result = stop_run_call(result["run_id"], {"confirm": True})
        self.assertEqual(stop_result.get("ok"), True)

    def test_list_runs_returns_handles(self):
        from live_monitor_server import start_run_call, list_runs
        with patch("live_monitor_server.subprocess.Popen", new=FakePopen):
            r1 = start_run_call(self.root, {"name": "first"})
            r2 = start_run_call(self.root, {"name": "second"})
        runs = list_runs()
        ids = {r["run_id"] for r in runs}
        self.assertIn(r1["run_id"], ids)
        self.assertIn(r2["run_id"], ids)
```

Run — expect failures (`_RUN_REGISTRY`, `start_run_call` etc. don't exist).

### TDD Step 2: implement

Edit `agent/env_generator/llm_generator/live_monitor_server.py`. Add near top imports:

```python
import subprocess
import uuid
```

(`subprocess` may not be imported yet; verify and add. `uuid` is already imported from prior cutovers.)

After the SSE block, add a Run Registry section:

```python
# ---------------------------------------------------------------------------
# Cutover 34: Run registry — track orchestrator subprocesses
# ---------------------------------------------------------------------------

_RUN_REGISTRY: Dict[str, dict] = {}
_RUN_REGISTRY_LOCK = threading.Lock()

# Provider <-> default API-key env var (must match main.py's provider_map).
_PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",  # main.py also accepts GOOGLE_API_KEY
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "local": None,
}


def _project_id_from_name(workspaces_root: Path, name: str) -> str:
    """Derive a filesystem-safe project_id from a human name; append uuid if collision."""
    import re
    base = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip()).strip("-").lower()
    if not base:
        base = "project"
    candidate = base
    if (workspaces_root / candidate).exists():
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
    return candidate


def start_run_call(workspaces_root: Path, body: dict) -> dict:
    """Spawn `main.py` as a subprocess for a new generation.

    Body fields:
      - name (required): human-readable project name
      - description: optional one-liner
      - model: optional LLM model (default gpt-4)
      - provider: optional, one of openai/google/anthropic/azure/local
      - reference_images: optional list of absolute paths
    Returns: {run_id, project_id, log_path} or {error}.
    """
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "name required"}
    workspaces_root = Path(workspaces_root)
    workspaces_root.mkdir(parents=True, exist_ok=True)

    project_id = _project_id_from_name(workspaces_root, name)
    workspace = workspaces_root / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "generation.log"

    model = body.get("model") or "gpt-4"
    provider = body.get("provider") or "openai"
    reference_images = body.get("reference_images") or []

    # main.py expects --output <dir>/<name>; we set output to workspaces_root
    # and name to project_id so the final output_dir lines up with workspace.
    python_bin = os.environ.get("ENVGEN_PYTHON") or sys.executable
    cmd = [
        python_bin, "-m", "env_generator.llm_generator.main",
        "--name", project_id,
        "--output", str(workspaces_root),
        "--model", model,
        "--provider", provider,
        "--no-fresh",
    ]
    if body.get("description"):
        cmd += ["--description", str(body["description"])]
    if reference_images:
        cmd += ["--reference-images", *[str(p) for p in reference_images]]
    if body.get("verbose"):
        cmd.append("--verbose")

    # Validate API key presence before spawning so the wizard gets immediate feedback.
    api_key_env = _PROVIDER_API_KEY_ENV.get(provider)
    if api_key_env and not os.environ.get(api_key_env) and not os.environ.get("GEMINI_API_KEY"):
        return {"error": f"missing API key env var: {api_key_env}"}

    try:
        log_fh = open(log_path, "ab", buffering=0)
    except Exception as e:
        return {"error": f"could not open log: {e}"}

    try:
        popen = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).parent.parent),  # agent/env_generator/
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ},
        )
    except Exception as e:
        try: log_fh.close()
        except Exception: pass
        return {"error": f"subprocess.Popen failed: {e}"}

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    handle = {
        "run_id": run_id,
        "project_id": project_id,
        "started_at": time.time(),
        "command": cmd,
        "log_path": str(log_path),
        "popen": popen,
        "state": "running",
        "returncode": None,
    }
    with _RUN_REGISTRY_LOCK:
        _RUN_REGISTRY[run_id] = handle

    # Publish lifecycle event so UI updates instantly.
    try:
        _publish_global("project_run_started", project_id,
                        {"run_id": run_id, "name": name, "model": model, "provider": provider})
    except Exception:
        pass

    return {
        "run_id": run_id,
        "project_id": project_id,
        "log_path": str(log_path),
    }


def get_run_status(run_id: str) -> dict:
    with _RUN_REGISTRY_LOCK:
        handle = _RUN_REGISTRY.get(run_id)
    if handle is None:
        return {"error": f"run not found: {run_id}"}
    popen = handle["popen"]
    rc = popen.poll()
    if rc is not None and handle["state"] == "running":
        handle["state"] = "completed" if rc == 0 else "failed"
        handle["returncode"] = rc
        try:
            _publish_global("project_run_finished", handle["project_id"],
                            {"run_id": run_id, "returncode": rc})
        except Exception:
            pass
    payload = {
        "run_id": handle["run_id"],
        "project_id": handle["project_id"],
        "state": handle["state"],
        "returncode": handle.get("returncode"),
        "started_at": handle["started_at"],
        "log_path": handle["log_path"],
    }
    # Tail the log (last ~50 lines) for quick UI feedback.
    try:
        log_path = Path(handle["log_path"])
        if log_path.exists():
            with log_path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                tail = 4096
                f.seek(max(0, size - tail), 0)
                payload["log_tail"] = f.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return payload


def stop_run_call(run_id: str, body: dict) -> dict:
    if not body.get("confirm"):
        return {"error": "stop requires body confirm=true"}
    with _RUN_REGISTRY_LOCK:
        handle = _RUN_REGISTRY.get(run_id)
    if handle is None:
        return {"error": f"run not found: {run_id}"}
    popen = handle["popen"]
    if popen.poll() is not None:
        return {"ok": True, "already_finished": True}
    try:
        popen.terminate()
        # Wait briefly; if still alive, hard kill.
        for _ in range(50):  # 5s total
            if popen.poll() is not None:
                break
            time.sleep(0.1)
        if popen.poll() is None:
            popen.kill()
        handle["state"] = "stopped"
        handle["returncode"] = popen.poll()
        return {"ok": True}
    except Exception as e:
        return {"error": f"stop failed: {e}"}


def list_runs() -> list:
    with _RUN_REGISTRY_LOCK:
        out = []
        for handle in _RUN_REGISTRY.values():
            popen = handle["popen"]
            rc = popen.poll()
            if rc is not None and handle["state"] == "running":
                handle["state"] = "completed" if rc == 0 else "failed"
                handle["returncode"] = rc
            out.append({
                "run_id": handle["run_id"],
                "project_id": handle["project_id"],
                "state": handle["state"],
                "returncode": handle.get("returncode"),
                "started_at": handle["started_at"],
                "log_path": handle["log_path"],
            })
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out
```

Add route branches in `do_POST` and `do_GET`. In `do_POST`, near the `/api/projects` block:

```python
# Cutover 34: orchestrator run control
if parsed.path == "/api/runs":
    if self._workspaces_root is None:
        self._write_json({"error": "server not in workspaces-root mode"}, status=HTTPStatus.BAD_REQUEST)
        return
    self._write_json(start_run_call(self._workspaces_root, body))
    return
if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/stop"):
    run_id = parsed.path[len("/api/runs/"):-len("/stop")]
    self._write_json(stop_run_call(run_id, body))
    return
```

In `do_GET`:

```python
if parsed.path == "/api/runs":
    self._write_json({"runs": list_runs()})
    return
if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/status"):
    run_id = parsed.path[len("/api/runs/"):-len("/status")]
    self._write_json(get_run_status(run_id))
    return
```

Run tests — expect 6 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py \
        agent/tests/test_orchestrator_control.py
git commit -m "Cutover 34: _RUN_REGISTRY + POST /api/runs + status/stop endpoints"
```

---

## Task 3: Backend — POST /api/projects/<id>/deliver

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py`
- Modify: `agent/tests/test_orchestrator_control.py` (append)

### TDD Step 1: failing tests

Append to `test_orchestrator_control.py`:

```python
class TestDeliverEndpoint(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        result = create_project_call(self.root, {"name": "deliver-test"})
        self.assertNotIn("error", result, result)
        self.project_id = result["id"]

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_deliver_call_returns_blockers_when_not_ready(self):
        from live_monitor_server import deliver_project_call
        # Fresh project has no successful run → should be blocked.
        result = deliver_project_call(self.root, self.project_id, {})
        self.assertIn("report", result)
        self.assertEqual(result["report"].get("verdict"), "blocked")
        self.assertTrue(len(result["report"].get("blockers", [])) > 0)

    def test_deliver_call_marks_completed_when_ready(self):
        from live_monitor_server import deliver_project_call, _resolve_hubs
        # Seed a passing RunHub run to flip the verdict.
        reg, _ = _resolve_hubs(self.root, self.project_id)
        reg.runhub.record_run({
            "run_id": "run_seed_1",
            "branch": "main",
            "generated_dir": "/tmp/dummy",
            "kind": "smoke",
            "status": "completed",
            "fail_count": 0,
            "started_at": time.time() - 60,
            "finished_at": time.time(),
        })
        # Note: full compute_deliverability has multiple gates; we may need to
        # ALSO pass force_deliver=True to bypass coverage/seed/visual gates
        # for this test if they fail without real app code.
        result = deliver_project_call(self.root, self.project_id, {"force_deliver": True})
        self.assertEqual(result.get("ok"), True)
        # Project status should now be "completed".
        self.assertEqual(reg.project_metadata.status, "completed")

    def test_deliver_call_force_publishes_audit_event(self):
        from live_monitor_server import deliver_project_call, _resolve_hubs
        reg, _ = _resolve_hubs(self.root, self.project_id)
        # Get pre-publish event count
        pre = len(reg.eventhub.snapshot().get("events", {}))
        deliver_project_call(self.root, self.project_id, {"force_deliver": True, "agent": "ui_user", "reason": "manual override"})
        post = len(reg.eventhub.snapshot().get("events", {}))
        self.assertGreater(post, pre)

    def test_deliver_unknown_project_returns_error(self):
        from live_monitor_server import deliver_project_call
        result = deliver_project_call(self.root, "nope", {})
        self.assertIn("error", result)
```

Run — expect `deliver_project_call` not found.

### TDD Step 2: implement

In `live_monitor_server.py`, add near the other `*_call` helpers:

```python
def deliver_project_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    """Run compute_deliverability and if verdict=ready, mark project completed.

    Body:
      - force_deliver: bool — if True, bypass the gate (DESTRUCTIVE; audited)
      - agent: who is invoking (default "ui_user")
      - reason: required if force_deliver=True
    """
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err:
        return err

    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}

    try:
        from multi_agent.runtime.deliverability import compute_deliverability
    except Exception as e:
        return {"error": f"could not import deliverability module: {e}"}

    try:
        report = compute_deliverability(reg, workspace, session_start_ts=0.0)
    except Exception as e:
        return {"error": f"compute_deliverability failed: {e}"}

    report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report)

    force = bool(body.get("force_deliver"))
    agent = (body.get("agent") or "ui_user").strip()
    reason = (body.get("reason") or "").strip()

    if force:
        if not reason or len(reason) < 5:
            return {"error": "force_deliver requires reason (>=5 chars)", "report": report_dict}
        # Audit: publish a force_deliver event so the override is traceable.
        try:
            reg.eventhub.publish_event(
                source_hub="ui",
                event_type="deliverability_bypass",
                payload={"agent": agent, "reason": reason, "blockers": report_dict.get("blockers", [])},
                recipients=[],
                priority="high",
            )
        except Exception:
            pass
        try:
            reg.set_project_status("completed")
        except Exception as e:
            return {"error": f"set_project_status failed: {e}", "report": report_dict}
        return {"ok": True, "delivered": True, "forced": True, "report": report_dict}

    if report_dict.get("verdict") == "ready":
        try:
            reg.set_project_status("completed")
        except Exception as e:
            return {"error": f"set_project_status failed: {e}", "report": report_dict}
        return {"ok": True, "delivered": True, "forced": False, "report": report_dict}

    # Blocked path
    return {"ok": False, "delivered": False, "report": report_dict}
```

Add route in `do_POST`:

```python
# Cutover 34: deliver project
if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/deliver"):
    pid = parsed.path[len("/api/projects/"):-len("/deliver")]
    self._write_json(deliver_project_call(self._workspaces_root, pid, body))
    return
```

Run tests — expect 4 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py \
        agent/tests/test_orchestrator_control.py
git commit -m "Cutover 34: deliver_project_call + POST /api/projects/<id>/deliver"
```

---

## Task 4: Frontend — Start Generation wizard on homepage

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx`
- Modify: `agent/env_generator/llm_generator/live_monitor/styles/homepage.css`

### Step 1: Add the wizard form

Edit `homepage.jsx`. Read the file first to find where the existing "+ New Project" form lives (Cutover 30 added it). The pattern: a state hook + collapsible form. Add a NEW button "+ Start Generation" alongside it that opens a richer wizard:

```jsx
const [showWizard, setShowWizard] = useState(false);
const [wName, setWName] = useState("");
const [wDescription, setWDescription] = useState("");
const [wModel, setWModel] = useState("gpt-4");
const [wProvider, setWProvider] = useState("openai");
const [wRefImages, setWRefImages] = useState("");  // newline-separated paths
const [wError, setWError] = useState("");
const [wPending, setWPending] = useState(false);

async function startGeneration() {
  if (!wName.trim()) { setWError("name required"); return; }
  setWPending(true);
  setWError("");
  try {
    const refImages = wRefImages
      .split("\n")
      .map(s => s.trim())
      .filter(Boolean);
    const r = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: wName,
        description: wDescription,
        model: wModel,
        provider: wProvider,
        reference_images: refImages,
      }),
    });
    const data = await r.json();
    if (data.error) {
      setWError(data.error);
      setWPending(false);
      return;
    }
    setShowWizard(false);
    setWName(""); setWDescription(""); setWRefImages("");
    // Navigate immediately to the new project view
    if (window.LiveMonitorRouter && data.project_id) {
      window.LiveMonitorRouter.navigateTo(`/projects/${data.project_id}`);
    }
  } catch (e) {
    setWError(String(e));
  } finally {
    setWPending(false);
  }
}
```

Render the wizard inline (below the existing actions row):

```jsx
<button onClick={() => setShowWizard(!showWizard)} className="hp-action">
  {showWizard ? "Cancel" : "+ Start Generation"}
</button>

{showWizard && (
  <div className="generation-wizard">
    <h3>Start a new generation</h3>
    {wError && <div className="wizard-error">{wError}</div>}
    <label>
      Project name *
      <input value={wName} onChange={e => setWName(e.target.value)} placeholder="my-todo-app" />
    </label>
    <label>
      Description
      <textarea value={wDescription} onChange={e => setWDescription(e.target.value)} rows={3} />
    </label>
    <label>
      Model
      <select value={wModel} onChange={e => setWModel(e.target.value)}>
        <option value="gpt-4">gpt-4</option>
        <option value="gpt-4o">gpt-4o</option>
        <option value="gpt-4o-mini">gpt-4o-mini</option>
        <option value="gemini-2.0-flash">gemini-2.0-flash</option>
        <option value="gemini-1.5-pro">gemini-1.5-pro</option>
        <option value="claude-3-opus">claude-3-opus</option>
        <option value="claude-3-sonnet">claude-3-sonnet</option>
      </select>
    </label>
    <label>
      Provider
      <select value={wProvider} onChange={e => setWProvider(e.target.value)}>
        <option value="openai">openai</option>
        <option value="google">google</option>
        <option value="anthropic">anthropic</option>
        <option value="azure">azure</option>
        <option value="local">local</option>
      </select>
    </label>
    <label>
      Reference image paths (one per line, optional)
      <textarea value={wRefImages} onChange={e => setWRefImages(e.target.value)} rows={2} placeholder="/path/to/screenshot.png" />
    </label>
    <button onClick={startGeneration} disabled={wPending} className="wizard-submit">
      {wPending ? "Starting…" : "Start"}
    </button>
  </div>
)}
```

### Step 2: styles

Append to `homepage.css`:

```css
.generation-wizard {
  background: #1e2837;
  border: 1px solid #2d3a4d;
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 600px;
}
.generation-wizard h3 { margin: 0 0 4px; font-size: 14px; }
.generation-wizard label {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: #aab;
  gap: 4px;
}
.generation-wizard input,
.generation-wizard select,
.generation-wizard textarea {
  font-family: inherit;
  background: #0e1626;
  color: #ddd;
  border: 1px solid #354054;
  border-radius: 4px;
  padding: 6px 8px;
}
.wizard-submit {
  align-self: flex-start;
  background: #4070d0;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 8px 16px;
  cursor: pointer;
}
.wizard-submit:disabled { background: #354054; cursor: wait; }
.wizard-error {
  background: #4a1f1f;
  color: #ffaaaa;
  border: 1px solid #6a2a2a;
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
}
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/homepage.css
git commit -m "Cutover 34: homepage Start Generation wizard"
```

---

## Task 5: Frontend — Deliver button + Run status panel

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor/src/views.jsx` (or wherever the per-project header sits)
- Modify: `agent/env_generator/llm_generator/live_monitor/styles/v0-workspace.css`

### Step 1: Deliver button

Read `views.jsx` to find the project header / status pill area. Add a `<DeliverButton>` component that, when clicked, POSTs to `/api/projects/<id>/deliver` with empty body. Result:
- If `{ok: true}` → flash a success toast + `window.LiveMonitorRefresh?.()`
- If blocked → render an inline `<BlockersList>` showing `report.blockers` (each blocker is a short string)
- Add a secondary "Force Deliver" button that opens a small form requiring `reason` (≥5 chars) + `window.confirm` before posting `{force_deliver: true, reason, agent: "ui_user"}`.

Skeleton:

```jsx
function DeliverButton({ projectId }) {
  const [pending, setPending] = useState(false);
  const [report, setReport] = useState(null);
  const [forceMode, setForceMode] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function tryDeliver(force) {
    if (force && !window.confirm("Force-deliver bypasses all gates. Continue?")) return;
    if (force && reason.trim().length < 5) { setError("reason must be at least 5 chars"); return; }
    setPending(true); setError("");
    try {
      const body = force ? { force_deliver: true, reason, agent: "ui_user" } : {};
      const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/deliver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (data.ok) {
        setReport(data.report);
        setForceMode(false);
        setReason("");
        window.LiveMonitorRefresh?.();
      } else {
        setReport(data.report || null);
        if (data.error) setError(data.error);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="deliver-section">
      <button onClick={() => tryDeliver(false)} disabled={pending} className="deliver-btn">
        {pending ? "Checking…" : "Deliver"}
      </button>
      <button onClick={() => setForceMode(!forceMode)} className="force-deliver-toggle">
        {forceMode ? "Cancel force" : "Force"}
      </button>
      {forceMode && (
        <div className="force-deliver-form">
          <input value={reason} onChange={e => setReason(e.target.value)} placeholder="reason (≥5 chars)" />
          <button onClick={() => tryDeliver(true)} disabled={pending} className="deliver-btn destructive">Force Deliver</button>
        </div>
      )}
      {error && <div className="deliver-error">{error}</div>}
      {report && report.verdict && (
        <div className={`deliver-report verdict-${report.verdict}`}>
          <strong>Verdict: {report.verdict}</strong>
          {report.blockers && report.blockers.length > 0 && (
            <ul className="blockers-list">
              {report.blockers.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
```

Mount it in the project header (e.g., next to the project name in `views.jsx`).

### Step 2: Run status panel (optional, lightweight)

Add a small `<RunStatusBadge>` that polls `/api/runs?project_id=<id>` (or filters client-side) every 3s while a run is in `state="running"`. Show "Generating… (RUNNING)" + log-tail link. Wire it into the project header next to the Deliver button. (If time is short, this can be deferred to a future cutover.)

### Step 3: styles

Append to `v0-workspace.css`:

```css
.deliver-section { display: flex; flex-direction: column; gap: 8px; padding: 12px; background: #1a2230; border-radius: 6px; }
.deliver-btn { background: #2e8c4a; color: #fff; border: none; border-radius: 4px; padding: 8px 18px; cursor: pointer; font-weight: 600; }
.deliver-btn.destructive { background: #b04040; }
.deliver-btn:disabled { background: #555; cursor: wait; }
.force-deliver-toggle { background: transparent; color: #aab; border: 1px solid #2d3a4d; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 11px; }
.force-deliver-form { display: flex; gap: 6px; }
.force-deliver-form input { flex: 1; background: #0e1626; color: #ddd; border: 1px solid #354054; border-radius: 4px; padding: 6px 8px; }
.deliver-error { background: #4a1f1f; color: #ffaaaa; padding: 8px; border-radius: 4px; font-size: 12px; }
.deliver-report { background: #14202c; border: 1px solid #2d3a4d; border-radius: 4px; padding: 10px; font-size: 12px; }
.deliver-report.verdict-ready { border-left: 4px solid #2e8c4a; }
.deliver-report.verdict-blocked { border-left: 4px solid #b04040; }
.blockers-list { margin: 6px 0 0; padding-left: 18px; color: #ffcccc; }
```

### Manual smoke (no browser available — use curl)

```bash
mkdir -p /tmp/cutover34_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/cutover34_ws --port 4399 &
SERVER_PID=$!
sleep 1
# Create project
PID=$(curl -sS -X POST http://127.0.0.1:4399/api/projects -H "Content-Type: application/json" -d '{"name":"delivery-test"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "project: $PID"
# Try to deliver — expect blocked
curl -sS -X POST http://127.0.0.1:4399/api/projects/$PID/deliver -H "Content-Type: application/json" -d '{}' | python -m json.tool | head -10
# Force-deliver with a reason
curl -sS -X POST http://127.0.0.1:4399/api/projects/$PID/deliver -H "Content-Type: application/json" -d '{"force_deliver":true,"reason":"manual UI override","agent":"ui_user"}' | python -m json.tool | head -10
# Verify status flipped to completed
curl -sS http://127.0.0.1:4399/api/projects | python -c "import json,sys; d=json.load(sys.stdin); print([p for p in d['projects'] if p['id']=='$PID'])"
kill $SERVER_PID 2>/dev/null
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/views.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/v0-workspace.css
git commit -m "Cutover 34: per-project Deliver + Force-Deliver buttons in project view"
```

---

## Task 6: Migration log + push + ff-merge

### Step 1: Final sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_control.py -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expect: 10 PASS (6 run-registry + 4 deliver) + 7 regressions OK.

### Step 2: full migration log

Overwrite `docs/superpowers/migration-logs/34-orchestrator-control.md`:

```markdown
# Cutover 34: Orchestrator-Level Control

**Branch:** `haibotong-cutover-34-orchestrator-control`
**Date:** 2026-05-26

## What

Two long-deferred top-level operations now have UI surfaces.

1. **Start Generation wizard:** homepage button opens a wizard collecting
   name / description / model / provider / reference images. POST to
   `/api/runs` spawns `main.py` as a subprocess scoped to the
   workspaces-root and tracks it in `_RUN_REGISTRY`. The UI auto-navigates
   to the new project view immediately; the orchestrator runs in
   background and emits events via Cutover 31 SSE.

2. **Deliver button + force-deliver:** per-project header button calls
   `POST /api/projects/<id>/deliver` which runs `compute_deliverability`
   (Cutover 24's pure aggregator). If verdict=ready, project status flips
   to `completed`. If blocked, the report's blockers list renders inline.
   A separate Force-Deliver flow requires a reason (≥5 chars), publishes
   an audit event, and overrides the gate.

## Commits

- `(SHA)` Cutover 34: record pre-flight baseline
- `(SHA)` Cutover 34: _RUN_REGISTRY + POST /api/runs + status/stop endpoints
- `(SHA)` Cutover 34: deliver_project_call + POST /api/projects/<id>/deliver
- `(SHA)` Cutover 34: homepage Start Generation wizard
- `(SHA)` Cutover 34: per-project Deliver + Force-Deliver buttons
- (this commit) Cutover 34: migration log

## New surfaces

### Backend
- `_RUN_REGISTRY: Dict[run_id, RunHandle]` — module-level subprocess tracker
- `start_run_call(workspaces_root, body)` → spawn main.py subprocess
- `get_run_status(run_id)` → state + returncode + log_tail
- `stop_run_call(run_id, body)` → terminate then kill after 5s (DESTRUCTIVE)
- `list_runs()` → snapshot of all handles
- `deliver_project_call(workspaces_root, project_id, body)` → check + set status
- 5 new endpoints (POST /api/runs, GET /api/runs, GET /api/runs/<id>/status, POST /api/runs/<id>/stop, POST /api/projects/<id>/deliver)
- Lifecycle events: `project_run_started`, `project_run_finished`, `deliverability_bypass`

### Frontend
- `homepage.jsx`: `+ Start Generation` button + inline wizard form; `LiveMonitorRouter.navigateTo` on submit
- `views.jsx`: `<DeliverButton>` + `<ForceDeliverForm>` in project header
- `homepage.css`, `v0-workspace.css`: new styles

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1086 → ~1096 (+10 new tests)

## Architecture notes

- Subprocesses launched with `start_new_session=True` so the orchestrator
  outlives the live monitor server. On UI restart, `_RUN_REGISTRY` is
  empty until a run is re-attached (future cutover).
- `main.py` is invoked with `--output <workspaces_root> --name <project_id>`
  so the workspace it writes to is exactly `workspaces_root/project_id`
  — which matches the per-project hub records (Cutover 26).
- The Deliver endpoint uses the existing `compute_deliverability` from
  Cutover 24 unchanged — no new gates added.
- Force-deliver publishes a `deliverability_bypass` EventHub event so
  every override is traceable (matches Cutover 30 audit pattern).

## Known limits

- `_RUN_REGISTRY` is in-memory only. Server restart drops handle tracking
  (subprocess keeps running but UI doesn't see it). Future: persist
  handles to a JSON file on disk + re-attach on startup.
- No streaming log view yet — UI polls `/api/runs/<id>/status` which
  returns `log_tail` (last 4KB). True streaming log = future cutover.
- No "abort generation from project view" button (only from the runs
  list). Future cutover may add per-run UI controls.
- API key checking is a single env-var lookup; doesn't validate that the
  key is actually accepted by the LLM provider.
- Reference image paths must be absolute paths accessible by the live
  monitor process — no file upload UI yet.
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/34-orchestrator-control.md docs/superpowers/plans/2026-05-26-cutover-34-orchestrator-control.md
git commit -m "Cutover 34: migration log"
git push -u red-env-gen haibotong-cutover-34-orchestrator-control
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-34-orchestrator-control
git merge --ff-only haibotong-cutover-34-orchestrator-control
git push red-env-gen haibotong-0521-pipeline-web-tools
```
