# PIPELINE FIX PROPOSAL #39 — frontend-quality: blank + stub pages (the create_release blocker)

Run #36 reached the delivery gate with a CORRECT backend (live-curl verified) but failed UI smoke:
"frontend renders a BLANK PAGE for /register and /notes". Root-caused from the generated tree
(generated/smoke-notes/app/frontend). THREE concrete gaps, the first deterministic:

## G1 (DETERMINISTIC, primary) — declared pages are ORPHANED by a non-router App.jsx
- The entry `main.jsx` → `src/App.jsx`. But `src/App.jsx` is a 24-line hand-rolled STUB: no
  React Router, no `<Routes>`, dropped the `@framework-managed-routes` marker, imports
  `components/LoginPage`+`TenantPicker`, and renders `if(!token) <LoginPage/>` else a placeholder
  `<h1>Notes App</h1>{/* Note editor will go here */}`.
- The DECLARED pages (`pages/Register.jsx`, `pages/NotesListPage.jsx`, `pages/NoteEditorPage.jsx`,
  `pages/LoginPage.jsx`) exist but are NEVER imported/routed → `/register`,`/notes` match nothing → blank.
- WHY the framework didn't fix it: `frontend_scaffold.scaffold_pages_from_contract` only (re)writes
  App.jsx when it's empty OR still carries the marker (frontend_scaffold.py:416) — the lane's stub
  dropped the marker, so it's left alone; and `project_missing_ui_routes` injects only into an
  existing `</Routes>` (frontend_scaffold.py:328) — the stub has none → no-op. BOTH bail → orphaned.

### G1 fix (deterministic, generalizable)
In `scaffold_pages_from_contract`, REGENERATE App.jsx (baseline `BrowserRouter`+`Routes` wiring every
declared ui_page → its page component, with imports) when App.jsx has **no usable router** (no
`</Routes>` found), EVEN IF the marker was dropped. Only PRESERVE a lane App.jsx that actually has a
`<Routes>` block (a real router the lane authored — then keep #19's additive injection). Rationale:
a stub that drops the marker AND has no router is not a legitimate "lane took over routing" — it's
broken (guaranteed blank pages). This makes frontend routing consistency-by-construction (the backend
analogue: framework owns the router wiring; the lane owns page CONTENT). Verify it does not clobber a
lane that authored a real custom router with layout nesting (those have `<Routes>` → preserved).

## G2 (model-content + GATE GAP) — pure-placeholder stub pages slip the dead-controls gate
- All declared pages are 8-line PLACEHOLDERS: `<h2>Notes List</h2><p>This section is being set up.</p>`
  — ZERO API calls, forms, state, or handlers. So even once routed (G1), they render empty stubs;
  the app delivers nothing usable.
- `frontend_audit._page_dead_controls` (frontend_audit.py:45-48) returns True only for
  `interactive(<form/submit) AND not bound` — a page with NO interactive markup at all has
  `interactive=False` → NOT flagged. So a pure "being set up" placeholder PASSES the gate → no
  remediation pressure → the lane never builds the real page.

### G2 fix
Add a STUB-PAGE detection to the frontend audit/delivery gate: a declared ui_page whose component is a
placeholder — heuristics: contains placeholder text (`being set up`/`under construction`/`coming
soon`/`TODO`/`placeholder`) OR (declared non-empty `apis_used` BUT the file references NO api call /
fetch / handler / form / input) — is flagged (a real failing check, like dead_controls) → files a
remediation task to the frontend lane. This is the C7 follow-up (surface stubs to DRIVE remediation).
Keep it a check that BLOCKS delivery (the app is non-functional with stubs) but is lane-fixable.

## G3 (prompt steer, supporting) — the few-shot/role doesn't strongly forbid placeholders
The frontend prompt already says "every interactive control must be wired" + "no framework fallback
pages — what you author is ALL the UI", but the lane still ships "being set up" placeholders. Add an
explicit clause: a page component MUST implement its declared purpose (render its data via its
`apis_used`, with the real list/form/editor) — a placeholder/"coming soon" body is a FAILED page, not
a deliverable. (Prose is weak alone — G2's gate is what enforces it.)

## Open questions for the reviewer
1. G1: confirm `scaffold_pages_from_contract` regenerating on "no `</Routes>`" won't clobber a
   legitimate lane router (those always contain `</Routes>` → preserved). Confirm the regen baseline
   wires the declared ui_pages' routes→components correctly (route + component from RegistryHub) and
   imports the page files. Does the baseline App.jsx (`_BASELINE_APP_JSX`) already enumerate declared
   pages, or only a static shell? (If static, the regen must project the declared pages in.)
2. G2: where best to place the stub gate — frontend_audit (per-page, flips implemented→stub) vs
   delivery_gate (aggregate)? Is there a false-positive risk for a legitimately-minimal page (e.g. a
   static "About" with no API)? Gate on declared `apis_used` non-empty to avoid flagging genuine
   static pages. Confirm the placeholder-text heuristic is safe (won't match real copy).
3. Is the blank-page (G1) the PRIMARY UI-smoke failure, and does fixing it + G2 plausibly let a future
   run deliver, or are there further UI-smoke checks (navigation, ui_flow) that also need real pages?

## Rank by impact on first create_release
G1 (deterministic, unblocks reachability) > G2 (drives real content via remediation) > G3 (supporting).
G1 alone makes pages reachable but still stubs; G1+G2 together are needed for a functional delivery.
