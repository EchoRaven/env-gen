# Cutover 30: UI Operation Parity

**Branch:** `haibotong-cutover-30-ui-ops`
**Date:** 2026-05-26

## What

UI now supports every meaningful mutation the multi-agent code can do.
**Read side:** each hub's `JSON.stringify` panel from Cutover 28 is
replaced with a domain-specific widget — CodeHub: PR + commit + branch
list, APIHub: 4 sub-tables (endpoints, tables, consumers, MCP servers),
WorkHub: 5-column kanban + pages + reviews, EventHub: thread timeline +
recent events + per-agent inbox counts, RunHub: run history with
pass/fail badges. **Write side:** 23 new `POST/DELETE` endpoints expose
every common HubRegistry mutation; each gets a UI button or form. 5
destructive operations are gated behind `window.confirm` (and the
project-delete operation requires the user to retype the project name).

## Why

After Cutover 28 the UI was view-only — agents could write to hubs but
humans couldn't. The user's exact ask:
"UI 的目标不仅是展示，也要能支持能用我们的代码进行的所有操作"
("UI's goal is not just display — it must also support ALL operations
the code can do."). This cutover closes that gap.

## Commits

- `ab84ad6a` Cutover 30: record pre-flight baseline
- `d0793b96` Cutover 30: project lifecycle endpoints (create, set_status, delete)
- `438182b6` Cutover 30: WorkHub operation endpoints (tasks, pages, reviews, dead-code allowlist)
- `3d56dff2` Cutover 30: CodeHub operation endpoints (open_pr, review, merge, force_merge, record_check)
- `d1fe8db6` Cutover 30: APIHub + EventHub + RunHub operation endpoints
- `38733418` Cutover 30: 5-hub domain widgets replace JSON dumps
- `6c4ca5f6` Cutover 30: operation buttons + forms wired to backend mutations
- (this commit) Cutover 30: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Endpoint test file (`test_live_monitor_endpoints.py`): 12 → 59 tests (+47)
- Pytest collected (full): 998 → ~1045

## New surfaces — Backend

**Project lifecycle (3 endpoints):**
- `POST /api/projects` → create_project_call (body: `{name, description?, project_id?}`)
- `POST /api/projects/<id>/status` → set_project_status_call (body: `{status}`)
- `DELETE /api/projects/<id>` → delete_project_call (body: `{confirm: true, confirm_name?}`) — path-traversal-defended

**WorkHub (6 endpoints):**
- `POST /api/projects/<id>/workhub/tasks` → workhub_create_task_call
- `POST .../workhub/tasks/<task_id>/priority` → workhub_set_priority_call
- `POST .../workhub/pages` → workhub_create_page_call
- `POST .../workhub/pages/<page_id>/design_review` → workhub_submit_design_review_call
- `POST .../workhub/pages/<page_id>/visual_review` → workhub_submit_visual_review_call
- `POST .../workhub/coverage_allowlist` → workhub_mark_intentionally_dead_call (DESTRUCTIVE)

**CodeHub (5 endpoints):**
- `POST .../codehub/pull_requests` → open_pr
- `POST .../codehub/pull_requests/<pr_id>/reviews` → submit_review
- `POST .../codehub/pull_requests/<pr_id>/merge` → merge_pr
- `POST .../codehub/pull_requests/<pr_id>/force_merge` → force_merge (DESTRUCTIVE; publishes audit event `force_merge_pr` from `source_hub="ui"`)
- `POST .../codehub/pull_requests/<pr_id>/checks` → record_check

**APIHub (4 endpoints):**
- `POST .../apihub/endpoints` → register_endpoint
- `POST .../apihub/tables` → register_table
- `POST .../apihub/consumers` → register_consumer
- `POST .../apihub/mcp_servers` → register_mcp_server

**EventHub (3 endpoints):**
- `POST .../eventhub/inbox/<agent>/mark_read` → mark_read
- `POST .../eventhub/inbox/<agent>/mark_all_read` → mark_all_read
- `POST .../eventhub/subscriptions` → subscribe

**RunHub (2 endpoints):**
- `POST .../runhub/runs` → record_run (body: `{branch, generated_dir, kind, status?}`)
- `POST .../runhub/runs/<run_id>/status` → update_run_status

Total: **23 endpoints**. All share the Cutover 28 `*_call(workspaces_root, project_id, body)` signature pattern and route through `_resolve_hubs(workspaces_root, project_id)` (added in Task 3) for consistent project + HubRegistry resolution.

`do_DELETE` method added to `MonitorHandler` (mirror of `do_POST`).

## New surfaces — Frontend

**Homepage (`homepage.jsx`):**
- "+ New project" button → inline form (name, description) → POST `/api/projects`
- Per-card "Archive" (confirm) and "Delete" (confirm + name retype) buttons
- Auto-refresh every 5s after mutations

**Hub widgets (`hub_panels.jsx` rewrite):**
- `<HubsTab>` now takes `{ hubs, projectId, onRefresh }` and threads them down
- `<CodeHubPanel>`: open PR list with per-row Merge / Review / Check / Force-merge buttons; `+ Open PR` form
- `<APIHubPanel>`: endpoint/table/consumer/MCP tables; `+ Endpoint`, `+ Table`, `+ Consumer`, `+ MCP Server` forms
- `<WorkHubPanel>`: 5-col kanban (pending/in_progress/completed/failed/blocked); per-task priority dropdown; `+ Task`, `+ Page` forms; design + visual review forms; `Mark Path Dead` form
- `<EventHubPanel>`: thread timeline + recent events stream + per-agent inbox; per-item `Mark read`; `+ Subscribe agent` form
- `<RunHubPanel>`: run history with status badges; per-run status dropdown; `+ Record Run` form

**Refresh wiring (`api.js`):**
- `useMonitorState(projectId)` returns its `load()` callback via `window.LiveMonitorRefresh` so mutation forms can trigger an immediate re-fetch instead of waiting for the 1.8s poll tick

**Views (`views.jsx`):**
- `<HubsTab>` invocation now includes `projectId={state?.projectId}` and `onRefresh={() => window.LiveMonitorRefresh?.()}`

## Destructive operations — confirmation gating

| Operation | Frontend gate | Backend gate |
|---|---|---|
| Force-merge PR | `window.confirm` + reason ≥ 20 chars | `force: true` body field; rejects without it; publishes `force_merge_pr` audit event from `source_hub="ui"` |
| Mark path intentionally dead | `window.confirm` + reason ≥ 10 chars | `agent` field required |
| Mark all inbox items read | `window.confirm` | none |
| Archive project | `window.confirm` | `status` validated against enum |
| Delete project | `window.confirm` + `window.prompt` requiring exact name re-entry | `confirm: true` required; optional `confirm_name` must match if provided; path-traversal-defended (refuses to rmtree workspaces_root itself); resolves to absolute paths first |

## Architecture notes

- Backend helpers all use `_resolve_hubs(workspaces_root, project_id)`
  → returns `(reg, workspace, error)` tuple. Helpers return early with
  `{"error": ...}` on resolution failure (unknown project, missing workspace).
- `delete_project_call` uses `Path.resolve()` + `Path.relative_to()`
  to defend against `../` traversal; explicitly refuses to delete the
  workspaces_root itself.
- Frontend forms are inline (not modals). State is component-local
  (`useState`) so closing the form discards input. After successful
  POST, the form resets + `onRefresh()` re-fetches state.
- Polling continues at 1.8s (api.js); mutations also trigger an
  immediate refresh via `window.LiveMonitorRefresh` injected on first
  state load.

## Explicitly deferred (future cutovers)

- **Cutover 31 (planned):** SSE/WebSocket to replace polling. Live
  mutation updates without 1.8s lag.
- **Cutover 32 (planned):** richer mutation editors that need multi-row
  forms:
  - `SubmitReviewForm.inline_comments` array (PR inline comments)
  - `PageReviewForm.challenges/deviations` arrays (design + visual)
  - APIHub `update_schema` / `deprecate_endpoint` (sub-cases of register)
  - APIHub `record_breaking_change_ack`
  - WorkHub block-editor for pages (currently just title + body string)
  - WorkHub plan editor (`create_plan`, `add_task_to_plan`)
- **Cutover 33 (maybe):** Task lifecycle ops (claim/complete/fail/cancel) — these are agent-internal today; UI exposing them changes the trust model.
- **Cutover 34 (maybe):** Orchestrator-level "Start Generation" wizard
  and `DeliverProjectTool` UI button (multi-gate flow with side
  effects; needs careful UX).
- EventHub `unsubscribe`, `publish_event` (general — non-human) — UI
  not added because there's no obvious user need yet (agents are the
  publishers).
- Auth, audit log viewer, multi-user — all out of scope for the
  local-only product surface.

## Known limits

- The 1.8s polling is still the dominant cost on browser CPU when many
  projects exist. Cutover 31 will fix.
- Snapshot widgets do NOT paginate. A workspace with 1000s of events
  or tasks will lag — virtualization is a future polish.
- `window.confirm` / `window.prompt` are unstyled native dialogs.
  Future: a styled `ConfirmDialog` component.
- Frontend has no automated test coverage (the codebase pattern is
  Python-side tests + manual browser checks). Backend endpoints are
  fully tested.
