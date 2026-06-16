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
   A separate Force-Deliver flow requires a reason (>=5 chars), publishes
   an audit event, and overrides the gate.

## Commits

- `4d7ef879` Cutover 34: record pre-flight baseline
- `ed207ca9` Cutover 34: _RUN_REGISTRY + POST /api/runs + status/stop endpoints
- `ab492039` Cutover 34: deliver_project_call + POST /api/projects/<id>/deliver
- `c9a435f8` Cutover 34: homepage Start Generation wizard
- `02ad2030` Cutover 34: per-project Deliver + Force-Deliver buttons
- (this commit) Cutover 34: migration log

## New surfaces

### Backend
- `_RUN_REGISTRY: Dict[run_id, RunHandle]` - module-level subprocess tracker
- `start_run_call(workspaces_root, body)` -> spawn main.py subprocess
- `get_run_status(run_id)` -> state + returncode + log_tail
- `stop_run_call(run_id, body)` -> terminate then kill after 5s (DESTRUCTIVE)
- `list_runs()` -> snapshot of all handles
- `deliver_project_call(workspaces_root, project_id, body)` -> check + set status
- 5 new endpoints (POST /api/runs, GET /api/runs, GET /api/runs/<id>/status, POST /api/runs/<id>/stop, POST /api/projects/<id>/deliver)
- Lifecycle events: `project_run_started`, `project_run_finished`, `deliverability_bypass`

### Frontend
- `homepage.jsx`: `+ Start Generation` button + inline wizard form;
  `LiveMonitorRouter.navigateTo` on submit
- `views.jsx`: `<DeliverButton>` mounted in `Center`'s `v0-topbar` next to
  the `StatusBadge`. Includes inline force-deliver form, reason input,
  confirm dialog, blockers list rendering, and success/error feedback.
- `homepage.css`, `v0-workspace.css`: new styles
  (`.generation-wizard`, `.wizard-*`, `.deliver-*`, `.force-deliver-*`,
  `.blockers-list`, verdict-ready / verdict-blocked variants)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Pytest collect: 1083 (baseline) -> 1093 (+10 new tests in
  `test_orchestrator_control.py`: 6 run-registry + 4 deliver)

## Architecture notes

- Subprocesses launched with `start_new_session=True` so the orchestrator
  outlives the live monitor server. On UI restart, `_RUN_REGISTRY` is
  empty until a run is re-attached (future cutover).
- `main.py` is invoked with `--output <workspaces_root> --name <project_id>`
  so the workspace it writes to is exactly `workspaces_root/project_id`
  - which matches the per-project hub records (Cutover 26).
- The Deliver endpoint uses the existing `compute_deliverability` from
  Cutover 24 unchanged - no new gates added.
- Force-deliver publishes a `deliverability_bypass` EventHub event so
  every override is traceable (matches Cutover 30 audit pattern).
- DeliverButton calls `window.LiveMonitorRefresh?.()` after a successful
  delivery so the project view repaints with the new status.

## Known limits

- `_RUN_REGISTRY` is in-memory only. Server restart drops handle tracking
  (subprocess keeps running but UI doesn't see it). Future: persist
  handles to a JSON file on disk + re-attach on startup.
- No streaming log view yet - UI polls `/api/runs/<id>/status` which
  returns `log_tail` (last 4KB). True streaming log = future cutover.
- No "abort generation from project view" button (only from the runs
  list). Future cutover may add per-run UI controls.
- API key checking is a single env-var lookup; doesn't validate that the
  key is actually accepted by the LLM provider.
- Reference image paths must be absolute paths accessible by the live
  monitor process - no file upload UI yet.
- No `<RunStatusBadge>` per-project polling indicator in the project
  header yet; intentionally deferred from this cutover.
