# Design-Prep Phase (Design Analysis Agent) — Design Spec

**Date:** 2026-07-04
**Branch:** feat/pipeline-opt-6
**Status:** Approved (design)

## Problem

The pipeline's visual-fidelity loop under-performs. In outlook run-65: 9 `component_specs`
were generated, but only **1** `MEASURED COLOR DIFF` fired, `zoom_compare` was called **0**
times (the frontend lane ignores the embedded call), and visual fidelity **escaped at the
900s bound 3×** instead of matching. Two root causes:

1. **No real-assets channel.** Only reference *images* are provided (`--reference-dir`). The
   frontend lane *draws approximations* of icons/logos/images, so the output looks AI-drawn;
   #75b even strips external stock photos as damage control.
2. **Design guidance is thin + LLM-voluntary.** The pre-gen `decompose_reference` emits
   *color-only* `component_specs`, and #53 embeds a `zoom_compare(...)` call in remediation
   text and *hopes the lane runs it* — which it doesn't. This violates both the user's
   methodology ("量取不靠猜 — measure, don't guess") and the pipeline's by-construction ethos.

## Goal

A one-shot pre-generation **Design-Prep phase** that consumes user-provided references, docs,
and **real assets**, measures the reference deterministically, has a single-shot analyst agent
write a rich design document, stages the real assets, and makes the frontend build **from the
document + reference the real assets** — so the output is reference-accurate and uses real
icons/logos/images, and the visual loop converges instead of escaping.

## Decisions (locked)

- **Asset pipeline:** staged + code-referenced. Real assets are physically staged into the
  generated frontend and referenced in code — not merely described.
- **Architecture:** hybrid. Deterministic tools *measure* (crop, eyedropper, palette, asset
  staging); a dedicated single-shot **analyst agent** *reasons* (per-component style/UX prose,
  asset annotations, component→crop→asset mapping). Honors "separate agent" + "measure, don't
  guess"; reuses the existing decompose/reference-spec integration points; no new team member
  with its own coordination lifecycle.

## Inputs

New CLI: `--design-input <dir>` with three OPTIONAL subfolders (back-compatible — if
`--design-input` is absent, fall back to today's `--reference-dir`, references-only):

- `references/` — reference screenshots (png/jpg).
- `docs/` — reference docs (md/html/pdf/txt): feature write-ups, design notes.
- `assets/` — real assets (svg icons, logos, buttons, background images), optionally grouped
  in `icons/ logos/ backgrounds/ buttons/` subfolders (grouping is a hint, not required).

## Phase flow (runs once, at run start, before the frontend/backend lanes)

1. **Deterministic measure** (functions; reuse + extend `material_prep.py` / `reference_materials.py`):
   - Compile `docs/` → `design/reference_spec.json` (existing `compile_reference_spec`).
   - Crop each reference into candidate component regions → `design/crops/<screen>/<component>.png`.
   - Sample exact hex per region (`region_background` / `find_accent`), extract the global palette.
   - **Ingest `assets/`** → a manifest entry per file: `{id, file, type, dims, transparent,
     dominant_colors, staged_path}`; **stage** each file into `design/assets/`.
2. **Single-shot analyst agent** (dedicated, runs once, does not reappear):
   - Inputs: the crops + measured colors + asset manifest (with measured colors/dims) + the
     compiled docs.
   - Task: per reference screen → identify components → per component write the rich design
     spec (**measured** colors from step 1, typography, spacing, radius, shadow, layout role,
     states) + **map to real assets** (this component uses asset ids …); annotate each asset
     (what it depicts, style, where-used); produce the global design system (palette, type
     scale, radius/shadow scales, iconography style, theme(s)).
   - Tools: `crop_reference`, `sample_color`, `extract_palette`, `view_image`,
     `list_references`, `list_assets`, **`annotate_asset`** (vision-describe an asset image) — new.
3. **Emit:** `design/design_system.json` (structured) + `design/design_system.md` (narrative),
   and keep writing `design/component_specs/<screen>.json` (so the existing color-diff gate and
   its consumers keep working — measured colors live in both).

## Design document schema (`design_system.json`)

```jsonc
{
  "design_system": {
    "palette": { "bg": "#0c1013", "surface": "#1f1f22", "accent": "#3880f3", "text": "#f5f5f5", "…": "…" },
    "type_scale": [ { "role": "h1", "size_px": 40, "weight": 700 }, { "role": "body", "size_px": 14, "weight": 400 } ],
    "radius_scale": { "sm": 4, "md": 8, "pill": 999 },
    "shadow_scale": [ "none", "0 1px 2px rgba(0,0,0,.2)" ],
    "iconography": { "style": "line", "stroke_px": 1.5 },
    "theme": { "default": "dark", "themes": ["dark", "light"] }
  },
  "assets": [
    { "id": "logo_ig", "file": "assets/ig_wordmark.svg", "type": "svg", "staged_path": "public/assets/ig_wordmark.svg",
      "dims": [103, 29], "transparent": true, "description": "Instagram wordmark", "use": ["top nav brand", "login header"] }
  ],
  "screens": [
    { "name": "home_feed", "reference": "references/home.png", "layout": "slim top bar + centered single-column feed + right rail",
      "components": [
        { "id": "top_nav", "crop": "design/crops/home_feed/top_nav.png", "region": [0, 0, 1, 0.08],
          "colors": { "bg": "#ffffff", "accent": "#3880f3" },   // MEASURED
          "typography": { "brand": { "size_px": 24, "weight": 700 } }, "radius": 0, "shadow": "none",
          "role": "global chrome", "states": [], "assets": ["logo_ig", "icon_heart"],
          "build_notes": "white top bar, IG wordmark left, action icons right" }
      ] }
  ]
}
```

`design_system.md` is the same content rendered as readable narrative for the lanes.

## Asset pipeline (staging + reference)

- The deterministic layer stages `assets/` → `design/assets/` and records `staged_path`
  (`public/assets/<file>`).
- At frontend scaffold, the framework COPIES `design/assets/` → `app/frontend/public/assets/`
  (served + bundled).
- `frontend_agent.j2` gets a new rule: *for any icon/logo/image a component needs, reference
  the real asset from the manifest (`/assets/<file>` or import the SVG) — do NOT draw an
  approximation; the manifest maps assets → components.*
- Backed by a **light gate**: a component the manifest maps to a real asset that does not
  reference that asset (by path/name) in its file = flagged (advisory remediation, not a hard
  block, to avoid false-blocking). Makes #75b's "strip external photos" largely unnecessary.

## Integration

- **Frontend lane:** `frontend_agent.j2` points at `design/design_system.md` + `.json` + the
  asset manifest + the use-real-assets rule. The visual/color-diff gates keep reading the
  measured colors (now from the richer doc; `component_specs` stays as the gate's source).
- **Backend lane:** light — reads `screens[]`/`components[]` to align data shapes to what the
  UI actually renders (secondary consumer; the primary consumer is the frontend).

## Testing

- Unit: asset ingestion + manifest correctness (id/type/dims/transparency/dominant colors,
  staged path); crop + color sampling determinism; `design_system.json` schema validity;
  back-compat (no `--design-input` → references-only, unchanged); the frontend use-real-assets
  gate (flag a component that ignores a mapped asset; don't flag one that uses it).
- Integration: the Design-Prep phase end-to-end on a small fixture (references + assets) →
  asserts `design_system.json` + staged assets + `component_specs` are produced.

## Validation

Assemble the 3 folders for instagram (references exist; `docs/` = the IG optimization guide +
reference docs; `assets/` = real IG icons/logos — e.g. the wordmark SVG, glyph icons, the
`close_friends.webp`). Run instagram-core with `--design-input` and verify: (a) the generated
frontend *references the real assets* (grep the built code for `/assets/<file>`), (b) the
color-diff gate fires with measured deviations, (c) visual fidelity converges rather than
escaping at the 900s bound.

## Out of scope (YAGNI)

- SVG optimization / re-coloring, sprite sheets.
- session-id live scraping of real sites (the guide's §5 — that's a manual asset-sourcing
  method, not part of the automated phase; the user provides assets).
- Automated typography *measurement* from pixels (text-band scanning) — the analyst agent
  estimates type scale from the crops; deterministic pixel font-measurement is a later refinement.
