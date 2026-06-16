# Cutover 33: Rich Editors

**Branch:** `haibotong-cutover-33-rich-editors`
**Date:** 2026-05-26

## What

Closes most of Cutover 30's deferred list. Six new operation surfaces, each
backed by an existing HubRegistry method:

- **WorkHub task lifecycle:** `claim`, `complete`, `fail`, `cancel`
- **WorkHub comments / decisions / plans:** add comment to any resource, record decision on a page, create a plan (with stages + tasks), add task to plan
- **APIHub schema refinements:** `update_schema` (endpoint), `deprecate_endpoint`, `update_table_schema`
- **CodeHub inline comments:** `submit_review` endpoint extended to accept optional `comments` and `inline_comments` arrays
- **Frontend rich editors:** task lifecycle buttons (status-gated), inline comments thread per task, decision/plan forms, endpoint schema editor with JSON validation, table schema editor, deprecate flow with replacement-id dropdown, review form with multi-row inline comments

## Why

Cutover 30 deferred these as "needs richer UI" — they require multi-row editors,
JSON validation, or dependent dropdowns that didn't fit Cutover 30's single-shot
form pattern. With the global SSE in Cutover 32, mutations now reach the UI fast
enough to make these editors feel responsive.

## Commits

- `8b512f2b` Cutover 33: record pre-flight baseline
- `5f4e8048` Cutover 33: WorkHub task lifecycle endpoints (claim/complete/fail/cancel)
- `1edc71b9` Cutover 33: WorkHub comments + decisions + plans endpoints
- `bf9e7ced` Cutover 33: APIHub schema refinements (update endpoint, deprecate, update table)
- `194435c0` Cutover 33: CodeHub review endpoint accepts comments + inline_comments
- `535c6423` Cutover 33: rich-editor frontend (task lifecycle + comments + decisions + plans + schema edit + inline reviews)
- (this commit) Cutover 33: migration log

## Test deltas

- Regressions: 7 OK → 7 OK
- Pytest collected: 1062 → ~1086 (+24 new endpoint tests across Tasks 2-5)
- `test_live_monitor_endpoints.py`: 59 → 73 passing (all Cutover 33 endpoint tests)

## New surfaces

### Backend (`live_monitor_server.py`)

- `POST /api/projects/<id>/workhub/tasks/<task_id>/claim` body `{agent}` → `workhub.claim_task`
- `POST .../workhub/tasks/<task_id>/complete` body `{agent, result?, evidence?}` → `workhub.complete_task`
- `POST .../workhub/tasks/<task_id>/fail` body `{agent, reason}` (reason ≥5 chars) → `workhub.fail_task` (DESTRUCTIVE-ish)
- `POST .../workhub/tasks/<task_id>/cancel` body `{agent, reason?}` → `workhub.cancel_task`
- `POST .../workhub/comments` body `{resource_type, resource_id, body, author?}` → `workhub.add_comment`
- `POST .../workhub/pages/<page_id>/decisions` body `{title, options[], chosen, reason, agent}` → `workhub.record_decision`
- `POST .../workhub/plans` body `{page_id, title, stages[], tasks[], agent}` → `workhub.create_plan`
- `POST .../workhub/plans/<plan_id>/tasks` body `{task_id, agent}` → `workhub.add_task_to_plan`
- `POST .../apihub/endpoints/<endpoint_id>/schema` body `{request?, response?, agent}` → `apihub.update_schema`
- `POST .../apihub/endpoints/<endpoint_id>/deprecate` body `{replacement_id?, sunset_date?, reason?, agent}` → `apihub.deprecate_endpoint` (DESTRUCTIVE)
- `POST .../apihub/tables/<table_name>/schema` body `{schema, agent}` → `apihub.update_table`
- `POST .../codehub/pull_requests/<pr_id>/reviews` (existing) body extended to accept optional `comments[]` and `inline_comments[]`

All paths URL-decode their id segments (caught during smoke test for APIHub
endpoint ids containing spaces and slashes — e.g., `"GET /api/users"`).

### Frontend (`live_monitor/src/hub_panels.jsx`)

- `TaskCard` component: lifecycle button cluster (status-gated), inline-comments `<details>` thread, comment-send form
- `DecisionForm`: page dropdown + title/options/chosen/reason fields
- `PlanForm`: page dropdown + title + comma-separated stages
- `EndpointSchemaForm`: two textareas (request/response) with client-side JSON validation
- `DeprecateEndpointForm`: replacement-id dropdown + sunset-date + reason; `window.confirm` before submit
- `TableSchemaForm`: single textarea with JSON validation
- `SubmitReviewForm` extended: free-form `comments`, `considered_alternatives`, and a multi-row `inline_comments` table with `+`/`×` controls

### Styles (`live_monitor/styles/hubs.css`)

- New rules for `.task-card`, `.lifecycle-btn`, `.comments-thread`, `.inline-comment-row`, `.schema-textarea`, `.deprecate-form`

## Bug caught and fixed

The APIHub endpoint id is `"METHOD path"` (e.g., `"GET /api/users"`) which the
frontend URL-encodes via `encodeURIComponent`. The Cutover 33 Task 4 routes
forgot to call `urllib.parse.unquote()` on the path segment, so all three
APIHub schema endpoints returned 404 from the UI even though the equivalent
in-process tests passed. Fixed in the same commit as the frontend
(`535c6423`).

## Architecture notes

- All new endpoints reuse the Cutover 30 `_resolve_hubs` helper, so they
  benefit from Cutover 31's per-project HubRegistry cache and Cutover 32's
  forwarder-bridge to the global SSE stream — every mutation pushes a hub
  event to the UI in real time.
- Destructive ops (`fail`, `deprecate`) follow the Cutover 30 pattern: `window.confirm`
  in the UI + audit-loggable event from the EventHub publish that the underlying
  hub method already emits.
- Inline comments are stored as part of the `code_reviews` JsonStore record
  (existing schema) — the UI extension is purely additive.

## Known limits

- Plan editor uses comma-separated stages instead of a true multi-row editor; future cutover can replace with a richer form.
- Block editor (`workhub.append_block` / `update_block`) is still unwired — the page detail panel doesn't surface block-level CRUD. Deferred to a future cutover (would need a dedicated page-detail view, larger frontend lift).
- Schema editor accepts arbitrary JSON but doesn't validate against the actual schema dialect — future cutover may add JSON-schema validation.
- Decision/plan forms show page-level dropdowns but no preview of existing decisions/plans on the page.
- Inline-comments form on reviews accepts file + line + body but no file-path autocomplete from the PR's changed files.
