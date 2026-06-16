# Cutover 36: Streaming Log View

**Branch:** `haibotong-cutover-36-streaming-logs`
**Date:** 2026-05-26

## What

Replaces Cutover 34's 4KB `log_tail` polling with a real SSE stream of
generation logs. UI opens `EventSource(/api/runs/<id>/log/stream)` and
receives the live log as `data: {chunk}\n\n` events. On run completion,
a final `data: {_end: true, returncode: N}` event closes the stream.

## Commits

- 1d7b3d72 Cutover 36: record pre-flight baseline
- b77c864a Cutover 36: GET /api/runs/<id>/log/stream SSE endpoint + active_runs in project state
- cd86d628 Cutover 36: RunLogStream component + View Logs button
- (this) Cutover 36: migration log

## New surfaces

### Backend
- `MonitorHandler._stream_run_log(run_id)` — initial 64KB snapshot + 200ms tail poll loop with heartbeat
- `GET /api/runs/<run_id>/log/stream` SSE endpoint (matched before `/status` since both share `/api/runs/` prefix)
- `build_project_state` adds `active_runs: [{run_id, state, started_at, returncode}]` (per-project run handles)

### Frontend
- `src/run_log_stream.jsx` — modal log viewer with auto-scroll
- `styles/run_log.css`
- `views.jsx` — per-project "Active runs" pills + log modal mounted inside `Center`
- Auto-follow toggle: user scrolling up freezes auto-scroll; scrolling back to bottom re-enables

## Test deltas
- Regressions: 7 OK -> 7 OK
- Pytest collect: 1108 -> 1112 (+4 log-stream tests)
- Collateral pytest suite (orchestrator-control, endpoints, sse, global-sse, auth): 119 passed

## Architecture notes

- The stream polls every 200ms — adequate for ~5 lines/sec output rate
  without burning CPU.
- Initial snapshot trims to last 64KB so users joining mid-run see
  recent context without flooding the channel. When the file exceeds
  the cap, the handler skips a partial first line so the snapshot
  starts cleanly at a newline boundary.
- Stream auto-closes on run completion (`_end` event); UI receives
  returncode and shows "Completed" or "Failed (rc=N)" pill.
- After the popen finishes the loop performs one final read between
  the last seek and EOF so we don't drop bytes flushed by the child
  between our previous read and its exit.
- File rotation/truncation detection: if `cur_size < pos`, the stream
  resets to position 0.
- Heartbeat (`: heartbeat\n\n`) every 15s during quiet periods so
  proxies don't drop the connection.

## Known limits

- Log files are read from disk; if the file is deleted mid-stream, the
  next read returns empty and the stream sits idle until the run
  finishes (then emits `_end`).
- No log filtering or grep — just the raw stream. Future: client-side
  text filter in the modal.
- Modal blocks the rest of the UI while open. Future: dockable side
  panel.
- One stream per run. Multiple browsers viewing the same run each open
  their own file handle.
- Sessions and cookies are forwarded via `withCredentials: true` on
  EventSource so auth (Cutover 35) works.
