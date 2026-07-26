# Frontend projection quality cascade — design

**Date:** 2026-07-25
**Area:** env-generator frontend lane (`multi_agent/runtime/frontend_scaffold.py`)
**Builds on:** #296/#297 (measured floor). **Status:** cascade approved; Chunk B in progress.

## Strategy — a best-available page-projection cascade

When the framework gap-fills a page the lane left unbuilt, give it the best
treatment available, in order:

1. **Reference-matched** — the page's route resolves to a measured design screen
   → full `_render_reference_page` (real reference layout). *Fidelity lever.*
   Widening this coverage is **Chunk A** (careful — `_design_screen_for_route`
   already has anti-wrong-graft guards #226/#229; a wrong graft is worse than a floor).
2. **Enriched measured floor (shape-aware)** — no matching screen → a measured,
   counts-as-built floor whose LAYOUT fits the page's data shape: **grid**,
   **detail**, or **list**. This is **Chunk B** (this doc). Extends #297's
   always-a-row-list floor.
3. **Existing** — auth/landing templates, clean static no-api page (unchanged).

Separate follow-on track (**Chunk C**, not projector-side): reduce the frontend
lane's registry-bookkeeping overhead so Layer 1 (the lane authoring the real
reference page itself) covers more pages.

## Chunk B — shape-aware measured floor

### Goal
The no-reference measured floor (#297) always renders a row list. Upgrade it to
pick a layout that fits the page: a **grid** for gallery/explore surfaces, a
**detail** card for single-resource pages, a **list** otherwise. All three keep
the #297 invariants: `data-projected="ref"` + `_STRUCTURED_MARKER` + measured
colors + real fetch of the page's own endpoint → counts as BUILT, exempt from the
fallback detector. Env-agnostic: shape is inferred from THIS env's page/endpoint
semantics, never hardcoded product content.

### Design
Add `_floor_shape(page, get_ep, name) -> "grid" | "detail" | "list"`:
- **detail** when the GET path carries a path param (`{` or `:` in `get_ep`,
  e.g. `/api/videos/{id}`) OR the page's route/name/component/`name` hints match
  detail semantics (`detail`, `show`, `view`, `single`, `profile`). Path-param
  wins first (a single-resource endpoint is a detail page regardless of name).
- **grid** when the route/name/component/hints tokens intersect a gallery set
  (`explore`, `gallery`, `grid`, `discover`, `browse`, `photos`, `media`,
  `thumbnails`, `search`).
- **list** otherwise (the #297 default).

In the #297 measured branch, select the template by `_floor_shape(...)`:
- **list** — the existing #297 row list (unchanged).
- **grid** — a responsive card grid: `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`,
  each cell a measured surface card with a thumbnail (`_imgOf`) + title (`_titleOf`).
- **detail** — a measured detail card: fetch, take the single item
  (`data.item || data` or `rows[0]`), render a hero (`_imgOf`) + title + a field
  list (`_metaOf`/all scalar fields).

All templates reuse the `_imgOf/_titleOf/_subOf/_metaOf` helpers, the
`localStorage` token fetch of `get_ep`, the measured `_measured_nav_jsx`, the
`_measured_floor_colors` set, the `data-projected="ref"` root + inline measured
`backgroundColor`, and the `_STRUCTURED_MARKER` prefix. No-palette path
(`_measured_floor_colors` returns None) still emits the #297/legacy data-fallback
list unchanged.

### Testing (TDD)
Over `_project_page_component` with the measured palette:
1. grid page (name/route `explore`) → output has `grid-cols` + `data-projected="ref"`
   + measured color; not `data-fallback`.
2. detail page (`apis_used: ["GET /api/videos/{id}"]`) → output takes a single item
   (no `rows.map` list shell) + `data-projected="ref"` + measured; not `data-fallback`.
3. list page (plain collection GET, no gallery keyword) → row list (`rows.map`) +
   `data-projected="ref"`.
4. all three: `_is_generic_fallback_page(out)` is False; fetches own endpoint.
5. `_floor_shape` unit table: path-param→detail; explore→grid; messages→list.
6. no palette → unchanged data-fallback list (regression of #297 §2 guard).

### Scope guard
Only `_project_page_component`'s measured branch + a new `_floor_shape` helper +
the two new templates. No change to `_render_reference_page`, the matcher, the
detector/gate, or the prompt.
