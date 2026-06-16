# 01 — APIHub Cutover

**Date:** 2026-05-21
**Branch:** `haibotong-hub-cutover-1-apihub` (worktree at `.worktrees/haibotong-hub-cutover-1-apihub`)
**Base:** `20d4117a` ("Add four-hub infrastructure WIP")
**Head:** `ea6938ee` ("Remove temporary APIHub parity tests")
**PR:** _to be filled when opened_

## Summary

First cutover of the four-hub plan. APIHub is now the sole authority for API contracts, the entire legacy `CRDTWorkspace.update_endpoint` family is deleted (12 methods + 2 stores), and breaking changes automatically create fix tasks in WorkHub per affected consumer.

This PR establishes the per-hub cutover SOP that the remaining three cutovers (EventHub bridge, WorkHub, CodeHub) will follow.

## Aggregate diff
- **20 commits**
- **24 files changed**, +717 / -995 lines (net **−278 lines**)
- Largest deletion: `tools/crdt_tools.py` (−541 lines, 6 legacy tool classes removed)
- Next largest: `multi_agent/runtime/crdt.py` (−344 lines, 12 absorbed methods + 2 stores)

## Files changed

### APIHub strengthened (`runtime/apihub.py`)
- Added `add_mock`, `add_example`, `deprecate_endpoint`.
- Expanded `detect_breaking_change` from 1 indicator (`removed_response_fields`) to 7: + `type_changed_fields`, `required_added_in_request`, `method_changed`, `path_changed`, `response_key_changed`, `auth_added`.
- `register_endpoint` now passes `method/path/response_key/auth_required` into the detector so production traffic exercises all 7.
- Added `attach_workhub()` for late binding; `_record_breaking_change` now also calls `workhub.create_task(...)` per affected consumer (with `source="apihub_breaking_change"`, `linked_apis`, `affected_files`, `priority="urgent"`).

### New LLM tools (`tools/hub_tools.py`)
Renamed `APIHubEndpointTool` → `APIHubRegisterEndpointTool` (NAME `apihub_register_endpoint`). Added 8 more APIHub tools, bringing APIHub surface to 10:

| Tool | Purpose |
|---|---|
| apihub_register_endpoint | Provider declares a new endpoint with schema |
| apihub_update_schema | Provider revises request/response shape |
| apihub_list_endpoints | Consumer/verifier filters by status/provider |
| apihub_get_endpoint | Single-endpoint lookup |
| apihub_register_consumer | Frontend (etc.) declares "I'm using this endpoint" |
| apihub_get_dependencies_for_file | "Which APIs does my file consume?" |
| apihub_get_breaking_changes | List recent breaking changes |
| apihub_record_contract_test | Verifier logs contract test result |
| apihub_deprecate_endpoint | Mark deprecated, optionally with `replacement_id` |
| apihub_request_review | Cross-agent review for sensitive endpoints |

### Tool bundle (`multi_agent/tool_bundles.py`)
`_bundle_apihub_tools` widened from 3 → 11 names (10 APIHub + hub_snapshot). No change to `agents_config.yaml` was needed — every agent that referenced `apihub_tools` (orchestrator/design/backend/frontend/verifier) now sees the full set.

### Caller switches (5 files)
- `orchestrator.py:711` reads endpoints from `hubs.apihub.get_endpoints()` (was `crdt_workspace.get_endpoints()`).
- `crdt_projection.py` now writes API spec ONLY via APIHub (legacy `update_endpoint` calls removed; also added a `deprecate_endpoint` branch when projecting stale-missing entries).
- `crdt_observer.py` now reads endpoints/consumers from `workspace.hubs.apihub` (`endpoints`/`api_consumers` version keys renamed to `apihub_*`).
- `tools/mcp_tools.py:582` reads endpoints from `hubs.apihub`.
- `tools/__init__.py` drops the 6 deleted legacy tool exports.

### Prompts (5 files)
All five `prompts/v2/*_agent.j2` migrated from legacy tool names to `apihub_*`. Added guidance:
- **design**: "API contract changes that remove fields, change types, change paths/methods, or add auth automatically create fix tasks for affected consumers."
- **backend**: "When you change an existing endpoint's schema, the contract guard automatically detects breaking changes and notifies consumers — verify the impact list before merging."
- **frontend**: "When you import a new endpoint into a component, call `apihub_register_consumer` so the contract guard can notify you if backend changes the schema."
- **verifier**: instruction to call `apihub_record_contract_test(endpoint_id=..., result={...}, evidence={...})` after each contract test run.

### Deletions
- `tools/crdt_tools.py`: 6 classes removed (`UpdateEndpointTool`, `GetEndpointsTool`, `RegisterApiUsageTool`, `GetApiConsumersTool`, `GetFileDependenciesTool`, `GetApiChangeNotificationsTool`) + their entries in `get_crdt_tools` and `__all__`.
- `runtime/crdt.py`: 12 methods removed (`update_endpoint`, `_detect_breaking_change`, `get_endpoint`, `get_endpoints`, `get_usable_endpoints`, `observe_endpoints`, `register_api_usage`, `unregister_api_usage`, `get_api_consumers`, `get_file_api_dependencies`, `_notify_api_consumers`, `get_api_change_notifications`, `get_api_dependency_graph`) + `_endpoints` and `_api_consumers` CRDTStore field initialization and `ensure_core_documents` entries.
- `agent/tests/test_apihub_parity.py`: temporary parity harness, deleted now that its job is done.
- `test_hub_architecture.py:test_legacy_endpoint_api_delegates_to_apihub`: removed (the delegation it tested no longer exists).

## Tests

| Suite | Result |
|---|---|
| `agent/tests/run_regressions.py` | **7 OK** (was 8 baseline; -1 for the removed legacy delegation test) |
| `test_hub_architecture` | 1 OK (was 2; -1 same reason) |
| `test_apihub_strengthen` | 11 OK |
| `test_apihub_tools` | 5 OK |
| `test_apihub_breaking_change_creates_task` | 1 OK |
| `test_crdt_deep_binding` | 3 OK |
| **Total non-deferred** | **28 OK** |

`agent/tests/test_hub_architecture.py` is now part of `agent/tests/run_regressions.py` (Task 2 — `Register hub_architecture tests in regression suite`), so future cutovers cannot silently break the golden 4-hub collaboration test.

## Live e2e (deferred)

The plan called for a 30-minute `run_facebook_generation.sh` smoke run, but the worktree environment does not have a reachable Docker daemon nor any LLM API key set. **Deferred to the user** to validate locally before merge.

What's been validated statically in place of the live run:
- Every `apihub_*` reference in `prompts/v2/*_agent.j2` corresponds to an actual tool name in `tools/hub_tools.py:HUB_TOOL_CLASSES` (0 dangling references).
- Every kwarg in `apihub_*(...)` examples matches the tool's `PARAMETERS` schema (Task 17 caught and fixed a `status_filter` → `status` regression).
- All 5 prompts render successfully via Jinja2.

Recommended smoke command (run after merge in a Docker-equipped environment with `OPENAI_API_KEY`):
```bash
timeout 1800 bash run_facebook_generation.sh --no-verify --limit-iterations 5
```

## Gotchas encountered

1. **Pre-existing baseline failures fixed first (commit `08ef39b1`)**:
   - `hubs/__init__.py` was importing `.apihub` and `.eventhub` which don't exist as sub-packages under `hubs/` (they live one level up at `runtime/`). Trimmed the broken imports.
   - `hubs/codehub/service.py` and `hubs/workhub/service.py` used `from ..eventhub import EventHub` (two dots = `hubs/`) instead of `from ...eventhub import EventHub` (three dots = `runtime/`). Fixed.
   - `orchestrator._validate_delivery_gate()` referenced `api_spec`/`db_spec` without defining them in scope (half-finished refactor in commit `7704252f`). Added the design-spec reads.
   - `test_task_suite_regressions._prepare_min_delivery_layout` didn't create `design/README.md`, which the delivery gate had started requiring. Added.

2. **Bundle-name vs. tool-name kwarg drift (commit `f4e35d30`)**: When migrating the legacy `get_endpoints(status_filter=...)` calls, two prompt files preserved the kwarg name verbatim — but `apihub_list_endpoints` accepts `status=`, not `status_filter=`. Spec reviewer caught it. Fix-up commit corrected both occurrences (verifier + orchestrator). Lesson for future cutovers: when renaming a tool, also audit kwargs against the new schema, not just the tool name.

3. **Expanded-scope deletion in Task 19**: The legacy method deletion in `crdt.py` was supposed to be a `crdt.py`-only edit, but the broad grep revealed that `crdt_observer.py`, `crdt_projection.py`, `tools/mcp_tools.py`, `test_hub_architecture.py`, `test_crdt_deep_binding.py`, and `test_task_suite_regressions.py` all still called the methods being deleted. The implementer subagent expanded the commit accordingly — justified, but the SOP for future cutovers should add an explicit pre-deletion grep step that surfaces all callers, not just the obviously-related modules.

4. **Hub tools accessing private stores**: `APIHubGetDependenciesForFileTool` and `APIHubGetBreakingChangesTool` read `self._hubs.apihub._consumers.value()` and `_breaking_changes.value()` directly (no public accessor exists yet). Same for `crdt_observer.py:90`. Mild encapsulation concern, non-blocking; flag for follow-up cleanup PR after all four cutovers land.

## SOP changes (apply to remaining cutovers)

1. **Add pre-deletion caller audit step** to the SOP between Step 3 (parity) and Step 4 (switch callers): grep the entire `agent/` tree (not just the file targeted for deletion) for all callers of methods scheduled for removal. Build the exhaustive list BEFORE touching call sites so no caller is overlooked.

2. **Add tool-name + kwarg static check** to the SOP after caller switches: programmatically extract `NAME` and `PARAMETERS` from each new HubTool class, then grep every `prompts/v2/*_agent.j2` to verify every `<tool_name>(<kwarg>=...)` reference uses a kwarg in that tool's schema. Catches the Task 17 class of regression.

3. **Live e2e smoke is environment-dependent**. For future cutovers we should require either:
   - The cutover branch passes the live smoke before merge, OR
   - The migration log documents what the live smoke would validate that static checks can't (so the reviewer can decide whether to gate on it).

4. **Resident agent prompts are tightly coupled to tool names.** A tool rename means a prompt rewrite. Future cutovers should budget more time for prompt updates than the surface diff suggests — frontend prompt alone had 12 substitution sites.

## Acceptance criteria status (from spec §12)

| Item | Status |
|---|---|
| A. Four hubs exist with the APIs in §§5-8 | APIHub complete; CodeHub/WorkHub/EventHub baseline as committed in `20d4117a`, full surface lands in cutovers 2-4. |
| B. All 13 legacy files deleted | APIHub portion done: 6 legacy tool classes deleted from `crdt_tools.py`, 12 methods + 2 stores deleted from `crdt.py`. Full file deletions land in cutovers 2-4. |
| C. `runtime/hubs.py:HubRegistry` replaces `crdt_workspace` | **Deferred** to cutover 4 (CodeHub) per plan §"Out of Scope". Callers still reach APIHub via `crdt_workspace.hubs.apihub`. |
| D. Every hub write fires an EventHub event with stable thread_id | APIHub side complete via `_emit`. Thread-id discipline lands with EventHub bridge in cutover 2. |
| E. MessageBusBridge | Not started; cutover 2. |
| F. agents_config.yaml controls tool exposure | Already true. APIHub tools auto-expose via `apihub_tools` bundle. |
| G. Real git worktrees | Not started; cutover 4. |
| H. run_regressions includes test_hub_architecture | **Done** (Task 2). |
| I. Live Facebook generation passing | **Deferred** to user verification (no Docker/LLM keys in env). |

## Next cutover

**Cutover 2: EventHub ↔ MessageBus bridge.** Plan to be written next session at `docs/superpowers/plans/2026-MM-DD-eventhub-bridge-cutover.md`. The cross-hub task-creation flow added in this cutover (Task 7) already exercises `_emit` correctly, so cutover 2's first job is to make those events also flow live to in-process agents via `MessageBus.send/broadcast`, not just sit in `eventhub_inboxes.json`.
