# Migration Log 06 — Final CRDT Purge (Cutover 5)

**Branch**: `haibotong-cutover-5-final-purge`  
**Date**: 2026-05-22  
**Phases**: A–F (6 phases, 15 commits)

---

## Summary

Cutover 5 completes the removal of the CRDT runtime from the multi-agent codebase.
CRDTWorkspace is replaced by HubRegistry; crdt_tools.py, crdt_metrics_tools.py,
crdt_tool_base.py are deleted; token/perf/retry tracking moves to SystemMetrics.

---

## Phase A — SystemMetrics + tool bundle

- Created `tools/system_tools.py`: `SystemMetrics` class (JSON stores in `shared/crdt/`)
  with `record_token_usage`, `get_token_usage`, `get_token_budget_status`,
  `get_performance_stats`, `get_retry_stats` plus 5 LLM tool wrappers.
- Wired `"system_tools"` bundle in `tool_bundles.py`.
- Added `self.metrics = SystemMetrics(output_dir)` to Orchestrator.
- 9 new tests in `tests/test_system_tools.py`.

**Commits**: `4ee9a966`, `e948128a`, `ccebcad3`

---

## Phase B — Token/perf/retry callers migrated

- Removed `record_token_usage`, `get_token_usage`, `get_token_budget_status`,
  `TOKEN_PRICING`, `_token_usage` store from `crdt.py`.
- `GetTokenUsageTool` (in crdt_metrics_tools.py) now reads from `SystemMetrics`.

**Commit**: `e74e2325`

---

## Phase C — Health/dashboard/progress purge

- Removed `increment_progress`, `get_progress`, `get_progress_dashboard`,
  `check_agent_health`, `get_stuck_agents`, `get_summary`, `_progress` G-Counter
  from `crdt.py`.

**Commit**: `d302805d`

---

## Phase D — Dead method purge

- Removed `publish_task`, `claim_task`, `get_pending_tasks`, `_tasks` store.
- Removed `update_artifact`, `get_artifacts`, `_artifacts` store.
- Removed `get_api_usage_records`, `get_build_records`, `get_contracts`.
- Removed `get_build_status`, `get_verification_checklist`.

**Commit**: `dfe7e065`

---

## Phase E — HubRegistry replaces CRDTWorkspace

### Task 12 — HubRegistry created
- `runtime/hub_registry.py`: thin aggregator exposing `.apihub`, `.codehub`,
  `.eventhub`, `.workhub` plus `.hubs` self-reference property for legacy chains.
- 10 tests in `tests/test_hub_registry.py`.

### Task 13 — Orchestrator switched
- Orchestrator now creates `HubRegistry`; keeps `self.crdt_workspace = self.hubs`
  transitional alias.
- Added `_get_validation_checks`, `_get_validation_results`, `_get_validation_summary`
  helpers replacing `CRDTValidationMixin` calls.

### Task 14 — Agents decoupled from CRDT observer
- `tooling.py`: `set_crdt_workspace()` → `set_hubs()`; compat shim kept;
  crdt_tools dynamic registration block removed.
- `base.py`: `_crdt_observer` → `_hubs`; run_loop observation guard updated.
- `agent_spawn_service.py`: calls `set_hubs(orchestrator.hubs)` directly.
- `sync.py`: `_collect_crdt_change_summary` stubbed (no-op); EventHub catchup
  uses `_hubs` attribute.
- `communication_tools.py`, `hub_tools.py`: prefer `_hubs` over `_crdt_workspace`.

### Task 15 — crdt.py collapsed; hub_workspace.py and crdt_observer.py deleted
- `crdt.py` → 3-line shim re-exporting `CRDTWorkspace` from `hub_registry.py`.
- `hub_registry.py`: added `CRDTWorkspace` compat class (HubRegistry +
  CRDTValidationMixin + all required stores) for import-compat with tests.
- `crdt_observer_stub.py`: minimal stubs for `WorkspaceObserver`, `ObservationResult`,
  `CRDTMetrics`, `enhance_with_crdt`.
- Deleted `crdt_observer.py`, `hub_workspace.py`.

**Commits**: `afa94e71`, `e9ed2a02`, `32fa3192`, `a91c06dc`

---

## Phase F — Tool cleanup + config

- Deleted `tools/crdt_tools.py`, `tools/crdt_metrics_tools.py`, `tools/crdt_tool_base.py`.
- `tools/__init__.py`: removed crdt tool imports.
- `hub_tools.py`: inlined `finalize_legacy_crdt_tools` helper; imports `ToolResult`
  from `_base` directly.
- `agents_config.yaml`: removed `"crdt"` from all `tool_categories` lists; updated
  coordination comment.
- `tools.py`: updated stale comment.

**Commit**: `c0b8d837`

---

## E2E Smoke Test Results

All 10 assertions green:
1. `shared/crdt/` directory created by HubRegistry
2. All four hubs (apihub, codehub, eventhub, workhub) accessible
3. `HubRegistry.hubs` self-reference property works
4. APIHub endpoint round-trip
5. EventHub agent status round-trip
6. WorkHub UI page round-trip
7. `get_versions()` returns dict
8. `snapshot()` has all hub keys
9. `CRDTWorkspace` compat shim — `record_validation_result` / `get_validation_results`
10. `SystemMetrics` — `record_token_usage` / `get_token_usage`

---

## Test Counts

- `test_hub_registry.py`: 10 tests
- `test_system_tools.py`: 9 tests
- Regression suite: 7 tests (all pass)
- Hub architecture suite: 125 tests (all pass)

---

## Invariants Preserved

- `shared/crdt/` directory convention kept for JSON persistence
- All `CRDTWorkspace` imports continue to work via shim
- `crdt_store.py`, `crdt_types.py`, `crdt_validation.py` kept intact
- Stage names `crdt_changes` / `crdt_sync` kept in pipeline (now no-op)
- No `Co-Authored-By: Claude` trailer in any commit

---

## Hard-cut finalization (post-main)

**Date**: 2026-05-22  
**Commits**: `8f466908`, `59052d3d`, `9a888240`

Converted the soft-cut shim to a true hard-cut so the audit acceptance
criteria pass.

### Changes

1. **Renamed `CRDTWorkspace` usages in production source** — all
   `_crdt_workspace` compat aliases, `set_crdt_workspace()` calls, fallback
   `getattr(..., "_crdt_workspace", None)` chains, and `crdt_workspace`
   attribute reads in `.py`, `.yaml`, and docs rewritten to use `_hubs`
   (HubRegistry) directly. Test files updated to import from
   `hub_registry.HubRegistry` instead of the deleted shim.

2. **Rewrote six v2 `.j2` agent prompts** — `CRDTWorkspace` replaced
   with `HubRegistry`, `APIHub`, `WorkHub`, `CodeHub`, `EventHub`
   throughout. All Jinja syntax and behavioural instructions preserved.

3. **Deleted `crdt.py` shim + `CRDTWorkspace` compat class** —
   Removed the 13-line `crdt.py` re-export and the
   `CRDTWorkspaceMeta` / `_make_crdt_workspace_class()` machinery from
   `hub_registry.py`. Added `get_tables()`, `update_table()`,
   `record_validation_result()`, `get_validation_results()`,
   `get_validation_summary()`, `create_dev_task_from_validation_failure()`,
   and `handle_validation_failure()` directly on `HubRegistry` so that
   tests exercising `CRDTValidationMixin` continue to pass.

### Final acceptance grep

```
git grep -lE "CRDTWorkspace|crdt_workspace|from .*runtime\.crdt\b" \
  -- ":!docs/" ":!agent/tests/" ":!**/.agent_logs/**" ":!**/*.jsonl"
```

**Result: empty (zero matches).**

### Test counts

- Regression suite (`run_regressions.py`): 7 tests OK
- Hub suite (6 test modules): 105 tests OK
- E2E smoke: worktree created, 3 live bridge events received
