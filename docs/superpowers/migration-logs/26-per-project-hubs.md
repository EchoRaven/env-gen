# Cutover 26: Per-Project Hub Records (Resume + Backup)

**Branch:** `haibotong-cutover-26-per-project-hubs`
**Date:** 2026-05-26

## What

Each workspace is now a first-class **project record** that survives
orchestrator exit/crash. `project.json` at workspace root carries
`{id, name, description, created_at, last_active_at, status, agents_used, schema_version}`.
HubRegistry creates/refreshes it on init; orchestrator marks
`status="completed"` on successful delivery and `"failed"` on terminal
failure. `ProjectIndex` + `list_projects()` + `resume_project()` give the
new UI (Cutover 28) and CLIs a stable enumeration/resume API.

## Why

Pre-Cutover 26, a workspace was an anonymous directory: no name, no
status, no listing. Once the orchestrator exited, nothing distinguished
a half-finished generation from a completed one or from leftover junk.
The user asked for "GitHub-like project records" — persistent, resumable,
backup-friendly. This is the foundation for the new product UI's
homepage/project-picker (Cutover 28) and for the human-agent chat
persistence (Cutover 27).

## Commits

- `5f5a0c21` Cutover 26: record pre-flight baseline (regressions 7 OK, discover 920 collected)
- `c36502a1` Cutover 26: add ProjectMetadata dataclass + JSON persistence
- `c021ae3f` Cutover 26: add ProjectIndex for cross-workspace project enumeration
- `ab85bb6e` Cutover 26: HubRegistry persists project metadata + touch/set_status helpers
- `25dc7125` Cutover 26: list_projects + resume_project public surface + e2e backup/resume
- `fcd3e675` Cutover 26: orchestrator passes project_name + sets status completed/failed
- (this commit) Cutover 26: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Targeted Cutover 26 sweep: **31 new tests pass** (6 metadata + 8 index + 9 hub_registry_project + 5 resume_e2e + 3 orchestrator_status)
- Collateral spot check: 27 hub-related tests pass (test_hub_architecture, test_apihub_tables, test_workhub_collab_tools, test_runhub_service, test_codehub_suggest_reviewers); Task 4 also ran 48 broader HubRegistry-using tests — all passed.
- Full pytest discover: not re-run on contended host; targeted sweep + spot checks cover the new surface and the HubRegistry constructor change.

## New surfaces

- `runtime/project.py` — `ProjectMetadata` dataclass, `ProjectIndex`,
  `list_projects(root)`, `resume_project(root, id)`, `load/save_project_metadata`,
  `now_ts()`
- `HubRegistry(base_dir, message_bus=None, *, project_id?, project_name?, project_description?)`
  — new keyword-only kwargs; existing positional callers unaffected
- `HubRegistry.project_metadata` — read-only view of persisted record
- `HubRegistry.touch()` — bump last_active_at
- `HubRegistry.set_project_status(status)` — `active|paused|completed|failed|archived`
- `Orchestrator` now passes `project_name=name` + `project_description` on
  HubRegistry construction; calls `hubs.touch()` at run start and
  `set_project_status("completed"|"failed")` in `run()`'s finally block

## Backup model

A workspace dir is fully self-contained (`project.json` + `shared/hubs/`
JsonStore files). `tar -cf backup.tar <workspace>/` is a complete
backup; extracting elsewhere and constructing `HubRegistry(new_path)`
restores all state. Verified by
`test_e2e_workspace_is_self_contained_tarball_backup_restores`.

## Resume model

`resume_project(workspaces_root, project_id)` returns the workspace
`Path`; pass it to `HubRegistry(path)` (or `Orchestrator(output_dir=path)`).
Existing `project.json` is preserved; passing `project_name` to a
HubRegistry pointed at an existing workspace does NOT clobber the
stored name. Verified by
`test_hub_registry_passing_name_to_existing_project_does_not_clobber` and
`test_e2e_resume_returns_workspace_path_and_reusable_registry`.

## Schema-version policy

`project.json` carries `schema_version: 1`. Future migrations bump and
ship a converter in `ProjectMetadata.from_dict`. Unknown fields are
tolerated (forward-compat) — `from_dict` filters to known fields only.

## Known limits (future cutovers)

- Project IDs are auto-generated (`proj_<12-hex>`) when not specified.
  No global ID collision check across multiple workspaces-roots.
- `agents_used` is not auto-populated yet — Cutover 27 will populate
  it as agents post messages.
- No archive/cleanup CLI — `status=archived` is persisted but no tool
  yet uses it.
- Backup is `tar -cf` manual; no scheduled snapshot or remote sync.
- A test-ordering-induced asyncio event-loop pollution exists in
  `test_apihub_tools.py` when run alongside certain other files. Confirmed
  pre-existing (reproduces without Cutover 26 changes); not addressed here.
