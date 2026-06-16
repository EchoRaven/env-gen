# Cutover 38: Run Reconnect on Server Restart

**Branch:** `haibotong-cutover-38-run-reconnect`
**Date:** 2026-05-26

## What

Persist Cutover 34's `_RUN_REGISTRY` to disk so the live monitor can
re-attach to live orchestrator subprocesses across a server restart.

- `_save_registry(workspaces_root)` -> writes `<workspaces_root>/.runs.json`
  (excludes the Popen handle; keeps pid + state + returncode + metadata)
- `_load_registry(workspaces_root)` -> reads the file, mints an
  `_AttachedRunHandle(pid)` for each live pid (verified via
  `os.kill(pid, 0)`), marks dead pids as `state="completed"`.
- Triggers: `start_run_call`, `stop_run_call`, `get_run_status` (on
  state transition). Load is lazy + idempotent via `_LOADED_ROOTS`,
  called inside `_resolve_hubs`.

`_AttachedRunHandle` mimics the Popen surface (`pid`, `poll()`,
`returncode`, `terminate()`, `kill()`, `wait()`) using `os.kill` for
liveness + signaling. Real exit status is unknown for non-child
processes, so `returncode` reports `0` on detected death (best-effort).

## Commits

- 85bef60f Cutover 38: record pre-flight baseline
- 8b56ad13 Cutover 38: persist _RUN_REGISTRY to .runs.json + _AttachedRunHandle for restart reconnect
- (this) Cutover 38: migration log

## Test deltas
- Regressions: 7 OK -> 7 OK
- Pytest collect: 1118 -> 1126 (+8 reconnect tests)
- Cross-cutting sweep (orchestrator_control + live_monitor_endpoints + auth + run_log_stream): 108 passed
- New `test_run_reconnect.py`: 8 passed (2 `_AttachedRunHandle` + 5 registry persistence + 1 `start_run_call` persistence)

## Architecture notes

- Persistence file location: `<workspaces_root>/.runs.json` -- alongside
  per-project `<project_id>/project.json` records (Cutover 26).
- File writes use atomic `os.replace(tmp, final)` to avoid partial reads.
- After restart, the SSE log stream (Cutover 36) still works because
  `_AttachedRunHandle.poll()` follows the same contract as Popen.
- The DeliverButton (Cutover 34) doesn't care about run handles -- it
  checks `compute_deliverability` directly.
- Project lifecycle SSE events (Cutover 32) `project_run_started` /
  `project_run_finished` are NOT replayed on reconnect (they're event-
  sourced and ephemeral). The UI sees the run in `active_runs` on next
  state refresh.

## Known limits

- Real exit status (returncode) is unknown for non-child reattached
  processes. The handle reports `0` once the pid disappears. If the
  orchestrator failed and you need the true return code, check the
  log file at `<workspace>/logs/generation.log`.
- `_LOADED_ROOTS` is per process. If you point a single server at
  multiple workspaces-roots over its lifetime (uncommon), each gets
  loaded the first time it's resolved.
- No file lock on `.runs.json`. If two live-monitor processes share a
  workspaces-root (also uncommon), concurrent saves could clobber.
  Add file locking in a future cutover if multi-server becomes a thing.
- Stale entries in `.runs.json` accumulate. Future cutover may add an
  "archive completed runs older than N days" cleanup.
