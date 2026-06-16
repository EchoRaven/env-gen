# Cutover 39: User-Defined Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Let users add custom deliverability gates from the UI. A gate is a typed rule the system evaluates against the current project state; if any user gate fails, `compute_deliverability` reports it as a blocker and the Deliver button is gated (force-deliver still works, audited as before). Four built-in gate types cover the most common asks: file_exists, endpoint_exists, mcp_tool_exists, visual_similarity. No arbitrary code execution — gate types are a fixed enum for security.

**Architecture:**
- Persist user gates per project at `<workspace>/.user_gates.json` — list of `{id, name, type, params, created_at, _updated_at}`.
- Backend module: `runtime/user_gates.py` exposes `evaluate_gate(gate, reg, workspace) -> {passed, message, details}`. Pure function over hub state + filesystem.
- 5 endpoints under `/api/projects/<id>/user_gates`:
  - `GET` → `{gates: [...]}` with current pass/fail state for each
  - `POST` → create a gate (validates type + params)
  - `PUT /<gate_id>` → update name/params
  - `DELETE /<gate_id>` → remove
  - `POST /<gate_id>/evaluate` → force re-evaluate one gate
- `deliver_project_call` extension: after `compute_deliverability`, evaluate all user gates and merge any failures into the blockers list. UI shows them with `user_gate:` prefix.
- Frontend: new "Gates" tab in WorkHub panel (or top-level project section) — list with status pills, "+ Add Gate" form with type dropdown + dynamic params form, edit/delete buttons.

**Gate types:**
- `file_exists`: params `{path: str}` — workspace contains this file
- `endpoint_exists`: params `{method: str, path: str}` — APIHub has a matching endpoint with status != "deprecated"
- `mcp_tool_exists`: params `{name: str}` — APIHub MCP registry has this tool
- `visual_similarity`: params `{page_id: str, min_similarity: float}` — WorkHub visual review for that page has `similarity_score >= min_similarity`

**Tech Stack:** stdlib only.

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. Pytest: `python -m pytest agent/tests/ -q`. NO `Co-Authored-By: Claude` trailer.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/39-user-gates.md`
- `agent/env_generator/llm_generator/multi_agent/runtime/user_gates.py`
- `agent/tests/test_user_gates.py`
- `agent/tests/test_user_gates_endpoints.py`

**Modify:**
- `agent/env_generator/llm_generator/live_monitor_server.py` (5 endpoints + extend `deliver_project_call`)
- `agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx` (Gates tab/section in WorkHubPanel)
- `agent/env_generator/llm_generator/live_monitor/styles/hubs.css`

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1126
- [ ] Migration log stub
- [ ] Stage plan
- [ ] Commit: `Cutover 39: record pre-flight baseline`

---

## Task 2: `user_gates.py` evaluator + tests

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/user_gates.py`
- Create: `agent/tests/test_user_gates.py`

### TDD Step 1: failing tests

```python
# agent/tests/test_user_gates.py
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.user_gates import (
    evaluate_gate,
    validate_gate,
    VALID_GATE_TYPES,
)


class TestValidateGate(unittest.TestCase):
    def test_known_type_passes(self):
        for t in VALID_GATE_TYPES:
            err = validate_gate({"type": t, "name": "x", "params": {}})
            # Some types require params; the validator should at least accept the type
            self.assertNotEqual(err, "unknown gate type", f"Type {t} rejected: {err}")

    def test_unknown_type_rejected(self):
        err = validate_gate({"type": "bogus", "name": "x", "params": {}})
        self.assertEqual(err, "unknown gate type")

    def test_file_exists_missing_path(self):
        err = validate_gate({"type": "file_exists", "name": "x", "params": {}})
        self.assertIn("path", err)

    def test_endpoint_exists_missing_path(self):
        err = validate_gate({"type": "endpoint_exists", "name": "x", "params": {"method": "GET"}})
        self.assertIn("path", err)

    def test_visual_similarity_validates_min(self):
        err = validate_gate({"type": "visual_similarity", "name": "x", "params": {"page_id": "p"}})
        self.assertIn("min_similarity", err)
        err = validate_gate({"type": "visual_similarity", "name": "x", "params": {"page_id": "p", "min_similarity": 2.0}})
        self.assertIn("between", err)
        err = validate_gate({"type": "visual_similarity", "name": "x", "params": {"page_id": "p", "min_similarity": 0.8}})
        self.assertIsNone(err)


class TestFileExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_file_present(self):
        (self.workspace / "README.md").write_text("hi")
        result = evaluate_gate({"type": "file_exists", "params": {"path": "README.md"}}, self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_file_absent(self):
        result = evaluate_gate({"type": "file_exists", "params": {"path": "nope.txt"}}, self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("nope.txt", result["message"])

    def test_rejects_path_traversal(self):
        result = evaluate_gate({"type": "file_exists", "params": {"path": "../outside.txt"}}, self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("invalid", result["message"].lower())


class TestEndpointExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_endpoint_registered(self):
        self.reg.apihub.register_endpoint("GET", "/api/users", schema={}, provider="backend", agent="test")
        result = evaluate_gate({"type": "endpoint_exists", "params": {"method": "GET", "path": "/api/users"}},
                               self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_endpoint_missing(self):
        result = evaluate_gate({"type": "endpoint_exists", "params": {"method": "POST", "path": "/api/login"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])

    def test_fails_when_endpoint_deprecated(self):
        self.reg.apihub.register_endpoint("DELETE", "/api/users", schema={}, provider="backend", agent="test")
        self.reg.apihub.deprecate_endpoint("DELETE /api/users", agent="test")
        result = evaluate_gate({"type": "endpoint_exists", "params": {"method": "DELETE", "path": "/api/users"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])


class TestMcpToolExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_mcp_tool_registered(self):
        self.reg.apihub.register_mcp_server(server_id="srv1", name="MyServer", agent="test")
        self.reg.apihub.register_mcp_tool(server_id="srv1", tool_name="search", input_schema={}, agent="test")
        result = evaluate_gate({"type": "mcp_tool_exists", "params": {"name": "search"}}, self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_missing(self):
        result = evaluate_gate({"type": "mcp_tool_exists", "params": {"name": "nonexistent"}}, self.reg, self.workspace)
        self.assertFalse(result["passed"])


class TestVisualSimilarityGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_similarity_above_min(self):
        # Register a visual review for a page with similarity=0.9
        page = self.reg.workhub.register_visual_review_task(
            route="/home", screenshot_path="/tmp/foo.png", agent="test"
        )
        self.reg.workhub.submit_visual_review(
            page_id=page["id"], reviewer="test", state="approve",
            summary="looks good and matches reference closely",
            similarity_score=0.9,
        )
        result = evaluate_gate({"type": "visual_similarity",
                                 "params": {"page_id": page["id"], "min_similarity": 0.8}},
                                self.reg, self.workspace)
        self.assertTrue(result["passed"], result)

    def test_fails_when_similarity_below_min(self):
        page = self.reg.workhub.register_visual_review_task(
            route="/home", screenshot_path="/tmp/foo.png", agent="test"
        )
        self.reg.workhub.submit_visual_review(
            page_id=page["id"], reviewer="test", state="needs_revision",
            summary="similarity is too low for approval",
            similarity_score=0.5,
        )
        result = evaluate_gate({"type": "visual_similarity",
                                 "params": {"page_id": page["id"], "min_similarity": 0.8}},
                                self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("0.5", result["message"])

    def test_fails_when_no_review_yet(self):
        result = evaluate_gate({"type": "visual_similarity",
                                 "params": {"page_id": "page_nope", "min_similarity": 0.8}},
                                self.reg, self.workspace)
        self.assertFalse(result["passed"])
```

Run → expect ImportError (`user_gates.py` doesn't exist).

### TDD Step 2: implement `user_gates.py`

Create `agent/env_generator/llm_generator/multi_agent/runtime/user_gates.py`:

```python
"""User-defined deliverability gates (Cutover 39).

Each gate is a small typed rule the operator authored via the UI.
`evaluate_gate(gate, reg, workspace)` is the single entry point used by
`deliver_project_call` (live monitor server) to extend the deliverability
report with user-provided blockers.

Gate types are a fixed enum — no arbitrary code execution. To add a new
gate type, register an evaluator function below and add it to
`VALID_GATE_TYPES`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

VALID_GATE_TYPES = {"file_exists", "endpoint_exists", "mcp_tool_exists", "visual_similarity"}


def validate_gate(gate: dict) -> Optional[str]:
    """Return None if gate is valid, else an error message."""
    t = (gate or {}).get("type")
    if t not in VALID_GATE_TYPES:
        return "unknown gate type"
    if not (gate.get("name") or "").strip():
        return "name required"
    params = gate.get("params") or {}
    if t == "file_exists":
        if not (params.get("path") or "").strip():
            return "params.path required"
    elif t == "endpoint_exists":
        if not (params.get("method") or "").strip():
            return "params.method required"
        if not (params.get("path") or "").strip():
            return "params.path required"
    elif t == "mcp_tool_exists":
        if not (params.get("name") or "").strip():
            return "params.name required"
    elif t == "visual_similarity":
        if not (params.get("page_id") or "").strip():
            return "params.page_id required"
        if "min_similarity" not in params:
            return "params.min_similarity required"
        ms = params.get("min_similarity")
        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
            return "params.min_similarity must be a number"
        if ms < 0.0 or ms > 1.0:
            return "params.min_similarity must be between 0 and 1"
    return None


def _eval_file_exists(params: dict, reg, workspace: Path) -> dict:
    path_str = (params.get("path") or "").strip()
    # Defense: reject path traversal — keep within workspace
    if not path_str or ".." in Path(path_str).parts or Path(path_str).is_absolute():
        return {"passed": False, "message": f"invalid path: {path_str!r}"}
    target = Path(workspace) / path_str
    try:
        target_resolved = target.resolve()
        workspace_resolved = Path(workspace).resolve()
        target_resolved.relative_to(workspace_resolved)
    except Exception:
        return {"passed": False, "message": f"invalid path (escapes workspace): {path_str!r}"}
    if target.exists():
        return {"passed": True, "message": f"file exists: {path_str}"}
    return {"passed": False, "message": f"file not found: {path_str}"}


def _eval_endpoint_exists(params: dict, reg, workspace: Path) -> dict:
    method = (params.get("method") or "").strip().upper()
    path = (params.get("path") or "").strip()
    endpoints = reg.apihub.list_endpoints() or {}
    for ep_id, ep in endpoints.items():
        if (ep.get("method") or "").upper() == method and ep.get("path") == path:
            status = (ep.get("status") or "").lower()
            if status == "deprecated":
                return {"passed": False, "message": f"endpoint {method} {path} is deprecated"}
            return {"passed": True, "message": f"endpoint registered: {method} {path}"}
    return {"passed": False, "message": f"endpoint not registered: {method} {path}"}


def _eval_mcp_tool_exists(params: dict, reg, workspace: Path) -> dict:
    name = (params.get("name") or "").strip()
    # APIHub stores MCP tools under providers; look across all servers
    try:
        tools = reg.apihub.list_mcp_tools() if hasattr(reg.apihub, "list_mcp_tools") else {}
    except Exception:
        tools = {}
    for tool in (tools or {}).values():
        if tool.get("name") == name or tool.get("tool_name") == name:
            return {"passed": True, "message": f"mcp tool registered: {name}"}
    # Fallback: scan providers/servers snapshot
    try:
        snap = reg.apihub.snapshot() or {}
        providers = snap.get("providers") or {}
        for prov in providers.values():
            for tool in (prov.get("tools") or []) if isinstance(prov, dict) else []:
                if isinstance(tool, dict) and tool.get("name") == name:
                    return {"passed": True, "message": f"mcp tool registered: {name}"}
    except Exception:
        pass
    return {"passed": False, "message": f"mcp tool not registered: {name}"}


def _eval_visual_similarity(params: dict, reg, workspace: Path) -> dict:
    page_id = (params.get("page_id") or "").strip()
    min_sim = float(params.get("min_similarity") or 0.0)
    review = reg.workhub.get_visual_review(page_id) if hasattr(reg.workhub, "get_visual_review") else None
    if not review:
        return {"passed": False, "message": f"no visual review for page {page_id}"}
    metadata = review.get("metadata") or {}
    # similarity_score may live on the review object directly or in metadata
    score = metadata.get("similarity_score")
    if score is None:
        score = review.get("similarity_score")
    if score is None:
        # Look through the review history for the latest score
        history = review.get("history") or metadata.get("history") or []
        for entry in reversed(history):
            if isinstance(entry, dict) and entry.get("similarity_score") is not None:
                score = entry["similarity_score"]
                break
    if score is None:
        return {"passed": False, "message": f"visual review for {page_id} has no similarity_score"}
    if score >= min_sim:
        return {"passed": True, "message": f"similarity {score} >= {min_sim}"}
    return {"passed": False, "message": f"similarity {score} < {min_sim}"}


_EVALUATORS: Dict[str, Callable[[dict, Any, Path], dict]] = {
    "file_exists": _eval_file_exists,
    "endpoint_exists": _eval_endpoint_exists,
    "mcp_tool_exists": _eval_mcp_tool_exists,
    "visual_similarity": _eval_visual_similarity,
}


def evaluate_gate(gate: dict, reg, workspace: Path) -> dict:
    """Run a gate. Returns {passed, message, details?}."""
    t = (gate or {}).get("type")
    fn = _EVALUATORS.get(t)
    if fn is None:
        return {"passed": False, "message": f"unknown gate type: {t}"}
    params = gate.get("params") or {}
    try:
        return fn(params, reg, workspace)
    except Exception as e:
        return {"passed": False, "message": f"evaluator crashed: {e}"}
```

Run → expect 14 PASS in `test_user_gates.py` (4 validators + 3 file + 3 endpoint + 2 mcp + 3 visual = 15 give or take).

If `reg.apihub.list_endpoints()` or `register_mcp_server` signature doesn't match, adapt the evaluator to use what's actually there.

### Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/user_gates.py agent/tests/test_user_gates.py
git commit -m "Cutover 39: user_gates.py evaluator + 4 gate types"
```

---

## Task 3: Backend endpoints (CRUD + evaluate + deliverability integration)

**Files:**
- Modify: `live_monitor_server.py`
- Create: `agent/tests/test_user_gates_endpoints.py`

### TDD Step 1: failing endpoint tests

```python
# agent/tests/test_user_gates_endpoints.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestUserGatesEndpoints(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        self.project_id = create_project_call(self.root, {"name": "gates-test"})["id"]

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_list_gates_empty(self):
        from live_monitor_server import list_user_gates_call
        result = list_user_gates_call(self.root, self.project_id)
        self.assertEqual(result, {"gates": []})

    def test_create_gate_validates_and_persists(self):
        from live_monitor_server import create_user_gate_call, list_user_gates_call
        result = create_user_gate_call(self.root, self.project_id, {
            "name": "README present",
            "type": "file_exists",
            "params": {"path": "README.md"},
        })
        self.assertNotIn("error", result, result)
        self.assertIn("id", result)
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["name"], "README present")
        # Each gate in the list includes its current status
        self.assertIn("status", gates[0])
        self.assertEqual(gates[0]["status"]["passed"], False)

    def test_create_gate_rejects_invalid(self):
        from live_monitor_server import create_user_gate_call
        result = create_user_gate_call(self.root, self.project_id, {
            "type": "unknown_type", "name": "x", "params": {},
        })
        self.assertIn("error", result)

    def test_update_gate_changes_params(self):
        from live_monitor_server import create_user_gate_call, update_user_gate_call, list_user_gates_call
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "gate1", "type": "file_exists", "params": {"path": "a.txt"},
        })
        update_user_gate_call(self.root, self.project_id, created["id"], {
            "params": {"path": "b.txt"},
        })
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(gates[0]["params"]["path"], "b.txt")

    def test_delete_gate(self):
        from live_monitor_server import create_user_gate_call, delete_user_gate_call, list_user_gates_call
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "gate1", "type": "file_exists", "params": {"path": "x.txt"},
        })
        delete_user_gate_call(self.root, self.project_id, created["id"])
        self.assertEqual(list_user_gates_call(self.root, self.project_id)["gates"], [])

    def test_evaluate_specific_gate(self):
        from live_monitor_server import create_user_gate_call, evaluate_user_gate_call
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "g", "type": "file_exists", "params": {"path": "nope.txt"},
        })
        result = evaluate_user_gate_call(self.root, self.project_id, created["id"])
        self.assertFalse(result["passed"])
        self.assertIn("nope.txt", result["message"])

    def test_deliver_includes_user_gate_blockers(self):
        from live_monitor_server import create_user_gate_call, deliver_project_call
        create_user_gate_call(self.root, self.project_id, {
            "name": "needs README", "type": "file_exists", "params": {"path": "README.md"},
        })
        result = deliver_project_call(self.root, self.project_id, {})
        # Should be blocked because the gate fails
        self.assertFalse(result.get("delivered", False))
        blockers = result.get("report", {}).get("blockers", [])
        # User gate failure should appear with a user_gate: prefix
        self.assertTrue(any("user_gate:" in b or "needs README" in b for b in blockers),
                        f"Expected user gate blocker, got: {blockers}")

    def test_gates_persisted_across_resolve(self):
        from live_monitor_server import create_user_gate_call, list_user_gates_call, _HUB_REGISTRY_CACHE
        create_user_gate_call(self.root, self.project_id, {
            "name": "g", "type": "file_exists", "params": {"path": "x"},
        })
        # Clear caches to force reload from disk
        _HUB_REGISTRY_CACHE.clear()
        gates_file = self.root / self.project_id / ".user_gates.json"
        self.assertTrue(gates_file.exists())
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(len(gates), 1)
```

Run → expect failures.

### TDD Step 2: implement endpoints + deliverability integration

Add to `live_monitor_server.py` (near other `*_call` helpers):

```python
# ---------------------------------------------------------------------------
# Cutover 39: User-defined gates
# ---------------------------------------------------------------------------

def _user_gates_file(workspace: Path) -> Path:
    return Path(workspace) / ".user_gates.json"


def _load_user_gates(workspace: Path) -> list:
    p = _user_gates_file(workspace)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _save_user_gates(workspace: Path, gates: list) -> None:
    p = _user_gates_file(workspace)
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(gates, indent=2, default=str))
        os.replace(tmp, p)
    except Exception:
        try: tmp.unlink()
        except Exception: pass


def list_user_gates_call(workspaces_root: Path, project_id: str) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    from multi_agent.runtime.user_gates import evaluate_gate
    gates = _load_user_gates(workspace)
    out = []
    for g in gates:
        status = evaluate_gate(g, reg, workspace)
        out.append({**g, "status": status})
    return {"gates": out}


def create_user_gate_call(workspaces_root: Path, project_id: str, body: dict) -> dict:
    from multi_agent.runtime.user_gates import validate_gate
    err_msg = validate_gate(body or {})
    if err_msg:
        return {"error": err_msg}
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    now = time.time()
    new_gate = {
        "id": f"gate_{uuid.uuid4().hex[:10]}",
        "name": body.get("name", ""),
        "type": body.get("type"),
        "params": body.get("params") or {},
        "created_at": now,
        "_updated_at": now,
        "created_by": body.get("agent") or "ui_user",
    }
    gates.append(new_gate)
    _save_user_gates(workspace, gates)
    return new_gate


def update_user_gate_call(workspaces_root: Path, project_id: str, gate_id: str, body: dict) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    found = False
    for g in gates:
        if g.get("id") == gate_id:
            if "name" in body: g["name"] = body["name"]
            if "params" in body: g["params"] = body["params"] or {}
            g["_updated_at"] = time.time()
            from multi_agent.runtime.user_gates import validate_gate
            err = validate_gate(g)
            if err:
                return {"error": err}
            found = True
            break
    if not found:
        return {"error": f"gate not found: {gate_id}"}
    _save_user_gates(workspace, gates)
    return {"ok": True, "gate_id": gate_id}


def delete_user_gate_call(workspaces_root: Path, project_id: str, gate_id: str) -> dict:
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    new_gates = [g for g in gates if g.get("id") != gate_id]
    if len(new_gates) == len(gates):
        return {"error": f"gate not found: {gate_id}"}
    _save_user_gates(workspace, new_gates)
    return {"ok": True}


def evaluate_user_gate_call(workspaces_root: Path, project_id: str, gate_id: str) -> dict:
    reg, err = _resolve_hubs(workspaces_root, project_id)
    if err: return err
    workspace = _project_workspace(workspaces_root, project_id)
    if workspace is None:
        return {"error": f"project not found: {project_id}"}
    gates = _load_user_gates(workspace)
    target = next((g for g in gates if g.get("id") == gate_id), None)
    if not target:
        return {"error": f"gate not found: {gate_id}"}
    from multi_agent.runtime.user_gates import evaluate_gate
    return evaluate_gate(target, reg, workspace)
```

### Routes — add to `do_GET` / `do_POST` / `do_DELETE`

```python
# In do_GET, near other project routes:
m = re.match(r"^/api/projects/([^/]+)/user_gates$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    self._write_json(list_user_gates_call(self._workspaces_root, pid))
    return

# In do_POST:
m = re.match(r"^/api/projects/([^/]+)/user_gates$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    self._write_json(create_user_gate_call(self._workspaces_root, pid, body))
    return

m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)$", parsed.path)
if m and self.command == "POST":
    pid = urllib.parse.unquote(m.group(1))
    gid = urllib.parse.unquote(m.group(2))
    self._write_json(update_user_gate_call(self._workspaces_root, pid, gid, body))
    return

m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)/evaluate$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    gid = urllib.parse.unquote(m.group(2))
    self._write_json(evaluate_user_gate_call(self._workspaces_root, pid, gid))
    return

# In do_DELETE:
m = re.match(r"^/api/projects/([^/]+)/user_gates/([^/]+)$", parsed.path)
if m:
    pid = urllib.parse.unquote(m.group(1))
    gid = urllib.parse.unquote(m.group(2))
    self._write_json(delete_user_gate_call(self._workspaces_root, pid, gid))
    return
```

### Extend `deliver_project_call`

In `deliver_project_call`, after `report = compute_deliverability(reg, workspace, session_start_ts=0.0)`, add:

```python
# Cutover 39: append user-gate failures to the blockers list.
from multi_agent.runtime.user_gates import evaluate_gate
gates = _load_user_gates(workspace)
report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report)
user_gate_blockers = []
for g in gates:
    status = evaluate_gate(g, reg, workspace)
    if not status.get("passed"):
        user_gate_blockers.append(f"user_gate:{g.get('name', g.get('id'))}: {status.get('message', 'failed')}")
existing = list(report_dict.get("blockers", []) or [])
existing.extend(user_gate_blockers)
report_dict["blockers"] = existing
if user_gate_blockers and report_dict.get("verdict") == "ready":
    report_dict["verdict"] = "blocked"
```

Then use `report_dict` in subsequent return statements (the function already converts to dict).

Run tests → expect 8 PASS.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor_server.py agent/tests/test_user_gates_endpoints.py
git commit -m "Cutover 39: user-gates CRUD endpoints + deliverability integration"
```

---

## Task 4: Frontend — Gates panel in WorkHub

**Files:**
- Modify: `live_monitor/src/hub_panels.jsx`
- Modify: `live_monitor/styles/hubs.css`

### Step 1: Add `<UserGatesSection>` to WorkHubPanel

Read the existing `hub_panels.jsx`. Add a UserGatesSection inside WorkHubPanel (above or below the existing pages list).

```jsx
function UserGatesSection({ projectId, workhub }) {
  const { useEffect, useState } = React;
  const [gates, setGates] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("file_exists");
  const [params, setParams] = useState({});

  async function refresh() {
    if (!projectId) return;
    const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`,
                          { credentials: "include" });
    const data = await r.json();
    setGates(data.gates || []);
  }
  useEffect(() => { refresh(); }, [projectId]);

  async function createGate() {
    if (!name.trim()) return;
    const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ name, type, params }),
    });
    const data = await r.json();
    if (data.error) { window.alert(data.error); return; }
    setShowAdd(false); setName(""); setParams({});
    refresh();
  }

  async function deleteGate(gid) {
    if (!window.confirm("Delete this gate?")) return;
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates/${encodeURIComponent(gid)}`,
                { method: "DELETE", credentials: "include" });
    refresh();
  }

  function renderParamsForm() {
    if (type === "file_exists") {
      return <input placeholder="path (e.g. README.md)" value={params.path || ""} onChange={e => setParams({path: e.target.value})} />;
    }
    if (type === "endpoint_exists") {
      return (
        <>
          <select value={params.method || "GET"} onChange={e => setParams({...params, method: e.target.value})}>
            {["GET","POST","PUT","PATCH","DELETE"].map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <input placeholder="/api/path" value={params.path || ""} onChange={e => setParams({...params, path: e.target.value})} />
        </>
      );
    }
    if (type === "mcp_tool_exists") {
      return <input placeholder="tool name" value={params.name || ""} onChange={e => setParams({name: e.target.value})} />;
    }
    if (type === "visual_similarity") {
      return (
        <>
          <input placeholder="page_id" value={params.page_id || ""} onChange={e => setParams({...params, page_id: e.target.value})} />
          <input type="number" min="0" max="1" step="0.05" placeholder="min similarity (0-1)"
                 value={params.min_similarity ?? ""} onChange={e => setParams({...params, min_similarity: parseFloat(e.target.value)})} />
        </>
      );
    }
    return null;
  }

  return (
    <div className="user-gates-section">
      <div className="user-gates-header">
        <strong>User Gates</strong>
        <button onClick={() => setShowAdd(!showAdd)} className="add-gate-btn">
          {showAdd ? "Cancel" : "+ Add Gate"}
        </button>
      </div>
      {showAdd && (
        <div className="add-gate-form">
          <input placeholder="Gate name" value={name} onChange={e => setName(e.target.value)} />
          <select value={type} onChange={e => { setType(e.target.value); setParams({}); }}>
            <option value="file_exists">file_exists</option>
            <option value="endpoint_exists">endpoint_exists</option>
            <option value="mcp_tool_exists">mcp_tool_exists</option>
            <option value="visual_similarity">visual_similarity</option>
          </select>
          {renderParamsForm()}
          <button onClick={createGate} className="create-gate-btn">Create</button>
        </div>
      )}
      {gates.length === 0 && <div className="empty-gates">(no user gates defined)</div>}
      {gates.map(g => (
        <div key={g.id} className={"user-gate " + (g.status?.passed ? "passed" : "failed")}>
          <div className="user-gate-row">
            <span className={"gate-pill " + (g.status?.passed ? "pass" : "fail")}>
              {g.status?.passed ? "PASS" : "FAIL"}
            </span>
            <strong>{g.name}</strong>
            <code className="gate-type">{g.type}</code>
            <button className="delete-gate-btn" onClick={() => deleteGate(g.id)}>×</button>
          </div>
          <div className="user-gate-detail">
            <code>{JSON.stringify(g.params)}</code>
            <div className="user-gate-msg">{g.status?.message || ""}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
```

In `WorkHubPanel`, mount it: `<UserGatesSection projectId={projectId} workhub={workhub} />` (likely near the top).

### Step 2: CSS

Append to `hubs.css`:

```css
.user-gates-section { background: #14202c; border: 1px solid #2d3a4d; border-radius: 6px; padding: 10px; margin-bottom: 12px; }
.user-gates-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.add-gate-btn { background: #4070d0; color: #fff; border: none; border-radius: 3px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.add-gate-form { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px; background: #1a2538; border-radius: 4px; margin-bottom: 8px; }
.add-gate-form input, .add-gate-form select { background: #0e1626; color: #ddd; border: 1px solid #354054; border-radius: 3px; padding: 4px 8px; font-size: 12px; }
.create-gate-btn { background: #2e8c4a; color: #fff; border: none; border-radius: 3px; padding: 4px 12px; font-size: 11px; cursor: pointer; }
.empty-gates { color: #889; padding: 8px; font-style: italic; font-size: 12px; }
.user-gate { background: #1a2538; border-left: 3px solid; border-radius: 3px; padding: 6px 8px; margin-bottom: 4px; }
.user-gate.passed { border-left-color: #2e8c4a; }
.user-gate.failed { border-left-color: #b04040; }
.user-gate-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.gate-pill { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.gate-pill.pass { background: #1a3a1a; color: #8e8; }
.gate-pill.fail { background: #3a1a1a; color: #faa; }
.gate-type { color: #889; font-family: monospace; font-size: 10px; }
.delete-gate-btn { margin-left: auto; background: transparent; color: #faa; border: none; cursor: pointer; font-size: 14px; }
.user-gate-detail { display: flex; flex-direction: column; margin-top: 4px; padding-left: 20px; font-size: 11px; }
.user-gate-detail code { color: #889; font-family: monospace; }
.user-gate-msg { color: #cdd; margin-top: 2px; }
```

### Manual smoke

```bash
mkdir -p /tmp/c39_ws
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/c39_ws --port 4402 &
SERVER_PID=$!
sleep 1
PID=$(curl -sS -X POST http://127.0.0.1:4402/api/projects -H "Content-Type: application/json" -d '{"name":"gates-demo"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
# Create a gate
curl -sS -X POST http://127.0.0.1:4402/api/projects/$PID/user_gates -H "Content-Type: application/json" -d '{"name":"needs README","type":"file_exists","params":{"path":"README.md"}}'
echo
# List should show one gate failing
curl -sS http://127.0.0.1:4402/api/projects/$PID/user_gates | python -m json.tool
# Deliver should be blocked
curl -sS -X POST http://127.0.0.1:4402/api/projects/$PID/deliver -H "Content-Type: application/json" -d '{}' | python -m json.tool | head -10
kill $SERVER_PID 2>/dev/null
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/hub_panels.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/hubs.css
git commit -m "Cutover 39: UserGatesSection frontend (CRUD + status pills)"
```

---

## Task 5: Migration log + push + ff-merge

### Step 1: full sweep

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_user_gates.py agent/tests/test_user_gates_endpoints.py -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_control.py agent/tests/test_live_monitor_endpoints.py agent/tests/test_run_log_stream.py agent/tests/test_run_reconnect.py agent/tests/test_auth.py -q 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

### Step 2: migration log

Overwrite `docs/superpowers/migration-logs/39-user-gates.md`:

```markdown
# Cutover 39: User-Defined Gates

**Branch:** `haibotong-cutover-39-user-gates`
**Date:** 2026-05-26

## What

Users author custom deliverability gates from the UI. Each gate is one
of four typed rules; if any user gate fails, `deliver_project_call`
marks the project blocked and surfaces the failure in the blockers list
prefixed with `user_gate:<name>`. Force-deliver still works and remains
audited.

## Gate types

- `file_exists` — `{path}` (relative to workspace; path-traversal rejected)
- `endpoint_exists` — `{method, path}` (matches APIHub, ignores deprecated)
- `mcp_tool_exists` — `{name}` (matches APIHub MCP registry)
- `visual_similarity` — `{page_id, min_similarity}` (reads latest visual review's similarity_score)

## Commits

- (SHA) Cutover 39: record pre-flight baseline
- (SHA) Cutover 39: user_gates.py evaluator + 4 gate types
- (SHA) Cutover 39: user-gates CRUD endpoints + deliverability integration
- (SHA) Cutover 39: UserGatesSection frontend (CRUD + status pills)
- (this) Cutover 39: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1126 → ~1144 (+18 new tests: 15 evaluator + 8 endpoints, minus overlap)

## New surfaces

### Backend
- `multi_agent/runtime/user_gates.py` — `validate_gate`, `evaluate_gate`, `VALID_GATE_TYPES`
- `_load_user_gates(workspace)` / `_save_user_gates(workspace, gates)` — atomic JSON at `<workspace>/.user_gates.json`
- `list_user_gates_call`, `create_user_gate_call`, `update_user_gate_call`, `delete_user_gate_call`, `evaluate_user_gate_call`
- `GET /api/projects/<id>/user_gates` — list with current status
- `POST /api/projects/<id>/user_gates` — create
- `POST /api/projects/<id>/user_gates/<gate_id>` — update (POST-as-PATCH per repo convention)
- `POST /api/projects/<id>/user_gates/<gate_id>/evaluate` — re-evaluate
- `DELETE /api/projects/<id>/user_gates/<gate_id>` — remove
- `deliver_project_call` now merges user-gate failures into `report.blockers` and flips verdict to `blocked`

### Frontend
- `<UserGatesSection>` inside `WorkHubPanel` — list with PASS/FAIL pills + Add form + dynamic params editor + delete

## Architecture notes

- No arbitrary code execution: gate types are a fixed enum. Adding new
  types requires editing `user_gates.py`.
- Path-traversal defense on `file_exists`: rejects `..` segments + absolute paths + paths that resolve outside workspace.
- Status is computed live on every list-gates call (cheap; reads JSON
  stores + filesystem). Future cutover may cache.
- User-gate failures combine with the existing compute_deliverability
  report; the verdict flips to `blocked` if any user gate fails AND
  the underlying report was `ready`.

## Known limits

- No gate ordering/priority — gates are evaluated in creation order; all are equal-weight blockers.
- No history/audit of gate result changes (whether a gate went from PASS to FAIL).
- No JSON-schema validation on gate `params` beyond the per-type checks.
- The `visual_similarity` gate reads `metadata.similarity_score` on the visual review; if the WorkHub schema changes, the evaluator may need an update.
- Future cutover may add a fifth gate type: `test_passes` (read RunHub for a tagged run).
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/39-user-gates.md docs/superpowers/plans/2026-05-26-cutover-39-user-gates.md
git commit -m "Cutover 39: migration log"
git push -u red-env-gen haibotong-cutover-39-user-gates
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-39-user-gates
git merge --ff-only haibotong-cutover-39-user-gates
git push red-env-gen haibotong-0521-pipeline-web-tools
```
