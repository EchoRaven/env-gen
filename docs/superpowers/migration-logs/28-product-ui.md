# Cutover 28: Product-Grade UI

**Branch:** `haibotong-cutover-28-product-ui`
**Date:** 2026-05-26

## What

Live monitor moves from single-project CRDT viewer to multi-project
workspace UI. Server gains `--workspaces-root` mode + 7 JSON endpoints
(project list, per-project state with 5-hub snapshots, conversation CRUD).
Frontend gains a hash-based router, a homepage with project picker, a
5-hub dashboard tab (Code/API/Work/Event/Run), and a ChatPanel tab that
drives Cutover 27's HumanConsole. CRDT tab removed from views.jsx; the
`crdt` key on `/api/state` is retained for back-compat but annotated.

## Why

Pre-Cutover 28, the UI required `--project-dir` per-process and rendered
"CRDT Document" — a model the runtime stopped using in Cutover 9. The
user asked for a "product-grade UI" with a homepage that lists projects,
shows each project's hub progress, and lets a human pick agents to chat
with. This delivers the consumable surface for Cutovers 26 + 27.

## Commits

- `6c5aa1ec` Cutover 28: record pre-flight baseline
- `e2a46d92` Cutover 28: live monitor --workspaces-root mode + /api/projects endpoint
- `650a13c5` Cutover 28: /api/projects/<id>/state with 5-hub snapshots
- `31e681ba` Cutover 28: conversation CRUD endpoints + do_POST on MonitorHandler
- `652269ec` Cutover 28: HTTP e2e smoke for /api/projects + POST conversation
- `e3d8da9b` Cutover 28: homepage + hash router + per-project state fetch
- `e71d42db` Cutover 28: 5-hub HubsTab replaces CRDT inspector; add chat tab slot
- `fcc67579` Cutover 28: ChatPanel component (conversation list + transcript + agent selector)
- (this commit) Cutover 28: CRDT housekeeping + migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collected: 979 → 991 (+12 endpoint tests)
- Endpoint test file `test_live_monitor_endpoints.py`: 12/12 passing
  (3 projects + 3 state + 5 conversations + 1 HTTP e2e smoke)
- Manual smoke verifications: `/api/ping` in single-project mode OK,
  `/api/projects` lists seeded projects, POST/GET conversations roundtrip OK

## New surfaces

### Backend (`live_monitor_server.py`)
- `--workspaces-root <dir>` arg (alternative to `--project-dir`)
- `GET /api/projects` → `{projects: [{id, name, status, created_at, last_active_at, workspace_path, description}]}`
- `GET /api/projects/<id>/state` → existing `build_state` payload + `{projectId, projectName, projectStatus, projectDescription, hubs}`
- `GET /api/projects/<id>/conversations` → `{conversations: [summary, ...]}`
- `GET /api/projects/<id>/conversations/<tid>/messages` → `{messages: [{message_id, source, text, created_at, event_type}]}`
- `POST /api/projects/<id>/conversations` body `{target_agents: [...], text, from_user?}` → conversation summary
- `POST /api/projects/<id>/conversations/<tid>/messages` body `{text, from_user?}` → `{ok: true}`
- Helpers: `build_projects_list`, `build_project_state`, `build_conversations_list`,
  `build_messages_list`, `start_conversation_call`, `send_message_call`,
  `_project_workspace`, `_hub_snapshots`. All in-process callable for tests.

### Frontend
- `src/router.jsx` — `window.LiveMonitorRouter.{useRoute, navigateTo}` (hash-based)
- `src/homepage.jsx` — project grid + 5s auto-refresh
- `src/hub_panels.jsx` — `<HubsTab>` + 5 hub panels (CodeHub, APIHub, WorkHub, EventHub, RunHub)
- `src/chat_panel.jsx` — `<ChatPanel>` with conversation list, transcript, agent selector
- `styles/homepage.css`, `styles/hubs.css`, `styles/chat.css`
- `src/api.js` — `useMonitorState(projectId?)` now fetches `/api/projects/<id>/state` when `projectId` set; falls back to `/api/state` otherwise (preserves `--project-dir` mode)
- `src/app.jsx` — split into router shell + `<ProjectMonitor>` wrapper; homepage rendered when `route.kind === "home"`

### Removed
- `<CrdtInspector>` body in `views.jsx` (replaced with `<HubsTab>` + `<ChatPanel>`)
- "crdt" tab key in `views.jsx` (replaced by "hubs" and "chat")

### Backward compat
- `--project-dir` mode still works (no homepage/chat; existing single-project view)
- `build_state` still returns `crdt` key (annotated as back-compat at line 1410)
- v0-workspace.css `.crdt-*` classes retained (no longer referenced by JSX; harmless)

## Known limits (future cutovers)

- HubsTab renders raw `JSON.stringify(snapshot)` for each hub — readable but
  not designed. Future: hub-specific widgets (CodeHub: PR list; APIHub:
  endpoint table; WorkHub: kanban; EventHub: thread timeline; RunHub: run
  history chart).
- Homepage has no "Create new project" button — orchestrator creates them.
- ChatPanel doesn't auto-route messages by intent; user must pick agents.
- No auth — local-only.
- Polling instead of websockets (5s convs refresh, 2s msgs refresh).
- KNOWN_AGENTS in `chat_panel.jsx` is hardcoded; future: serve from
  `/api/projects/<id>/agents` (drawn from agents_config.yaml).
- Orchestrator + live monitor are still separate processes. Messages
  written via the chat panel are durable (EventHub) but only consumed
  if an orchestrator is running (or drained from inbox on next start).
- `_hub_snapshots` constructs a fresh `HubRegistry` per request, which
  re-triggers project.json touch — harmless but does bump `last_active_at`.
  Future optimization: cache HubRegistry per project.
