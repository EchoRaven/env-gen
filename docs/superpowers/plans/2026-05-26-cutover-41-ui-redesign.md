# Cutover 41: Industrial UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Redesign the live monitor frontend for industrial-software aesthetics. Three pillars: (1) a CSS-variable-based theme system with light + dark modes and a persistent toggle; (2) routing extension so each hub gets its own focused page (`#/projects/<id>/<hubname>`); (3) a sidebar-driven project shell replacing the current top-tab layout. Visual language: Linear/Vercel-ish — clean, dense, neutral, with a clear blue accent.

**Architecture:**
- New `themes.js` exposes `window.MonitorTheme` with `useTheme()` hook, `toggle()`, `current()` reading `localStorage.envgen_theme`. Sets `data-theme="light"|"dark"` on `<html>`.
- All existing CSS rewritten to use CSS custom properties (`--bg-primary`, `--text-primary`, `--accent`, etc.). Two `:root[data-theme=...]` blocks define palettes.
- Router (`router.jsx`) parses `#/projects/<id>/<section>` where section ∈ {overview, codehub, apihub, workhub, eventhub, runhub, chat, references, gates, settings}.
- New `<ProjectShell>` component in `project_shell.jsx` provides the sidebar + main-content layout. Sidebar = nav rail with icons + labels (collapsible to 56px). Replaces the existing `<MonitorApp>` per-project tab UI.
- Five hub pages in `hub_pages.jsx`, each a focused full-width view (PR table, endpoints/tables tabs, kanban board, thread timeline, runs table). Reuse existing data shapes (`state.hubs.<name>`) — the new pages just render them more spaciously.
- Cross-cutting pages: `<OverviewPage>` (high-level counts + recent activity + deliverability state), `<ReferencesPage>` (full Cutover 40 panel), `<GatesPage>` (full Cutover 39 panel), `<ChatPage>` (full chat). Each was previously squeezed inside WorkHubPanel; now they get their own routes.
- Old `hub_panels.jsx` retained as a fallback (its widgets still work) but no longer mounted — the new pages import what they need or use new layouts.

**Visual language:**
- Light mode (default): white bg, near-black text, blue accent `#2563eb`, subtle borders `#e5e7eb`.
- Dark mode: deep gray `#0b0d10`, light text `#e6e8eb`, accent `#60a5fa`.
- System font stack. Base 13px. 4px/8px/16px/24px spacing units.
- Tables use sticky headers + zebra rows. Forms use 6px border radius. Hover/focus states everywhere.

**Tech Stack:** UMD React (no build step). Pure CSS variables. No new deps.

---

## Test infrastructure conventions

Frontend has no automated tests; manual smoke is required. Backend changes are minimal (none planned — the existing endpoints suffice). Regressions: `python agent/tests/run_regressions.py`. NO `Co-Authored-By: Claude` trailer.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/41-ui-redesign.md`
- `agent/env_generator/llm_generator/live_monitor/src/themes.js`
- `agent/env_generator/llm_generator/live_monitor/src/project_shell.jsx`
- `agent/env_generator/llm_generator/live_monitor/src/hub_pages.jsx`
- `agent/env_generator/llm_generator/live_monitor/src/cross_cutting_pages.jsx`  (Overview / References / Gates / Settings)
- `agent/env_generator/llm_generator/live_monitor/styles/design-tokens.css`  (CSS variables + base reset)
- `agent/env_generator/llm_generator/live_monitor/styles/shell.css`  (sidebar + layout)
- `agent/env_generator/llm_generator/live_monitor/styles/pages.css`  (per-hub page styles)

**Modify:**
- `agent/env_generator/llm_generator/live_monitor/src/router.jsx` (parse per-hub section routes)
- `agent/env_generator/llm_generator/live_monitor/src/app.jsx` (route to ProjectShell vs Homepage)
- `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx` (light/dark via tokens; small polish)
- `agent/env_generator/llm_generator/live_monitor/src/login_screen.jsx` (token-ified)
- `agent/env_generator/llm_generator/live_monitor/index.html` (load new JS + CSS; remove old single-tab styles)
- `agent/env_generator/llm_generator/live_monitor/styles/base.css` (replaced by design-tokens.css — keep but slim down)
- `agent/env_generator/llm_generator/live_monitor/styles/homepage.css` (token-ified)
- `agent/env_generator/llm_generator/live_monitor/styles/login.css` (token-ified)
- All other `.css` files (`hubs.css`, `chat.css`, `run_log.css`, `v0-workspace.css`, `payload.css`): replace hard-coded colors with `var(--...)` references. Leave structure alone.

---

## Task 1: Pre-flight baseline

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1163
- [ ] Migration log stub at `docs/superpowers/migration-logs/41-ui-redesign.md`
- [ ] Stage plan
- [ ] Commit: `Cutover 41: record pre-flight baseline`

---

## Task 2: Design tokens + theme system

**Files:**
- Create: `live_monitor/styles/design-tokens.css`
- Create: `live_monitor/src/themes.js`
- Modify: `live_monitor/index.html`

### Step 1: design-tokens.css

```css
/* Cutover 41: Design tokens. Two themes via data-theme attribute on <html>. */

:root, :root[data-theme="light"] {
  --bg-primary: #ffffff;
  --bg-secondary: #f7f8fa;
  --bg-tertiary: #ebedf0;
  --bg-elevated: #ffffff;
  --bg-hover: #f3f4f6;
  --bg-active: #e5e7eb;

  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --text-on-accent: #ffffff;

  --border: #e5e7eb;
  --border-strong: #d1d5db;
  --border-subtle: #f1f5f9;

  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --accent-soft: #dbeafe;
  --accent-on-soft: #1e40af;

  --success: #16a34a;
  --success-soft: #dcfce7;
  --warning: #ea580c;
  --warning-soft: #ffedd5;
  --danger: #dc2626;
  --danger-soft: #fee2e2;
  --info: #0284c7;
  --info-soft: #e0f2fe;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.10);

  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 10px;

  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, monospace;

  --sidebar-w: 220px;
  --sidebar-w-collapsed: 56px;
  --topbar-h: 52px;
}

:root[data-theme="dark"] {
  --bg-primary: #0b0d10;
  --bg-secondary: #14171c;
  --bg-tertiary: #1c2026;
  --bg-elevated: #181b21;
  --bg-hover: #1f242c;
  --bg-active: #262c36;

  --text-primary: #e6e8eb;
  --text-secondary: #9ca3af;
  --text-muted: #6b7280;
  --text-on-accent: #ffffff;

  --border: #2a2f37;
  --border-strong: #3a4150;
  --border-subtle: #1c2026;

  --accent: #60a5fa;
  --accent-hover: #93c5fd;
  --accent-soft: #1e3a5f;
  --accent-on-soft: #93c5fd;

  --success: #4ade80;
  --success-soft: #14532d;
  --warning: #fb923c;
  --warning-soft: #7c2d12;
  --danger: #f87171;
  --danger-soft: #7f1d1d;
  --info: #38bdf8;
  --info-soft: #0c4a6e;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.5);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.6);
}

/* Base reset + global typography */
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  transition: background-color 200ms, color 200ms;
}
button { font-family: inherit; }
code, pre { font-family: var(--font-mono); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 5px; }
::-webkit-scrollbar-track { background: transparent; }
```

### Step 2: themes.js

Create `live_monitor/src/themes.js`:

```javascript
window.MonitorTheme = (function () {
  const { useEffect, useState } = React;
  const STORAGE_KEY = "envgen_theme";

  function get() {
    try { return localStorage.getItem(STORAGE_KEY) || "light"; }
    catch (e) { return "light"; }
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function set(theme) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) {}
    apply(theme);
  }

  function useTheme() {
    const [theme, setTheme] = useState(get());
    useEffect(() => { apply(theme); }, [theme]);
    function toggle() {
      const next = theme === "dark" ? "light" : "dark";
      set(next);
      setTheme(next);
    }
    return { theme, toggle, setTheme: (t) => { set(t); setTheme(t); } };
  }

  // Apply immediately on script load so we don't flash the wrong theme.
  apply(get());

  return { useTheme, get, set, apply };
})();
```

### Step 3: index.html — load design-tokens.css FIRST and themes.js BEFORE any other JSX

Read `index.html`. The `<link rel="stylesheet" href="styles/design-tokens.css">` should be the FIRST stylesheet (before base.css and all others). The `<script src="src/themes.js">` should be loaded BEFORE `router.jsx` so it's available during initial render.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/styles/design-tokens.css \
        agent/env_generator/llm_generator/live_monitor/src/themes.js \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 41: design tokens (light+dark CSS vars) + themes.js with localStorage"
```

---

## Task 3: Token-ify existing CSS files

**Files:**
- Modify: ALL `.css` files in `live_monitor/styles/`

### Step 1: replace hard-coded colors with tokens

For each `.css` file (`base.css`, `homepage.css`, `hubs.css`, `chat.css`, `run_log.css`, `v0-workspace.css`, `payload.css`, `login.css`), do a search-and-replace:

| Old | New |
|-----|-----|
| `#0e1626`, `#0a1018`, `#181b20`, `#14202c` (dark bg primary) | `var(--bg-primary)` |
| `#14171c`, `#1a2538`, `#1a2230` (dark bg secondary) | `var(--bg-secondary)` |
| `#1c2026`, `#262c36`, `#2a2538` (dark bg tertiary) | `var(--bg-tertiary)` |
| `#181b21`, `#1f242c` (dark hover) | `var(--bg-hover)` |
| `#e6e8eb`, `#d4d4d4`, `#ddd`, `#cdd`, `#fff` (light text) | `var(--text-primary)` |
| `#9ca3af`, `#aab`, `#8aa`, `#889` (muted) | `var(--text-secondary)` or `var(--text-muted)` |
| `#2a2f37`, `#354054`, `#2d3a4d` (borders) | `var(--border)` |
| `#4070d0`, `#2563eb`, `#60a5fa` (blue accent) | `var(--accent)` |
| `#2e8c4a`, `#16a34a`, `#4ade80` (green) | `var(--success)` |
| `#b04040`, `#dc2626`, `#f87171`, `#ff6b6b`, `#ffaaaa`, `#faa` (red) | `var(--danger)` |
| `#f0c674`, `#ea580c`, `#fb923c` (orange/amber) | `var(--warning)` |

DO NOT touch the structure (layout, spacing, positioning) — only colors. Existing components keep working.

For accent variants (hover/soft): use `var(--accent-hover)` for hover backgrounds, `var(--accent-soft)` for tinted backgrounds (e.g. pill backgrounds).

Use grep to verify after each file:
```bash
grep -E "#[0-9a-fA-F]{3,6}" agent/env_generator/llm_generator/live_monitor/styles/homepage.css | head
```
Should only show colors inside `:root[data-theme=...]` blocks (none remaining in component selectors).

### Step 2: Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/styles/
git commit -m "Cutover 41: convert all existing CSS to use design tokens"
```

---

## Task 4: Router extension + ProjectShell sidebar layout

**Files:**
- Modify: `live_monitor/src/router.jsx`
- Create: `live_monitor/src/project_shell.jsx`
- Create: `live_monitor/styles/shell.css`
- Modify: `live_monitor/src/app.jsx`
- Modify: `live_monitor/index.html`

### Step 1: Extend router

Modify `router.jsx`'s `parseHash`:

```javascript
function parseHash(hash) {
  const clean = (hash || "").replace(/^#/, "");
  if (!clean || clean === "/") return { kind: "home" };
  // Per-hub / per-section routes: #/projects/<id>/<section>
  const sub = clean.match(/^\/projects\/([^/]+)\/([^/]+)\/?$/);
  if (sub) {
    return {
      kind: "project",
      projectId: decodeURIComponent(sub[1]),
      section: decodeURIComponent(sub[2]),
    };
  }
  const proj = clean.match(/^\/projects\/([^/]+)\/?$/);
  if (proj) {
    return {
      kind: "project",
      projectId: decodeURIComponent(proj[1]),
      section: "overview",  // default
    };
  }
  return { kind: "home" };
}
```

`navigateTo`, `useRoute` unchanged.

### Step 2: ProjectShell component

Create `live_monitor/src/project_shell.jsx`:

```jsx
window.ProjectShell = (function () {
  const { useEffect, useState } = React;

  const NAV_ITEMS = [
    { key: "overview",   label: "Overview",   icon: "▦" },
    { key: "codehub",    label: "CodeHub",    icon: "▣" },
    { key: "apihub",     label: "APIHub",     icon: "↔" },
    { key: "workhub",    label: "WorkHub",    icon: "⎙" },
    { key: "eventhub",   label: "EventHub",   icon: "✉" },
    { key: "runhub",     label: "RunHub",     icon: "▶" },
    { key: "chat",       label: "Chat",       icon: "◯" },
    { key: "references", label: "References", icon: "≡" },
    { key: "gates",      label: "Gates",      icon: "⊘" },
  ];

  function ProjectShell({ projectId, section, state, error, lastUpdated }) {
    const themeCtx = window.MonitorTheme.useTheme();
    const [collapsed, setCollapsed] = useState(false);

    function nav(k) {
      window.LiveMonitorRouter.navigateTo(`/projects/${encodeURIComponent(projectId)}/${k}`);
    }

    function PageContent() {
      const Pages = window.HubPages || {};
      const CC = window.CrossCuttingPages || {};
      switch (section) {
        case "overview":   return <CC.OverviewPage projectId={projectId} state={state} />;
        case "codehub":    return <Pages.CodeHubPage projectId={projectId} hub={state?.hubs?.codehub} state={state} />;
        case "apihub":     return <Pages.APIHubPage projectId={projectId} hub={state?.hubs?.apihub} />;
        case "workhub":    return <Pages.WorkHubPage projectId={projectId} hub={state?.hubs?.workhub} />;
        case "eventhub":   return <Pages.EventHubPage projectId={projectId} hub={state?.hubs?.eventhub} />;
        case "runhub":     return <Pages.RunHubPage projectId={projectId} hub={state?.hubs?.runhub} state={state} />;
        case "chat":       return <CC.ChatPage projectId={projectId} />;
        case "references": return <CC.ReferencesPage projectId={projectId} />;
        case "gates":      return <CC.GatesPage projectId={projectId} />;
        default:           return <CC.OverviewPage projectId={projectId} state={state} />;
      }
    }

    return (
      <div className={"shell " + (collapsed ? "shell-collapsed" : "")}>
        <aside className="shell-sidebar">
          <div className="shell-sidebar-header">
            <button className="shell-back" title="Back to projects"
                    onClick={() => window.LiveMonitorRouter.navigateTo("/")}>←</button>
            {!collapsed && (
              <div className="shell-project-name" title={state?.projectName || projectId}>
                {state?.projectName || projectId}
              </div>
            )}
          </div>
          <nav className="shell-nav">
            {NAV_ITEMS.map(item => (
              <button key={item.key}
                      className={"shell-nav-item " + (section === item.key ? "active" : "")}
                      onClick={() => nav(item.key)}
                      title={item.label}>
                <span className="shell-nav-icon">{item.icon}</span>
                {!collapsed && <span className="shell-nav-label">{item.label}</span>}
              </button>
            ))}
          </nav>
          <div className="shell-sidebar-footer">
            <button className="shell-collapse-btn" onClick={() => setCollapsed(!collapsed)}
                    title={collapsed ? "Expand" : "Collapse"}>
              {collapsed ? "»" : "«"}
            </button>
          </div>
        </aside>
        <div className="shell-main">
          <header className="shell-topbar">
            <div className="shell-topbar-section">
              {NAV_ITEMS.find(n => n.key === section)?.label || section}
            </div>
            <div className="shell-topbar-actions">
              {state?.projectStatus && (
                <span className={"shell-status-pill status-" + state.projectStatus}>
                  {state.projectStatus}
                </span>
              )}
              {lastUpdated && <span className="shell-updated">updated {lastUpdated}</span>}
              <button className="shell-theme-toggle" onClick={themeCtx.toggle}
                      title={"Switch to " + (themeCtx.theme === "dark" ? "light" : "dark")}>
                {themeCtx.theme === "dark" ? "☀" : "☾"}
              </button>
              <button className="shell-logout" onClick={async () => {
                await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
                window.location.reload();
              }} title="Logout">⎋</button>
            </div>
          </header>
          {error && <div className="shell-error-bar">Error: {error}</div>}
          <main className="shell-content">
            <PageContent />
          </main>
        </div>
      </div>
    );
  }

  return ProjectShell;
})();
```

### Step 3: shell.css

Create `live_monitor/styles/shell.css`:

```css
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  height: 100vh;
  background: var(--bg-secondary);
  color: var(--text-primary);
  transition: grid-template-columns 200ms;
}
.shell.shell-collapsed { grid-template-columns: var(--sidebar-w-collapsed) 1fr; }

.shell-sidebar {
  background: var(--bg-primary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.shell-sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--topbar-h);
  padding: 0 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.shell-back {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-secondary); border-radius: var(--radius-sm);
  width: 28px; height: 28px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; flex-shrink: 0;
}
.shell-back:hover { color: var(--accent); border-color: var(--accent); }
.shell-project-name {
  font-weight: 600; font-size: 13px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.shell-nav { flex: 1; overflow-y: auto; padding: 8px 0; }
.shell-nav-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 8px 16px;
  background: transparent; border: none; cursor: pointer;
  color: var(--text-secondary); font-size: 13px; text-align: left;
  border-left: 2px solid transparent;
}
.shell-nav-item:hover {
  background: var(--bg-hover); color: var(--text-primary);
}
.shell-nav-item.active {
  background: var(--accent-soft); color: var(--accent-on-soft);
  border-left-color: var(--accent); font-weight: 600;
}
.shell-nav-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; font-size: 14px;
}
.shell-nav-label { flex: 1; }

.shell-sidebar-footer { padding: 8px; border-top: 1px solid var(--border-subtle); }
.shell-collapse-btn {
  width: 100%; padding: 6px;
  background: transparent; border: 1px solid var(--border);
  color: var(--text-secondary); border-radius: var(--radius-sm);
  cursor: pointer; font-size: 12px;
}
.shell-collapse-btn:hover { color: var(--accent); border-color: var(--accent); }

.shell-main {
  display: flex; flex-direction: column; min-width: 0;
  background: var(--bg-secondary);
}
.shell-topbar {
  height: var(--topbar-h);
  display: flex; align-items: center;
  padding: 0 24px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
}
.shell-topbar-section {
  font-weight: 600; font-size: 14px;
  text-transform: capitalize;
}
.shell-topbar-actions {
  margin-left: auto;
  display: flex; align-items: center; gap: 8px;
}
.shell-status-pill {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  padding: 3px 10px; border-radius: 999px; letter-spacing: 0.5px;
}
.status-active     { background: var(--info-soft); color: var(--info); }
.status-completed  { background: var(--success-soft); color: var(--success); }
.status-failed     { background: var(--danger-soft); color: var(--danger); }
.status-paused     { background: var(--warning-soft); color: var(--warning); }
.status-archived   { background: var(--bg-tertiary); color: var(--text-muted); }

.shell-updated { color: var(--text-muted); font-size: 11px; }
.shell-theme-toggle, .shell-logout {
  width: 32px; height: 32px;
  background: transparent; border: 1px solid var(--border);
  color: var(--text-secondary); border-radius: var(--radius-sm);
  cursor: pointer; font-size: 14px;
  display: flex; align-items: center; justify-content: center;
}
.shell-theme-toggle:hover, .shell-logout:hover {
  color: var(--accent); border-color: var(--accent);
}

.shell-error-bar {
  padding: 8px 24px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.shell-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
```

### Step 4: app.jsx rewires

Read `app.jsx`. Replace the per-project rendering branch to use `<window.ProjectShell>`:

```jsx
if (route.kind === "project") {
  return <window.ProjectShell
            projectId={route.projectId}
            section={route.section || "overview"}
            state={state}
            error={error}
            lastUpdated={lastUpdated} />;
}
```

Remove (or stop using) the prior tab-based per-project component. Keep `useMonitorState` so the data flow is unchanged.

### Step 5: index.html — add new files

In `<head>`:
```html
<link rel="stylesheet" href="styles/shell.css">
```

Before `app.jsx` in body:
```html
<script type="text/babel" src="src/project_shell.jsx"></script>
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/router.jsx \
        agent/env_generator/llm_generator/live_monitor/src/project_shell.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/shell.css \
        agent/env_generator/llm_generator/live_monitor/src/app.jsx \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 41: ProjectShell sidebar layout + per-section routing"
```

---

## Task 5: Per-hub focused pages

**Files:**
- Create: `live_monitor/src/hub_pages.jsx`
- Create: `live_monitor/styles/pages.css`
- Modify: `live_monitor/index.html`

### Step 1: hub_pages.jsx

The five per-hub pages reuse the data from the existing snapshot shape. Each page is a focused full-width view, NOT a card in a grid.

```jsx
window.HubPages = (function () {
  const { useState } = React;

  // ------------------------- helpers -------------------------

  function Section({ title, action, children }) {
    return (
      <section className="page-section">
        <div className="page-section-header">
          <h3>{title}</h3>
          {action}
        </div>
        <div className="page-section-body">{children}</div>
      </section>
    );
  }

  function DataTable({ columns, rows, empty }) {
    if (!rows || rows.length === 0) {
      return <div className="empty-state">{empty || "No data."}</div>;
    }
    return (
      <table className="data-table">
        <thead>
          <tr>{columns.map(c => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id || i}>
              {columns.map(c => <td key={c.key}>{c.render ? c.render(row) : row[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  function StatPill({ label, value, tone }) {
    return (
      <div className={"stat-pill stat-" + (tone || "neutral")}>
        <div className="stat-pill-value">{value}</div>
        <div className="stat-pill-label">{label}</div>
      </div>
    );
  }

  // ------------------------- CodeHub -------------------------
  function CodeHubPage({ projectId, hub, state }) {
    const prs = Object.values(hub?.pull_requests || {});
    const commits = Object.values(hub?.commits || {});
    const branches = Object.values(hub?.branches || {});
    return (
      <div className="page">
        <div className="page-stats">
          <StatPill label="Open PRs" value={prs.filter(p => p.merge_state !== "merged").length} tone="info" />
          <StatPill label="Merged" value={prs.filter(p => p.merge_state === "merged").length} tone="success" />
          <StatPill label="Branches" value={branches.length} tone="neutral" />
          <StatPill label="Commits" value={commits.length} tone="neutral" />
        </div>
        <Section title="Pull Requests">
          <DataTable
            columns={[
              { key: "id", label: "#", width: 60, render: r => <code>{(r.id || "").substr(0, 8)}</code> },
              { key: "title", label: "Title" },
              { key: "author", label: "Author", width: 120 },
              { key: "merge_state", label: "State", width: 100,
                render: r => <span className={"chip chip-" + (r.merge_state || "open")}>{r.merge_state || "open"}</span> },
            ]}
            rows={prs}
            empty="No pull requests yet."
          />
        </Section>
        <Section title="Recent Commits">
          <DataTable
            columns={[
              { key: "sha", label: "SHA", width: 100, render: r => <code>{(r.sha || r.id || "").substr(0, 7)}</code> },
              { key: "message", label: "Message", render: r => r.message || r.msg || "(no message)" },
              { key: "author", label: "Author", width: 120 },
            ]}
            rows={commits.slice(0, 20)}
            empty="No commits yet."
          />
        </Section>
        <Section title="Branches">
          <DataTable
            columns={[
              { key: "name", label: "Name" },
              { key: "head", label: "Head SHA", render: r => <code>{(r.head || "").substr(0, 7)}</code> },
            ]}
            rows={branches}
            empty="No branches."
          />
        </Section>
      </div>
    );
  }

  // ------------------------- APIHub -------------------------
  function APIHubPage({ projectId, hub }) {
    const [tab, setTab] = useState("endpoints");
    const endpoints = Object.values(hub?.endpoints || {});
    const tables = Object.values(hub?.tables || {});
    const consumers = Object.values(hub?.consumers || {});
    const providers = Object.values(hub?.providers || {});
    const mcpServers = providers.filter(p => p.kind === "server");
    return (
      <div className="page">
        <div className="page-stats">
          <StatPill label="Endpoints" value={endpoints.length} tone="info" />
          <StatPill label="Tables" value={tables.length} tone="neutral" />
          <StatPill label="Consumers" value={consumers.length} tone="neutral" />
          <StatPill label="MCP Servers" value={mcpServers.length} tone="neutral" />
        </div>
        <div className="page-tabs">
          {["endpoints", "tables", "consumers", "mcp"].map(t => (
            <button key={t} className={"page-tab " + (tab === t ? "active" : "")}
                    onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        {tab === "endpoints" && (
          <Section title="Endpoints">
            <DataTable columns={[
              { key: "method", label: "Method", width: 80, render: r => <span className={"method-chip m-" + (r.method || "").toLowerCase()}>{r.method}</span> },
              { key: "path", label: "Path", render: r => <code>{r.path}</code> },
              { key: "provider", label: "Provider", width: 120 },
              { key: "status", label: "Status", width: 100,
                render: r => <span className={"chip chip-" + (r.status || "")}>{r.status || "—"}</span> },
            ]} rows={endpoints} empty="No endpoints registered." />
          </Section>
        )}
        {tab === "tables" && (
          <Section title="Tables">
            <DataTable columns={[
              { key: "name", label: "Name" },
              { key: "provider", label: "Provider", width: 120 },
              { key: "columns", label: "Columns", render: r => (r.schema?.columns || r.columns || []).join(", ") },
            ]} rows={tables} empty="No tables registered." />
          </Section>
        )}
        {tab === "consumers" && (
          <Section title="Consumers">
            <DataTable columns={[
              { key: "name", label: "Name" },
              { key: "depends_on", label: "Depends on", render: r => (r.depends_on_endpoints || r.depends_on || []).join(", ") || "—" },
            ]} rows={consumers} empty="No consumers registered." />
          </Section>
        )}
        {tab === "mcp" && (
          <Section title="MCP Servers">
            <DataTable columns={[
              { key: "name", label: "Server" },
              { key: "transport", label: "Transport", width: 100 },
              { key: "endpoint", label: "Endpoint", render: r => <code>{r.endpoint}</code> },
              { key: "tools", label: "Tools", render: r => (r.tools || []).map(t => t.name || t).join(", ") || "—" },
            ]} rows={mcpServers} empty="No MCP servers registered." />
          </Section>
        )}
      </div>
    );
  }

  // ------------------------- WorkHub -------------------------
  function WorkHubPage({ projectId, hub }) {
    const [tab, setTab] = useState("board");
    const tasks = Object.values(hub?.tasks || {});
    const pages = Object.values(hub?.pages || {});
    const reviews = Object.values(hub?.code_reviews || {});

    const columns = ["pending", "in_progress", "completed", "failed", "blocked"];
    function tasksByStatus(status) {
      return tasks.filter(t => (t.status || "pending") === status);
    }

    return (
      <div className="page">
        <div className="page-stats">
          <StatPill label="Total Tasks" value={tasks.length} tone="info" />
          <StatPill label="Completed" value={tasksByStatus("completed").length} tone="success" />
          <StatPill label="Blocked" value={tasksByStatus("blocked").length} tone="warning" />
          <StatPill label="Pages" value={pages.length} tone="neutral" />
        </div>
        <div className="page-tabs">
          {["board", "pages", "reviews"].map(t => (
            <button key={t} className={"page-tab " + (tab === t ? "active" : "")}
                    onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        {tab === "board" && (
          <div className="kanban">
            {columns.map(col => (
              <div key={col} className="kanban-column">
                <div className="kanban-column-header">
                  <strong>{col.replace("_", " ")}</strong>
                  <span className="kanban-count">{tasksByStatus(col).length}</span>
                </div>
                <div className="kanban-column-body">
                  {tasksByStatus(col).map(t => (
                    <div key={t.id} className="kanban-card">
                      <div className="kanban-card-title">{t.title || t.id}</div>
                      <div className="kanban-card-meta">
                        <span className={"priority-chip pri-" + (t.metadata?.priority || "P2").toLowerCase()}>
                          {t.metadata?.priority || "P2"}
                        </span>
                        <span className="kanban-card-assignee">{t.assignee || t.agent || "—"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
        {tab === "pages" && (
          <Section title="Pages">
            <DataTable columns={[
              { key: "title", label: "Title", render: r => r.title || r.id },
              { key: "kind", label: "Kind", width: 120 },
              { key: "attendees", label: "Attendees", render: r => (r.attendees || []).join(", ") || "—" },
            ]} rows={pages} empty="No pages." />
          </Section>
        )}
        {tab === "reviews" && (
          <Section title="Code Reviews">
            <DataTable columns={[
              { key: "pr_id", label: "PR", render: r => <code>{(r.pr_id || "").substr(0, 8)}</code>, width: 100 },
              { key: "reviewer", label: "Reviewer", width: 120 },
              { key: "state", label: "State", width: 100,
                render: r => <span className={"chip chip-" + r.state}>{r.state}</span> },
            ]} rows={reviews} empty="No reviews yet." />
          </Section>
        )}
      </div>
    );
  }

  // ------------------------- EventHub -------------------------
  function EventHubPage({ projectId, hub }) {
    const threads = Object.values(hub?.threads || {});
    const events = Object.values(hub?.events || {}).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const inboxes = Object.values(hub?.inboxes || {});
    return (
      <div className="page">
        <div className="page-stats">
          <StatPill label="Threads" value={threads.length} tone="info" />
          <StatPill label="Events" value={events.length} tone="neutral" />
          <StatPill label="Inboxes" value={inboxes.length} tone="neutral" />
        </div>
        <Section title="Recent Events">
          <DataTable columns={[
            { key: "event_type", label: "Type", width: 160,
              render: r => <span className={"chip chip-" + (r.priority || "normal")}>{r.event_type}</span> },
            { key: "source_hub", label: "Source", width: 120 },
            { key: "recipients", label: "Recipients", render: r => (r.recipients || []).join(", ") || "—" },
            { key: "created_at", label: "When", width: 160,
              render: r => new Date((r.created_at || 0) * 1000).toLocaleString() },
          ]} rows={events.slice(0, 50)} empty="No events." />
        </Section>
        <Section title="Threads">
          <DataTable columns={[
            { key: "id", label: "Thread", render: r => <code>{(r.id || "").substr(0, 12)}</code> },
            { key: "participants", label: "Participants", render: r => (r.participants || []).join(", ") },
            { key: "event_ids", label: "Messages", width: 100,
              render: r => (r.event_ids || []).length },
          ]} rows={threads} empty="No threads." />
        </Section>
      </div>
    );
  }

  // ------------------------- RunHub -------------------------
  function RunHubPage({ projectId, hub, state }) {
    const runs = Object.values(hub?.runs || {}).sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
    return (
      <div className="page">
        <div className="page-stats">
          <StatPill label="Total Runs" value={runs.length} tone="info" />
          <StatPill label="Successful" value={runs.filter(r => r.status === "completed" && (r.fail_count || 0) === 0).length} tone="success" />
          <StatPill label="Failed" value={runs.filter(r => r.status === "failed" || (r.fail_count || 0) > 0).length} tone="danger" />
        </div>
        <Section title="Run History">
          <DataTable columns={[
            { key: "id", label: "ID", render: r => <code>{(r.id || "").substr(0, 12)}</code>, width: 160 },
            { key: "branch", label: "Branch", width: 120 },
            { key: "status", label: "Status", width: 120,
              render: r => <span className={"chip chip-" + r.status}>{r.status}</span> },
            { key: "fail_count", label: "Failures", width: 100,
              render: r => r.fail_count || 0 },
            { key: "started_at", label: "Started", width: 180,
              render: r => new Date((r.started_at || 0) * 1000).toLocaleString() },
          ]} rows={runs} empty="No runs yet." />
        </Section>
      </div>
    );
  }

  return { CodeHubPage, APIHubPage, WorkHubPage, EventHubPage, RunHubPage };
})();
```

### Step 2: pages.css

```css
.page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

/* ---------------- stat pills row ---------------- */
.page-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.stat-pill {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-shadow: var(--shadow-sm);
}
.stat-pill-value { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.stat-pill-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
.stat-info    .stat-pill-value { color: var(--accent); }
.stat-success .stat-pill-value { color: var(--success); }
.stat-warning .stat-pill-value { color: var(--warning); }
.stat-danger  .stat-pill-value { color: var(--danger); }

/* ---------------- section ---------------- */
.page-section {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.page-section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}
.page-section-header h3 { margin: 0; font-size: 13px; font-weight: 600; }
.page-section-body { padding: 0; }

/* ---------------- data table ---------------- */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table thead th {
  position: sticky; top: 0;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}
.data-table tbody td {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
}
.data-table tbody tr:hover { background: var(--bg-hover); }
.data-table tbody tr:last-child td { border-bottom: none; }
.data-table code { color: var(--text-secondary); font-size: 12px; }

.empty-state { padding: 32px; text-align: center; color: var(--text-muted); font-style: italic; }

/* ---------------- chips ---------------- */
.chip {
  display: inline-flex; align-items: center;
  padding: 2px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.3px;
  background: var(--bg-tertiary); color: var(--text-secondary);
}
.chip-open, .chip-ready, .chip-active, .chip-in_progress, .chip-info, .chip-normal { background: var(--info-soft); color: var(--info); }
.chip-completed, .chip-merged, .chip-approve, .chip-passed, .chip-success { background: var(--success-soft); color: var(--success); }
.chip-failed, .chip-blocked, .chip-changes_requested, .chip-danger, .chip-critical { background: var(--danger-soft); color: var(--danger); }
.chip-pending, .chip-paused, .chip-warning, .chip-deprecated, .chip-needs_revision, .chip-high { background: var(--warning-soft); color: var(--warning); }

.method-chip {
  display: inline-flex; padding: 2px 8px; border-radius: var(--radius-sm);
  font-size: 11px; font-weight: 700; font-family: var(--font-mono);
}
.m-get    { background: var(--info-soft); color: var(--info); }
.m-post   { background: var(--success-soft); color: var(--success); }
.m-put    { background: var(--warning-soft); color: var(--warning); }
.m-patch  { background: var(--warning-soft); color: var(--warning); }
.m-delete { background: var(--danger-soft); color: var(--danger); }

.priority-chip {
  display: inline-flex; padding: 1px 8px; border-radius: var(--radius-sm);
  font-size: 10px; font-weight: 700; font-family: var(--font-mono);
}
.pri-p0 { background: var(--danger-soft); color: var(--danger); }
.pri-p1 { background: var(--warning-soft); color: var(--warning); }
.pri-p2 { background: var(--info-soft); color: var(--info); }
.pri-p3 { background: var(--bg-tertiary); color: var(--text-secondary); }

/* ---------------- tabs ---------------- */
.page-tabs {
  display: flex; gap: 4px;
  border-bottom: 1px solid var(--border);
  padding-left: 4px;
}
.page-tab {
  background: transparent; border: none;
  padding: 8px 16px;
  font-size: 13px; color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  text-transform: capitalize;
}
.page-tab:hover { color: var(--text-primary); }
.page-tab.active {
  color: var(--accent); font-weight: 600;
  border-bottom-color: var(--accent);
}

/* ---------------- kanban ---------------- */
.kanban {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  min-height: 400px;
}
.kanban-column {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex; flex-direction: column;
  min-width: 0;
}
.kanban-column-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
  text-transform: capitalize;
}
.kanban-count {
  background: var(--bg-tertiary); color: var(--text-secondary);
  border-radius: 999px; padding: 1px 8px; font-size: 11px; font-weight: 600;
}
.kanban-column-body { padding: 8px; display: flex; flex-direction: column; gap: 6px; flex: 1; overflow-y: auto; }
.kanban-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}
.kanban-card:hover { border-color: var(--accent); }
.kanban-card-title { font-size: 12px; font-weight: 500; margin-bottom: 6px; color: var(--text-primary); }
.kanban-card-meta { display: flex; justify-content: space-between; align-items: center; }
.kanban-card-assignee { font-size: 11px; color: var(--text-muted); }
```

### Step 3: index.html

Add:
```html
<link rel="stylesheet" href="styles/pages.css">
<script type="text/babel" src="src/hub_pages.jsx"></script>
```
(Both BEFORE `project_shell.jsx`.)

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/hub_pages.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/pages.css \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 41: per-hub focused pages (CodeHub/APIHub/WorkHub/EventHub/RunHub)"
```

---

## Task 6: Cross-cutting pages (Overview / Chat / References / Gates)

**Files:**
- Create: `live_monitor/src/cross_cutting_pages.jsx`
- Modify: `live_monitor/index.html`

### Step 1: cross_cutting_pages.jsx

```jsx
window.CrossCuttingPages = (function () {
  const { useEffect, useState, useRef } = React;

  // ------------------------- Overview -------------------------
  function OverviewPage({ projectId, state }) {
    const hubs = state?.hubs || {};
    const ch = hubs.codehub || {};
    const ah = hubs.apihub || {};
    const wh = hubs.workhub || {};
    const eh = hubs.eventhub || {};
    const rh = hubs.runhub || {};
    const tasks = Object.values(wh.tasks || {});
    const taskByStatus = (s) => tasks.filter(t => (t.status || "pending") === s).length;

    function StatCard({ label, value, hub, tone }) {
      const nav = () => window.LiveMonitorRouter.navigateTo(`/projects/${encodeURIComponent(projectId)}/${hub}`);
      return (
        <div className={"overview-card tone-" + (tone || "neutral")} onClick={nav}>
          <div className="overview-card-value">{value}</div>
          <div className="overview-card-label">{label}</div>
        </div>
      );
    }

    return (
      <div className="page">
        <div className="overview-header">
          <h2>{state?.projectName || projectId}</h2>
          {state?.projectDescription && <p>{state.projectDescription}</p>}
        </div>
        <div className="overview-grid">
          <StatCard label="Pull Requests" value={Object.keys(ch.pull_requests || {}).length} hub="codehub" tone="info" />
          <StatCard label="API Endpoints" value={Object.keys(ah.endpoints || {}).length} hub="apihub" tone="info" />
          <StatCard label="Tables" value={Object.keys(ah.tables || {}).length} hub="apihub" tone="neutral" />
          <StatCard label="Tasks" value={tasks.length} hub="workhub" tone="info" />
          <StatCard label="Pages" value={Object.keys(wh.pages || {}).length} hub="workhub" tone="neutral" />
          <StatCard label="Threads" value={Object.keys(eh.threads || {}).length} hub="eventhub" tone="neutral" />
          <StatCard label="Runs" value={Object.keys(rh.runs || {}).length} hub="runhub" tone="info" />
        </div>
        <div className="overview-row">
          <section className="page-section">
            <div className="page-section-header"><h3>Task Status</h3></div>
            <div className="page-section-body">
              <div className="overview-bar-chart">
                {["pending", "in_progress", "completed", "failed", "blocked"].map(s => (
                  <div key={s} className="overview-bar-item">
                    <div className="overview-bar-label">{s.replace("_", " ")}</div>
                    <div className="overview-bar-track">
                      <div className={"overview-bar-fill bar-" + s}
                           style={{ width: `${Math.min(100, (taskByStatus(s) / Math.max(1, tasks.length)) * 100)}%` }} />
                    </div>
                    <div className="overview-bar-count">{taskByStatus(s)}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>
          <section className="page-section">
            <div className="page-section-header"><h3>Recent Events</h3></div>
            <div className="page-section-body">
              <ul className="overview-event-list">
                {Object.values(eh.events || {})
                  .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
                  .slice(0, 8)
                  .map(e => (
                    <li key={e.id}>
                      <span className="chip chip-info">{e.event_type}</span>
                      <span className="overview-event-source">{e.source_hub}</span>
                      <span className="overview-event-time">{new Date((e.created_at || 0) * 1000).toLocaleTimeString()}</span>
                    </li>
                  ))}
                {Object.keys(eh.events || {}).length === 0 && <li className="empty-state-inline">No events yet.</li>}
              </ul>
            </div>
          </section>
        </div>
      </div>
    );
  }

  // ------------------------- Chat -------------------------
  // Reuse the existing ChatPanel component verbatim — it works in a full-page context.
  function ChatPage({ projectId }) {
    return (
      <div className="page page-chat">
        <window.LiveMonitorChatPanel projectId={projectId} />
      </div>
    );
  }

  // ------------------------- References -------------------------
  function ReferencesPage({ projectId }) {
    const [files, setFiles] = useState([]);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");
    const fileInputRef = useRef(null);

    async function refresh() {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`,
                              { credentials: "include" });
        const data = await r.json();
        setFiles(data.files || []);
        setError("");
      } catch (e) { setError(String(e)); }
    }
    useEffect(() => { refresh(); }, [projectId]);

    function handleFile(file) {
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) { setError(`${file.name} > 10MB cap`); return; }
      setPending(true); setError("");
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const b64 = (ev.target.result || "").split(",")[1] || "";
          const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/references`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ filename: file.name, content_base64: b64 }),
          });
          const data = await r.json();
          if (data.error) setError(data.error); else refresh();
        } catch (e) { setError(String(e)); }
        finally { setPending(false); }
      };
      reader.readAsDataURL(file);
    }

    async function deleteFile(name) {
      if (!window.confirm(`Delete '${name}'?`)) return;
      await fetch(`/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}`,
                  { method: "DELETE", credentials: "include" });
      refresh();
    }

    function fmtSize(n) {
      if (n < 1024) return `${n}B`;
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
      return `${(n / (1024 * 1024)).toFixed(1)}MB`;
    }

    return (
      <div className="page">
        <section className="page-section">
          <div className="page-section-header">
            <h3>Reference Files</h3>
            <div>
              <input type="file" ref={fileInputRef} onChange={(e) => { handleFile(e.target.files?.[0]); e.target.value = ""; }}
                     style={{ display: "none" }} />
              <button onClick={() => fileInputRef.current?.click()} disabled={pending} className="btn btn-primary">
                {pending ? "Uploading…" : "+ Upload"}
              </button>
            </div>
          </div>
          <div className="page-section-body">
            {error && <div className="alert alert-danger">{error}</div>}
            {files.length === 0 ? <div className="empty-state">No reference files yet. Click + Upload.</div> :
              <table className="data-table">
                <thead>
                  <tr><th>Category</th><th>Name</th><th>Size</th><th></th></tr>
                </thead>
                <tbody>
                  {files.map(f => (
                    <tr key={f.name}>
                      <td><span className={"chip chip-info"}>{f.category}</span></td>
                      <td><code>{f.name}</code></td>
                      <td>{fmtSize(f.size)}</td>
                      <td style={{ textAlign: "right" }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => deleteFile(f.name)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          </div>
        </section>
      </div>
    );
  }

  // ------------------------- Gates -------------------------
  function GatesPage({ projectId }) {
    const [gates, setGates] = useState([]);
    const [showAdd, setShowAdd] = useState(false);
    const [name, setName] = useState("");
    const [type, setType] = useState("file_exists");
    const [params, setParams] = useState({});
    const [error, setError] = useState("");

    async function refresh() {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`,
                            { credentials: "include" });
      const data = await r.json();
      setGates(data.gates || []);
    }
    useEffect(() => { refresh(); }, [projectId]);

    async function createGate() {
      if (!name.trim()) { setError("name required"); return; }
      const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ name, type, params }),
      });
      const data = await r.json();
      if (data.error) { setError(data.error); return; }
      setShowAdd(false); setName(""); setParams({}); setError("");
      refresh();
    }

    async function deleteGate(gid) {
      if (!window.confirm("Delete gate?")) return;
      await fetch(`/api/projects/${encodeURIComponent(projectId)}/user_gates/${encodeURIComponent(gid)}`,
                  { method: "DELETE", credentials: "include" });
      refresh();
    }

    function ParamsForm() {
      if (type === "file_exists") {
        return <input className="input" placeholder="path (e.g. README.md)" value={params.path || ""} onChange={e => setParams({ path: e.target.value })} />;
      }
      if (type === "endpoint_exists") {
        return (<>
          <select className="input" value={params.method || "GET"} onChange={e => setParams({ ...params, method: e.target.value })}>
            {["GET","POST","PUT","PATCH","DELETE"].map(m => <option key={m}>{m}</option>)}
          </select>
          <input className="input" placeholder="/api/path" value={params.path || ""} onChange={e => setParams({ ...params, path: e.target.value })} />
        </>);
      }
      if (type === "mcp_tool_exists") {
        return <input className="input" placeholder="tool name" value={params.name || ""} onChange={e => setParams({ name: e.target.value })} />;
      }
      if (type === "visual_similarity") {
        return (<>
          <input className="input" placeholder="page_id" value={params.page_id || ""} onChange={e => setParams({ ...params, page_id: e.target.value })} />
          <input className="input" type="number" min="0" max="1" step="0.05" placeholder="min similarity"
                 value={params.min_similarity ?? ""} onChange={e => setParams({ ...params, min_similarity: parseFloat(e.target.value) })} />
        </>);
      }
      return null;
    }

    return (
      <div className="page">
        <section className="page-section">
          <div className="page-section-header">
            <h3>User-Defined Gates</h3>
            <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
              {showAdd ? "Cancel" : "+ Add Gate"}
            </button>
          </div>
          <div className="page-section-body">
            {showAdd && (
              <div className="add-gate-form-v2">
                {error && <div className="alert alert-danger">{error}</div>}
                <input className="input" placeholder="Gate name" value={name} onChange={e => setName(e.target.value)} />
                <select className="input" value={type} onChange={e => { setType(e.target.value); setParams({}); }}>
                  <option value="file_exists">file_exists</option>
                  <option value="endpoint_exists">endpoint_exists</option>
                  <option value="mcp_tool_exists">mcp_tool_exists</option>
                  <option value="visual_similarity">visual_similarity</option>
                </select>
                <ParamsForm />
                <button className="btn btn-primary" onClick={createGate}>Create</button>
              </div>
            )}
            {gates.length === 0 && !showAdd ?
              <div className="empty-state">No gates defined. Add one to gate the Deliver button.</div> :
              <table className="data-table">
                <thead>
                  <tr><th>Status</th><th>Name</th><th>Type</th><th>Params</th><th>Message</th><th></th></tr>
                </thead>
                <tbody>
                  {gates.map(g => (
                    <tr key={g.id}>
                      <td><span className={"chip chip-" + (g.status?.passed ? "passed" : "failed")}>
                        {g.status?.passed ? "PASS" : "FAIL"}</span></td>
                      <td>{g.name}</td>
                      <td><code>{g.type}</code></td>
                      <td><code style={{ fontSize: "11px" }}>{JSON.stringify(g.params)}</code></td>
                      <td style={{ color: "var(--text-secondary)" }}>{g.status?.message || ""}</td>
                      <td style={{ textAlign: "right" }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => deleteGate(g.id)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          </div>
        </section>
      </div>
    );
  }

  return { OverviewPage, ChatPage, ReferencesPage, GatesPage };
})();
```

### Step 2: append more styles to pages.css

```css
/* ---------------- buttons + inputs ---------------- */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent;
  font-family: inherit;
  transition: background 120ms, border-color 120ms;
}
.btn-primary { background: var(--accent); color: var(--text-on-accent); }
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:disabled { background: var(--text-muted); cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--text-secondary); border-color: var(--border); }
.btn-ghost:hover { color: var(--accent); border-color: var(--accent); }
.btn-danger { background: var(--danger); color: var(--text-on-accent); }
.btn-danger:hover { filter: brightness(1.1); }
.btn-sm { padding: 3px 10px; font-size: 12px; }

.input {
  background: var(--bg-primary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; font-family: inherit; font-size: 13px;
  margin-right: 6px;
}
.input:focus { outline: 2px solid var(--accent); outline-offset: -1px; border-color: var(--accent); }

.alert { padding: 8px 12px; border-radius: var(--radius-sm); font-size: 12px; margin-bottom: 8px; }
.alert-danger { background: var(--danger-soft); color: var(--danger); }
.alert-success { background: var(--success-soft); color: var(--success); }

.add-gate-form-v2 { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); margin-bottom: 12px; }

/* ---------------- overview ---------------- */
.overview-header h2 { margin: 0 0 8px; font-size: 22px; }
.overview-header p { margin: 0; color: var(--text-secondary); }
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.overview-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  cursor: pointer;
  transition: border-color 120ms, transform 120ms;
}
.overview-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.overview-card-value { font-size: 28px; font-weight: 700; color: var(--text-primary); margin-bottom: 4px; }
.overview-card-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.overview-card.tone-info .overview-card-value { color: var(--accent); }

.overview-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.overview-bar-chart { padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.overview-bar-item { display: grid; grid-template-columns: 100px 1fr 40px; align-items: center; gap: 10px; }
.overview-bar-label { font-size: 12px; color: var(--text-secondary); text-transform: capitalize; }
.overview-bar-track { background: var(--bg-tertiary); border-radius: var(--radius-sm); height: 8px; overflow: hidden; }
.overview-bar-fill { height: 100%; border-radius: var(--radius-sm); }
.bar-pending     { background: var(--text-muted); }
.bar-in_progress { background: var(--info); }
.bar-completed   { background: var(--success); }
.bar-failed      { background: var(--danger); }
.bar-blocked     { background: var(--warning); }
.overview-bar-count { font-size: 12px; color: var(--text-secondary); text-align: right; font-weight: 600; }

.overview-event-list { list-style: none; padding: 0; margin: 0; }
.overview-event-list li {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; border-bottom: 1px solid var(--border-subtle);
}
.overview-event-list li:last-child { border-bottom: none; }
.overview-event-source { color: var(--text-secondary); font-size: 12px; }
.overview-event-time { margin-left: auto; color: var(--text-muted); font-size: 11px; }
.empty-state-inline { padding: 16px; color: var(--text-muted); font-style: italic; }

.page-chat .chat-panel { height: calc(100vh - 140px); margin: 0; }
```

### Step 3: index.html

Add `<script type="text/babel" src="src/cross_cutting_pages.jsx"></script>` BEFORE `project_shell.jsx`.

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/cross_cutting_pages.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/pages.css \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 41: cross-cutting pages (Overview/Chat/References/Gates)"
```

---

## Task 7: Polish + Homepage refresh + smoke test

**Files:**
- Modify: `live_monitor/src/homepage.jsx`
- Modify: `live_monitor/styles/homepage.css`
- Modify: `live_monitor/src/login_screen.jsx`
- Modify: `live_monitor/styles/login.css`

### Step 1: Homepage polish

The existing homepage uses good-enough layout — main updates:
1. Add a theme toggle button in the top-right corner.
2. Make project cards open the new shell route `#/projects/<id>/overview` instead of `#/projects/<id>` (the router now treats both the same, but the explicit `/overview` is clearer).
3. Token-ify colors if not already done in Task 3.
4. Use `.btn .btn-primary` for the "+ New project" / "+ Start Generation" buttons.

Read homepage.jsx and adjust as needed. Replace the old custom button classes with the new `.btn` system where it makes sense (keeps page consistent).

### Step 2: Login screen polish

Same — token-ify; ensure the input borders + button use the new tokens.

### Step 3: Manual smoke test

```bash
# Use the existing /tmp/envgen_demo workspace
# Kill the old server first
pkill -f "live_monitor_server.*4500" 2>/dev/null
sleep 1
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py \
    --workspaces-root /tmp/envgen_demo --host 0.0.0.0 --port 4500 > /tmp/envgen_demo_server.log 2>&1 &
sleep 2
curl -sS http://127.0.0.1:4500/api/ping
# Sanity-check the data path still works
curl -sS http://127.0.0.1:4500/api/projects/todo-app/state | python -c "import sys,json; d=json.load(sys.stdin); print('hubs:', list(d.get('hubs', {}).keys()))"
```

Open the browser to verify:
- Homepage renders with light theme by default
- Click theme toggle (top-right) → switches to dark, persists across refresh
- Click a project card → navigates to `#/projects/todo-app/overview`
- Sidebar shows 9 nav items + project name + collapse button
- Click CodeHub / APIHub / WorkHub / EventHub / RunHub — each opens its own page
- Click Chat / References / Gates — each opens its own page
- Click ← back button in sidebar → returns to homepage

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/homepage.css \
        agent/env_generator/llm_generator/live_monitor/src/login_screen.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/login.css
git commit -m "Cutover 41: homepage + login token-ified, theme toggle, route to /overview"
```

---

## Task 8: Migration log + push + ff-merge

### Step 1: regressions sanity

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py agent/tests/test_references.py agent/tests/test_user_gates_endpoints.py -q 2>&1 | tail -3
```

(No backend tests change — only a smoke.)

### Step 2: full migration log

```markdown
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

- (SHA) Cutover 41: record pre-flight baseline
- (SHA) Cutover 41: design tokens (light+dark CSS vars) + themes.js with localStorage
- (SHA) Cutover 41: convert all existing CSS to use design tokens
- (SHA) Cutover 41: ProjectShell sidebar layout + per-section routing
- (SHA) Cutover 41: per-hub focused pages
- (SHA) Cutover 41: cross-cutting pages (Overview/Chat/References/Gates)
- (SHA) Cutover 41: homepage + login token-ified, theme toggle
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
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/41-ui-redesign.md docs/superpowers/plans/2026-05-26-cutover-41-ui-redesign.md
git commit -m "Cutover 41: migration log"
git push -u red-env-gen haibotong-cutover-41-ui-redesign
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-41-ui-redesign
git merge --ff-only haibotong-cutover-41-ui-redesign
git push red-env-gen haibotong-0521-pipeline-web-tools
```
