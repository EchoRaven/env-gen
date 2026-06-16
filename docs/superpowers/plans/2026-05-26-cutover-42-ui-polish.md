# Cutover 42: Reference-Driven UI Polish (Notion/GitHub/Apifox)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Lift the UI from "OK" to "industrial-product" quality by studying Notion, GitHub, Apifox, Jira, and Gemini and applying their patterns. Three pillars: (1) **distinctive typography** (IBM Plex Sans + Mono via Google Fonts — industrial, technical, free, not the overused Inter/Roboto/Space-Grotesk); (2) **Notion-style grouped sidebar** with proper SVG icons + workspace switcher + section headers; (3) **GitHub-style page hero + dense data tables** with breadcrumbs, multi-line metadata rows, sticky headers, and refined chips.

Also bundled: the inline-render bug fix (PageContent no longer remounts every poll → no more screen flash, form state preserved on Gates/References).

**Aesthetic direction:** Operations Console. Notion-warmth in light mode (paper-white `#fdfdfc`, warm dark text `#37352f`), GitHub-precision in dark mode (`#0d1117` + `#161b22` panels). Indigo-blue accent, soft tinted status pills. Whitespace generous, but data dense where appropriate. Never decorative for decoration's sake.

**Tech stack:** Google Fonts (IBM Plex Sans + Mono), inline SVG icons (no icon-font dep), React (no build step).

---

## Test infrastructure conventions

Tests in `agent/tests/` with sys.path boilerplate. Regressions: `python agent/tests/run_regressions.py`. NO `Co-Authored-By: Claude` trailer.

This cutover is pure-frontend — no backend tests change. Manual smoke verifies the user-visible behavior.

---

## File Structure

**Create:**
- `docs/superpowers/migration-logs/42-ui-polish.md`
- `agent/env_generator/llm_generator/live_monitor/src/icons.jsx`  (SVG icon library)

**Modify:**
- `agent/env_generator/llm_generator/live_monitor/styles/design-tokens.css` — refined palette + font family vars + add `@import` for Google Fonts
- `agent/env_generator/llm_generator/live_monitor/styles/shell.css` — Notion-style sidebar with sections + workspace switcher
- `agent/env_generator/llm_generator/live_monitor/styles/pages.css` — GitHub-style page hero + 2-line data table rows + refined chips
- `agent/env_generator/llm_generator/live_monitor/styles/homepage.css` — match new visual language
- `agent/env_generator/llm_generator/live_monitor/src/project_shell.jsx` — grouped nav sections + SVG icons + workspace switcher header
- `agent/env_generator/llm_generator/live_monitor/src/hub_pages.jsx` — page hero pattern + multi-line table rows (already-good kanban stays)
- `agent/env_generator/llm_generator/live_monitor/src/cross_cutting_pages.jsx` — same page hero pattern
- `agent/env_generator/llm_generator/live_monitor/src/homepage.jsx` — refined project cards with metadata rows (GitHub-style)
- `agent/env_generator/llm_generator/live_monitor/index.html` — Google Fonts `<link>` + `icons.jsx` load

---

## Task 1: Pre-flight baseline + verify bug fix

- [ ] Regressions → 7 OK
- [ ] Pytest collect → ~1163
- [ ] Open http://127.0.0.1:4500/, navigate to TODO App project, click each hub tab — verify the pages render (no "Loading…") and the screen no longer flashes every poll. (The bug fix shipped at the start of Cutover 42.)
- [ ] Migration log stub
- [ ] Stage plan file
- [ ] Commit: `Cutover 42: pre-flight baseline (PageContent inline render bug fix)`
  (The fix was already applied to project_shell.jsx as part of pre-Cutover-42 unblocking; include the inline-render change in this commit.)

---

## Task 2: Typography + refined palette

**Files:**
- Modify: `live_monitor/styles/design-tokens.css`
- Modify: `live_monitor/index.html`

### Step 1: Add Google Fonts

In `index.html` `<head>`, BEFORE the existing stylesheets:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

### Step 2: Rewrite design-tokens.css palette + font vars

Open `design-tokens.css`. Replace the entire light-theme `:root` block and dark `:root[data-theme="dark"]` block with these values (keep the structure section + base reset below the tokens):

```css
:root, :root[data-theme="light"] {
  /* Notion-warmth — paper white, warm dark text */
  --bg-primary: #ffffff;
  --bg-secondary: #fbfbfa;     /* page bg — slightly off-white */
  --bg-tertiary: #f1f1ef;      /* panels, sidebar items */
  --bg-elevated: #ffffff;
  --bg-hover: #f7f7f5;
  --bg-active: #ebebe9;
  --bg-sidebar: #fbfbfa;
  --bg-canvas: #ffffff;

  --text-primary: #37352f;     /* Notion warm-dark */
  --text-secondary: #6b6960;
  --text-muted: #91918c;
  --text-on-accent: #ffffff;

  --border: #e9e9e7;
  --border-strong: #d9d9d7;
  --border-subtle: #f1f1ef;

  /* Indigo-blue (not the overused Linear-blue, not purple) */
  --accent: #2e90fa;
  --accent-hover: #1570cd;
  --accent-soft: #eaf4fe;
  --accent-on-soft: #1d61aa;

  /* Status tints — soft, deliberate, Notion-like */
  --success: #0f9d58;
  --success-soft: #e7f5ed;
  --warning: #d97706;
  --warning-soft: #fef3e2;
  --danger: #d92c2c;
  --danger-soft: #fce8e8;
  --info: #2e90fa;
  --info-soft: #eaf4fe;
  --neutral: #6b6960;
  --neutral-soft: #f1f1ef;

  --shadow-xs: 0 1px 2px rgba(15, 15, 15, 0.04);
  --shadow-sm: 0 1px 3px rgba(15, 15, 15, 0.06), 0 1px 2px rgba(15, 15, 15, 0.04);
  --shadow-md: 0 4px 12px rgba(15, 15, 15, 0.08), 0 2px 4px rgba(15, 15, 15, 0.04);
  --shadow-lg: 0 12px 28px rgba(15, 15, 15, 0.12), 0 4px 12px rgba(15, 15, 15, 0.06);

  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  --font-sans: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", "SF Mono", Menlo, Monaco, Consolas, monospace;

  --sidebar-w: 252px;
  --sidebar-w-collapsed: 56px;
  --topbar-h: 48px;
}

:root[data-theme="dark"] {
  /* GitHub-precision — deep blue-black, cool text */
  --bg-primary: #0d1117;
  --bg-secondary: #010409;
  --bg-tertiary: #161b22;
  --bg-elevated: #161b22;
  --bg-hover: #1c2128;
  --bg-active: #21262d;
  --bg-sidebar: #010409;
  --bg-canvas: #0d1117;

  --text-primary: #e6edf3;
  --text-secondary: #9198a1;
  --text-muted: #6e7681;
  --text-on-accent: #ffffff;

  --border: #21262d;
  --border-strong: #2f3742;
  --border-subtle: #161b22;

  --accent: #4493f8;
  --accent-hover: #6cb6ff;
  --accent-soft: #0d2d5b;
  --accent-on-soft: #79c0ff;

  --success: #3fb950;
  --success-soft: #0f2716;
  --warning: #d29922;
  --warning-soft: #2d2306;
  --danger: #f85149;
  --danger-soft: #2d0a0a;
  --info: #58a6ff;
  --info-soft: #0d2d5b;
  --neutral: #9198a1;
  --neutral-soft: #1c2128;

  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.6), 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.6), 0 2px 4px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 12px 28px rgba(0, 0, 0, 0.7), 0 4px 12px rgba(0, 0, 0, 0.5);
}

/* Base reset + global typography */
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
  font-feature-settings: "kern" 1, "ss01" 1;
  transition: background-color 160ms ease, color 160ms ease;
}
button { font-family: inherit; }
code, pre { font-family: var(--font-mono); font-size: 12px; }
::-webkit-scrollbar { width: 12px; height: 12px; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 6px; border: 3px solid var(--bg-primary); }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
::-webkit-scrollbar-track { background: transparent; }
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/styles/design-tokens.css \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 42: IBM Plex Sans/Mono + refined Notion/GitHub palette"
```

---

## Task 3: SVG icon library

**Files:**
- Create: `live_monitor/src/icons.jsx`
- Modify: `live_monitor/index.html`

### Step 1: icons.jsx

Create a small inline-SVG icon set. Stroke-based, 16x16, 1.5px stroke — Lucide-style.

```jsx
window.Icons = (function () {
  function Icon({ d, size = 16, stroke = "currentColor", fill = "none", strokeWidth = 1.5, ...rest }) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill={fill}
           stroke={stroke} strokeWidth={strokeWidth}
           strokeLinecap="round" strokeLinejoin="round" {...rest}>
        {d}
      </svg>
    );
  }
  // Lucide-derived paths (https://lucide.dev) — re-rendered inline. All under ISC.
  const PATHS = {
    home:       <><path d="M3 12 L12 3 L21 12" /><path d="M5 10v10h14V10" /></>,
    grid:       <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    code:       <><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></>,
    api:        <><path d="M4 8h16"/><path d="M4 16h16"/><path d="M10 4l-2 16"/><path d="M16 4l-2 16"/></>,
    workhub:    <><path d="M3 5h18"/><path d="M3 12h18"/><path d="M3 19h18"/><circle cx="6" cy="5" r="1.2" fill="currentColor"/><circle cx="11" cy="12" r="1.2" fill="currentColor"/><circle cx="16" cy="19" r="1.2" fill="currentColor"/></>,
    inbox:      <><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></>,
    play:       <><polygon points="6 3 20 12 6 21 6 3" fill="currentColor" stroke="none"/></>,
    chat:       <><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>,
    file:       <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    shield:     <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></>,
    settings:   <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></>,
    sun:        <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></>,
    moon:       <><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></>,
    logout:     <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></>,
    chevronLeft:  <><polyline points="15 18 9 12 15 6"/></>,
    chevronRight: <><polyline points="9 18 15 12 9 6"/></>,
    chevronDown:  <><polyline points="6 9 12 15 18 9"/></>,
    plus:       <><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>,
    search:     <><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>,
    folder:     <><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></>,
  };
  // Stable wrapper components (one per icon name)
  const map = {};
  for (const [k, p] of Object.entries(PATHS)) {
    map[k] = (props) => <Icon d={p} {...props} />;
  }
  return map;
})();
```

### Step 2: Load in index.html

Add `<script type="text/babel" src="/src/icons.jsx"></script>` BEFORE `project_shell.jsx` (must be available when shell renders).

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/icons.jsx \
        agent/env_generator/llm_generator/live_monitor/index.html
git commit -m "Cutover 42: SVG icon library (Lucide-style stroke icons)"
```

---

## Task 4: Sidebar redesign (Notion-style grouped sections + SVG icons)

**Files:**
- Modify: `live_monitor/src/project_shell.jsx`
- Modify: `live_monitor/styles/shell.css`

### Step 1: project_shell.jsx grouped nav

Replace the NAV_ITEMS array + sidebar JSX. The grouped structure:

```jsx
const NAV_GROUPS = [
  { header: null, items: [
    { key: "overview", label: "Overview", icon: "home" },
  ]},
  { header: "Hubs", items: [
    { key: "codehub",  label: "CodeHub",  icon: "code" },
    { key: "apihub",   label: "APIHub",   icon: "api" },
    { key: "workhub",  label: "WorkHub",  icon: "workhub" },
    { key: "eventhub", label: "EventHub", icon: "inbox" },
    { key: "runhub",   label: "RunHub",   icon: "play" },
  ]},
  { header: "Workspace", items: [
    { key: "chat",       label: "Chat",       icon: "chat" },
    { key: "references", label: "References", icon: "file" },
    { key: "gates",      label: "Gates",      icon: "shield" },
  ]},
];
```

Replace the sidebar JSX render block to:

```jsx
<aside className="shell-sidebar">
  <div className="shell-workspace">
    <button className="shell-ws-switcher"
            onClick={() => window.LiveMonitorRouter.navigateTo("/")}
            title="Back to all projects">
      <div className="shell-ws-avatar">
        {(state?.projectName || projectId).substr(0, 2).toUpperCase()}
      </div>
      {!collapsed && (
        <div className="shell-ws-meta">
          <div className="shell-ws-name">{state?.projectName || projectId}</div>
          <div className="shell-ws-sub">
            {state?.projectStatus ? `· ${state.projectStatus}` : "project"}
          </div>
        </div>
      )}
      {!collapsed && <window.Icons.chevronLeft size={14} />}
    </button>
  </div>

  <nav className="shell-nav">
    {NAV_GROUPS.map((group, i) => (
      <div key={i} className="shell-nav-group">
        {group.header && !collapsed && (
          <div className="shell-nav-header">{group.header}</div>
        )}
        {group.items.map(item => {
          const IconComp = window.Icons[item.icon];
          return (
            <button key={item.key}
                    className={"shell-nav-item " + (section === item.key ? "active" : "")}
                    onClick={() => nav(item.key)}
                    title={item.label}>
              <span className="shell-nav-icon">{IconComp ? <IconComp size={16} /> : null}</span>
              {!collapsed && <span className="shell-nav-label">{item.label}</span>}
            </button>
          );
        })}
      </div>
    ))}
  </nav>

  <div className="shell-sidebar-footer">
    <button className="shell-icon-btn" onClick={themeCtx.toggle}
            title={"Switch to " + (themeCtx.theme === "dark" ? "light" : "dark") + " mode"}>
      {themeCtx.theme === "dark" ? <window.Icons.sun size={16} /> : <window.Icons.moon size={16} />}
    </button>
    <button className="shell-icon-btn" onClick={async () => {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
      window.location.reload();
    }} title="Logout">
      <window.Icons.logout size={16} />
    </button>
    <button className="shell-icon-btn shell-collapse-btn"
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
      {collapsed ? <window.Icons.chevronRight size={16} /> : <window.Icons.chevronLeft size={16} />}
    </button>
  </div>
</aside>
```

Also slim down the topbar — remove the duplicate status pill + Logout (now in sidebar footer). Keep only: page title H1 + breadcrumb-ish + `lastUpdated`.

```jsx
<header className="shell-topbar">
  <div className="shell-topbar-left">
    <h1 className="shell-page-title">
      {NAV_GROUPS.flatMap(g => g.items).find(n => n.key === section)?.label || section}
    </h1>
    {lastUpdated && <span className="shell-updated">Updated {lastUpdated}</span>}
  </div>
</header>
```

### Step 2: shell.css rewrite

Replace shell.css with the Notion-grouped layout. Key additions: `.shell-workspace`, `.shell-ws-switcher`, `.shell-ws-avatar`, `.shell-nav-group`, `.shell-nav-header`, `.shell-icon-btn`. Sidebar `background: var(--bg-sidebar)` (slightly different from main bg).

```css
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  height: 100vh;
  background: var(--bg-secondary);
  color: var(--text-primary);
  transition: grid-template-columns 200ms ease;
  overflow: hidden;
}
.shell.shell-collapsed { grid-template-columns: var(--sidebar-w-collapsed) 1fr; }

.shell-sidebar {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* Workspace switcher (Notion-style avatar + name) */
.shell-workspace {
  padding: 10px;
  border-bottom: 1px solid var(--border-subtle);
}
.shell-ws-switcher {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 8px 10px;
  background: transparent; border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-primary); cursor: pointer; text-align: left;
}
.shell-ws-switcher:hover { background: var(--bg-hover); }
.shell-ws-avatar {
  width: 28px; height: 28px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--accent), var(--accent-hover));
  color: var(--text-on-accent);
  font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.5px;
  box-shadow: var(--shadow-xs);
}
.shell-ws-meta { flex: 1; min-width: 0; }
.shell-ws-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.shell-ws-sub { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

.shell-nav { flex: 1; overflow-y: auto; padding: 8px 6px; }
.shell-nav-group { padding-bottom: 8px; }
.shell-nav-header {
  padding: 12px 12px 4px;
  font-size: 10px; font-weight: 600; letter-spacing: 0.06em;
  color: var(--text-muted); text-transform: uppercase;
}
.shell-nav-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 6px 12px;
  background: transparent; border: none;
  border-radius: var(--radius-md);
  color: var(--text-secondary); font-size: 13px;
  font-weight: 400;
  text-align: left; cursor: pointer;
  margin: 1px 0;
  transition: background-color 80ms ease;
}
.shell-nav-item:hover {
  background: var(--bg-hover); color: var(--text-primary);
}
.shell-nav-item.active {
  background: var(--accent-soft);
  color: var(--accent-on-soft);
  font-weight: 500;
}
.shell-nav-item.active .shell-nav-icon svg { color: var(--accent); }
.shell-nav-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px;
  color: var(--text-muted);
}
.shell-nav-item:hover .shell-nav-icon { color: var(--text-secondary); }
.shell-nav-label { flex: 1; }

.shell-sidebar-footer {
  display: flex; gap: 4px;
  padding: 8px;
  border-top: 1px solid var(--border-subtle);
}
.shell-collapsed .shell-sidebar-footer { flex-direction: column; }
.shell-icon-btn {
  width: 32px; height: 32px;
  background: transparent; border: none;
  color: var(--text-secondary); border-radius: var(--radius-md);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.shell-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.shell-icon-btn.shell-collapse-btn { margin-left: auto; }
.shell-collapsed .shell-icon-btn.shell-collapse-btn { margin-left: 0; }

/* Main / topbar / content */
.shell-main {
  display: flex; flex-direction: column; min-width: 0;
  background: var(--bg-secondary);
  overflow: hidden;
}
.shell-topbar {
  height: var(--topbar-h);
  display: flex; align-items: center;
  padding: 0 24px;
  background: var(--bg-canvas);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.shell-topbar-left {
  display: flex; align-items: baseline; gap: 16px;
}
.shell-page-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.shell-updated {
  font-size: 11px;
  color: var(--text-muted);
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
  background: var(--bg-secondary);
}
```

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/project_shell.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/shell.css
git commit -m "Cutover 42: grouped sidebar with workspace switcher + SVG icons"
```

---

## Task 5: Page hero pattern + refined data tables

**Files:**
- Modify: `live_monitor/styles/pages.css`
- Modify: `live_monitor/src/hub_pages.jsx`
- Modify: `live_monitor/src/cross_cutting_pages.jsx`

### Step 1: pages.css — page hero + GitHub-style rows

Replace the existing `.page` styles + add new patterns. Keep `.stat-pill`, `.kanban`, etc. but refine. Below shows the additions/replacements:

```css
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 32px 64px;
}

/* ----- page hero (GitHub-style) ----- */
.page-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 8px;
}
.page-hero-meta { flex: 1; min-width: 0; }
.page-hero-title {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 4px;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}
.page-hero-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}
.page-hero-actions {
  display: flex; gap: 8px; flex-shrink: 0;
}

/* ----- stat pills (refined) ----- */
.page-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: border-color 120ms ease;
}
.stat-pill:hover { border-color: var(--border-strong); }
.stat-pill-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  font-weight: 500;
}
.stat-pill-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  font-feature-settings: "tnum" 1;
  letter-spacing: -0.01em;
}
.stat-info    .stat-pill-value { color: var(--info); }
.stat-success .stat-pill-value { color: var(--success); }
.stat-warning .stat-pill-value { color: var(--warning); }
.stat-danger  .stat-pill-value { color: var(--danger); }

/* ----- section card ----- */
.page-section {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.page-section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: transparent;
}
.page-section-header h3 {
  margin: 0; font-size: 13px; font-weight: 600;
  color: var(--text-primary);
}
.page-section-body { padding: 0; }

/* ----- GitHub-style 2-line table rows ----- */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--bg-elevated);
  color: var(--text-muted);
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}
.data-table tbody td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
  vertical-align: top;
}
.data-table tbody tr { transition: background-color 80ms ease; }
.data-table tbody tr:hover { background: var(--bg-hover); }
.data-table tbody tr:last-child td { border-bottom: none; }
.data-table code {
  color: var(--text-secondary);
  font-size: 11.5px;
  background: var(--bg-tertiary);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}
.cell-primary {
  font-weight: 500;
  color: var(--text-primary);
  display: block;
  margin-bottom: 2px;
}
.cell-meta {
  display: flex; align-items: center; gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
.cell-meta-item { display: inline-flex; align-items: center; gap: 4px; }

.empty-state {
  padding: 48px 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}
.empty-state-title {
  font-size: 15px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

/* ----- chips (refined Notion-soft) ----- */
.chip {
  display: inline-flex; align-items: center;
  padding: 2px 8px; border-radius: var(--radius-sm);
  font-size: 11px; font-weight: 500;
  background: var(--neutral-soft); color: var(--text-secondary);
  line-height: 1.4;
}
.chip-open, .chip-active, .chip-in_progress, .chip-info, .chip-normal, .chip-ready, .chip-deliverable { background: var(--info-soft); color: var(--info); }
.chip-completed, .chip-merged, .chip-approve, .chip-passed, .chip-success { background: var(--success-soft); color: var(--success); }
.chip-failed, .chip-blocked, .chip-changes_requested, .chip-danger, .chip-critical { background: var(--danger-soft); color: var(--danger); }
.chip-pending, .chip-paused, .chip-warning, .chip-deprecated, .chip-needs_revision, .chip-high { background: var(--warning-soft); color: var(--warning); }
.chip-archived, .chip-cancelled { background: var(--neutral-soft); color: var(--text-muted); }

/* HTTP method chips */
.method-chip {
  display: inline-flex; padding: 1px 8px; border-radius: var(--radius-sm);
  font-size: 11px; font-weight: 600; font-family: var(--font-mono);
  letter-spacing: 0.02em;
}
.m-get    { background: var(--info-soft); color: var(--info); }
.m-post   { background: var(--success-soft); color: var(--success); }
.m-put    { background: var(--warning-soft); color: var(--warning); }
.m-patch  { background: var(--warning-soft); color: var(--warning); }
.m-delete { background: var(--danger-soft); color: var(--danger); }

.priority-chip {
  display: inline-flex; padding: 1px 6px; border-radius: var(--radius-sm);
  font-size: 10px; font-weight: 700; font-family: var(--font-mono);
}
.pri-p0 { background: var(--danger-soft); color: var(--danger); }
.pri-p1 { background: var(--warning-soft); color: var(--warning); }
.pri-p2 { background: var(--info-soft); color: var(--info); }
.pri-p3 { background: var(--neutral-soft); color: var(--text-muted); }

/* tabs (Notion-style underline) */
.page-tabs {
  display: flex; gap: 2px;
  border-bottom: 1px solid var(--border);
  padding-left: 4px;
  margin-bottom: -1px;
}
.page-tab {
  background: transparent; border: none;
  padding: 8px 14px;
  font-size: 13px; color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  text-transform: capitalize;
  font-family: inherit;
}
.page-tab:hover { color: var(--text-primary); }
.page-tab.active {
  color: var(--text-primary); font-weight: 500;
  border-bottom-color: var(--accent);
}

/* kanban refinements */
.kanban {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  min-height: 400px;
}
.kanban-column {
  background: var(--bg-tertiary);
  border-radius: var(--radius-lg);
  display: flex; flex-direction: column;
  min-width: 0;
  max-height: 600px;
}
.kanban-column-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  text-transform: capitalize;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.kanban-count {
  background: var(--bg-primary); color: var(--text-muted);
  border-radius: 999px; padding: 1px 8px; font-size: 11px; font-weight: 500;
  border: 1px solid var(--border);
}
.kanban-column-body { padding: 0 8px 8px; display: flex; flex-direction: column; gap: 6px; flex: 1; overflow-y: auto; }
.kanban-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  box-shadow: var(--shadow-xs);
  transition: box-shadow 80ms ease, border-color 80ms ease;
}
.kanban-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}
.kanban-card-title { font-size: 13px; font-weight: 500; margin-bottom: 8px; color: var(--text-primary); line-height: 1.4; }
.kanban-card-meta { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.kanban-card-assignee { font-size: 11px; color: var(--text-muted); }

/* buttons (refined) */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: var(--radius-md);
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent;
  font-family: inherit;
  transition: background-color 80ms ease, border-color 80ms ease;
}
.btn-primary {
  background: var(--accent); color: var(--text-on-accent);
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:disabled { background: var(--text-muted); cursor: not-allowed; }
.btn-ghost {
  background: var(--bg-elevated); color: var(--text-secondary);
  border-color: var(--border);
}
.btn-ghost:hover { color: var(--text-primary); border-color: var(--border-strong); background: var(--bg-hover); }
.btn-danger { background: var(--danger); color: var(--text-on-accent); }
.btn-danger:hover { filter: brightness(1.05); }
.btn-sm { padding: 3px 10px; font-size: 12px; }

.input {
  background: var(--bg-primary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 6px 12px; font-family: inherit; font-size: 13px;
}
.input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }

.alert { padding: 10px 14px; border-radius: var(--radius-md); font-size: 12px; margin: 0 16px 12px; }
.alert-danger { background: var(--danger-soft); color: var(--danger); border: 1px solid var(--danger); border-color: color-mix(in srgb, var(--danger) 30%, transparent); }

.add-gate-form-v2 { display: flex; flex-wrap: wrap; gap: 8px; padding: 16px; background: var(--bg-tertiary); border-bottom: 1px solid var(--border); }

/* overview */
.overview-header { margin-bottom: 4px; }
.overview-header h2 { margin: 0 0 8px; font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
.overview-header p { margin: 0; color: var(--text-secondary); font-size: 14px; line-height: 1.5; }
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}
.overview-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  cursor: pointer;
  transition: border-color 120ms ease, transform 120ms ease;
}
.overview-card:hover { border-color: var(--accent); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.overview-card-value { font-size: 28px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; font-feature-settings: "tnum" 1; }
.overview-card-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 500; }
.overview-card.tone-info .overview-card-value { color: var(--accent); }
.overview-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.overview-bar-chart { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.overview-bar-item { display: grid; grid-template-columns: 100px 1fr 40px; align-items: center; gap: 12px; }
.overview-bar-label { font-size: 12px; color: var(--text-secondary); text-transform: capitalize; }
.overview-bar-track { background: var(--bg-tertiary); border-radius: var(--radius-sm); height: 8px; overflow: hidden; }
.overview-bar-fill { height: 100%; border-radius: var(--radius-sm); transition: width 240ms ease; }
.bar-pending     { background: var(--text-muted); }
.bar-in_progress { background: var(--info); }
.bar-completed   { background: var(--success); }
.bar-failed      { background: var(--danger); }
.bar-blocked     { background: var(--warning); }
.overview-bar-count { font-size: 12px; color: var(--text-primary); text-align: right; font-weight: 600; font-feature-settings: "tnum" 1; }
.overview-event-list { list-style: none; padding: 0; margin: 0; }
.overview-event-list li {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid var(--border-subtle);
}
.overview-event-list li:last-child { border-bottom: none; }
.overview-event-source { color: var(--text-secondary); font-size: 12px; }
.overview-event-time { margin-left: auto; color: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.empty-state-inline { padding: 16px; color: var(--text-muted); font-style: italic; }
.page-chat .chat-panel { height: calc(100vh - 96px); margin: 0; border-radius: var(--radius-lg); border: 1px solid var(--border); }
```

### Step 2: hub_pages.jsx — add PageHero wrapper

In `hub_pages.jsx`, add inside the IIFE:

```jsx
function PageHero({ title, subtitle, actions }) {
  return (
    <div className="page-hero">
      <div className="page-hero-meta">
        <h1 className="page-hero-title">{title}</h1>
        {subtitle && <p className="page-hero-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-hero-actions">{actions}</div>}
    </div>
  );
}
```

Then at the top of EACH per-hub page render, ADD:

```jsx
<PageHero title="CodeHub" subtitle="Pull requests, commits, and branches in this project." />
// or
<PageHero title="APIHub" subtitle="Endpoints, tables, consumers, and MCP servers." />
// or
<PageHero title="WorkHub" subtitle="Tasks board, pages, and reviews." />
// or
<PageHero title="EventHub" subtitle="Hub event stream and conversation threads." />
// or
<PageHero title="RunHub" subtitle="End-to-end run history and current status." />
```

Insert as the FIRST child of `<div className="page">` in each page.

### Step 3: cross_cutting_pages.jsx — same hero treatment

Add the same `PageHero` (or import-via-window) to `ReferencesPage`, `GatesPage`, `ChatPage`. For `OverviewPage`, the existing `<div className="overview-header">` already plays this role; just refine its CSS as the page-hero above does.

For `ReferencesPage`:
```jsx
<PageHero
  title="References"
  subtitle="Upload reference materials. Files land in workspace/references/ and are auto-indexed for agents."
  actions={<button onClick={...} disabled={pending} className="btn btn-primary">{pending ? "Uploading…" : "+ Upload"}</button>} />
```

For `GatesPage`:
```jsx
<PageHero
  title="Delivery Gates"
  subtitle="User-defined checks. Failures block Deliver until resolved."
  actions={<button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>{showAdd ? "Cancel" : "+ Add Gate"}</button>} />
```

For `ChatPage`:
```jsx
<PageHero
  title="Chat with Agents"
  subtitle="Send a message to one or more agents. Messages have the highest priority and route to all agent inboxes." />
```

Inside each page, REMOVE the in-section action button (since it moved to the hero) — keep section header simple.

### Step 4: GitHub-style 2-line rows in tables

Where useful (e.g., the PR list, the endpoint list), use the `.cell-primary` + `.cell-meta` pattern instead of one-row text. Example for the CodeHub PR table:

```jsx
{
  key: "title", label: "Pull Request",
  render: r => (
    <>
      <span className="cell-primary">{r.title || "(untitled)"}</span>
      <span className="cell-meta">
        <span className="cell-meta-item"><code>#{(r.id || "").substr(0, 8)}</code></span>
        <span className="cell-meta-item">{r.author || "—"}</span>
        <span className="cell-meta-item">opened {r.created_at ? new Date(r.created_at * 1000).toLocaleDateString() : "—"}</span>
      </span>
    </>
  )
}
```

And the corresponding plain "author / id" columns can be removed since they're embedded.

Apply the same pattern to:
- APIHub endpoints table (path + method up top, provider + status meta below)
- WorkHub tasks (in non-kanban "list" view if added — for the kanban, the existing card layout is fine)
- RunHub runs (run id + branch top; status + started_at + duration below)

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/styles/pages.css \
        agent/env_generator/llm_generator/live_monitor/src/hub_pages.jsx \
        agent/env_generator/llm_generator/live_monitor/src/cross_cutting_pages.jsx
git commit -m "Cutover 42: page hero pattern + GitHub-style multi-line rows + refined chips"
```

---

## Task 6: Homepage polish (GitHub-style repo cards) + final smoke + push

**Files:**
- Modify: `live_monitor/src/homepage.jsx`
- Modify: `live_monitor/styles/homepage.css`

### Step 1: Refined project cards

Inspired by GitHub's "My contributions" list — each row 2 lines (title + metadata), hover highlight, language dot, status pill on right. Width is full not card-grid.

Replace the project grid render with a list:

```jsx
<ul className="project-list">
  {projects.map(p => (
    <li key={p.id} className="project-row"
        onClick={() => window.LiveMonitorRouter.navigateTo(`/projects/${encodeURIComponent(p.id)}/overview`)}>
      <div className="project-row-avatar">{p.name.substr(0, 2).toUpperCase()}</div>
      <div className="project-row-meta">
        <div className="project-row-title">{p.name}</div>
        <div className="project-row-sub">
          {p.description ? <span className="project-row-desc">{p.description}</span> : <em>no description</em>}
          <span className="project-row-meta-dot">·</span>
          <span className="project-row-id"><code>{p.id}</code></span>
          <span className="project-row-meta-dot">·</span>
          <span>Updated {fmtTime(p.last_active_at)}</span>
        </div>
      </div>
      <div className="project-row-status">
        <span className={"chip chip-" + p.status}>{p.status}</span>
      </div>
    </li>
  ))}
</ul>
```

### Step 2: homepage.css

```css
.homepage {
  max-width: 1200px;
  margin: 0 auto;
  padding: 48px 32px;
}
.homepage-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 32px; }
.homepage-header h1 { font-size: 28px; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.02em; }
.homepage-subtitle { color: var(--text-secondary); margin: 0; font-size: 14px; }
.homepage-actions { display: flex; gap: 8px; flex-shrink: 0; }

.project-list { list-style: none; padding: 0; margin: 0; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
.project-row {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: background-color 80ms ease;
}
.project-row:last-child { border-bottom: none; }
.project-row:hover { background: var(--bg-hover); }
.project-row-avatar {
  width: 36px; height: 36px; flex-shrink: 0;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--accent), var(--accent-hover));
  color: var(--text-on-accent);
  font-size: 13px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.5px;
  box-shadow: var(--shadow-xs);
}
.project-row-meta { flex: 1; min-width: 0; }
.project-row-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 2px; }
.project-row-sub { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.project-row-desc { color: var(--text-secondary); }
.project-row-meta-dot { opacity: 0.5; }
.project-row-id code { background: var(--bg-tertiary); padding: 1px 6px; border-radius: var(--radius-sm); color: var(--text-secondary); }
.project-row-status { flex-shrink: 0; }
```

### Step 3: Manual smoke + restart

```bash
pkill -f "live_monitor_server.*4500" 2>/dev/null
sleep 1
cd /data/common/haibotong/env-gen
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/envgen_demo --host 0.0.0.0 --port 4500 > /tmp/envgen_demo_server.log 2>&1 &
sleep 2
curl -sS http://127.0.0.1:4500/api/ping
```

Open the browser. Verify:
- IBM Plex Sans font loads (check Network → fonts.gstatic.com)
- Sidebar shows grouped sections (Hubs / Workspace)
- SVG icons in sidebar
- Workspace switcher avatar visible at top
- Theme toggle in sidebar footer (sun/moon icons)
- No more screen flash on polls
- Click each hub → page renders (not Loading)

### Commit

```bash
git add agent/env_generator/llm_generator/live_monitor/src/homepage.jsx \
        agent/env_generator/llm_generator/live_monitor/styles/homepage.css
git commit -m "Cutover 42: homepage refined (GitHub-style project rows + avatars)"
```

---

## Task 7: Migration log + push + ff-merge

### Step 1: Regressions sanity

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_live_monitor_endpoints.py agent/tests/test_user_gates_endpoints.py agent/tests/test_references.py -q
```

### Step 2: migration log

```markdown
# Cutover 42: Reference-Driven UI Polish

**Branch:** `haibotong-cutover-42-ui-polish`
**Date:** 2026-05-26

## What

Visual refinement informed by Notion, GitHub, Apifox, Jira, and Gemini
reference screenshots. Three pillars:

1. **Typography**: IBM Plex Sans (body) + IBM Plex Mono (code) via
   Google Fonts. Distinctive industrial heritage; avoids Inter/Roboto
   AI cliché.
2. **Notion-grouped sidebar**: workspace switcher with avatar at top,
   nav grouped under section headers (Hubs / Workspace), SVG icons
   throughout (Lucide-style 16x16 strokes), theme/logout/collapse
   moved to sidebar footer as icon buttons.
3. **GitHub-style page hero + dense tables**: each page has a hero
   (title + subtitle + actions), multi-line table rows with `.cell-primary`
   + `.cell-meta` metadata, refined chip colors (soft Notion-style
   tints), tabs use Notion-underline.

Also bundled the inline-render bug fix: `PageContent` was an inner-defined
component in `ProjectShell` → React saw a new function reference every
render → full unmount+remount every 1.8s poll → form drafts wiped, screen
flashed. Fixed by computing `pageContent` as a value (not a component)
and inlining it in JSX.

## Commits

- (SHA) Cutover 42: pre-flight baseline (PageContent inline render bug fix)
- (SHA) Cutover 42: IBM Plex Sans/Mono + refined Notion/GitHub palette
- (SHA) Cutover 42: SVG icon library (Lucide-style stroke icons)
- (SHA) Cutover 42: grouped sidebar with workspace switcher + SVG icons
- (SHA) Cutover 42: page hero pattern + GitHub-style multi-line rows + refined chips
- (SHA) Cutover 42: homepage refined (GitHub-style project rows + avatars)
- (this) Cutover 42: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Pytest collect: ~1163 (no test changes)

## New surfaces

### Frontend
- Google Fonts CDN preload + `IBM Plex Sans` + `IBM Plex Mono`
- Refined design tokens (warmer light, GitHub-precision dark)
- `src/icons.jsx` — `window.Icons` Lucide-style SVG icon set (16 icons)
- `<PageHero title subtitle actions />` pattern in `hub_pages.jsx` + reused in cross-cutting
- Grouped sidebar with `NAV_GROUPS`: Overview / Hubs / Workspace
- Workspace switcher with project initials avatar
- Theme toggle + logout moved into sidebar footer
- Homepage project list (GitHub-style 2-line rows, no longer card grid)
- Status chips refined: soft tinted, ~Notion palette

## Critical bug fix (root cause)

`function PageContent() { ... }` defined inside `ProjectShell`:
- Every parent render creates a fresh function reference
- React's reconciler treats `<PageContent />` as a new component type
- Triggers full unmount → remount of the entire page tree
- Local state (form drafts, scroll, expanded sections) wiped on every poll
- User-visible: screen "refreshes" every 1.8s; Gates form clears mid-typing

Fix: compute `pageContent` as a React element (not a component), inline
into JSX. Now ProjectShell's render reconciles by type (CodeHubPage,
GatesPage, etc. are stable module-level functions), preserving local
state across renders.

## Known limits

- Old `hub_panels.jsx` still ships but is unused — purge in a future cutover.
- Sidebar collapse-to-icon-only mode hides section headers; icons stand
  alone without labels. Acceptable but tooltips could be added.
- Page hero `actions` slot defined but only Refs/Gates currently use it.
  Future cutover may add per-page primary actions (e.g., "New PR" on CodeHub).
- IBM Plex Sans loads from Google CDN; air-gapped deployments would need
  self-hosting.
- Workspace switcher is single-project; future cutover could make it a
  dropdown to switch projects without going home.
```

### Step 3: commit + push + ff-merge

```bash
git add docs/superpowers/migration-logs/42-ui-polish.md docs/superpowers/plans/2026-05-26-cutover-42-ui-polish.md
git commit -m "Cutover 42: migration log"
git push -u red-env-gen haibotong-cutover-42-ui-polish
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-42-ui-polish
git merge --ff-only haibotong-cutover-42-ui-polish
git push red-env-gen haibotong-0521-pipeline-web-tools
```

### Step 4: restart server from parent

```bash
pkill -f "live_monitor_server.*4500" 2>/dev/null
sleep 1
cd /data/common/haibotong/env-gen
/home/haibotong/miniconda3/envs/dt/bin/python agent/env_generator/llm_generator/live_monitor_server.py --workspaces-root /tmp/envgen_demo --host 0.0.0.0 --port 4500 > /tmp/envgen_demo_server.log 2>&1 &
sleep 2
curl -sS http://127.0.0.1:4500/api/ping
```
