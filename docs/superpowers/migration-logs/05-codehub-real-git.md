# Migration Log 05 — Cutover 4: CodeHub Real Git

**Branch:** `haibotong-cutover-4-codehub-real-git`
**Date:** 2026-05-22
**Author:** haibotong@virtueai.com

---

## 1. Context

Cutover 4 replaced the CRDT-based file-coordination and legacy tracking stores with real git-worktree operations via CodeHub, and moved validation/build/artifact tracking to CodeHub.checks and APIHub.register_table.

---

## 2. Phase Summary

### Phase A (Tasks 1–5): Git foundations
- Added `GitOps` subprocess wrapper for CodeHub
- `CodeHub.ensure_repo`, `register_agent_worktree`, `cleanup_worktree` (real git)
- `CodeHub.commit` with real git commit
- `CodeHub.open_pull_request` validates against real git branch state
- Register agent worktree via CodeHub during spawn
- Added `codehub_commit` LLM tool

### Phase B (Tasks 6–9): Read / list / diff / conflict
- `CodeHub.get_diff` with truncation
- `CodeHub.get_blob`, `get_file_content`
- `CodeHub.list_prs` filter API
- `CodeHub.list_checks`, `get_check_summary`
- `CodeHub.resolve_conflict`
- `CodeHub.merge_pull_request` (real git merge + conflict task)
- 6 new CodeHub LLM tools (diff/blob/list/conflict)

### Phase C (Tasks 10–12): Validation migration (dual-write)
- Added CodeHub validation migration parity tests
- Switched validation callers from `CRDTWorkspace.record_validation_result` to `CodeHub.record_check` + WorkHub

### Phase D (Tasks 13–14): Build / artifact / table migration (dual-write)
- Switched build / verification callers to `CodeHub.record_check`
- Migrated artifact tracking to `CodeHub.checks` (kind=artifact)
- Migrated `update_table` family to `APIHub.register_table`

### Phase E (Tasks 15–19): Remaining hub migrations (dual-write)
- EventHub agent_status, WorkHub project page, WorkHub knowledge blocks, WorkHub ui_pages, EventHub escalate

### Phase F (Tasks 20–25): Hard-cut — delete legacy files + CRDT methods

---

## 3. Files Deleted

| File | Lines | Replaced By |
|------|-------|-------------|
| `multi_agent/runtime/file_coordination.py` | 787 | `CodeHub.register_agent_worktree` + git worktree |
| `multi_agent/runtime/crdt_projection.py` | ~260 | `apihub.register_endpoint`, `apihub.register_table` directly |
| `tools/crdt_file_coordination_tools.py` | ~340 | Dropped (agents edit own worktree, commit via `codehub_commit`) |
| `tools/crdt_validation_tools.py` | ~600 | `codehub_record_check` LLM tool |

Note: `crdt_observer.py` was retained (used by agents for hub change polling via `crdt_observer.poll()`).

---

## 4. CRDT Methods Removed (~28 methods)

**File-coordination (from crdt.py):**
`record_file_read`, `record_file_write`, `sync_file_change`, `get_file_state`, `get_files`, `get_file_history`, `record_projection_error`, `clear_projection_error`, `get_projection_errors`, `publish_file_region`, `claim_file_region`, `complete_file_region`, `get_file_region`, `get_file_regions`, `reserve_file_anchor`, `record_file_anchor_op`, `get_file_anchor`, `get_file_anchors`, `get_file_anchor_ops`, `sync_text_document_snapshot`, `get_text_document_snapshots`

**Build/state (from crdt.py):**
`record_build_attempt`, `get_build_history`, `add_api_contract`, `get_api_contract`, `list_api_contracts`, `get_state_hash`, `wait_for_convergence`, `record_operation_time`, `get_performance_stats`, `record_retry`, `get_retry_stats`

**CRDT Stores deleted:**
`_files`, `_file_history`, `_projection_errors`, `_file_regions`, `_file_anchors`, `_file_anchor_ops`, `_crdt_text_docs`, `_performance`, `_retries`

---

## 5. Methods Added

### CodeHub
`commit`, `get_diff`, `get_blob`, `get_file_content`, `list_prs`, `list_checks`, `get_check_summary`, `resolve_conflict`, `register_agent_worktree`, `cleanup_worktree`, `ensure_repo`, `merge_pull_request` (real git)

### APIHub
`register_table`, `update_table_schema`, `list_tables`, `get_table`

---

## 6. Commit List (Phase F)

| Hash | Message |
|------|---------|
| `c998a167` | Delete file_coordination.py and all CRDT file-coordination methods (replaced by git worktree) |
| `45de2deb` | Delete crdt_file_coordination_tools.py and crdt_validation_tools.py |
| `f33bf391` | Delete crdt_projection.py and clean up crdt_observer.py (replaced by hub-direct calls) |
| `813688de` | Final cleanup of legacy CRDT methods absorbed into CodeHub/APIHub |
| `f24a9894` | Update agent prompts to use CodeHub.record_check and APIHub.register_table (drop legacy CRDT calls) |
| (this commit) | Add Cutover 4 migration log |

---

## 7. E2E Smoke Output

```
worktree at: /tmp/tmpjirrv7ea/worktrees/backend
backend received 3 live event(s) via bridge
```

---

## 8. Test Counts

- Regressions: 7/7 OK
- Full suite: 224 tests total (7 errors are pre-existing asyncio event-loop contamination in test runner, confirmed unrelated to Cutover 4 changes)
- Tests updated: `test_crdt_deep_binding.py` rewritten for hub-direct API (sync_file_change deleted)

---

## 9. Gotchas

1. **`register_agent_worktree` returns a `Path`**, not a dict — the plan's smoke snippet used `worktree['worktree_path']` but actual return is `worktree_path` directly.
2. **Graceful-degrade for metadata-only repos**: `ensure_repo()` creates an empty initial commit when HEAD has no commits, so worktrees can be created.
3. **`pr_id="main"` synthetic key**: validation/build/artifact checks use `pr_id="main"` as a synthetic pull-request key for the default delivery gate.
4. **Dual-write fallback during Phase E**: methods like `update_table`, `record_validation_result`, `update_artifact` continued to write to both CodeHub/APIHub and the legacy CRDT store until Phase F hard-cut.
5. **`crdt_observer.py` retained**: agents use `WorkspaceObserver.poll()` to detect hub changes — file-coord poll blocks removed from observer but endpoint/table/page polling retained.
6. **asyncio test isolation**: `test_workhub_tools` and others fail with event-loop errors when run in the full discover suite but pass individually — pre-existing issue, not introduced by Cutover 4.

---

## 10. Next

**Cutover 5**: `system_tools` migration + final CRDT purge (remove remaining dual-write fallbacks, simplify `CRDTWorkspace` to thin hub-proxy, eliminate `crdt_validation.py` mixin).
