# Cutover 37: WorkHub Block Editor

**Branch:** `haibotong-cutover-37-block-editor`
**Date:** 2026-05-26

## What

Closes Cutover 33's deferred WorkHub block editor.

Backend: 3 endpoints over the existing `workhub.append_block` /
`update_block` / `insert_block_after` methods.

Frontend: each page row in `WorkHubPanel` gains an Expand toggle that
reveals a `<BlockEditor>` showing every block (sorted by `ord`), with
inline-click-to-edit, "+ Insert after" buttons of each block (with
type dropdown text/code/heading/quote), and a sticky "Add block" form
at the bottom.

## Commits

- 6f2c1992 Cutover 37: record pre-flight baseline
- b6760f4e Cutover 37: WorkHub block editor backend endpoints (append/update/insert-after)
- 270b60c6 Cutover 37: WorkHub block editor frontend (expandable page block lists)
- (this) Cutover 37: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: 1112 → 1118 (+6 block-editor tests)
- `test_live_monitor_endpoints.py`: 73 → 79 (all passing)
- `test_orchestrator_control.py` + `test_auth.py` + `test_run_log_stream.py`: 29 passed (unchanged)

## New surfaces

### Backend
- `workhub_append_block_call(workspaces_root, project_id, page_id, body)` → `workhub.append_block`
- `workhub_update_block_call(workspaces_root, project_id, block_id, body)` → `workhub.update_block`
- `workhub_insert_block_after_call(workspaces_root, project_id, page_id, after_block_id, body)` → `workhub.insert_block_after`
- `POST /api/projects/<id>/workhub/pages/<page_id>/blocks`
- `POST /api/projects/<id>/workhub/blocks/<block_id>` (POST-as-update; matches Cutover 33 set_priority pattern)
- `POST /api/projects/<id>/workhub/pages/<page_id>/blocks/<after_id>/after`

Routes use regex dispatch (matching insert-after pattern first, then
append, then update) to avoid collision between `/blocks` and
`/blocks/<id>` shapes.

### Frontend
- `<BlockEditor projectId page blocks onRefresh />` component in `hub_panels.jsx`
- Per-page Expand toggle in `WorkHubPanel` (renders a second `<tr>` with
  `colSpan=5` containing the BlockEditor when expanded)
- Click-to-edit content (textarea); Save/Cancel buttons
- "+ Insert after" prompts for content (via `window.prompt`); 4 type buttons
- "+ Add block" at bottom with type dropdown + textarea

## Known limits

- No delete operation — WorkHub doesn't expose `delete_block`. Users
  can clear the content to "(empty)" but the block record stays.
- No reorder by drag — to reorder, use Insert After + clear original.
- No rich text — content is plain text (textarea). Markdown/HTML
  rendering is a future cutover.
- Block ord rebalancing not exposed: heavy insert-after activity may
  eventually exhaust integer gaps (WorkHub uses 1024-step ords, so
  thousands of inserts are needed before this matters).
- `+ Insert after` uses `window.prompt` (one-line input). Multi-line
  block content via insert-after needs the future drag-or-modal flow.
