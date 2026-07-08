# Design-Prep Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-shot pre-generation Design-Prep phase that ingests user references + docs + real assets, measures the reference deterministically, has a single-shot analyst agent write a rich `design_system.json/.md`, stages the real assets, and makes the frontend build from the doc + reference the real assets.

**Architecture:** Hybrid. Deterministic functions in `material_prep.py`/`design_prep.py` measure (crop, sample hex, palette, asset staging); a single-shot analyst agent enriches (per-component style/UX prose, asset annotations, component→asset mapping). One phase, run at run start, before the frontend/backend lanes.

**Tech Stack:** Python 3.11, PIL (pure, no numpy), the existing multi_agent runtime + tool bundles, Jinja2 prompts. Tests: pytest under `agent/tests/` (gitignored dev tests).

## Global Constraints

- Env-agnostic; delivery-safe; best-effort (never raise into the pipeline — a Design-Prep failure degrades to today's references-only behavior, never blocks a run).
- Back-compatible: absent `--design-input` → today's `--reference-dir` behavior, unchanged.
- Pure PIL (no numpy). Deterministic sampling (no randomness).
- All paths the frontend build sees are RELATIVE to `app/frontend/` (assets land in `app/frontend/public/assets/`, referenced as `/assets/<file>`).
- No `Co-Authored-By` trailer in commits (user preference). Branch: `feat/pipeline-opt-6`.

---

### Task 1: Asset ingestion + staging (deterministic)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/material_prep.py` (add `ingest_assets`)
- Test: `agent/tests/test_design_asset_ingest.py`

**Interfaces:**
- Produces: `ingest_assets(assets_dir: str|Path, stage_dir: str|Path) -> List[Dict]` — a manifest;
  each entry `{"id","file","type","dims":[w,h]|None,"transparent":bool,"dominant_colors":[hex],"staged_path"}`.
  `id` = slug of the filename stem; `type` ∈ {svg,png,jpg,webp,gif,other}; `staged_path` = `public/assets/<file>`.
  Copies each asset into `stage_dir`. Best-effort; `[]` on a missing dir; skips unreadable files.

- [ ] **Step 1: failing test** — a fixture dir with `heart.svg` + `logo.png` (RGBA) → manifest has 2 entries with correct id/type/transparent/staged_path, and both files copied into stage_dir. Also `ingest_assets("/nonexistent", tmp)==[]`.
- [ ] **Step 2: run → FAIL** (`ingest_assets` undefined).
- [ ] **Step 3: implement** — scan `assets_dir` recursively for image files; per file: `id=_slug(stem)` (dedupe on collision with `-2`), `type` from suffix, `dims`/`transparent` via PIL for rasters (svg → parse `viewBox`/width-height, transparent=True), `dominant_colors` via existing `extract_palette` for rasters (svg → `[]`), copy to `stage_dir/<relpath>`, `staged_path=f"public/assets/{relpath}"`. Wrap in try/except → best-effort.
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): asset ingestion + staging (#task1)`).

---

### Task 2: `--design-input` resolution (CLI + back-compat)

**Files:**
- Modify: `agent/env_generator/llm_generator/main.py` (add `--design-input` arg)
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/design_prep.py` (add `resolve_design_input`)
- Test: `agent/tests/test_design_input_resolve.py`

**Interfaces:**
- Produces: `resolve_design_input(design_input: str|None, reference_dir: str|None, reference_images: list) -> Dict`
  → `{"references":[paths], "docs":[paths], "assets_dir": str|None}`. If `design_input` set, read its
  `references/ docs/ assets/` subfolders; else fall back to `reference_dir`/`reference_images` (references-only,
  `docs=[]`, `assets_dir=None`). Missing subfolders → empty.

- [ ] **Step 1: failing test** — a fixture `design_input/` with `references/a.png`, `docs/x.md`, `assets/i.svg`
  → resolver returns references=[a.png], docs=[x.md], assets_dir ends with `assets`. And with
  `design_input=None, reference_dir=<dir of pngs>` → references from that dir, docs=[], assets_dir=None.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** `resolve_design_input`; add `parser.add_argument("--design-input", default=None)` in main.py + pass through to the orchestrator constructor path (thread as `design_input`).
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): --design-input resolution + back-compat (#task2)`).

---

### Task 3: Deterministic Design-Prep skeleton (measure → skeleton doc)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/design_prep.py` (add `build_skeleton_design_system`)
- Test: `agent/tests/test_design_prep_skeleton.py`

**Interfaces:**
- Consumes: `ingest_assets` (Task 1), the existing `material_prep.decompose_reference`/`extract_palette`/`crop_region`.
- Produces: `build_skeleton_design_system(resolved: Dict, output_dir: str|Path, *, existing_specs: Dict|None=None) -> Dict`
  → the skeleton `design_system` dict: `{"design_system":{"palette":{...measured...},"theme":{...}},"assets":[manifest],
  "screens":[{"name","reference","components":[{"id","crop","region","colors":{measured},"assets":[],"role":"","build_notes":""}]}]}`.
  Writes `design/assets/` (staged), records the manifest. Reuses `component_specs` regions/colors when present
  (from an earlier decompose) so we don't re-measure. Deterministic only — no LLM. Best-effort.

- [ ] **Step 1: failing test** — a fixture with one reference png + a `component_specs/<screen>.json` (region+bg/accent)
  + an assets dir → skeleton has `design_system.palette` (non-empty), `assets` = the manifest, and `screens[0].components`
  carry the measured `colors` from the spec, `assets:[]` empty (analyst fills later).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — palette via `extract_palette` over the references; assets via `ingest_assets` into
  `<output_dir>/design/assets`; screens/components from `existing_specs` (or `decompose_reference` output shape) with
  measured colors; theme default from palette luminance (dark if bg luminance < 0.5).
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): deterministic skeleton design_system (#task3)`).

---

### Task 4: `annotate_asset` tool + analyst enrichment pass

**Files:**
- Modify: `agent/tools/material_prep_tools.py` (add `annotate_asset`, `list_assets` to the tool set)
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/design_prep.py` (add `enrich_design_system`)
- Create: `agent/env_generator/llm_generator/multi_agent/prompts/v3/design_analyst.j2` (analyst system prompt)
- Test: `agent/tests/test_design_prep_enrich.py`

**Interfaces:**
- Consumes: the skeleton (Task 3), an `llm` client.
- Produces: `async enrich_design_system(skeleton: Dict, output_dir, llm) -> Dict` — the analyst agent (single-shot)
  reads the crops + measured colors + asset manifest + compiled docs, fills each component's `role`/`build_notes`/
  `typography`/`assets:[ids]` and each asset's `description`/`use`, and returns the enriched dict. Writes
  `design/design_system.json` + `design/design_system.md`. Best-effort: on any LLM error, writes the SKELETON
  (deterministic facts still ship). `annotate_asset(image_path)->{description,use}` is a vision tool.

- [ ] **Step 1: failing test** — with a MOCK llm returning a fixed enriched JSON (component→asset mapping + prose),
  `enrich_design_system(skeleton, tmp, mock)` writes `design_system.json` whose components carry `assets:["logo"]` +
  non-empty `build_notes`, and `design_system.md` exists. And with a MOCK llm that RAISES → the skeleton is written
  (never raises, deterministic facts preserved).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `design_analyst.j2` (measure-don't-guess: colors are MEASURED facts, do not change them;
  map each component to the real assets it should use; annotate assets); `enrich_design_system` builds the prompt from
  the skeleton + docs, calls llm, parses the JSON, merges (colors stay measured), writes both files. try/except → skeleton.
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): analyst enrichment + annotate_asset tool (#task4)`).

---

### Task 5: Phase entry + wire into run start

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/design_prep.py` (add `async run_design_prep`)
- Modify: the run-start path that today calls `compile_reference_spec` (grep: `compile_reference_spec` caller in the orchestrator/lifecycle) to also call `run_design_prep`
- Test: `agent/tests/test_design_prep_phase.py`

**Interfaces:**
- Produces: `async run_design_prep(design_input, reference_dir, reference_images, output_dir, llm) -> Dict` —
  resolve → skeleton → enrich → returns the design_system dict; writes all artifacts under `<output_dir>/design/`.
  Best-effort; returns `{}` on total failure (run continues references-only).

- [ ] **Step 1: failing test** — end-to-end on a fixture (`design_input/` with references+docs+assets, mock llm) →
  `<output_dir>/design/design_system.json` + `design/assets/<file>` + `design/component_specs/*` all exist.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** `run_design_prep` (compose Tasks 2–4 + `compile_reference_spec` for docs); wire the caller
  at run start (after the reference-spec compile), guarded by try/except.
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): phase entry + wired at run start (#task5)`).

---

### Task 6: Stage assets into the frontend + frontend use-real-assets rule

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py` (copy `design/assets/` → `app/frontend/public/assets/`)
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v3/frontend_agent.j2` (use-real-assets rule + point at design_system)
- Test: `agent/tests/test_frontend_asset_staging.py`

**Interfaces:**
- Produces: `stage_design_assets(output_dir) -> List[str]` — copies `<output_dir>/design/assets/*` into
  `<output_dir>/app/frontend/public/assets/`, returns the copied rel paths. Best-effort. Called in the frontend scaffold.

- [ ] **Step 1: failing test** — a fixture `design/assets/logo.svg` → after `stage_design_assets(out)`,
  `out/app/frontend/public/assets/logo.svg` exists.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** `stage_design_assets` + call it in `scaffold_frontend_baseline` (or the frontend scaffold entry);
  add the frontend_agent.j2 rule: "Real assets are in design/design_system.json → assets[] (staged at public/assets/).
  For any icon/logo/image a component needs, reference the real asset (`/assets/<file>` or import the SVG) — do NOT draw
  an approximation; the manifest maps assets → components."
- [ ] **Step 4: run → PASS** (+ assert the j2 contains "public/assets").
- [ ] **Step 5: commit** (`feat(design-prep): stage assets into frontend + use-real-assets rule (#task6)`).

---

### Task 7: use-real-assets advisory gate

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/frontend_audit.py` (add `audit_asset_usage`)
- Test: `agent/tests/test_asset_usage_audit.py`

**Interfaces:**
- Produces: `audit_asset_usage(frontend_dir, design_system: Dict) -> Dict` →
  `{"unused_mapped":[{"component","asset","file"}]}` — for each component whose `design_system` mapping names an
  asset, if NO frontend file references that asset's file basename → flag it. Advisory (feeds remediation text),
  NEVER a hard delivery block. Best-effort.

- [ ] **Step 1: failing test** — a design_system mapping `top_nav→logo (ig.svg)` + a frontend where no file mentions
  `ig.svg` → `unused_mapped` has 1 entry; a frontend where `TopNav.jsx` has `/assets/ig.svg` → `unused_mapped==[]`.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — collect mapped (component,asset,file); grep the frontend `src/` for each file basename;
  flag the misses.
- [ ] **Step 4: run → PASS.**
- [ ] **Step 5: commit** (`feat(design-prep): use-real-assets advisory audit (#task7)`).

---

## Self-Review

- **Spec coverage:** inputs+folders (Task 2), deterministic measure+asset ingest (Tasks 1,3), analyst agent+doc (Task 4),
  phase entry (Task 5), asset staging+frontend rule (Task 6), advisory gate (Task 7), tests (each task). Backend light-use:
  the doc's `screens[]/components[]` are readable by the backend lane via the same `design_system.json` — no separate task
  (the artifact exists; backend consumption is a prompt-note folded into a later polish, not core). ✓
- **Placeholder scan:** each task has concrete interfaces + test assertions + implementation approach. ✓
- **Type consistency:** `ingest_assets`→manifest (Task 1) consumed by `build_skeleton_design_system` (Task 3) as `assets`;
  skeleton (Task 3) consumed by `enrich_design_system` (Task 4); the enriched dict consumed by `run_design_prep` (Task 5)
  and `audit_asset_usage` (Task 7). Consistent. ✓

## Validation (post-implementation, not a task)

Assemble instagram's 3 folders (references exist; docs = the IG guide; assets = real IG icons/logos), run
instagram-core with `--design-input`, verify: (a) built frontend references `/assets/<file>`, (b) color-diff gate fires,
(c) visual fidelity converges (no 900s escape).
