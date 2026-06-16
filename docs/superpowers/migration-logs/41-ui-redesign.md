# Cutover 41: Industrial UI Redesign

**Branch:** `haibotong-cutover-41-ui-redesign`
**Date:** 2026-05-26

## What

Frontend visual + structural overhaul. Three pillars:
1. **Theme system** — CSS variables with light + dark palettes; persisted via `localStorage`; toggle in top-right.
2. **Per-hub pages** — each of CodeHub / APIHub / WorkHub / EventHub / RunHub now has its own full-width focused page (`#/projects/<id>/<hubname>`). Plus Overview / Chat / References / Gates / Settings get dedicated routes.
3. **Sidebar shell** — replaces the old top-tab UI with a collapsible left sidebar (220px / 56px) carrying 9 nav entries and the project switcher.

Visual language: Linear/Vercel-inspired neutral palette, blue accent, system font stack, dense data tables with sticky headers, refined chips/buttons/inputs.

## Commits

- `c27e1981` Cutover 41: record pre-flight baseline
- `aa154e72` Cutover 41: design tokens (light+dark CSS vars) + themes.js with localStorage
- `1155d9c0` Cutover 41: convert all existing CSS to use design tokens
- `f5c0ca1a` Cutover 41: ProjectShell sidebar layout + per-section routing
- `fb647526` Cutover 41: per-hub focused pages (CodeHub/APIHub/WorkHub/EventHub/RunHub)
- `4e79f2f1` Cutover 41: cross-cutting pages (Overview/Chat/References/Gates)
- `31218592` Cutover 41: homepage + login token-ified, theme toggle, route to /overview
- (this) Cutover 41: migration log

## New surfaces

### Frontend
- `styles/design-tokens.css` — light + dark palettes via `:root[data-theme]`
- `src/themes.js` — `window.MonitorTheme.useTheme()` hook + auto-apply on load
- `styles/shell.css` — sidebar + topbar + content
- `src/project_shell.jsx` — `<ProjectShell>` (sidebar + main)
- `styles/pages.css` — page sections, data tables, kanban, stat pills, chips, buttons, inputs
- `src/hub_pages.jsx` — `<CodeHubPage>` / `<APIHubPage>` / `<WorkHubPage>` / `<EventHubPage>` / `<RunHubPage>`
- `src/cross_cutting_pages.jsx` — `<OverviewPage>` / `<ChatPage>` / `<ReferencesPage>` / `<GatesPage>`
- Router parses `#/projects/<id>/<section>`; default section = overview

### Backend
- None (no API changes)

## Verification

- `python agent/tests/run_regressions.py` — 7 OK
- `pytest agent/tests/test_live_monitor_endpoints.py agent/tests/test_references.py agent/tests/test_user_gates_endpoints.py -q` — 100 passed
- Smoke: `live_monitor_server --workspaces-root /tmp/envgen_demo --port 4500`
  - `/api/ping` → `{"ok": true}`
  - `/api/projects/todo-app/state` → `hubs: ['codehub', 'workhub', 'apihub', 'eventhub', 'runhub']`

## Design tokens (sample)

- `--accent: #2563eb` light / `#60a5fa` dark
- `--bg-primary: #ffffff` light / `#0b0d10` dark
- `--text-primary: #0f172a` light / `#e6e8eb` dark
- 13px base, system font, 4/8/16/24 spacing

## Known limits

- Old `hub_panels.jsx` retained as a fallback but no longer mounted —
  cleanup can remove it in a follow-up.
- No keyboard shortcuts for nav (could add ⌘K palette later).
- Mobile/narrow viewports use the same layout (no responsive
  sidebar collapse yet). Future cutover.
- Chat page uses the legacy `ChatPanel` component as-is (good enough);
  may want a v2 with the new tokens applied directly.
- Sidebar icons are unicode glyphs (▦ ▣ ↔ ⎙ ✉ ▶ ◯ ≡ ⊘) — replace with
  SVG icons in a future cutover.
- No empty-state illustrations.
- Light mode is the system default; user preference NOT yet read from
  `prefers-color-scheme`. Future cutover.
