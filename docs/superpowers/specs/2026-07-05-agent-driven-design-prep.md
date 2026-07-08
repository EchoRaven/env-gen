# Agent-Driven Design-Prep — Re-Architecture Spec

**Date:** 2026-07-05  **Branch:** feat/pipeline-opt-6  **Status:** Approved-direction (user handed the field manual as the spec basis + "继续优化")
**Source of truth:** `/data/common/haibotong/screenshot_diagnose.md` (Page-Mimicry Generation Field Manual). This spec encodes its methodology into a dedicated agent.

## Why re-architect (supersedes the v1 "single-shot analyst" decision)

Design-Prep v1 measured colors DETERMINISTICALLY and had ONE single-shot analyst reason over the
whole screenshot. The user's directive: **the agent must do the per-component measurement itself**
— decompose into components, then crop + eyedrop + analyze EACH one in a tool-loop, inside our
configurable-agent framework. "否则怎么知道每个组件的具体颜色、设计." Whole-page reasoning can't
reach per-component fidelity; the manual's entire thesis is measure-per-component, "别猜颜色".

The tools to do this ALREADY EXIST as agent tools (`tools/material_prep_tools.py`): `sample_color`
(row-mode bg / saturation-scan accent, §3.1), `crop_reference` (§2), `extract_palette`,
`zoom_compare` (§6), `decompose_reference`. They're bundled (`reference_images`, `vision_tools`)
and even handed to the frontend lane — which ignores them (LLM-voluntary → 0 calls). The fix is a
DEDICATED agent whose sole job is this measurement, so it actually runs it.

## Architecture

A new **`design_analyst` configurable-agent profile** (agents_config.yaml), spawned ONCE at run
start (one-shot, via `agent_spawn_service.spawn` — the test-user-squad precedent), not a resident
lane. It runs the manual's stages 1–4 (collect → crop → per-component eyedrop → per-component
spec), then emits `design/design_system.json` + `.md`. Stages 5–7 (build/compare/zoom-diff/
adversarial-review) stay with the existing frontend + visual-fidelity loop, now fed by the richer
doc. Deterministic asset ingestion/staging (`ingest_assets`, `stage_design_assets`) stays as-is.

### The agent's tool chain (all exist except measure_layout)
- `list_reference_images` / `view_image` — enumerate + look.
- `decompose_reference` — name the components + regions per screen (§2 region proposer).
- `crop_reference` — physically crop each component → `design/crops/<screen>__<comp>.png` (§2). This
  closes the "no physical crops" gap: the AGENT produces them.
- `sample_color` — per component: `kind=background` row-mode (opaque chrome truth) vs
  `kind=accent` saturation-scan (the semantic/button color); target chrome-strip vs translucent
  panel separately (§3.1, §3.3).
- `extract_palette` — global palette seed.
- **`measure_layout` (NEW, §15 gap)** — PIL pixel measurement the agent currently CANNOT do:
  column count (gap-line detection), content width (non-dark edge scan), nav-item spacing
  (y-clustering), dominant button color (bright-pixel mode). The manual's "key weapon" for
  spacing/columns that "肉眼量不准".
- `list_assets` / `annotate_asset` — map components → real staged assets; per-element brand-asset
  vs generatable decision (§10, §17). Brand glyphs/logos come from the user's `assets/`; generic
  icons/layout the frontend generates.
- `file` write tools — persist `design/design_system.json` + `.md` (schema below) + per-component
  spec files. (No new write tool — the agent writes JSON via file tools; a light validator may be
  added if the agent's JSON drifts.)

### The agent's method (prompt = the field manual, condensed)
Encoded in `prompts/v3/design_analyst.j2`:
1. **Lever order** (§8): 大面积背景/材质 > 精确色 > 信息密度/状态分布 > 图标风格 > 结构. Spend
   effort top-down; structure is LAST.
2. **Per screen** → `decompose_reference` → for EACH component: `crop_reference` → `view_image` the
   crop → `sample_color` (bg row-mode + accent saturation; chrome vs translucent panel separately)
   → optional `measure_layout` for spacing/columns → write the component spec (layout, MEASURED
   tokens, dimensions, content, state).
3. **别猜颜色** (§3): every hex is measured, never guessed. Distinguish opaque chrome (#292929-class)
   from wallpaper-bled translucent panels (navy) — single-point sampling lies.
4. **塌缩点 checklist** (§6, §16): flag/spec the high-frequency collapses — missing/extra small
   elements, dropped semantic colors (all-gray is the #1 collapse), unrealistic state distribution
   (all-read vs unread-blue-dominant), compressed density, split compound controls; social-UI:
   nav icon order/shape, Follow/Following, repost+counts, no stories bar in feed, global dock.
5. **Brand boundary** (§10, §17): per element decide brand-asset (→ user `assets/`) vs generatable.
6. **Emit** the global palette + type scale + per-component specs → design_system.json/.md.

## design_system.json (unchanged schema from v1, now agent-authored)
`{ design_system:{palette,type_scale,radius_scale,shadow_scale,iconography,theme}, assets:[…],
screens:[{name,reference,layout,components:[{id,crop,region,colors{MEASURED},typography,radius,
shadow,role,state,assets:[ids],build_notes}]}] }`. Colors are the agent's MEASURED values.

## Build increments (TDD, each committed)
1. **`measure_layout` tool** (§15 PIL measurement) — new deterministic tool + bundle wiring. Fully
   unit-testable now.
2. **`design_analyst.j2` prompt** — encodes the manual. Render-testable + reviewable.
3. **`design_analyst` profile** in agents_config.yaml — one-shot, tools = the chain above. Config +
   tool-surface validation testable.
4. **One-shot spawn wiring** — orchestrator spawns `design_analyst` at run start (has spawn_service);
   `run_design_prep` keeps the deterministic asset staging + becomes the fallback when spawn is
   unavailable. Config-testable; live agent run needs API keys.

## Validation
Unit tests per increment (no keys). The live agent run (does it follow the prompt, call the tools,
produce a good doc) needs `OPENAI_API_KEY` — deferred to a keyed run on instagram-core with
`--design-input` (real IG assets + the manual's checklist as the acceptance criteria: §13).

## Out of scope (this pass)
Stages 5–7 automation (they exist: frontend build loop + visual_fidelity zoom-diff + the adversarial
review workflow). DOM-probe live-site measurement (§12 — that's manual asset sourcing, user-provided).
