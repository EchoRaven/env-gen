# Cutover 7 — Schema 3-Layer + Registration Discipline + Reviewer Gate

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Lock down PR / merge / registration so frontend ↔ backend ↔ database stay aligned at the code level. Enforce **mandatory registration discipline**: every new backend API must be registered on APIHub before its consumer can land; every new UI page/component must be declared on WorkHub; every API a component uses must be declared as a `register_consumer`. Plus the schema 3-layer (L1 write-time, L2 merge-time, L3 step-time-already-shipped) and 2-reviewer hard gate with orchestrator auto-injection.

**Architecture:** Five enforcement layers active simultaneously:
1. **APIHub L1 write-time** — `register_consumer / register_table_consumer` reject schema mismatches and unknown endpoints/tables
2. **Registration-manifest validation** — PR's `linked_apis / linked_tasks / linked_pages / linked_consumers` must all resolve to existing hub records
3. **CodeHub L2 merge-time verifier gate** — contract tests for every `linked_api` must pass; every `linked_task` must be `completed`
4. **2-reviewer gate** — `open_pull_request` requires ≥ 2 reviewers; `orchestrator` auto-injected; `_is_pr_approved` requires ALL approve
5. **`force_merge` bypass** — only `orchestrator`, ≥ 20-char reason, audited

**Tech Stack:** Python 3.11 (`dt` conda env), unittest, existing `HubTool` patterns, no new external deps (pure dict subset check for schemas).

**Source spec:** `docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md` §6 (gate invariants), §7 (schema 3-layer), §8 (reviewer enforcement).

**Out of scope (deferred to Cutover 8):**
- `hub_pulse` + `hub_commit_gate` step-pipeline stages
- Prompt template updates introducing pulse/gate sections
- AST-based code parsing for auto-detected registration (declarative manifest only for now)

---

## Pre-Reading

- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — `register_consumer / register_table_consumer / get_endpoints / get_table` already exist
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — `open_pull_request / merge_pull_request / submit_review / _is_pr_approved` already exist
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — `get_task / list_pages / get_page / update_ui_page / get_ui_pages` already exist (added Cutover 3 + 6)
- Existing `attach_workhub(workhub)` pattern on APIHub — replicate for CodeHub

## File Map

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — write-time L1 in `register_consumer` + `register_table_consumer`; helper `_schema_subset_check`
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — `attach_workhub`; rewrite `open_pull_request` with manifest validation + 2-reviewer + orchestrator auto-injection; rewrite `_is_pr_approved` strict; `_run_premerge_verifier_gate`; rewrite `merge_pull_request` calling premerge; `force_merge_pull_request`; `suggest_reviewers`
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — call `codehub.attach_workhub(workhub)` after construction
- `agent/env_generator/llm_generator/tools/hub_tools.py` — 2 new tool classes (`CodeHubSuggestReviewersTool`, `CodeHubForceMergeTool`); modify `CodeHubOpenPRTool` parameters to accept `linked_pages / linked_consumers`
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — widen `_bundle_codehub_tools.include_names` with the 2 new tools
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `codehub_force_merge` to orchestrator profile's `allow_tools` (or remove from other profiles' bundle via `deny_tools`)

**Create:**
- `agent/tests/test_apihub_l1_write_time_gate.py` — L1 schema_subset_check + unknown-endpoint + deprecated cases
- `agent/tests/test_codehub_open_pr_gates.py` — 2-reviewer + orchestrator auto-injection + linked_tasks-required + linked_apis/pages/consumers validation
- `agent/tests/test_codehub_premerge_gate.py` — L2 verifier gate (contract test + task completion + registration manifest checks)
- `agent/tests/test_codehub_suggest_reviewers.py` — weighted picker (already used as filename in spec §11; cf. previous cutovers — match naming)
- `agent/tests/test_codehub_force_merge.py` — orchestrator-only + reason length + audit event
- `agent/tests/test_codehub_strict_approval.py` — `_is_pr_approved` requires ALL reviewers approve
- `docs/superpowers/migration-logs/08-schema-gates-and-registration-discipline.md`

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1:** Create worktree from parent

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-7-schema-gates -b haibotong-cutover-7-schema-gates red-env-gen/haibotong-0521-pipeline-web-tools
cd .worktrees/haibotong-cutover-7-schema-gates
```

- [ ] **Step 2:** Baseline tests

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: regressions 7 OK; ≥ 274 tests OK.

---

## Phase A — APIHub Layer 1 Write-Time Gate

### Task 2: TDD `_schema_subset_check` helper

**Files:**
- Create: `agent/tests/test_apihub_l1_write_time_gate.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1:** Write failing test for `_schema_subset_check`

Create `agent/tests/test_apihub_l1_write_time_gate.py`:

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.apihub import _schema_subset_check  # noqa: E402


class SchemaSubsetCheckTests(unittest.TestCase):
    def test_expected_subset_of_actual_returns_none(self):
        actual = {"id": "int", "name": "string", "extra": "string"}
        expected = {"id": "int", "name": "string"}
        self.assertIsNone(_schema_subset_check(expected, actual))

    def test_missing_field_reports_missing(self):
        actual = {"id": "int"}
        expected = {"id": "int", "name": "string"}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertIn("name", result["missing"])
        self.assertEqual(result["type_mismatches"], [])

    def test_type_mismatch_reports_it(self):
        actual = {"id": "string"}
        expected = {"id": "int"}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertEqual(result["missing"], [])
        self.assertIn("id", result["type_mismatches"])

    def test_empty_expected_always_subset(self):
        self.assertIsNone(_schema_subset_check({}, {"id": "int"}))
        self.assertIsNone(_schema_subset_check({}, {}))

    def test_nested_dict_recursive_check(self):
        actual = {"response": {"data": {"id": "int", "name": "string"}}}
        expected = {"response": {"data": {"id": "int"}}}
        self.assertIsNone(_schema_subset_check(expected, actual))

    def test_nested_dict_missing_reports_dotted_path(self):
        actual = {"response": {"data": {"id": "int"}}}
        expected = {"response": {"data": {"id": "int", "name": "string"}}}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertIn("response.data.name", result["missing"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL (ImportError — function not defined)

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_l1_write_time_gate -v 2>&1 | tail -10
```

- [ ] **Step 3:** Implement `_schema_subset_check` in `apihub.py`

Add this module-level helper near the top of `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` (after the imports, before the `APIHub` class):

```python
def _schema_subset_check(expected: dict, actual: dict, path: str = "") -> "dict | None":
    """Return None if `expected` is a structural+type subset of `actual`.
    Otherwise return {"missing": [dotted_paths], "type_mismatches": [dotted_paths]}.

    Pure dict comparison. No jsonschema dependency. Allows `actual` to have
    additional keys (additive endpoints OK).
    """
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return None  # non-dict — skip; only dict shapes are validated
    missing: list = []
    type_mismatches: list = []
    for key, expected_val in expected.items():
        dotted = f"{path}.{key}" if path else key
        if key not in actual:
            missing.append(dotted)
            continue
        actual_val = actual[key]
        if isinstance(expected_val, dict) and isinstance(actual_val, dict):
            sub = _schema_subset_check(expected_val, actual_val, path=dotted)
            if sub is not None:
                missing.extend(sub["missing"])
                type_mismatches.extend(sub["type_mismatches"])
        elif expected_val != actual_val:
            type_mismatches.append(dotted)
    if missing or type_mismatches:
        return {"missing": missing, "type_mismatches": type_mismatches}
    return None
```

- [ ] **Step 4:** Run, confirm PASS (6 tests)

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_l1_write_time_gate -v 2>&1 | tail -10
```

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_apihub_l1_write_time_gate.py \
        agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "Add _schema_subset_check helper for APIHub L1 write-time gate"
```

### Task 3: TDD `register_consumer` write-time gate

**Files:**
- Modify: `agent/tests/test_apihub_l1_write_time_gate.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1:** Append tests to `test_apihub_l1_write_time_gate.py`

Add this class **at module level after `SchemaSubsetCheckTests`** (before `if __name__`):

```python
class RegisterConsumerWriteTimeGateTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).apihub

    def test_register_consumer_unknown_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_consumer(
                "GET /api/nope", "src/Feed.jsx", "frontend", metadata={})
            self.assertEqual(result.get("error"), "endpoint_not_registered")

    def test_register_consumer_deprecated_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/old", schema={}, provider="backend", agent="design")
            hub.register_endpoint("GET", "/api/new", schema={}, provider="backend", agent="design")
            hub.deprecate_endpoint("GET /api/old", replacement_id="GET /api/new", agent="design")
            result = hub.register_consumer("GET /api/old", "src/Feed.jsx", "frontend")
            self.assertEqual(result.get("error"), "endpoint_deprecated")
            self.assertEqual(result.get("replacement_id"), "GET /api/new")

    def test_register_consumer_expected_schema_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="design",
            )
            # Frontend expects a field the endpoint doesn't have
            result = hub.register_consumer(
                "GET /api/feed", "src/Feed.jsx", "frontend",
                metadata={"expected_schema": {"response": {"posts": [], "missing_field": 0}}},
            )
            self.assertEqual(result.get("error"), "schema_mismatch")
            self.assertIn("response.missing_field", result.get("missing_fields", []))

    def test_register_consumer_expected_schema_match_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="design",
            )
            # Frontend expects subset of what endpoint provides
            result = hub.register_consumer(
                "GET /api/feed", "src/Feed.jsx", "frontend",
                metadata={"expected_schema": {"response": {"posts": []}}},
            )
            self.assertNotIn("error", result)
            self.assertEqual(result["file_path"], "src/Feed.jsx")

    def test_register_consumer_no_expected_schema_still_works(self):
        # Backward compat: existing callers don't pass expected_schema
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="design")
            result = hub.register_consumer("GET /api/feed", "src/Feed.jsx", "frontend")
            self.assertNotIn("error", result)
```

- [ ] **Step 2:** Run, confirm FAIL for all 5

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_l1_write_time_gate.RegisterConsumerWriteTimeGateTests -v 2>&1 | tail -10
```

- [ ] **Step 3:** Modify `register_consumer` in `apihub.py`

Find the existing method (search `def register_consumer`). Prepend the write-time gate:

```python
    def register_consumer(self, endpoint_id: str, file_path: str, agent: str,
                          metadata: dict = None) -> dict:
        # L1 write-time gate
        endpoint = self._endpoints.value().get(endpoint_id)
        if not endpoint:
            return {"error": "endpoint_not_registered",
                    "endpoint_id": endpoint_id,
                    "hint": "Call apihub_register_endpoint first (backend agent)."}
        if endpoint.get("status") == "deprecated":
            return {"error": "endpoint_deprecated",
                    "endpoint_id": endpoint_id,
                    "replacement_id": endpoint.get("replacement_id"),
                    "hint": "Use the replacement endpoint instead."}
        if metadata and "expected_schema" in metadata:
            mismatch = _schema_subset_check(
                metadata["expected_schema"], endpoint.get("schema", {}))
            if mismatch:
                return {"error": "schema_mismatch",
                        "endpoint_id": endpoint_id,
                        "missing_fields": mismatch.get("missing"),
                        "type_mismatches": mismatch.get("type_mismatches"),
                        "hint": "Fix consumer code to match endpoint schema, "
                                "or apihub_request_review to negotiate a change."}
        # ...existing body unchanged below this line...
```

(Keep the existing write logic that follows.)

- [ ] **Step 4:** Run, confirm 5 new tests + 6 prior all PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_l1_write_time_gate -v 2>&1 | tail -15
```

- [ ] **Step 5:** Run hub regressions to confirm no break

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_tools agent.tests.test_apihub_strengthen agent.tests.test_hub_architecture agent.tests.test_apihub_breaking_change_creates_task 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all OK. If `test_apihub_breaking_change_creates_task` fails (it calls `register_consumer` indirectly), inspect — likely the test setup expects the gate. If so, fix the test to register the endpoint first.

- [ ] **Step 6:** Commit

```bash
git add agent/tests/test_apihub_l1_write_time_gate.py \
        agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "APIHub L1 write-time gate: reject unknown/deprecated endpoint + schema mismatch"
```

### Task 4: TDD `register_table_consumer` write-time gate (parallel to Task 3)

**Files:**
- Modify: `agent/tests/test_apihub_l1_write_time_gate.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1:** Append tests

```python
class RegisterTableConsumerWriteTimeGateTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).apihub

    def test_register_table_consumer_unknown_table_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_table_consumer(
                "missing_table", "src/users.py", "backend")
            self.assertIn("error", result)

    def test_register_table_consumer_expected_columns_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users",
                               schema={"id": "int", "email": "string"},
                               provider="database", agent="design")
            result = hub.register_table_consumer(
                "users", "src/users.py", "backend",
                metadata={"expected_columns": {"id": "int", "phone": "string"}},
            )
            self.assertEqual(result.get("error"), "schema_mismatch")
            self.assertIn("phone", result.get("missing_fields", []))

    def test_register_table_consumer_expected_columns_match_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users",
                               schema={"id": "int", "email": "string"},
                               provider="database", agent="design")
            result = hub.register_table_consumer(
                "users", "src/users.py", "backend",
                metadata={"expected_columns": {"id": "int"}},
            )
            self.assertNotIn("error", result)
            self.assertEqual(result["table_name"], "users")
```

- [ ] **Step 2:** Run, confirm FAIL (schema_mismatch path not yet implemented for table consumer; unknown table already returns error from Cutover 6)

- [ ] **Step 3:** Modify `register_table_consumer` in `apihub.py`

Find the method. Replace the start of its body with:

```python
    def register_table_consumer(self, table_name: str, file_path: str, agent: str,
                                metadata: dict = None) -> dict:
        # L1 write-time gate
        table = self.get_table(table_name)
        if not table:
            return {"error": "table_not_registered",
                    "table_name": table_name,
                    "hint": "Call apihub_register_table first (database/design agent)."}
        if metadata and "expected_columns" in metadata:
            mismatch = _schema_subset_check(
                metadata["expected_columns"], table.get("schema", {}))
            if mismatch:
                return {"error": "schema_mismatch",
                        "table_name": table_name,
                        "missing_fields": mismatch.get("missing"),
                        "type_mismatches": mismatch.get("type_mismatches"),
                        "hint": "Fix consumer code to match table schema, "
                                "or coordinate with database/design agent."}
        # ...existing body unchanged below...
```

- [ ] **Step 4:** Run all L1 tests + regressions

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_l1_write_time_gate agent.tests.test_apihub_tables_breaking_change 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all OK.

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_apihub_l1_write_time_gate.py \
        agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "APIHub L1 write-time gate for register_table_consumer (expected_columns check)"
```

---

## Phase B — CodeHub `open_pull_request` Manifest + Reviewer Gate

### Task 5: TDD `open_pull_request` requires linked_tasks non-empty + linked_apis in APIHub + linked_pages in WorkHub

**Files:**
- Create: `agent/tests/test_codehub_open_pr_gates.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`

- [ ] **Step 1:** Write failing tests

Create `agent/tests/test_codehub_open_pr_gates.py`:

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class OpenPRGatesTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        # We are not opening a real git PR, just exercising the metadata path
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        return hubs, ch

    def test_open_pr_requires_non_empty_linked_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["orchestrator", "frontend"],
                linked_tasks=[],  # empty
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_tasks_required")

    def test_open_pr_requires_two_reviewers_after_author_exclusion(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="Build feed", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["backend"],  # author is sole reviewer → 0 distinct → fails
                linked_tasks=[task["id"]],
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "insufficient_reviewers")
            self.assertEqual(result.get("required"), 2)

    def test_open_pr_auto_injects_orchestrator_when_author_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend"],  # only 1 explicit; orchestrator injected → 2 distinct
                linked_tasks=[task["id"]],
                title="Feed API",
                author="backend",
            )
            self.assertNotIn("error", result)
            self.assertIn("orchestrator", result["reviewers"])
            self.assertIn("frontend", result["reviewers"])

    def test_open_pr_orchestrator_author_does_not_self_inject(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "verifier"],
                linked_tasks=[task["id"]],
                title="Cleanup",
                author="orchestrator",
            )
            self.assertNotIn("error", result)
            # author=orchestrator → no auto-injection
            self.assertNotIn("orchestrator", result["reviewers"])

    def test_open_pr_linked_api_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_apis=["GET /api/ghost"],  # not in APIHub
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_apis_unknown")
            self.assertIn("GET /api/ghost", result.get("unknown", []))

    def test_open_pr_linked_pages_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="frontend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/frontend",
                reviewers=["backend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_pages=["page_does_not_exist"],
                title="UI",
                author="frontend",
            )
            self.assertEqual(result.get("error"), "linked_pages_unknown")

    def test_open_pr_linked_tasks_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=["task_ghost"],
                title="x",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_tasks_unknown")
            self.assertIn("task_ghost", result.get("unknown", []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Wire CodeHub ↔ APIHub ↔ WorkHub for manifest validation

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`, find `attach_workhub` (added earlier when WorkHub linkage was needed for conflict tasks). If only `_workhub` is stored, also add `_apihub`:

```python
    def attach_workhub(self, workhub) -> None:
        self._workhub = workhub

    def attach_apihub(self, apihub) -> None:
        self._apihub = apihub
```

(If `attach_apihub` doesn't exist, add it. If only `attach_workhub` exists, leave it and add `attach_apihub` next to it.)

In `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`, find where `codehub.attach_workhub(workhub)` is called (likely right after WorkHub is constructed). Add:

```python
self.codehub.attach_apihub(self.apihub)
```

If `attach_workhub(workhub)` call doesn't exist there either, add both:

```python
if hasattr(self.codehub, "attach_workhub"):
    self.codehub.attach_workhub(self.workhub)
if hasattr(self.codehub, "attach_apihub"):
    self.codehub.attach_apihub(self.apihub)
```

- [ ] **Step 3:** Rewrite `open_pull_request` in CodeHub

Find the existing `open_pull_request` method. Replace its parameters and gate-checking section with:

```python
    def open_pull_request(
        self,
        branch: str,
        target: str = "main",
        reviewers: list = None,
        linked_tasks: list = None,
        linked_apis: list = None,
        linked_pages: list = None,
        linked_consumers: list = None,
        title: str = "",
        body: str = "",
        author: str = "",
        repo_id: str = "main",
    ) -> dict:
        reviewers = list(reviewers or [])
        linked_tasks = list(linked_tasks or [])
        linked_apis = list(linked_apis or [])
        linked_pages = list(linked_pages or [])
        linked_consumers = list(linked_consumers or [])

        # Gate 1: at least one linked task
        if not linked_tasks:
            return {"error": "linked_tasks_required",
                    "hint": "Every PR must reference at least one WorkHub task. "
                            "Create one with workhub_create_task or link an existing one."}

        # Gate 2: orchestrator auto-injection (unless author is orchestrator)
        if author != "orchestrator" and "orchestrator" not in reviewers:
            reviewers.append("orchestrator")

        # Gate 3: at least 2 distinct reviewers (excluding author)
        distinct = [r for r in reviewers if r != author]
        if len(distinct) < 2:
            return {"error": "insufficient_reviewers",
                    "current": distinct, "required": 2,
                    "hint": "Call codehub_suggest_reviewers(branch, linked_apis, ...) for candidates."}

        # Gate 4: every linked_api must exist in APIHub
        if linked_apis and hasattr(self, "_apihub") and self._apihub is not None:
            known = set(self._apihub.get_endpoints().keys())
            unknown = [a for a in linked_apis if a not in known]
            if unknown:
                return {"error": "linked_apis_unknown",
                        "unknown": unknown,
                        "hint": "Register the endpoint first via apihub_register_endpoint."}

        # Gate 5: every linked_task must exist in WorkHub
        if hasattr(self, "_workhub") and self._workhub is not None:
            unknown_tasks = [t for t in linked_tasks if self._workhub.get_task(t) is None]
            if unknown_tasks:
                return {"error": "linked_tasks_unknown",
                        "unknown": unknown_tasks,
                        "hint": "Create the WorkHub task first via workhub_create_task."}

        # Gate 6: every linked_page must exist in WorkHub
        if linked_pages and hasattr(self, "_workhub") and self._workhub is not None:
            unknown_pages = [
                p for p in linked_pages
                if self._workhub.get_page(p, with_blocks=False) is None
            ]
            if unknown_pages:
                return {"error": "linked_pages_unknown",
                        "unknown": unknown_pages,
                        "hint": "Create the WorkHub page first via workhub_create_page."}

        # Gate 7: every linked_consumer must exist in APIHub consumers
        if linked_consumers and hasattr(self, "_apihub") and self._apihub is not None:
            consumer_keys = set(self._apihub._consumers.value().keys())
            unknown_consumers = [c for c in linked_consumers if c not in consumer_keys]
            if unknown_consumers:
                return {"error": "linked_consumers_unknown",
                        "unknown": unknown_consumers,
                        "hint": "Register the API consumer first via apihub_register_consumer."}

        # All gates passed — proceed with existing PR creation logic
        # ...existing body that creates the PR record in self.stores.pull_requests...

        from ...crdt_types import Timestamp
        ts = Timestamp.now(author or "codehub")
        pr_id = f"pr_{ts.wall_time:.0f}_{branch.replace('/', '_')}"
        head = None
        try:
            head = self.git.current_head(self.repo_root / "workspaces" / branch.split("/")[-1])
        except Exception:
            head = None
        pr = {
            "id": pr_id,
            "branch": branch, "source_branch": branch,
            "target_branch": target,
            "title": title, "body": body,
            "author": author,
            "reviewers": list(reviewers),
            "linked_tasks": list(linked_tasks),
            "linked_apis": list(linked_apis),
            "linked_pages": list(linked_pages),
            "linked_consumers": list(linked_consumers),
            "status": "open",
            "merge_state": "blocked",
            "head": head,
            "created_at": ts.wall_time,
            "_updated_by": author,
            "_updated_at": ts.wall_time,
        }
        self.stores.pull_requests.update(lambda m: m.set(pr_id, pr, ts))
        self._emit("pr_opened", pr, recipients=list(reviewers), priority="normal")
        return pr
```

Note: the actual current body of `open_pull_request` may differ. **Preserve any existing functionality** (status field defaults, real-git head detection, event emission) and only add the gate logic at the top + the new linked_pages / linked_consumers fields.

- [ ] **Step 4:** Run, confirm all 7 tests PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_open_pr_gates -v 2>&1 | tail -12
```

- [ ] **Step 5:** Confirm no regression in existing codehub tests

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_architecture agent.tests.test_codehub_inline_comments agent.tests.test_codehub_git_ops 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

If existing tests break (e.g., they call `open_pull_request` without `linked_tasks`), fix those tests to supply a task. Don't loosen the gate.

- [ ] **Step 6:** Commit

```bash
git add agent/tests/test_codehub_open_pr_gates.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py
git commit -m "CodeHub.open_pull_request: 7 gates (tasks/reviewers/apis/pages/consumers)"
```

---

## Phase C — Strict Approval

### Task 6: TDD `_is_pr_approved` requires ALL reviewers approve

**Files:**
- Create: `agent/tests/test_codehub_strict_approval.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1:** Write tests

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class StrictApprovalTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            title="x", author="backend",
        )
        return hubs, ch, pr

    def test_pr_not_approved_until_all_reviewers_approve(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            # One of two reviewers approves — still not ready
            ch.submit_review(pr["id"], "frontend", "approve")
            after = ch.stores.pull_requests.get().get(pr["id"])
            self.assertEqual(after.get("merge_state"), "blocked")

    def test_pr_ready_only_after_all_approve(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            ch.submit_review(pr["id"], "frontend", "approve")
            ch.submit_review(pr["id"], "orchestrator", "approve")
            after = ch.stores.pull_requests.get().get(pr["id"])
            self.assertEqual(after.get("merge_state"), "ready")

    def test_request_changes_overrides_other_approvals(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup(td)
            ch.submit_review(pr["id"], "frontend", "approve")
            ch.submit_review(pr["id"], "orchestrator", "request_changes")
            after = ch.stores.pull_requests.get().get(pr["id"])
            self.assertEqual(after.get("merge_state"), "changes_requested")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm at least one of the 3 fails (current `_is_pr_approved` may be permissive)

- [ ] **Step 3:** Rewrite `_is_pr_approved` in service.py

```python
    def _is_pr_approved(self, pr: dict, extra_review: dict = None) -> bool:
        reviews = [r for r in self.stores.code_reviews.value().values()
                   if r.get("pr_id") == pr.get("id")]
        if extra_review:
            reviews.append(extra_review)
        approved = {r.get("reviewer") for r in reviews if r.get("state") == "approve"}
        required = set(pr.get("reviewers") or [])
        # Strict: ALL required reviewers must approve, not just one
        return required.issubset(approved)
```

- [ ] **Step 4:** Run, confirm 3 PASS

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_codehub_strict_approval.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
git commit -m "CodeHub: _is_pr_approved requires ALL reviewers approve, not just one"
```

---

## Phase D — `codehub.suggest_reviewers`

### Task 7: TDD weighted reviewer picker

**Files:**
- Create: `agent/tests/test_codehub_suggest_reviewers.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1:** Write tests

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class SuggestReviewersTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        return hubs, ch

    def test_suggest_reviewers_always_includes_orchestrator(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=[], linked_tasks=[], author="backend",
            )
            agents = [s["agent"] for s in result]
            self.assertIn("orchestrator", agents)

    def test_suggest_reviewers_excludes_author(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=[], linked_tasks=[], author="orchestrator",
            )
            agents = [s["agent"] for s in result]
            self.assertNotIn("orchestrator", agents)

    def test_suggest_reviewers_weights_api_consumers(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            hubs.apihub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="design")
            hubs.apihub.register_consumer("GET /api/feed",
                                          "src/Feed.jsx", "frontend")
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=["GET /api/feed"],
                linked_tasks=[],
                author="backend",
            )
            # frontend should be high-scored as consumer
            agents = [s["agent"] for s in result]
            self.assertIn("frontend", agents)
            # orchestrator is always first (mandatory)
            self.assertEqual(agents[0], "orchestrator")
            self.assertEqual(result[0]["score"], 100.0)

    def test_suggest_reviewers_reasons_explained(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            hubs.apihub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="design")
            hubs.apihub.register_consumer("GET /api/feed",
                                          "src/Feed.jsx", "frontend")
            result = ch.suggest_reviewers(
                branch="agent/backend",
                linked_apis=["GET /api/feed"],
                linked_tasks=[],
                author="backend",
            )
            frontend_entry = next(s for s in result if s["agent"] == "frontend")
            self.assertTrue(any("consumer of GET /api/feed" in r
                                for r in frontend_entry["reasons"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Implement `suggest_reviewers` in service.py

```python
    def suggest_reviewers(self, branch: str, linked_apis: list = None,
                          linked_tasks: list = None, author: str = "",
                          k: int = 3) -> list:
        """Weighted reviewer picker. Returns top-k {agent, score, reasons}."""
        candidates: dict = {}
        reasons_map: dict = {}

        def add(agent: str, weight: float, reason: str):
            if not agent or agent == author:
                return
            candidates[agent] = candidates.get(agent, 0.0) + weight
            reasons_map.setdefault(agent, []).append(reason)

        # Signal 1: API consumers (weight 3.0 each)
        if linked_apis and getattr(self, "_apihub", None) is not None:
            for endpoint_id in linked_apis:
                for c in self._apihub.get_consumers(endpoint_id):
                    add(c.get("agent"), 3.0, f"consumer of {endpoint_id}")

        # Signal 2: recent committer trailer (weight 1.0 each)
        try:
            entries = self.git.log_for_branch("main", max_count=20)
            for entry in entries:
                subj = entry.get("subject", "")
                # [agent: name] trailer convention
                if "[agent:" in subj:
                    start = subj.index("[agent:") + len("[agent:")
                    end = subj.index("]", start)
                    trailer = subj[start:end].strip()
                    add(trailer, 1.0, f"recent committer on main")
        except Exception:
            pass

        # Signal 3: plan attendees (weight 0.5)
        if linked_tasks and getattr(self, "_workhub", None) is not None:
            for task_id in linked_tasks:
                task = self._workhub.get_task(task_id)
                if not task or not task.get("plan_id"):
                    continue
                for att in (self._workhub.snapshot().get("attendees", {}) or {}).values():
                    add(att.get("agent_id") or att.get("agent"), 0.5,
                        f"attendee of plan related to {task_id}")

        # Mandatory: orchestrator (unless author IS orchestrator)
        if author != "orchestrator":
            candidates["orchestrator"] = candidates.get("orchestrator", 0.0) + 100.0
            reasons_map.setdefault("orchestrator", []).append("mandatory lead reviewer")

        ranked = sorted(candidates.items(), key=lambda x: -x[1])
        return [{"agent": a, "score": s, "reasons": reasons_map.get(a, [])}
                for a, s in ranked[:k]]
```

- [ ] **Step 4:** Run, confirm 4 PASS.

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_codehub_suggest_reviewers.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
git commit -m "Add CodeHub.suggest_reviewers (weighted picker, orchestrator mandatory)"
```

---

## Phase E — L2 Merge-Time Verifier Gate

### Task 8: TDD `_run_premerge_verifier_gate`

**Files:**
- Create: `agent/tests/test_codehub_premerge_gate.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1:** Write tests

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class PreMergeGateTests(unittest.TestCase):
    def _setup_pr(self, td, endpoint_test_status="passed"):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        hubs.apihub.register_endpoint("GET", "/api/feed", schema={},
                                       provider="backend", agent="design")
        if endpoint_test_status is not None:
            hubs.apihub.record_api_test(
                "GET /api/feed",
                {"passed": endpoint_test_status == "passed"},
                evidence={"trace": "ok" if endpoint_test_status == "passed" else "fail"},
                agent="verifier",
            )
        task = hubs.workhub.create_task(title="x", assignee="backend",
                                        agent="orchestrator")
        # Complete the task so it satisfies premerge
        hubs.workhub.claim_task(task["id"], "backend")
        hubs.workhub.complete_task(task["id"], "backend", result={"ok": True})
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            linked_apis=["GET /api/feed"],
            title="x", author="backend",
        )
        # Approve so merge gate isn't blocked at reviewer stage
        ch.submit_review(pr["id"], "frontend", "approve")
        ch.submit_review(pr["id"], "orchestrator", "approve")
        return hubs, ch, pr

    def test_premerge_gate_passes_when_contract_test_passed_and_task_complete(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="passed")
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get().get(pr["id"]))
            self.assertTrue(result["passed"])
            self.assertEqual(result["failed_checks"], [])

    def test_premerge_gate_fails_on_failed_contract_test(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get().get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("contract_test_failed", kinds)

    def test_premerge_gate_fails_on_missing_contract_test(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status=None)
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get().get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("contract_test_missing", kinds)

    def test_premerge_gate_fails_on_incomplete_linked_task(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.register_agent_repo("backend", str(Path(td) / "backend"))
            ch.ensure_branch("backend", "agent/backend")
            hubs.apihub.register_endpoint("GET", "/api/feed", schema={},
                                          provider="backend", agent="design")
            hubs.apihub.record_api_test("GET /api/feed", {"passed": True},
                                        evidence={}, agent="verifier")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            # Task left in 'pending' — NOT completed
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_apis=["GET /api/feed"],
                title="x", author="backend",
            )
            ch.submit_review(pr["id"], "frontend", "approve")
            ch.submit_review(pr["id"], "orchestrator", "approve")
            result = ch._run_premerge_verifier_gate(
                ch.stores.pull_requests.get().get(pr["id"]))
            self.assertFalse(result["passed"])
            kinds = [c["kind"] for c in result["failed_checks"]]
            self.assertIn("linked_task_incomplete", kinds)

    def test_merge_pull_request_returns_error_when_premerge_gate_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            result = ch.merge_pull_request(pr["id"], agent="orchestrator")
            self.assertEqual(result.get("error"), "premerge_gate_failed")

    def test_merge_pull_request_creates_workhub_fix_task_on_gate_failure(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_pr(td, endpoint_test_status="failed")
            ch.merge_pull_request(pr["id"], agent="orchestrator")
            # A new WorkHub task should be assigned to the PR author
            tasks = list(hubs.workhub.snapshot()["tasks"].values())
            fix_tasks = [
                t for t in tasks
                if t.get("metadata", {}).get("source") == "codehub_premerge_gate"
                and t.get("assignee") == "backend"
            ]
            self.assertGreaterEqual(len(fix_tasks), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Implement `_run_premerge_verifier_gate` + integrate into `merge_pull_request`

Add the helper method to service.py:

```python
    def _run_premerge_verifier_gate(self, pr: dict) -> dict:
        failed: list = []
        apihub = getattr(self, "_apihub", None)
        workhub = getattr(self, "_workhub", None)

        # Check 1: every linked_api must have a recent passing contract test
        if apihub is not None:
            for endpoint_id in pr.get("linked_apis") or []:
                tests = apihub.get_contract_test_results(endpoint_id)
                if not tests:
                    failed.append({"kind": "contract_test_missing",
                                   "endpoint": endpoint_id})
                    continue
                latest = max(tests, key=lambda t: t.get("created_at", 0))
                if not latest.get("result", {}).get("passed"):
                    failed.append({"kind": "contract_test_failed",
                                   "endpoint": endpoint_id,
                                   "evidence": latest.get("evidence")})

        # Check 2: every linked_task must be completed
        if workhub is not None:
            for task_id in pr.get("linked_tasks") or []:
                task = workhub.get_task(task_id)
                if not task:
                    failed.append({"kind": "linked_task_missing",
                                   "task_id": task_id})
                elif task.get("status") != "completed":
                    failed.append({"kind": "linked_task_incomplete",
                                   "task_id": task_id,
                                   "status": task.get("status")})

        return {"passed": not failed, "failed_checks": failed}
```

Then modify `merge_pull_request` to call the gate before any merge:

```python
    def merge_pull_request(self, pr_id: str, strategy: str = "squash",
                           agent: str = "codehub") -> dict:
        pr = self.stores.pull_requests.get().get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        if pr.get("merge_state") != "ready":
            return {"error": "PR not ready", "merge_state": pr.get("merge_state")}

        # L2 verifier gate
        gate = self._run_premerge_verifier_gate(pr)
        if not gate["passed"]:
            from ...crdt_types import Timestamp
            ts = Timestamp.now(agent)
            updated = dict(pr)
            updated["status"] = "premerge_failed"
            updated["premerge_failures"] = gate["failed_checks"]
            updated["_updated_by"] = agent
            updated["_updated_at"] = ts.wall_time
            self.stores.pull_requests.update(lambda m: m.set(pr_id, updated, ts))
            # Auto-create fix task in WorkHub for PR author
            workhub = getattr(self, "_workhub", None)
            if workhub is not None:
                try:
                    workhub.create_task(
                        title=f"Pre-merge verifier failed for PR {pr_id}",
                        description=f"Failures: {gate['failed_checks']}",
                        assignee=pr.get("author"),
                        agent=agent,
                        source="codehub_premerge_gate",
                        linked_pr=pr_id,
                        priority="urgent",
                    )
                except Exception:
                    pass
            self._emit("premerge_failed", {"pr_id": pr_id,
                                            "failed_checks": gate["failed_checks"]},
                       recipients=[pr.get("author")] if pr.get("author") else [],
                       priority="urgent")
            return {"error": "premerge_gate_failed",
                    "failed_checks": gate["failed_checks"]}

        # Gate passed — proceed with existing merge logic
        # ...existing merge body unchanged below...
```

(Preserve any existing post-gate body: real git merge, status updates, event emission.)

- [ ] **Step 4:** Run, confirm all 6 tests PASS.

- [ ] **Step 5:** Confirm no regression

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_architecture agent.tests.test_codehub_merge 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

If `test_codehub_merge` fails because old tests don't satisfy the new gate, update them to register endpoints + complete linked_tasks.

- [ ] **Step 6:** Commit

```bash
git add agent/tests/test_codehub_premerge_gate.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
git commit -m "CodeHub L2 merge-time verifier gate (contract tests + task completion)"
```

---

## Phase F — Force-Merge Orchestrator Bypass

### Task 9: TDD `force_merge_pull_request`

**Files:**
- Create: `agent/tests/test_codehub_force_merge.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1:** Write tests

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class ForceMergeTests(unittest.TestCase):
    def _setup_failing_pr(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        hubs.apihub.register_endpoint("GET", "/api/feed", schema={},
                                       provider="backend", agent="design")
        hubs.apihub.record_api_test("GET /api/feed", {"passed": False},
                                     evidence={"trace": "fail"}, agent="verifier")
        task = hubs.workhub.create_task(title="x", assignee="backend",
                                        agent="orchestrator")
        hubs.workhub.claim_task(task["id"], "backend")
        hubs.workhub.complete_task(task["id"], "backend", result={"ok": True})
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            linked_apis=["GET /api/feed"],
            title="x", author="backend",
        )
        ch.submit_review(pr["id"], "frontend", "approve")
        ch.submit_review(pr["id"], "orchestrator", "approve")
        return hubs, ch, pr

    def test_force_merge_rejected_for_non_orchestrator(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"], reason="long enough reason xxxxxxx", agent="backend")
            self.assertEqual(result.get("error"), "force_merge_orchestrator_only")

    def test_force_merge_rejected_for_short_reason(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"], reason="short", agent="orchestrator")
            self.assertEqual(result.get("error"), "force_merge_reason_too_short")

    def test_force_merge_orchestrator_with_valid_reason_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"],
                reason="Emergency hotfix: contract tests broken in CI, manually verified locally",
                agent="orchestrator",
            )
            self.assertNotIn("error", result)
            updated = ch.stores.pull_requests.get().get(pr["id"])
            self.assertTrue(updated.get("force_merged"))
            self.assertEqual(updated.get("force_by"), "orchestrator")

    def test_force_merge_emits_urgent_eventhub_event(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_failing_pr(td)
            ch.force_merge_pull_request(
                pr["id"],
                reason="Emergency hotfix needed for production outage debugging",
                agent="orchestrator",
            )
            events = list(hubs.eventhub.snapshot()["events"].values())
            force_events = [e for e in events if e.get("event_type") == "pr_force_merged"]
            self.assertGreaterEqual(len(force_events), 1)
            self.assertEqual(force_events[-1]["priority"], "urgent")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Implement `force_merge_pull_request` in service.py

```python
    def force_merge_pull_request(self, pr_id: str, reason: str, agent: str) -> dict:
        if agent != "orchestrator":
            return {"error": "force_merge_orchestrator_only",
                    "hint": "Only orchestrator can bypass the verifier gate."}
        if not reason or len(reason) < 20:
            return {"error": "force_merge_reason_too_short",
                    "min_length": 20,
                    "hint": "Provide a substantive reason (≥ 20 chars) for audit."}
        pr = self.stores.pull_requests.get().get(pr_id)
        if not pr:
            return {"error": f"PR not found: {pr_id}"}
        from ...crdt_types import Timestamp
        ts = Timestamp.now(agent)
        forced = dict(pr)
        forced["merge_state"] = "ready"
        forced["force_merged"] = True
        forced["force_reason"] = reason
        forced["force_by"] = agent
        forced["forced_at"] = ts.wall_time
        forced["_updated_by"] = agent
        forced["_updated_at"] = ts.wall_time
        self.stores.pull_requests.update(lambda m: m.set(pr_id, forced, ts))
        self._emit("pr_force_merged",
                   {"pr_id": pr_id, "reason": reason, "agent": agent},
                   recipients=["orchestrator"], priority="urgent")
        return self.merge_pull_request(pr_id, strategy="squash", agent=agent)
```

- [ ] **Step 4:** Run, confirm 4 PASS.

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_codehub_force_merge.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
git commit -m "CodeHub.force_merge_pull_request: orchestrator-only bypass with audit"
```

---

## Phase G — New LLM Tools

### Task 10: Add 2 new tool classes + extend `codehub_open_pr` schema

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`

- [ ] **Step 1:** Locate existing CodeHub tools

```bash
grep -nE "class CodeHub[A-Z].*Tool\b" agent/env_generator/llm_generator/tools/hub_tools.py
```

- [ ] **Step 2:** Extend `CodeHubOpenPRTool` to expose `linked_pages` + `linked_consumers`

Find the existing `CodeHubOpenPRTool`. Replace its PARAMETERS to include the two new fields:

```python
class CodeHubOpenPRTool(HubTool):
    NAME = "codehub_open_pr"
    DESCRIPTION = (
        "Open a CodeHub pull request. linked_tasks REQUIRED non-empty. "
        "linked_apis / linked_pages / linked_consumers optional but every entry "
        "must resolve to an existing hub record. ≥ 2 reviewers required (orchestrator auto-injected)."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string"},
            "target": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "string"}},
            "linked_tasks": {"type": "array", "items": {"type": "string"}},
            "linked_apis": {"type": "array", "items": {"type": "string"}},
            "linked_pages": {"type": "array", "items": {"type": "string"}},
            "linked_consumers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["branch", "linked_tasks"],
    }

    async def _run(self, branch: str, linked_tasks: list, target: str = "main",
                   title: str = "", body: str = "",
                   reviewers: list = None,
                   linked_apis: list = None,
                   linked_pages: list = None,
                   linked_consumers: list = None) -> ToolResult:
        result = self._hubs.codehub.open_pull_request(
            branch=branch, target=target,
            reviewers=reviewers or [],
            linked_tasks=linked_tasks,
            linked_apis=linked_apis or [],
            linked_pages=linked_pages or [],
            linked_consumers=linked_consumers or [],
            title=title, body=body, author=self._agent_id,
        )
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"], data=result)
        return ToolResult(data=result)
```

- [ ] **Step 3:** Add 2 new tool classes after `CodeHubReviewPRTool` (or near other CodeHub tools)

```python
class CodeHubSuggestReviewersTool(HubTool):
    NAME = "codehub_suggest_reviewers"
    DESCRIPTION = (
        "Suggest reviewers for a PR using weighted signals (API consumers, "
        "recent committers, plan attendees). Orchestrator always included."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string"},
            "linked_apis": {"type": "array", "items": {"type": "string"}},
            "linked_tasks": {"type": "array", "items": {"type": "string"}},
            "k": {"type": "integer", "description": "Max suggestions to return"},
        },
        "required": ["branch"],
    }

    async def _run(self, branch: str, linked_apis: list = None,
                   linked_tasks: list = None, k: int = 3) -> ToolResult:
        return ToolResult(data={
            "suggestions": self._hubs.codehub.suggest_reviewers(
                branch=branch,
                linked_apis=linked_apis or [],
                linked_tasks=linked_tasks or [],
                author=self._agent_id,
                k=k,
            )
        })


class CodeHubForceMergeTool(HubTool):
    NAME = "codehub_force_merge"
    DESCRIPTION = (
        "Emergency bypass of the merge verifier gate. ORCHESTRATOR ONLY. "
        "Requires a substantive reason (≥ 20 chars) for audit. Use sparingly."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "pr_id": {"type": "string"},
            "reason": {"type": "string", "description": "≥ 20 chars audit reason"},
        },
        "required": ["pr_id", "reason"],
    }

    async def _run(self, pr_id: str, reason: str) -> ToolResult:
        result = self._hubs.codehub.force_merge_pull_request(
            pr_id, reason=reason, agent=self._agent_id)
        if "error" in result:
            return ToolResult(success=False, error_message=result["error"], data=result)
        return ToolResult(data=result)
```

Add both to `HUB_TOOL_CLASSES`.

- [ ] **Step 4:** Widen `_bundle_codehub_tools.include_names` in `tool_bundles.py`

Find the bundle helper. Add both new tool names to `include_names`:

```python
            "codehub_suggest_reviewers",
            "codehub_force_merge",
```

- [ ] **Step 5:** Deny `codehub_force_merge` for non-orchestrator profiles

Open `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`. For every profile that is NOT `orchestrator` (likely: `design`, `database`, `backend`, `frontend`, `verifier`, `knowledge`, `worker`, `analysis_worker`, `review_worker`), find its `deny_tools:` list (or add one if absent) and append `codehub_force_merge`.

Example for `backend`:
```yaml
  backend:
    # ...existing config...
    deny_tools:
      - codehub_force_merge   # orchestrator-only emergency tool
      # ...other existing deny entries...
```

- [ ] **Step 6:** Run all tool tests

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_suggest_reviewers agent.tests.test_codehub_force_merge agent.tests.test_codehub_open_pr_gates agent.tests.test_apihub_tools agent.tests.test_workhub_collab_tools 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 7:** Commit

```bash
git add agent/env_generator/llm_generator/tools/hub_tools.py \
        agent/env_generator/llm_generator/multi_agent/tool_bundles.py \
        agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml
git commit -m "Add CodeHub suggest_reviewers + force_merge LLM tools (orchestrator-only deny)"
```

---

## Phase H — Ship

### Task 11: Full discover + migration log + push

- [ ] **Step 1:** Run discover

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all OK. If existing tests broke due to new gates (e.g., a test calls `open_pull_request` without `linked_tasks` or with an unknown endpoint), fix the test to satisfy the gates. **Do not loosen the gates.**

- [ ] **Step 2:** Confirm zero Claude trailers

```bash
git log --pretty=%B red-env-gen/haibotong-0521-pipeline-web-tools..HEAD | grep -c "Co-Authored-By:"
```

Expected: 0.

- [ ] **Step 3:** Write migration log

Create `docs/superpowers/migration-logs/08-schema-gates-and-registration-discipline.md`:

```markdown
# 08 — Schema 3-Layer + Registration Discipline + Reviewer Gate

**Branch:** haibotong-cutover-7-schema-gates
**Predecessor:** haibotong-cutover-6-tool-surface-fill (merged into parent)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §6-8

## Summary

Locks down PR/merge/registration so frontend ↔ backend ↔ database stay aligned
at code level. Five enforcement layers:

1. APIHub L1 write-time gate — register_consumer / register_table_consumer
   reject unknown endpoint, deprecated endpoint, schema mismatch
2. Registration manifest — open_pr requires linked_tasks non-empty; every
   linked_api / linked_page / linked_consumer must resolve to a hub record
3. 2-reviewer gate — open_pr requires ≥ 2 distinct reviewers (excl. author);
   orchestrator auto-injected unless author IS orchestrator
4. Strict approval — _is_pr_approved requires ALL reviewers to approve
5. L2 merge verifier gate — contract test pass + linked_task completion;
   failure auto-creates WorkHub fix task assigned to PR author
6. force_merge bypass — orchestrator-only, ≥ 20-char reason, audit via
   urgent EventHub event

## Files modified
- runtime/apihub.py (L1 write-time gate + _schema_subset_check helper)
- runtime/hubs/codehub/service.py (7-gate open_pr + strict approval +
  suggest_reviewers + premerge gate + force_merge + attach_apihub)
- runtime/hub_registry.py (attach_apihub wiring)
- tools/hub_tools.py (CodeHubOpenPRTool params expanded;
  CodeHubSuggestReviewersTool + CodeHubForceMergeTool added)
- multi_agent/tool_bundles.py (widen codehub bundle)
- agents/agents_config.yaml (deny codehub_force_merge for non-orchestrator)

## Test additions
- test_apihub_l1_write_time_gate.py (15 tests: _schema_subset_check + consumer/table_consumer gates)
- test_codehub_open_pr_gates.py (7 tests)
- test_codehub_strict_approval.py (3 tests)
- test_codehub_suggest_reviewers.py (4 tests)
- test_codehub_premerge_gate.py (6 tests)
- test_codehub_force_merge.py (4 tests)

## Commits

<paste output of `git log --oneline red-env-gen/haibotong-0521-pipeline-web-tools..HEAD`>

## Regression evidence

<paste last 5 lines of run_regressions.py>

## Next

Cutover 8 — step-pipeline integration (hub_pulse + hub_commit_gate stages,
prompt updates).
```

- [ ] **Step 4:** Commit + push

```bash
git add docs/superpowers/migration-logs/08-schema-gates-and-registration-discipline.md
git commit -m "Add Cutover 7 migration log"
git push red-env-gen haibotong-cutover-7-schema-gates -u 2>&1 | tail -3
```

- [ ] **Step 5:** Print PR compare URL

```bash
echo "PR compare: https://github.com/Virtue-AI/red-env-gen/compare/haibotong-0521-pipeline-web-tools...haibotong-cutover-7-schema-gates"
```

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer on any commit.**
- Use `dt` conda env: `/home/haibotong/miniconda3/envs/dt/bin/python`.
- Branch from `red-env-gen/haibotong-0521-pipeline-web-tools`.
- Each task ≈ 1 commit; 11 tasks → 11 commits.

## Recovery Notes

- Tests that previously relied on permissive PR opening will break; **fix them to satisfy the new gates** rather than loosening the gates.
- If `_run_premerge_verifier_gate` introduces false positives (e.g., a task that the test left in `pending` for legitimate reasons), the right fix is to complete the task in the test setup, not to skip the gate.
- `force_merge` is a deliberate emergency lever. If the test environment can't reach the verifier gate's positive path (no `_apihub` attached), force_merge still works — but tests should prefer happy-path coverage to keep the gate honest.

## Out of Scope (deferred to Cutover 8)

- `hub_pulse` step-start stage
- `hub_commit_gate` step-end stage
- Prompt template updates introducing pulse/gate sections
- AST-based file-scan detection (right now agents declare manifest themselves via `linked_*` params)
