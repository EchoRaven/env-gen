# APIHub Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all API-contract coordination from the monolithic `CRDTWorkspace` into the standalone `APIHub`, delete the legacy code, and validate the cutover with regressions + a real end-to-end run. This is **cutover #1 of 4**, establishing the SOP for the remaining hubs (EventHub bridge, WorkHub, CodeHub).

**Architecture:** The hubs already exist and are dual-written. This plan strengthens `APIHub` to be authoritative, builds out the missing 8 LLM-facing tools, switches all readers and writers to APIHub-only, then deletes ~290 lines of obsolete endpoint code from `crdt.py` plus 6 stale tool classes. Cross-hub: on breaking change, APIHub now auto-creates a fix `Task` in WorkHub.

**Tech Stack:** Python 3.9+, `unittest`, CRDT JSON stores on disk, in-process `MessageBus` (`agent/utils/communication.py`), existing `tools/hub_tools.py` wrapper pattern.

**Source spec:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` (sections 5, 9, 10.5).

---

## Pre-Reading (orient yourself)

- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — the target hub (172 lines)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py:305-596` — the legacy endpoint methods to be removed
- `agent/env_generator/llm_generator/tools/hub_tools.py` — existing thin-wrapper tool layer (185 lines), extend in place
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — WorkHub.create_task for cross-hub breaking-change flow
- `agent/tests/test_hub_architecture.py` — golden e2e test we want to keep green
- `agent/tests/run_regressions.py` — regression entry point

## File Map

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — add methods, enhance breaking-change
- `agent/env_generator/llm_generator/tools/hub_tools.py` — add 8 APIHub tool classes
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py:_bundle_apihub_tools` — widen `include_names`
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py:711` — read endpoints from `hubs.apihub`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py:80` — single-write to APIHub
- `agent/env_generator/llm_generator/tools/crdt_tools.py` — delete 6 endpoint/consumer tool classes
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py` — delete absorbed methods (Phase 5)
- `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` — drop deleted exports if any
- `agent/tests/run_regressions.py` — register the hub architecture test

**Create:**
- `agent/tests/test_apihub_strengthen.py` — TDD for new APIHub methods
- `agent/tests/test_apihub_tools.py` — TDD for new tool classes
- `agent/tests/test_apihub_parity.py` — temporary parity tests, deleted in Phase 5
- `agent/tests/test_apihub_breaking_change_creates_task.py` — cross-hub integration test
- `docs/superpowers/migration-logs/01-apihub.md` — cutover report

---

## Phase 0 — Pre-flight

### Task 1: Branch, stash, and verify baseline regressions

**Files:** None modified.

- [ ] **Step 1: Confirm clean working tree (or stash uncommitted changes)**

Run:
```bash
cd /data/common/haibotong/env-gen
git status --short
```

Expected: only `??` lines for untracked unrelated artifacts. If `M` lines exist, stash them:
```bash
git stash push -m "pre-apihub-cutover stash"
```

- [ ] **Step 2: Create the cutover branch from the current branch tip**

Run:
```bash
git checkout -b haibotong-hub-cutover-1-apihub
```

Expected output: `Switched to a new branch 'haibotong-hub-cutover-1-apihub'`.

- [ ] **Step 3: Run baseline regressions**

Run:
```bash
cd /data/common/haibotong/env-gen
python3 agent/tests/run_regressions.py
```

Expected: `OK` at the bottom. Record the test count for later comparison. If any test fails on the baseline, **stop and fix the baseline first** — do not start the cutover with a broken baseline.

- [ ] **Step 4: Run the hub architecture test (not yet in regressions)**

Run:
```bash
cd /data/common/haibotong/env-gen
python3 -m unittest agent.tests.test_hub_architecture -v
```

Expected: 2 tests, all `ok`.

- [ ] **Step 5: Commit the branch creation marker (empty commit)**

Skip — `git checkout -b` already moved HEAD. No commit needed yet.

---

## Phase 1 — Strengthen APIHub (TDD)

### Task 2: Register hub_architecture in regressions

**Files:**
- Modify: `agent/tests/run_regressions.py`

- [ ] **Step 1: Read the current regression suite**

Open `agent/tests/run_regressions.py`. Confirm it currently registers only `TaskSuiteRegressionTests` and `DataEngineRegressionTests`.

- [ ] **Step 2: Modify `build_suite()` to also load `HubArchitectureTests`**

Apply this edit:

```python
def build_suite() -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader

    from test_task_suite_regressions import TaskSuiteRegressionTests
    from test_data_engine_regressions import DataEngineRegressionTests
    from test_hub_architecture import HubArchitectureTests

    suite.addTests(loader.loadTestsFromTestCase(TaskSuiteRegressionTests))
    suite.addTests(loader.loadTestsFromTestCase(DataEngineRegressionTests))
    suite.addTests(loader.loadTestsFromTestCase(HubArchitectureTests))
    return suite
```

- [ ] **Step 3: Run regressions to confirm the hub test is included**

Run:
```bash
python3 agent/tests/run_regressions.py 2>&1 | tail -5
```

Expected output contains a line like `Ran 12 tests in ...s` (2 more than baseline) and ends with `OK`.

- [ ] **Step 4: Commit**

```bash
git add agent/tests/run_regressions.py
git commit -m "Register hub_architecture tests in regression suite"
```

### Task 3: TDD — `APIHub.update_schema`

**Files:**
- Create: `agent/tests/test_apihub_strengthen.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_apihub_strengthen.py` with:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402


class APIHubStrengthenTests(unittest.TestCase):
    def _hub(self, td):
        return CRDTWorkspace(Path(td)).hubs.apihub

    def test_update_schema_merges_request_and_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "POST", "/api/posts",
                schema={"request": {"title": "string"}, "response": {"id": "int"}},
                provider="backend", agent="design",
            )
            updated = hub.update_schema(
                "POST /api/posts",
                response={"id": "int", "created_at": "string"},
                agent="backend",
            )
            self.assertEqual(updated["schema"]["request"], {"title": "string"})
            self.assertEqual(updated["schema"]["response"], {"id": "int", "created_at": "string"})

    def test_update_schema_returns_error_for_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.update_schema("GET /api/nope", request={"q": "string"}, agent="backend")
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails (or passes if `update_schema` already exists)**

Run:
```bash
cd /data/common/haibotong/env-gen
python3 -m unittest agent.tests.test_apihub_strengthen.APIHubStrengthenTests.test_update_schema_merges_request_and_response -v
```

Expected: PASS — `update_schema` already exists in `apihub.py:71`. If it FAILS, fix `apihub.py` to match the spec semantics (merge into existing schema, not overwrite). Move on either way.

- [ ] **Step 3: Run the error-path test**

Run:
```bash
python3 -m unittest agent.tests.test_apihub_strengthen.APIHubStrengthenTests.test_update_schema_returns_error_for_unknown_endpoint -v
```

Expected: PASS.

- [ ] **Step 4: Commit if no implementation changes needed**

```bash
git add agent/tests/test_apihub_strengthen.py
git commit -m "Test APIHub.update_schema request/response merge + error path"
```

### Task 4: TDD — `APIHub.add_mock` and `APIHub.add_example`

**Files:**
- Modify: `agent/tests/test_apihub_strengthen.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Add failing tests to `test_apihub_strengthen.py`**

Append these two methods to `APIHubStrengthenTests`:

```python
    def test_add_mock_stores_mock_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="design")
            mock = hub.add_mock(
                "GET /api/feed",
                {"posts": [{"id": 1, "title": "hello"}], "total": 1},
                agent="design",
            )
            self.assertEqual(mock["endpoint_id"], "GET /api/feed")
            stored = hub.snapshot()["mocks"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(list(stored.values())[0]["response"]["total"], 1)

    def test_add_example_stores_request_and_response_pair(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("POST", "/api/posts", schema={}, provider="backend", agent="design")
            example = hub.add_example(
                "POST /api/posts",
                request_example={"title": "hello"},
                response_example={"id": 42, "title": "hello"},
                agent="backend",
            )
            self.assertEqual(example["request"], {"title": "hello"})
            self.assertEqual(example["response"], {"id": 42, "title": "hello"})
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
python3 -m unittest agent.tests.test_apihub_strengthen.APIHubStrengthenTests -v
```

Expected: `test_add_mock_stores_mock_response` and `test_add_example_stores_request_and_response_pair` FAIL with `AttributeError: 'APIHub' object has no attribute 'add_mock'` / `add_example`.

- [ ] **Step 3: Implement `add_mock` and `add_example` in `apihub.py`**

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`, add these methods to the `APIHub` class (place them right after `record_api_test` for adjacency to other writes):

```python
    def add_mock(self, endpoint_id: str, mock_response: dict, agent: str = "") -> dict:
        if endpoint_id not in self._endpoints.value():
            return {"error": f"Endpoint not found: {endpoint_id}"}
        ts = Timestamp.now(agent or "apihub")
        mock_id = f"mock:{endpoint_id}:{ts.wall_time}:{ts.logical}"
        mock = {
            "id": mock_id,
            "endpoint_id": endpoint_id,
            "response": mock_response or {},
            "created_by": agent,
            "created_at": ts.wall_time,
        }
        self._mocks.update(lambda m: m.set(mock_id, mock, ts))
        self._emit("mock_added", mock, recipients=[])
        return mock

    def add_example(self, endpoint_id: str, request_example: dict = None,
                    response_example: dict = None, agent: str = "") -> dict:
        if endpoint_id not in self._endpoints.value():
            return {"error": f"Endpoint not found: {endpoint_id}"}
        ts = Timestamp.now(agent or "apihub")
        example_id = f"example:{endpoint_id}:{ts.wall_time}:{ts.logical}"
        example = {
            "id": example_id,
            "endpoint_id": endpoint_id,
            "request": request_example or {},
            "response": response_example or {},
            "created_by": agent,
            "created_at": ts.wall_time,
        }
        self._examples.update(lambda m: m.set(example_id, example, ts))
        self._emit("example_added", example, recipients=[])
        return example
```

- [ ] **Step 4: Run tests to confirm pass**

Run:
```bash
python3 -m unittest agent.tests.test_apihub_strengthen -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_apihub_strengthen.py agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "Add APIHub.add_mock and APIHub.add_example with TDD"
```

### Task 5: TDD — `APIHub.deprecate_endpoint`

**Files:**
- Modify: `agent/tests/test_apihub_strengthen.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Write failing test**

Append to `APIHubStrengthenTests`:

```python
    def test_deprecate_endpoint_marks_status_and_records_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/posts/v1", schema={}, provider="backend", agent="design")
            hub.register_endpoint("GET", "/api/posts/v2", schema={}, provider="backend", agent="design")
            result = hub.deprecate_endpoint(
                "GET /api/posts/v1",
                replacement_id="GET /api/posts/v2",
                agent="design",
            )
            self.assertEqual(result["status"], "deprecated")
            self.assertEqual(result["replacement_id"], "GET /api/posts/v2")
            # status persisted in main endpoints store
            current = hub.get_endpoints()["GET /api/posts/v1"]
            self.assertEqual(current["status"], "deprecated")
            self.assertEqual(current.get("replacement_id"), "GET /api/posts/v2")
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
python3 -m unittest agent.tests.test_apihub_strengthen.APIHubStrengthenTests.test_deprecate_endpoint_marks_status_and_records_replacement -v
```

Expected: FAIL with `AttributeError: 'APIHub' object has no attribute 'deprecate_endpoint'`.

- [ ] **Step 3: Implement `deprecate_endpoint`**

Add to `apihub.py` (after `add_example`):

```python
    def deprecate_endpoint(self, endpoint_id: str, replacement_id: str = None,
                           agent: str = "") -> dict:
        endpoint = self._endpoints.get().get(endpoint_id)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}
        ts = Timestamp.now(agent or "apihub")
        updated = dict(endpoint)
        updated["status"] = "deprecated"
        if replacement_id:
            updated["replacement_id"] = replacement_id
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self._endpoints.update(lambda m: m.set(endpoint_id, updated, ts))
        consumers = [c.get("agent") for c in self._consumers.value().values()
                     if c.get("endpoint_id") == endpoint_id]
        self._emit(
            "endpoint_deprecated",
            {"endpoint_id": endpoint_id, "replacement_id": replacement_id, "deprecated_by": agent},
            recipients=sorted(set(consumers)),
            priority="high",
        )
        return updated
```

- [ ] **Step 4: Run to confirm pass**

```bash
python3 -m unittest agent.tests.test_apihub_strengthen -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_apihub_strengthen.py agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "Add APIHub.deprecate_endpoint with replacement_id and EventHub notification"
```

### Task 6: TDD — Enhanced `_detect_breaking_change`

**Files:**
- Modify: `agent/tests/test_apihub_strengthen.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Write failing tests for the 5 additional breaking-change cases**

Append to `APIHubStrengthenTests`:

```python
    def test_breaking_change_detects_type_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response": {"id": "int", "name": "string"}}
            new = {"response": {"id": "string", "name": "string"}}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("id", result.get("type_changed_fields", []))

    def test_breaking_change_detects_required_added_in_request(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"request": {"title": "string"}}
            new = {"request": {"title": "string", "author_id": "int (required)"}}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("author_id", result.get("required_added_in_request", []))

    def test_breaking_change_detects_path_method_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"method": "GET", "path": "/api/feed"}
            new = {"method": "POST", "path": "/api/feed"}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("method_changed"))

    def test_breaking_change_detects_response_key_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response_key": "posts"}
            new = {"response_key": "items"}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("response_key_changed"))

    def test_breaking_change_detects_auth_added(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"auth_required": False}
            new = {"auth_required": True}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("auth_added"))

    def test_breaking_change_returns_not_breaking_for_additive_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response": {"id": "int"}}
            new = {"response": {"id": "int", "created_at": "string"}}
            result = hub.detect_breaking_change(old, new)
            self.assertFalse(result["is_breaking"])
```

- [ ] **Step 2: Run to confirm failures**

Run:
```bash
python3 -m unittest agent.tests.test_apihub_strengthen -v 2>&1 | tail -25
```

Expected: the 5 new tests FAIL because the current `detect_breaking_change` only checks `removed_response_fields`. The 6th (`returns_not_breaking_for_additive_response`) should pass.

- [ ] **Step 3: Rewrite `detect_breaking_change` to cover all six cases**

Replace the current `detect_breaking_change` body in `apihub.py:108` with:

```python
    def detect_breaking_change(self, old_schema: dict, new_schema: dict) -> dict:
        old_schema = old_schema or {}
        new_schema = new_schema or {}
        old_response = old_schema.get("response") or {}
        new_response = new_schema.get("response") or {}
        old_request = old_schema.get("request") or {}
        new_request = new_schema.get("request") or {}

        removed_response_fields: list = []
        type_changed_fields: list = []
        if isinstance(old_response, dict) and isinstance(new_response, dict):
            removed_response_fields = sorted(set(old_response.keys()) - set(new_response.keys()))
            for key in old_response.keys() & new_response.keys():
                if old_response[key] != new_response[key]:
                    type_changed_fields.append(key)

        required_added_in_request: list = []
        if isinstance(old_request, dict) and isinstance(new_request, dict):
            for key in set(new_request.keys()) - set(old_request.keys()):
                value = new_request[key]
                if isinstance(value, str) and "required" in value.lower():
                    required_added_in_request.append(key)

        method_changed = bool(
            old_schema.get("method") and new_schema.get("method")
            and old_schema["method"] != new_schema["method"]
        )
        path_changed = bool(
            old_schema.get("path") and new_schema.get("path")
            and old_schema["path"] != new_schema["path"]
        )
        response_key_changed = bool(
            old_schema.get("response_key") != new_schema.get("response_key")
            and (old_schema.get("response_key") is not None or new_schema.get("response_key") is not None)
        )
        auth_added = bool(new_schema.get("auth_required") and not old_schema.get("auth_required"))

        is_breaking = any([
            removed_response_fields, type_changed_fields,
            required_added_in_request, method_changed, path_changed,
            response_key_changed, auth_added,
        ])

        return {
            "is_breaking": is_breaking,
            "removed_response_fields": removed_response_fields,
            "type_changed_fields": sorted(type_changed_fields),
            "required_added_in_request": sorted(required_added_in_request),
            "method_changed": method_changed,
            "path_changed": path_changed,
            "response_key_changed": response_key_changed,
            "auth_added": auth_added,
        }
```

Note: `register_endpoint` (line 47) currently passes `endpoint["schema"]` to `detect_breaking_change`. After this change the function accepts the same shape; no caller change needed. But we want to also detect path/method/response_key/auth_required diffs — those live on the top-level endpoint, not under `schema`. Update `register_endpoint` to merge top-level keys into the dict passed to `detect_breaking_change`:

Find this block in `register_endpoint`:
```python
        breaking = self.detect_breaking_change((old or {}).get("schema") or {}, endpoint["schema"])
```

Replace with:
```python
        old_full = {
            **((old or {}).get("schema") or {}),
            "method": (old or {}).get("method"),
            "path": (old or {}).get("path"),
            "response_key": ((old or {}).get("metadata") or {}).get("response_key"),
            "auth_required": ((old or {}).get("metadata") or {}).get("auth_required"),
        }
        new_full = {
            **endpoint["schema"],
            "method": endpoint.get("method"),
            "path": endpoint.get("path"),
            "response_key": (endpoint.get("metadata") or {}).get("response_key"),
            "auth_required": (endpoint.get("metadata") or {}).get("auth_required"),
        }
        breaking = self.detect_breaking_change(old_full, new_full)
```

- [ ] **Step 4: Run all APIHub strengthen tests**

```bash
python3 -m unittest agent.tests.test_apihub_strengthen -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Run hub architecture + regressions to confirm no regression**

```bash
python3 -m unittest agent.tests.test_hub_architecture -v
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: both pass with `OK`.

- [ ] **Step 6: Commit**

```bash
git add agent/tests/test_apihub_strengthen.py agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "Expand APIHub.detect_breaking_change to cover 7 breaking conditions"
```

### Task 7: TDD — Breaking change auto-creates WorkHub fix task

**Files:**
- Create: `agent/tests/test_apihub_breaking_change_creates_task.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Write failing cross-hub integration test**

Create `agent/tests/test_apihub_breaking_change_creates_task.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402


class BreakingChangeCreatesTaskTests(unittest.TestCase):
    def test_breaking_change_auto_creates_workhub_task_per_consumer(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            hubs = ws.hubs

            # design publishes the endpoint, frontend registers as consumer
            hubs.apihub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="design",
            )
            hubs.apihub.register_consumer(
                "GET /api/feed", "app/frontend/src/services/api.js", "frontend",
            )

            # backend pushes a breaking schema change
            hubs.apihub.update_schema(
                "GET /api/feed",
                response={"items": []},   # removes `posts` and `total`
                agent="backend",
            )

            # there must be at least one WorkHub task whose assignee is the affected consumer
            tasks = list(hubs.workhub.snapshot()["tasks"].values())
            fix_tasks = [
                t for t in tasks
                if t.get("assignee") == "frontend"
                and t.get("metadata", {}).get("source") == "apihub_breaking_change"
                and "GET /api/feed" in (t.get("metadata", {}).get("linked_apis") or [])
            ]
            self.assertEqual(len(fix_tasks), 1, f"expected exactly one frontend fix task, got: {fix_tasks}")
            task = fix_tasks[0]
            self.assertIn("/api/feed", task["title"])
            self.assertEqual(task["status"], "pending")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m unittest agent.tests.test_apihub_breaking_change_creates_task -v
```

Expected: FAIL (no WorkHub fix task created — current `_record_breaking_change` only fires an EventHub event).

- [ ] **Step 3: Wire APIHub → WorkHub task creation**

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`, find `_record_breaking_change` (around line 116). Replace it with:

```python
    def _record_breaking_change(self, endpoint_id: str, breaking: dict, agent: str = "") -> dict:
        ts = Timestamp.now(agent or "apihub")
        key = f"breaking:{endpoint_id}:{ts.wall_time}"
        payload = {"id": key, "endpoint_id": endpoint_id, "breaking": breaking,
                   "created_at": ts.wall_time, "_updated_by": agent}
        self._breaking_changes.update(lambda m: m.set(key, payload, ts))
        consumers = [c for c in self._consumers.value().values()
                     if c.get("endpoint_id") == endpoint_id]
        recipient_agents = sorted(set(c.get("agent") for c in consumers if c.get("agent")))

        self._emit("breaking_change_detected", payload,
                   recipients=recipient_agents, priority="urgent")

        # Auto-create a fix task in WorkHub per affected consumer agent
        workhub = getattr(self, "_workhub", None)
        if workhub is not None:
            for consumer_agent in recipient_agents:
                consumer_files = [
                    c.get("file_path") for c in consumers
                    if c.get("agent") == consumer_agent
                ]
                try:
                    workhub.create_task(
                        title=f"Fix breaking change in {endpoint_id}",
                        description=(
                            f"APIHub detected a breaking change in {endpoint_id}: "
                            f"{breaking}. Consumer files: {consumer_files}"
                        ),
                        assignee=consumer_agent,
                        agent=agent or "apihub",
                        source="apihub_breaking_change",
                        linked_apis=[endpoint_id],
                        affected_files=consumer_files,
                        priority="urgent",
                    )
                except Exception:
                    # Hub linkage missing in test setup is non-fatal; the event still went out.
                    pass
        return payload
```

The new code reads from `self._workhub` — we need to set that. Find `__init__` (line 16) and replace its signature and body:

```python
    def __init__(self, crdt_dir: Path, eventhub: "EventHub | None" = None,
                 workhub: "WorkHub | None" = None):
        self.crdt_dir = Path(crdt_dir)
        self.eventhub = eventhub
        self._workhub = workhub
        self._projects = CRDTStore(self.crdt_dir / "apihub_projects.json", LWWMap)
        self._endpoints = CRDTStore(self.crdt_dir / "apihub_endpoints.json", LWWMap)
        self._schemas = CRDTStore(self.crdt_dir / "apihub_schemas.json", LWWMap)
        self._examples = CRDTStore(self.crdt_dir / "apihub_examples.json", LWWMap)
        self._mocks = CRDTStore(self.crdt_dir / "apihub_mocks.json", LWWMap)
        self._contract_tests = CRDTStore(self.crdt_dir / "apihub_contract_tests.json", LWWMap)
        self._providers = CRDTStore(self.crdt_dir / "apihub_providers.json", LWWMap)
        self._consumers = CRDTStore(self.crdt_dir / "apihub_consumers.json", LWWMap)
        self._api_reviews = CRDTStore(self.crdt_dir / "apihub_reviews.json", LWWMap)
        self._breaking_changes = CRDTStore(self.crdt_dir / "apihub_breaking_changes.json", LWWMap)
        self.ensure_documents()
```

Add a setter (for late binding from `HubWorkspace`):

```python
    def attach_workhub(self, workhub) -> None:
        self._workhub = workhub
```

- [ ] **Step 4: Wire `HubWorkspace` to inject WorkHub into APIHub**

Open `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py`. After the existing instantiations, add `self.apihub.attach_workhub(self.workhub)`:

```python
class HubWorkspace:
    """Aggregator for the four collaboration hubs."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.crdt_dir = self.base_dir / "shared" / "crdt"
        self.crdt_dir.mkdir(parents=True, exist_ok=True)
        self.eventhub = EventHub(self.crdt_dir)
        self.codehub = CodeHub(self.crdt_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub = APIHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub.attach_workhub(self.workhub)
```

- [ ] **Step 5: Run the cross-hub test**

```bash
python3 -m unittest agent.tests.test_apihub_breaking_change_creates_task -v
```

Expected: PASS.

- [ ] **Step 6: Run all hub-related tests + regressions**

```bash
python3 -m unittest agent.tests.test_apihub_strengthen agent.tests.test_hub_architecture agent.tests.test_apihub_breaking_change_creates_task -v
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all PASS, regressions OK.

- [ ] **Step 7: Commit**

```bash
git add agent/tests/test_apihub_breaking_change_creates_task.py \
        agent/env_generator/llm_generator/multi_agent/runtime/apihub.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py
git commit -m "Auto-create WorkHub fix task on APIHub breaking change"
```

---

## Phase 2 — Build the new tool layer

### Task 8: TDD — Add 8 missing APIHub tool classes to `tools/hub_tools.py`

**Files:**
- Create: `agent/tests/test_apihub_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1: Write failing tool-schema test**

Create `agent/tests/test_apihub_tools.py`:

```python
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_TOOLS = {
    "apihub_register_endpoint",
    "apihub_update_schema",
    "apihub_list_endpoints",
    "apihub_get_endpoint",
    "apihub_register_consumer",
    "apihub_get_dependencies_for_file",
    "apihub_get_breaking_changes",
    "apihub_record_contract_test",
    "apihub_deprecate_endpoint",
    "apihub_request_review",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class APIHubToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        ws = CRDTWorkspace(Path(td))
        tools = create_hub_tools(agent_id="backend", hub_workspace=ws.hubs)
        return ws.hubs, {tool.NAME: tool for tool in tools}

    def test_all_required_apihub_tools_are_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing tools: {missing}")

    def test_apihub_register_endpoint_tool_writes_through(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["apihub_register_endpoint"]
            result = _run(tool._run(method="GET", path="/api/feed",
                                    schema={"response": {"posts": []}}, provider="backend"))
            self.assertTrue(result.success if hasattr(result, "success") else True)
            self.assertIn("GET /api/feed", hubs.apihub.get_endpoints())

    def test_apihub_list_endpoints_tool_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="design")
            tool = tool_by_name["apihub_list_endpoints"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertIn("GET /api/feed", data.get("endpoints", data))

    def test_apihub_deprecate_endpoint_tool_marks_deprecated(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_endpoint("GET", "/api/old", schema={}, provider="backend", agent="design")
            tool = tool_by_name["apihub_deprecate_endpoint"]
            result = _run(tool._run(endpoint_id="GET /api/old", replacement_id="GET /api/new"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data.get("status"), "deprecated")

    def test_apihub_record_contract_test_tool_persists_result(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="design")
            tool = tool_by_name["apihub_record_contract_test"]
            _run(tool._run(
                endpoint_id="GET /api/feed",
                result={"passed": True, "duration_ms": 12},
                evidence={"trace": "200 OK"},
            ))
            tests = hubs.apihub.snapshot()["contract_tests"]
            self.assertEqual(len(tests), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m unittest agent.tests.test_apihub_tools -v 2>&1 | tail -25
```

Expected: `test_all_required_apihub_tools_are_exported` FAILS with `missing tools: {'apihub_update_schema', ...}` (8 missing).

- [ ] **Step 3: Add the 8 new tool classes to `tools/hub_tools.py`**

In `tools/hub_tools.py`, **after** the existing `APIHubConsumerTool` class (around line 138), add:

```python
class APIHubUpdateSchemaTool(HubTool):
    NAME = "apihub_update_schema"
    DESCRIPTION = "Update request/response schema of an existing APIHub endpoint."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string", "description": "Format: 'METHOD /path'"},
            "request": {"type": "object"},
            "response": {"type": "object"},
        },
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str, request: dict = None, response: dict = None) -> ToolResult:
        return ToolResult(data=self._hubs.apihub.update_schema(
            endpoint_id, request=request, response=response, agent=self._agent_id))


class APIHubListEndpointsTool(HubTool):
    NAME = "apihub_list_endpoints"
    DESCRIPTION = "List all APIHub endpoints, optionally filtered by status or provider."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "provider": {"type": "string"},
        },
    }

    async def _run(self, status: str = None, provider: str = None) -> ToolResult:
        endpoints = self._hubs.apihub.get_endpoints()
        if status:
            endpoints = {k: v for k, v in endpoints.items() if v.get("status") == status}
        if provider:
            endpoints = {k: v for k, v in endpoints.items() if v.get("provider") == provider}
        return ToolResult(data={"endpoints": endpoints})


class APIHubGetEndpointTool(HubTool):
    NAME = "apihub_get_endpoint"
    DESCRIPTION = "Get a single APIHub endpoint by its id (format 'METHOD /path')."
    PARAMETERS = {
        "type": "object",
        "properties": {"endpoint_id": {"type": "string"}},
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str) -> ToolResult:
        endpoint = self._hubs.apihub.get_endpoints().get(endpoint_id)
        if not endpoint:
            return ToolResult(success=False, error_message=f"Endpoint not found: {endpoint_id}")
        return ToolResult(data=endpoint)


class APIHubGetDependenciesForFileTool(HubTool):
    NAME = "apihub_get_dependencies_for_file"
    DESCRIPTION = "List API endpoints a specific source file depends on."
    PARAMETERS = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    }

    async def _run(self, file_path: str) -> ToolResult:
        deps = [c for c in self._hubs.apihub._consumers.value().values()
                if c.get("file_path") == file_path]
        return ToolResult(data={"dependencies": deps})


class APIHubGetBreakingChangesTool(HubTool):
    NAME = "apihub_get_breaking_changes"
    DESCRIPTION = "List recorded APIHub breaking changes (newest first)."
    PARAMETERS = {
        "type": "object",
        "properties": {"since_ts": {"type": "number"}},
    }

    async def _run(self, since_ts: float = None) -> ToolResult:
        items = list(self._hubs.apihub._breaking_changes.value().values())
        if since_ts is not None:
            items = [b for b in items if b.get("created_at", 0) >= since_ts]
        items.sort(key=lambda b: b.get("created_at", 0), reverse=True)
        return ToolResult(data={"breaking_changes": items})


class APIHubRecordContractTestTool(HubTool):
    NAME = "apihub_record_contract_test"
    DESCRIPTION = "Record a contract test result against an APIHub endpoint."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "result": {"type": "object"},
            "evidence": {"type": "object"},
        },
        "required": ["endpoint_id", "result"],
    }

    async def _run(self, endpoint_id: str, result: dict, evidence: dict = None) -> ToolResult:
        return ToolResult(data=self._hubs.apihub.record_api_test(
            endpoint_id, result, evidence=evidence or {}, agent=self._agent_id))


class APIHubDeprecateEndpointTool(HubTool):
    NAME = "apihub_deprecate_endpoint"
    DESCRIPTION = "Mark an APIHub endpoint as deprecated, optionally pointing to a replacement."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "replacement_id": {"type": "string"},
        },
        "required": ["endpoint_id"],
    }

    async def _run(self, endpoint_id: str, replacement_id: str = None) -> ToolResult:
        return ToolResult(data=self._hubs.apihub.deprecate_endpoint(
            endpoint_id, replacement_id=replacement_id, agent=self._agent_id))


class APIHubRequestReviewTool(HubTool):
    NAME = "apihub_request_review"
    DESCRIPTION = "Request review of an APIHub endpoint from named agents."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["endpoint_id", "reviewers"],
    }

    async def _run(self, endpoint_id: str, reviewers: list, reason: str = "") -> ToolResult:
        return ToolResult(data=self._hubs.apihub.request_api_review(
            endpoint_id, reviewers, agent=self._agent_id, reason=reason))
```

The current `APIHubEndpointTool` class registers endpoints under the name `apihub_endpoint`. Rename it to `apihub_register_endpoint` for naming consistency. Edit `tools/hub_tools.py`:

Find:
```python
class APIHubEndpointTool(HubTool):
    NAME = "apihub_endpoint"
```

Change to:
```python
class APIHubRegisterEndpointTool(HubTool):
    NAME = "apihub_register_endpoint"
```

Then update the `HUB_TOOL_CLASSES` list at the bottom — replace `APIHubEndpointTool` with `APIHubRegisterEndpointTool` and add the 8 new classes:

```python
HUB_TOOL_CLASSES = [
    CodeHubRegisterRepoTool,
    CodeHubRecordCommitTool,
    CodeHubOpenPRTool,
    CodeHubReviewPRTool,
    CodeHubMergePRTool,
    CodeHubCreateReleaseTool,
    WorkHubCreatePageTool,
    WorkHubTaskTool,
    APIHubRegisterEndpointTool,
    APIHubUpdateSchemaTool,
    APIHubListEndpointsTool,
    APIHubGetEndpointTool,
    APIHubConsumerTool,
    APIHubGetDependenciesForFileTool,
    APIHubGetBreakingChangesTool,
    APIHubRecordContractTestTool,
    APIHubDeprecateEndpointTool,
    APIHubRequestReviewTool,
    EventHubInboxTool,
    HubSnapshotTool,
]
```

- [ ] **Step 4: Run tool tests**

```bash
python3 -m unittest agent.tests.test_apihub_tools -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_apihub_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add 8 missing APIHub LLM tools + rename apihub_endpoint to apihub_register_endpoint"
```

### Task 9: Wire new APIHub tools into the bundle

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`

- [ ] **Step 1: Locate and update `_bundle_apihub_tools`**

In `tool_bundles.py` around line 254, replace the function body with:

```python
def _bundle_apihub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "apihub_register_endpoint",
            "apihub_update_schema",
            "apihub_list_endpoints",
            "apihub_get_endpoint",
            "apihub_register_consumer",
            "apihub_get_dependencies_for_file",
            "apihub_get_breaking_changes",
            "apihub_record_contract_test",
            "apihub_deprecate_endpoint",
            "apihub_request_review",
            "hub_snapshot",
        },
    )
    builder.add(tools, "apihub", "hub")
```

- [ ] **Step 2: Run hub tests and regressions to verify bundle still loads**

```bash
python3 -m unittest agent.tests.test_apihub_tools agent.tests.test_hub_architecture -v
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/tool_bundles.py
git commit -m "Widen apihub_tools bundle to expose all 10 APIHub tools"
```

---

## Phase 3 — Parity audit

### Task 10: TDD — Parity tests between legacy CRDTWorkspace and APIHub

**Files:**
- Create: `agent/tests/test_apihub_parity.py`

- [ ] **Step 1: Write parity tests**

Create `agent/tests/test_apihub_parity.py`:

```python
"""Temporary parity tests: deleted after Phase 5 of the APIHub cutover."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402


class APIHubParityTests(unittest.TestCase):
    def test_update_endpoint_propagates_to_apihub(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            ws.update_endpoint(
                "GET /api/feed",
                {"method": "GET", "path": "/api/feed", "status": "defined",
                 "response_format": {"posts": []}, "request_body": {"query": "string"}},
                agent="design",
            )
            hub_eps = ws.hubs.apihub.get_endpoints()
            crdt_eps = ws._endpoints.value()
            self.assertIn("GET /api/feed", hub_eps)
            self.assertIn("GET /api/feed", crdt_eps)
            self.assertEqual(hub_eps["GET /api/feed"]["status"], "defined")

    def test_register_api_usage_propagates_to_apihub_consumers(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            ws.update_endpoint("GET /api/feed", {"method": "GET", "path": "/api/feed",
                                                  "status": "defined"}, agent="design")
            ws.register_api_usage("GET /api/feed", "app/frontend/src/Feed.jsx", "frontend")
            # Expectation: APIHub consumers may need to mirror the legacy registration.
            # If they don't yet, this test pins the requirement.
            hub_consumers = [c for c in ws.hubs.apihub._consumers.value().values()
                             if c.get("endpoint_id") == "GET /api/feed"
                             and c.get("file_path") == "app/frontend/src/Feed.jsx"]
            self.assertEqual(len(hub_consumers), 1)

    def test_get_endpoints_returns_same_set_as_apihub(self):
        with tempfile.TemporaryDirectory() as td:
            ws = CRDTWorkspace(Path(td))
            for path in ("/api/a", "/api/b"):
                ws.update_endpoint(f"GET {path}", {"method": "GET", "path": path, "status": "defined"}, agent="design")
            legacy_keys = set(ws.get_endpoints().keys())
            hub_keys = set(ws.hubs.apihub.get_endpoints().keys())
            self.assertEqual(legacy_keys, hub_keys)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run parity tests**

```bash
python3 -m unittest agent.tests.test_apihub_parity -v
```

Expected: `test_update_endpoint_propagates_to_apihub` PASSES (dual-write already wires this in `crdt.py:344`). `test_get_endpoints_returns_same_set_as_apihub` PASSES.

`test_register_api_usage_propagates_to_apihub_consumers` may FAIL because legacy `register_api_usage` only writes to `_api_consumers` (its own LWW map), not to APIHub. If it fails, **stop and do Step 3.**

- [ ] **Step 3: If consumer parity fails, mirror the write**

Open `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py:427` (`register_api_usage`). At the end of the method, immediately after `self._api_consumers.update(...)`, add the APIHub mirror:

```python
        try:
            self.hubs.apihub.register_consumer(
                endpoint_key, consumer_file, consumer_agent,
                metadata={"usage_type": usage_type,
                          "line_number": line_number,
                          "component_name": component_name},
            )
        except Exception:
            pass
```

Then re-run parity:
```bash
python3 -m unittest agent.tests.test_apihub_parity -v
```

Expected: all 3 PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_apihub_parity.py
# include crdt.py only if Step 3 was needed
git status --short
git commit -m "Add temporary APIHub parity tests (deleted after cutover Phase 5)"
```

---

## Phase 4 — Switch callers

> This phase changes one file per commit. Do not bundle multiple call-site changes into one commit.

### Task 11: Switch `orchestrator.py:711` to read endpoints from APIHub

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/orchestrator.py`

- [ ] **Step 1: Read the current line**

```bash
sed -n '705,720p' agent/env_generator/llm_generator/multi_agent/orchestrator.py
```

Find the line: `endpoints = self.crdt_workspace.get_endpoints() or {}`.

- [ ] **Step 2: Apply the edit**

Replace that line with:

```python
        endpoints = self.crdt_workspace.hubs.apihub.get_endpoints() or {}
```

(Keeping access via `crdt_workspace.hubs` until full CRDTWorkspace removal — that happens in a later cutover.)

- [ ] **Step 3: Run regressions**

```bash
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/orchestrator.py
git commit -m "Read delivery-gate endpoints from hubs.apihub instead of legacy CRDT"
```

### Task 12: Switch `crdt_projection.py:80` to single-write into APIHub

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py`

- [ ] **Step 1: Inspect current dual-write block**

```bash
sed -n '70,100p' agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py
```

You should see the block calling `workspace.hubs.apihub.register_endpoint(...)`. Confirm there is also a legacy `workspace.update_endpoint(...)` call nearby.

- [ ] **Step 2: Delete the legacy `update_endpoint` call, keep only the APIHub call**

Apply the edit: remove the line(s) that invoke `workspace.update_endpoint(...)`. Leave the `workspace.hubs.apihub.register_endpoint(...)` block intact.

- [ ] **Step 3: Run regressions + parity**

```bash
python3 -m unittest agent.tests.test_apihub_parity -v
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: parity remains green (dual-write still happens via `crdt.py:update_endpoint` for any other caller); regressions OK.

- [ ] **Step 4: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py
git commit -m "crdt_projection: write API spec only via APIHub, not legacy CRDTWorkspace"
```

### Task 13: Remove legacy endpoint/consumer tool classes from `crdt_tools.py`

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/crdt_tools.py`

- [ ] **Step 1: Identify the 6 classes to delete**

```bash
grep -n "^class \(UpdateEndpointTool\|GetEndpointsTool\|RegisterApiUsageTool\|GetApiConsumersTool\|GetFileDependenciesTool\|GetApiChangeNotificationsTool\)" agent/env_generator/llm_generator/tools/crdt_tools.py
```

You should see 6 line numbers. Note them.

- [ ] **Step 2: Delete each class definition**

Open `tools/crdt_tools.py` and remove the entire `class UpdateEndpointTool ...`, `class GetEndpointsTool ...`, `class RegisterApiUsageTool ...`, `class GetApiConsumersTool ...`, `class GetFileDependenciesTool ...`, `class GetApiChangeNotificationsTool ...` blocks (each ends before the next `class` line).

- [ ] **Step 3: Remove their entries from `get_crdt_tools(...)` and `__all__`**

In the same file, find `def get_crdt_tools(...)` and delete the lines listing these 6 tools. Then delete them from the `__all__` list at the bottom.

- [ ] **Step 4: Run tests — import must still succeed**

```bash
python3 -c "from tools.crdt_tools import get_crdt_tools" || echo "IMPORT FAILED"
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: no import error, regressions OK.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/crdt_tools.py
git commit -m "Remove 6 legacy endpoint/consumer tool classes (replaced by apihub_* tools)"
```

### Task 14: Update `prompts/v2/design_agent.j2` to reference new tool names

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`

- [ ] **Step 1: Locate legacy tool references**

```bash
grep -n "update_endpoint\|register_api_usage\|get_endpoints\|get_api_consumers\|get_api_change_notifications\|get_file_dependencies" agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2
```

- [ ] **Step 2: Replace each occurrence**

| Old tool reference | New tool name |
|---|---|
| `update_endpoint(...)` | `apihub_register_endpoint(method=..., path=..., schema=..., status=...)` |
| `get_endpoints()` | `apihub_list_endpoints()` |
| `register_api_usage(...)` | `apihub_register_consumer(endpoint_id=..., file_path=...)` |
| `get_api_consumers(...)` | (rare in design.j2; if present) `apihub_get_breaking_changes()` for notification-style flow |
| `get_file_dependencies(...)` | `apihub_get_dependencies_for_file(file_path=...)` |
| `get_api_change_notifications()` | `apihub_get_breaking_changes()` |

Open `design_agent.j2` and apply substitutions in narrative text and example code blocks. Where the template explains the API contract publishing flow, also add a sentence: "API contract changes that remove fields, change types, change paths/methods, or add auth automatically create fix tasks for affected consumers."

- [ ] **Step 3: Verify no stale references**

```bash
grep -nE "update_endpoint|register_api_usage|get_endpoints\b|get_api_consumers|get_api_change_notifications|get_file_dependencies" agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2
```

Expected: no matches.

- [ ] **Step 4: Smoke-test prompt rendering**

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('agent/env_generator/llm_generator/multi_agent/prompts'))
tpl = env.get_template('v2/design_agent.j2')
print(tpl.render(name='test', api_port=8000, ui_port=3000, db_port=5432)[:200])
"
```

Expected: prints first 200 chars without `UndefinedError`. (If a context var is missing, add a stub value to the test call.)

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2
git commit -m "design prompt: switch endpoint tool references to apihub_* names"
```

### Task 15: Update `prompts/v2/backend_agent.j2`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`

- [ ] **Step 1, 2, 3, 4, 5: Repeat Task 14 steps verbatim against `backend_agent.j2`**

Use the same substitution table from Task 14, Step 2. After verifying no stale references and rendering succeeds, commit:

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2
git commit -m "backend prompt: switch endpoint tool references to apihub_* names"
```

### Task 16: Update `prompts/v2/frontend_agent.j2`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`

- [ ] **Step 1-5: Repeat Task 14 against `frontend_agent.j2`**

Commit:
```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2
git commit -m "frontend prompt: switch endpoint tool references to apihub_* names"
```

### Task 17: Update `prompts/v2/verifier_agent.j2` and `orchestrator_agent.j2`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`

- [ ] **Step 1: Apply Task 14 substitutions to verifier_agent.j2**

Also add: `apihub_record_contract_test(endpoint_id=..., result=..., evidence=...)` as the recommended way for verifier to log contract test outcomes.

- [ ] **Step 2: Apply Task 14 substitutions to orchestrator_agent.j2**

- [ ] **Step 3: Verify no stale references in either**

```bash
grep -nE "update_endpoint|register_api_usage|get_endpoints\b|get_api_consumers|get_api_change_notifications|get_file_dependencies" \
  agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2 \
  agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2
```

Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2
git commit -m "verifier+orchestrator prompts: switch endpoint tool references to apihub_*"
```

### Task 18: Full regression sanity check + end-to-end smoke

**Files:** None modified.

- [ ] **Step 1: Run regressions**

```bash
python3 agent/tests/run_regressions.py
```

Expected: OK, all tests pass.

- [ ] **Step 2: Run a small end-to-end smoke generation (30-minute cap, generate-only)**

```bash
# In another shell or with a timeout wrapper:
timeout 1800 bash run_facebook_generation.sh --no-verify --limit-iterations 5 \
   > /tmp/apihub-cutover-smoke.log 2>&1 || true
tail -40 /tmp/apihub-cutover-smoke.log
```

Expected: log ends without a Python traceback; you see at least one APIHub-related event line (`apihub_register_endpoint` invocation or `endpoint_registered` event log). If you see a traceback referencing legacy `update_endpoint`, **stop and fix the missed call site** before proceeding.

- [ ] **Step 3: Commit a smoke log marker (informational, optional)**

```bash
mkdir -p docs/superpowers/migration-logs
cp /tmp/apihub-cutover-smoke.log docs/superpowers/migration-logs/01-apihub-smoke.log
git add docs/superpowers/migration-logs/01-apihub-smoke.log
git commit -m "Record APIHub cutover end-to-end smoke log"
```

---

## Phase 5 — Remove legacy code

> Only proceed once Phase 4 is green. Each task in this phase deletes code; revert is cheap pre-merge.

### Task 19: Delete absorbed endpoint methods from `crdt.py`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py`

- [ ] **Step 1: Confirm no caller still uses legacy methods**

```bash
grep -rn --include='*.py' \
  -e 'workspace\.update_endpoint\b' \
  -e 'workspace\.get_endpoint\b' \
  -e 'workspace\.get_endpoints\b' \
  -e 'workspace\.get_usable_endpoints\b' \
  -e 'workspace\.observe_endpoints\b' \
  -e 'workspace\.register_api_usage\b' \
  -e 'workspace\.unregister_api_usage\b' \
  -e 'workspace\.get_api_consumers\b' \
  -e 'workspace\.get_file_api_dependencies\b' \
  -e 'workspace\._notify_api_consumers\b' \
  -e 'workspace\.get_api_change_notifications\b' \
  -e 'workspace\.get_api_dependency_graph\b' \
  agent/
```

Expected: zero matches. If matches show up, **stop and rewrite those call sites first** (Task 14-17 missed them).

- [ ] **Step 2: Delete the following methods from `crdt.py`**

Delete the entire body of each of these `CRDTWorkspace` methods (lines 305-596 covers most of them; verify with grep first):

- `update_endpoint`
- `_detect_breaking_change`
- `get_endpoint`
- `get_endpoints`
- `get_usable_endpoints`
- `observe_endpoints`
- `register_api_usage`
- `unregister_api_usage`
- `get_api_consumers`
- `get_file_api_dependencies`
- `_notify_api_consumers`
- `get_api_change_notifications`
- `get_api_dependency_graph`

After deletion, the `CRDTWorkspace` class should have ~290 fewer lines.

- [ ] **Step 3: Delete the `_endpoints` and `_api_consumers` store fields**

In `crdt.py` `__init__` (around line 84 and 117), delete:

```python
        self._endpoints = CRDTStore(
            self.crdt_dir / "endpoints.json",
            LWWMap
        )
```

and

```python
        self._api_consumers = CRDTStore(
            self.crdt_dir / "api_consumers.json",
            LWWMap
        )
```

In `ensure_core_documents` (around line 258), remove their entries from the `stores` list.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest agent.tests.test_hub_architecture agent.tests.test_apihub_strengthen \
                    agent.tests.test_apihub_breaking_change_creates_task agent.tests.test_apihub_tools -v
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all PASS, regressions OK.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/crdt.py
git commit -m "Delete absorbed endpoint/consumer methods + stores from CRDTWorkspace"
```

### Task 20: Delete the temporary parity tests

**Files:**
- Delete: `agent/tests/test_apihub_parity.py`

- [ ] **Step 1: Remove the file**

```bash
git rm agent/tests/test_apihub_parity.py
```

- [ ] **Step 2: Confirm regressions still clean**

```bash
python3 agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: OK.

- [ ] **Step 3: Commit**

```bash
git commit -m "Remove temporary APIHub parity tests (their job is done)"
```

### Task 21: End-to-end full Facebook generation

**Files:** None modified.

- [ ] **Step 1: Run the full generation**

```bash
timeout 5400 bash run_facebook_generation.sh > /tmp/apihub-cutover-e2e.log 2>&1 || true
```

Expected: completes within 90 minutes. Output ends with a success line (look for "Generation complete" or similar in the script's tail).

- [ ] **Step 2: Validate APIHub state in the output project**

```bash
ls generated/facebook*/shared/crdt/apihub_*.json | head
cat $(ls generated/facebook*/shared/crdt/apihub_endpoints.json | head -1) | python3 -m json.tool | head -40
```

Expected: `apihub_endpoints.json` is non-empty with real endpoints; `apihub_contract_tests.json` has at least one entry.

- [ ] **Step 3: Save the log**

```bash
cp /tmp/apihub-cutover-e2e.log docs/superpowers/migration-logs/01-apihub-e2e.log
git add docs/superpowers/migration-logs/01-apihub-e2e.log
git commit -m "Record APIHub cutover full e2e Facebook generation log"
```

---

## Phase 6 — Docs and merge

### Task 22: Write migration log

**Files:**
- Create: `docs/superpowers/migration-logs/01-apihub.md`

- [ ] **Step 1: Draft the migration log**

Create `docs/superpowers/migration-logs/01-apihub.md` with this template (fill in real values from your runs):

```markdown
# 01 — APIHub Cutover

**Date:** 2026-MM-DD
**Branch:** haibotong-hub-cutover-1-apihub
**PR:** <to be filled after open>

## Summary
First hub cutover from the four-hub plan. APIHub is now the sole authority on API contracts, the legacy `CRDTWorkspace.update_endpoint` family is deleted, and breaking changes automatically create fix tasks in WorkHub.

## Files changed
- Added 8 new APIHub tools to `tools/hub_tools.py` (10 total now).
- Strengthened `APIHub` with: `add_mock`, `add_example`, `deprecate_endpoint`, expanded `detect_breaking_change`, breaking-change → WorkHub fix-task wiring.
- Deleted ~290 lines from `crdt.py` (endpoint + consumer methods + their stores).
- Deleted 6 legacy tool classes from `crdt_tools.py`.
- Updated 5 prompts in `prompts/v2/`.
- Hub architecture test now part of `run_regressions.py`.

## SOP changes (apply to remaining cutovers)
- (Capture anything surprising encountered during this cut here)

## Regression evidence
- Final regression pass: <PASTE OUTPUT LAST 10 LINES>
- E2E Facebook generation log: docs/superpowers/migration-logs/01-apihub-e2e.log

## Gotchas
- (List any rough patches: missing call sites, prompt context-var mismatches, race conditions, etc.)

## Next cutover
- EventHub bridge (`docs/superpowers/plans/2026-MM-DD-eventhub-bridge-cutover.md` — to be written after this PR merges)
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/migration-logs/01-apihub.md
git commit -m "Add APIHub cutover migration log"
```

### Task 23: Self-review and open PR

**Files:** None modified.

- [ ] **Step 1: Review your own diff**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat | tail -20
```

Expected: a tidy list of small commits, all related to APIHub cutover. No unrelated drift.

- [ ] **Step 2: Run `/code-review` skill on the branch**

In Claude Code:
```
/code-review
```

Address any high-confidence findings before opening the PR.

- [ ] **Step 3: Open the PR**

```bash
git push -u origin haibotong-hub-cutover-1-apihub
gh pr create --title "Hub cutover 1/4: APIHub" --body "$(cat <<'EOF'
## Summary
- First of 4 hub cutovers from the four-hub design spec.
- APIHub is now the sole authority for API contracts; CRDTWorkspace endpoint methods are deleted.
- Breaking changes auto-create fix tasks in WorkHub.

## Spec
- docs/superpowers/specs/2026-05-21-four-hubs-design.md
- docs/superpowers/plans/2026-05-21-apihub-cutover.md

## Test plan
- [x] Full regression suite (incl. test_hub_architecture)
- [x] APIHub strengthen tests
- [x] APIHub tools tests
- [x] Cross-hub breaking-change → WorkHub task test
- [x] End-to-end Facebook generation (log under docs/superpowers/migration-logs/)

## Next
- EventHub bridge cutover (plan to be written after merge)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Share it with the team.

---

## Out of Scope

These are NOT part of this PR — they belong to later cutovers or follow-up cleanup PRs:

- `WorkHub` / `CodeHub` / `EventHub` data model changes beyond what APIHub directly needs.
- Building the `MessageBusBridge` (Cutover 2).
- Splitting `tools/hub_tools.py` into a package directory (`hub_tools/`) — deferred until after CodeHub cut. The spec target is the package; we keep the single file in this PR to avoid bundling restructuring with the cutover.
- Creating `runtime/hubs.py:HubRegistry` and replacing the `crdt_workspace.hubs.<x>` access pattern — deferred until the last cutover (CodeHub), where `CRDTWorkspace` is finally deleted. For this PR, callers continue to reach APIHub via `crdt_workspace.hubs.apihub`.
- Real `git worktree` integration (Cutover 4).
- Deleting `crdt_dev_tasks.py`, `crdt_validation.py`, `crdt_projection.py`, `file_coordination.py` (later cutovers).
- Removing the `HubWorkspace` aggregator — that goes when the last legacy method leaves `crdt.py`.

## Recovery Notes

If something goes catastrophically wrong mid-Phase-4 or Phase-5:
1. `git reset --hard HEAD~1` undoes the last commit (the changes are small per commit).
2. The branch can be rebuilt from any point; cherry-pick earlier task commits as needed.
3. If a missed call site is found post-PR, treat it as a Cutover 1.1 follow-up PR, not a force-push.
