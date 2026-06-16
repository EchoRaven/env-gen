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

- `61d10bb3` Cutover 42: pre-flight baseline (PageContent inline render bug fix)
- `826a7fb8` Cutover 42: IBM Plex Sans/Mono + refined Notion/GitHub palette
- `46a2b587` Cutover 42: SVG icon library (Lucide-style stroke icons)
- `474d53a3` Cutover 42: grouped sidebar with workspace switcher + SVG icons
- `bc76197e` Cutover 42: page hero pattern + GitHub-style multi-line rows + refined chips
- `8ffb04d0` Cutover 42: homepage refined (GitHub-style project rows + avatars)
- (this) Cutover 42: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Endpoint sweep (`test_live_monitor_endpoints` + `test_user_gates_endpoints` + `test_references`): 100 passed
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
