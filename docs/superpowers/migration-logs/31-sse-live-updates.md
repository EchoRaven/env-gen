# Cutover 31: SSE (Server-Sent Events) Replacing Polling — Migration Log

**Branch:** `haibotong-cutover-31-sse`
**Parent branch:** `haibotong-0521-pipeline-web-tools`
**Date:** 2026-05-26

## What

Replaced the live-monitor's polling loops (1.8s state poll, 2s chat-messages
poll, 3s chat-conversations poll) with Server-Sent Events so a mutation reaches
the browser in ~50ms instead of waiting for the next poll tick. Polling stays
as a degraded fallback at 30s, kicking in automatically on SSE disconnect.

Two backend mechanics make this work:

1. **Multi-bridge `EventHub`**: `attach_bridge` previously stored a single
   bridge in `self._bridge`; replaced with `self._bridges: List[Any]` and an
   `add_bridge(b)` method. Legacy `attach_bridge` is now a backward-compat
   alias that appends. This lets the existing `MessageBusBridge` (agent
   delivery) and a new `_SSEHub` (browser delivery) coexist on the same
   EventHub.

2. **Per-project HubRegistry cache**: `_resolve_hubs` previously rebuilt
   `HubRegistry` per request, so each request owned its own `EventHub` —
   fatal for SSE because a bridge attached on `GET /events` would never see
   the EventHub used by a later `POST /workhub/tasks`. Fixed with a module-
   level `_HUB_REGISTRY_CACHE: Dict[Tuple[str, str], HubRegistry]` keyed by
   `(workspaces_root, project_id)`. `delete_project_call` flushes the cache.

Plus a critical fix in `EventHub.publish_event`: the bridge-dispatch loop
called `asyncio.get_event_loop()`, which raises `RuntimeError` in non-main
threads (e.g. a `ThreadingHTTPServer` request handler). The bare `except` 
swallowed the error and dropped the event silently. Switched to
`asyncio.get_running_loop()` + explicit fallback to synchronous delivery
when no loop is running.

## Why

After Cutover 30 the UI supported every mutation, but every state change
still had to wait 1.8s+ for the next poll. The user's experience was sluggish
and the constant polling churned both browser and server CPU. SSE pushes
events server -> client in real time and lets us slash the polling rate to
a 30s safety net.

## Commits

- `00fc15ac` Cutover 31: record pre-flight baseline
- `391c7e29` Cutover 31: multi-bridge EventHub + per-project HubRegistry cache
- `be57db36` Cutover 31: _SSEHub class + GET /api/projects/<id>/events endpoint
- `0253bff5` Cutover 31: SSE frontend hook + api.js + chat panel integration
- (this commit) Cutover 31: migration log

## Test deltas

- Regressions: 7 OK -> 7 OK
- New `agent/tests/test_live_monitor_sse.py`: 9 tests (HubRegistry cache,
  `_SSEHub` unit, endpoint smoke).
- Appended to `agent/tests/test_eventhub_completeness.py`: +3 multi-bridge
  tests (dispatch-to-all, backward-compat, exception-isolation).
- Pytest collected (full): 1045 -> **1057** (+12).
- Targeted sweep `pytest test_live_monitor_sse.py test_eventhub_completeness.py
  test_live_monitor_endpoints.py -q` -> **84 passed**.

## Manual smoke test

```bash
mkdir -p /tmp/sse-smoke-ws
python live_monitor_server.py --workspaces-root /tmp/sse-smoke-ws --port 4211 &
PID=$(curl -s -X POST http://127.0.0.1:4211/api/projects \
  -H "Content-Type: application/json" -d '{"name":"smoke"}' | jq -r .id)
curl -s -N http://127.0.0.1:4211/api/projects/$PID/events > /tmp/sse-out.txt &
sleep 0.5
curl -s -X POST http://127.0.0.1:4211/api/projects/$PID/workhub/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"smoke task","agent":"orchestrator","priority":"P1"}'
# Result: /tmp/sse-out.txt contains a `data:` line with
#   {"id":"evt_...","event_type":"task_created","source_hub":"workhub",...}
```

## New surfaces — Backend

**`EventHub` (`multi_agent/runtime/eventhub.py`):**
- `add_bridge(bridge)` — appends to `_bridges`; tolerates `None`.
- `attach_bridge(bridge)` — backward-compat alias for `add_bridge`.
- `publish_event` now dispatches to every bridge in `_bridges`, isolating
  exceptions so one bad bridge cannot block delivery to the others. Uses
  `asyncio.get_running_loop()` (returns the running loop in async contexts;
  raises RuntimeError otherwise -> falls back to sync `bridge.deliver`).

**`live_monitor_server.py`:**
- `_HUB_REGISTRY_CACHE: Dict[Tuple[str, str], HubRegistry]` + lock.
- `_hub_cache_key(workspaces_root, project_id)` -> `(resolved_str, project_id)`.
- `_clear_hub_registry_cache_for_project(...)` — evicts both registry and SSE-hub caches; called from `delete_project_call`.
- `_resolve_hubs` now returns the cached HubRegistry (or builds + caches it
  on first call).
- `_SSEHub` class — fan-out queue per project. Implements bridge protocol
  (`deliver(event)` -> `broadcast(event)`). Drops events silently when a
  client queue is full (default 256 deep).
- `_SSE_HUB_CACHE` + `_get_or_create_sse_hub(workspaces_root, project_id)`
  builds an `_SSEHub`, attaches it to the project's EventHub via `add_bridge`,
  and caches it for the project's lifetime.
- `MonitorHandler._stream_sse(project_id)` — opens an SSE response, writes
  `: connected\n\n`, then loops reading from the per-client queue. Each event
  is serialized as a slim `data: {id, event_type, source_hub, thread_id,
  created_at, recipients}` frame. Sends `: heartbeat` every 15s when idle.
  Handles `BrokenPipeError` / `ConnectionResetError` cleanly.
- `do_GET` routes `/api/projects/<id>/events` to `_stream_sse`.

## New surfaces — Frontend

**`live_monitor/src/sse.js` (NEW):**
- `window.MonitorSSE.useSSE(projectId, onEvent)` — React hook. Opens an
  `EventSource`, reconnects with exponential backoff (500ms -> 30s cap),
  calls `onEvent(parsedEvent)` for every message, returns `{connected}`.
- `window.MonitorSSE.isConnected()` — global flag for the polling code.

**`live_monitor/src/api.js`:**
- `useMonitorState(projectId)` now opens an EventSource inline (one per
  `projectId`); every message triggers `load()`.
- Polling interval switches to 30000ms whenever `MonitorSSE.isConnected()`
  returns true, 1800ms otherwise. Re-evaluates on every tick so disconnects
  re-fast-poll automatically.
- Existing `window.LiveMonitorRefresh` hook preserved.
- Cleanup closes the EventSource + clears the interval.

**`live_monitor/src/chat_panel.jsx`:**
- Replaced the `setInterval(refreshConversations, 3000)` and
  `setInterval(refreshMessages, 2000)` with 30000ms fallback intervals.
- Added `window.MonitorSSE.useSSE(projectId, ...)` that refetches
  conversations on `human_message` / `agent_reply` events and also refetches
  messages when the event's `thread_id === activeThread`.

**`live_monitor/index.html`:**
- Loads `src/sse.js` before `src/api.js` so the hook is registered first.

## Architecture notes

- **Multi-bridge design**: `EventHub` is owned by the project (per-project
  HubRegistry from Cutover 26). Both `MessageBusBridge` (agent delivery) and
  `_SSEHub` (browser delivery) attach to it. New consumers (e.g. webhooks)
  drop in by adding another `bridge.deliver(event)` implementer.
- **Per-project HubRegistry cache** is mandatory for SSE. Without it, the
  EventHub instance differs between `GET /events` (where the bridge is
  attached) and the `POST` that mutates state — the bridge would never see
  the new event. The cache trades memory for correctness.
- **SSE handler** runs in a `ThreadingHTTPServer` worker thread; the
  `queue.Queue.get(timeout=15.0)` is a blocking call that wakes on either a
  new event or the heartbeat tick. One thread per open SSE connection.
- **Synchronous bridge fan-out**: Once `asyncio.get_running_loop()` returns
  RuntimeError (no loop in this thread), we call `bridge.deliver(event)`
  synchronously on the publishing thread. `_SSEHub.deliver` is non-blocking
  (queue.put_nowait drops silently on full), so this is safe.
- **EventSource per tab**: Browsers cap ~6 concurrent connections per
  origin. With one connection per open project tab, this is the practical
  limit; future cross-project channels (homepage feed) should multiplex.

## Known limits

- **`homepage.jsx` still polls `/api/projects` every 5s.** Cross-project SSE
  needs a global event channel (not scoped to a single project); deferred.
- **SSE queue overflow**: per-client queue is bounded at 256 events.
  Overflowing events are dropped; the 30s fallback poll re-syncs the UI
  through `/state`. In practice events are slim (~200 bytes) and clients
  drain promptly, so overflow is rare.
- **EventSource per-tab connection cap**: ~6 connections per origin per
  browser. Power-user workflows with many projects open will hit this.
- **HubRegistry cache has no eviction policy** beyond explicit delete.
  Projects loaded once stay in memory for the server's lifetime. A future
  LRU pass can bound this.
- **Frontend lacks automated test coverage** (codebase pattern is Python-
  side tests + manual browser checks). Backend SSE path is fully tested.

## Explicitly deferred (future cutovers)

- Cross-project / homepage SSE channel.
- LRU eviction for `_HUB_REGISTRY_CACHE` / `_SSE_HUB_CACHE`.
- Selective subscription on the SSE channel (`?event_types=task_created,
  agent_reply`) — currently every project event is sent to every client.
- Reconnect resumption (`Last-Event-ID`) — currently a reconnect simply
  begins receiving new events; the 30s state poll fills any gap.
