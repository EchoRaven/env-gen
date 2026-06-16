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

- `file_exists` -- `{path}` (relative to workspace; path-traversal rejected)
- `endpoint_exists` -- `{method, path}` (matches APIHub, ignores deprecated)
- `mcp_tool_exists` -- `{name}` (matches APIHub MCP registry)
- `visual_similarity` -- `{page_id, min_similarity}` (reads latest visual review's `similarity_score`)

## Commits

- `6dc3fc00` Cutover 39: record pre-flight baseline
- `ec6d5122` Cutover 39: user_gates.py evaluator + 4 gate types
- `f10edd91` Cutover 39: user-gates CRUD endpoints + deliverability integration
- `c300c85d` Cutover 39: UserGatesSection frontend (CRUD + status pills)
- (this) Cutover 39: migration log

## Test deltas

- Regressions: 7 OK -> 7 OK
- Pytest collect: 1126 -> 1150 (+24 new tests: 16 evaluator + 8 endpoints)
- All user-gate tests: 24/24 PASS
- Adjacent regression sweep (orchestrator + live_monitor + run_log_stream
  + run_reconnect + auth): 116/116 PASS

## New surfaces

### Backend

- `multi_agent/runtime/user_gates.py` -- `validate_gate`, `evaluate_gate`,
  `VALID_GATE_TYPES`, four evaluator functions
- `_load_user_gates(workspace)` / `_save_user_gates(workspace, gates)` --
  atomic JSON at `<workspace>/.user_gates.json`
- `list_user_gates_call`, `create_user_gate_call`, `update_user_gate_call`,
  `delete_user_gate_call`, `evaluate_user_gate_call`
- `GET /api/projects/<id>/user_gates` -- list with current status
- `POST /api/projects/<id>/user_gates` -- create
- `POST /api/projects/<id>/user_gates/<gate_id>` -- update (POST-as-PATCH
  per repo convention)
- `POST /api/projects/<id>/user_gates/<gate_id>/evaluate` -- re-evaluate
- `DELETE /api/projects/<id>/user_gates/<gate_id>` -- remove
- `deliver_project_call` now merges user-gate failures into
  `report.blockers` and flips verdict to `blocked`

### Frontend

- `<UserGatesSection>` inside `WorkHubPanel` -- list with PASS/FAIL pills
  + Add form + dynamic params editor + delete

## Architecture notes

- No arbitrary code execution: gate types are a fixed enum. Adding new
  types requires editing `user_gates.py`.
- Path-traversal defense on `file_exists`: rejects `..` segments +
  absolute paths + paths that resolve outside workspace.
- Status is computed live on every list-gates call (cheap; reads JSON
  stores + filesystem). Future cutover may cache.
- User-gate failures combine with the existing `compute_deliverability`
  report; the verdict flips to `blocked` if any user gate fails AND the
  underlying verdict was `ready` or `deliverable`.
- Deliverability accepts both `"ready"` and `"deliverable"` verdicts as
  "passing" -- `compute_deliverability` currently emits `"deliverable"`,
  but the integration is defensive against either label.

## Route ordering note (Cutover 37 lesson)

In `do_POST`, the `/user_gates/<gid>/evaluate` regex is registered
BEFORE the bare `/user_gates/<gid>` (update) regex. Otherwise the
update pattern's `[^/]+` would swallow `evaluate` as a gate id and
silently rewrite the gate. Same regex-ordering rule as Cutover 37 has
to be observed for any future suffix-style sub-routes.

## API surface adaptations

The original plan referenced a few methods that differ in the real
hubs. We adapted the evaluator + tests to match the actual surfaces:

- `APIHub.get_endpoints()` (not `list_endpoints()`)
- `APIHub.register_mcp_server(name, transport, endpoint, ...)` --
  server is keyed by `name`, not by `server_id`
- `APIHub.register_mcp_tool(server_name, tool_name, schema=...)` --
  uses `server_name`/`schema`, not `server_id`/`input_schema`
- `APIHub.get_mcp_tools()` (not `list_mcp_tools()`)
- `WorkHub.register_visual_review_task(route, screenshot_path,
  reference_path, ...)` -- requires `reference_path` positional
- `WorkHub.submit_visual_review(state="approve", ...)` -- requires
  >=3 substantive deviations + >=20-char summary; tests use
  three deviations and a longer summary; the failing-similarity test
  uses `state="needs_revision"` with one deviation instead.

The evaluator reads `metadata.review_history[-1].similarity_score`
since that is where the WorkHub service actually persists the score.

## Known limits

- No gate ordering/priority -- gates are evaluated in creation order;
  all are equal-weight blockers.
- No history/audit of gate result changes (whether a gate went from
  PASS to FAIL).
- No JSON-schema validation on gate `params` beyond the per-type
  checks.
- The `visual_similarity` gate reads `metadata.review_history` on the
  visual review; if the WorkHub schema changes, the evaluator may need
  an update.
- Future cutover may add a fifth gate type: `test_passes` (read RunHub
  for a tagged run).
