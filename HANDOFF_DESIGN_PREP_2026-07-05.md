# HANDOFF — Agent-Driven Design-Prep + Pipeline Optimization (2026-07-05)

**For a fresh session with zero prior context.** This continues the `/loop 持续优化整个pipeline`
work on the forgingground-gen env-generation pipeline. Read this top to bottom once, then use the
"CONTINUATION DIRECTIVE" at the end as your standing instruction.

---

## 0. TL;DR

A dedicated **`design_analyst`** configurable-agent was built + wired into the pipeline. It runs
ONCE before generation, and — per the user's field manual `/data/common/haibotong/screenshot_diagnose.md`
— **crops + eyedrops + measures each UI component itself** (not framework-pre-chewed), producing a
measured `design/design_system.json` that the frontend/backend lanes build from + the staged REAL
assets they reference. Plus several adjacent field-manual pipeline fixes.

- **Branch:** `feat/pipeline-opt-6` (LOCAL only — the user merges via PR, like opt-5). Tip: `6b2826b`.
- **~18 commits**, ~105 unit/config tests green (tests are LOCAL-only, `agent/tests/` gitignored).
- **A LIVE validation run is IN PROGRESS** (see §4) — the design_analyst is working on Gemini right now.

---

## 1. Environment / how to run (IMPORTANT — this was the earlier blocker)

- **Provider = Google Gemini.** The API key lives in **`/tmp/envgen_key.sh`** (`export GOOGLE_API_KEY=…`).
  The run scripts `source` it. DO NOT look only at shell env vars — the key is in that FILE.
  (The previous session wrongly reported "blocked on keys" for hours because it never checked the file.)
- **Model:** **`gemini-3.1-pro-preview-customtools`** — the user's model, now set as default in
  `/tmp/envgen_key.sh` (PROVIDER=google + MODEL + OPENAI_API_KEY=dummy exported there). It WORKS via
  direct call even though it is NOT in `models.list()` (preview). The `-customtools` variant is tuned
  for tool use (the tool-loop the design_analyst relies on).
- **Python:** `/home/haibotong/miniconda3/envs/dt/bin/python`.
- **Launch the design-prep validation run:**
  ```bash
  cd /data/common/haibotong/forgingground-gen
  . /tmp/envgen_key.sh
  export PROVIDER=google MODEL=gemini-3.1-pro-preview-customtools OPENAI_API_KEY=dummy ENVGEN_MAX_WALLCLOCK_SEC=5400
  ./run_instagram_designinput.sh          # uses design_inputs/instagram (REAL 47-icon asset pack)
  ```
  (`run_instagram_designinput.sh` skips the OpenAI check when PROVIDER≠openai and passes
  `--design-input design_inputs/instagram --provider google --model $MODEL`.)
- **Docker is required** (visual gate builds/runs the generated app). It is available on this host.

---

## 2. What was built (the feature)

The agent-driven Design-Prep phase. Key files (all on `feat/pipeline-opt-6`):

- **`agent/env_generator/llm_generator/multi_agent/runtime/design_prep.py`** — the phase:
  `resolve_design_input` (--design-input → references/docs/assets) · `build_skeleton_design_system`
  (deterministic MEASURED skeleton: palette + component regions + staged assets) ·
  `write_skeleton_design_system` (the agent's starting doc) · `build_design_analyst_briefing` ·
  `load_valid_design_system` (parseable+structural guard) · `enrich_design_system` (single-shot
  FALLBACK) · `design_system_summary_for_requirements` (folds the doc into the requirements EVERY
  lane reads — non-voluntary).
- **`.../runtime/material_prep.py`** — measurement primitives + the `measure_layout` metrics
  (`content_bounds`, `grid_columns`, `row_bands` with clustering) + `ingest_assets` (real assets →
  manifest + staged).
- **`agent/env_generator/llm_generator/tools/material_prep_tools.py`** — the agent tools the
  design_analyst calls: `sample_color` (row-mode bg / saturation accent), `crop_reference`,
  `extract_palette`, `zoom_compare`, **`measure_layout`** (new), `decompose_reference`.
- **`.../prompts/v3/design_analyst.j2`** — the agent's mandate = the field manual (measure-don't-
  guess, lever order, translucency trap, 塌缩点 checklist, brand boundary, output schema).
- **`.../agents/agents_config.yaml`** — the `design_analyst` profile (spawnable/one-shot, tool
  bundles reference_images + vision_tools).
- **`.../multi_agent/orchestrator.py`** — `_compile_reference_materials` writes the skeleton, spawns
  `design_analyst` (`_spawn_design_analyst`), validates output (malformed → single-shot rebuild),
  folds the summary into the returned requirements.
- **`.../runtime/frontend_scaffold.py`** — `stage_design_assets` (design/assets → app/frontend/
  public/assets) + the nginx cache policy (§3 below).
- **`.../prompts/v3/frontend_agent.j2`** — "use the REAL staged assets, don't draw approximations" rule.
- **`.../runtime/path_routed_workspace.py`** — `design_analyst` added to the `design/` route writers
  (else its writes are denied — this was a real blind-build blocker that was caught + fixed).
- **`design_inputs/instagram/`** (LOCAL, gitignored) — the REAL asset pack: 11 IG captures +
  47 real icon SVGs + PIPELINE.md + ground-truth `tokens.json`. Assembled from
  `/data/common/haibotong/instagram_assets_pack.tgz`.

## 3. Adjacent pipeline fixes shipped this session (whole-pipeline, not just design-prep)

- **FIX #79 (`c4a4388`)** — instagram-core opt6 abort root cause: a body-less `POST /api/auth/register`
  chain step bypassed ALL auth coercions in `chain_executor.normalize_steps` (they keyed only on the
  un-prefixed `/auth/*`; the AS is mounted at both `/` and `/api`). Fix: collapse `/api/auth/*`→`/auth/*`.
- **★nginx cache policy (`6b2826b`)** — the framework nginx config had NO Cache-Control → stale
  index.html → "my change doesn't show" phantom bugs (manual §5.3/§9; the recurring "bump ?v=" pain).
  Now: `immutable` on hashed `/assets/` + `no-store` on index.html/SPA. Kills the whole stale-bundle
  class deterministically, all envs.
- **Seed STATE DISTRIBUTION (`e88ff1b`)** — backend_agent.j2 seed rules now target a realistic state
  MIX (mostly-unread inbox, varied feed engagement) + honor the design_analyst's measured `state`
  (manual lever #3).
- **Malformed-JSON robustness (`953984f`)** — a design_analyst that writes bad JSON → single-shot
  rebuild instead of losing the whole phase.

## 4. THE LIVE RUN IN PROGRESS (started 2026-07-05 ~20:08)

- **PID 338771**, log at **`ig_designprep_live.log`**, output at **`generated/instagram-core-di/`**.
- Model = **gemini-3.1-pro-preview-customtools** (the user's model; the earlier 2.5-pro run was killed + relaunched on this).
- **What already worked live:** the `design_analyst` spawned, read the skeleton `design_system.json`
  + `reference_spec.json`, and began decomposing `home_feed.png` + planning per-component
  crop+eyedrop+measure. `design/design_system.json`, `component_specs/`, `assets/` are present in the
  output. **The core new feature runs on Gemini.**
- **How to check it:**
  ```bash
  cd /data/common/haibotong/forgingground-gen
  ps -p 338771 && tail -40 ig_designprep_live.log   # PID may change if relaunched — pgrep -f 'main.py --name instagram-core-di'
  grep -E 'design_analyst|Design-Prep|design_system.json ready|crops|finish' ig_designprep_live.log | tail
  ls generated/instagram-core-di/design/crops/ 2>/dev/null   # did it physically crop components?
  cat generated/instagram-core-di/design/design_system.json | python -m json.tool | head -60
  ```
- **Acceptance criteria to verify (the whole point):**
  1. `design_system.json` has per-component MEASURED colors + `assets` mappings + `build_notes`.
  2. `design/crops/` has physical per-component crops.
  3. The built frontend REFERENCES the real assets: `grep -r "/assets/" generated/instagram-core-di/app/frontend/src/`.
  4. The color-diff / visual-fidelity gate FIRES and CONVERGES (no 900s escape).
  5. Overall run reaches DELIVERY (or diagnose the abort if it doesn't).

## 5. Known issues / gotchas

- **Gemini `FinishReason.UNEXPECTED_TOOL_CALL`** was seen on gemini-2.5-pro; the `-customtools` variant
  should reduce it. Also seen: design_analyst `update_json_path FAILED: Path index [0] expects array
  parent, got str` — it fumbles a JSON-edit path when enriching design_system.json; watch whether the
  customtools model does better, else consider a more forgiving enrich-write path. `FinishReason.UNEXPECTED_TOOL_CALL` — the pipeline retries
  and continues; watch whether it ever wedges a lane. (Gemini emits a tool call when the harness
  didn't offer tools; likely benign but worth confirming it doesn't cause a stall.)
- The full 11-screen design_input is HEAVY for design-prep (11 screens × ~10 components × several
  vision calls). If design-prep is too slow / hits its 1800s timeout, trim `design_inputs/instagram/
  references/` to ~4 key screens (home_feed, explore, profile, post_detail) for a faster loop.
- Tests are `agent/tests/` (gitignored, LOCAL). Run: `cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/test_design_*.py tests/test_measure_layout.py -q`.
- ~2 PRE-EXISTING test-debt failures in touched subsets are NOT regressions:
  `test_reference_materials::test_skeleton_main_includes_custom_router` and
  `test_workspace_routing::test_orchestrator_and_workers_have_broad_write` (both fail on the base too).
- GIT: push key = DEFAULT `id_ed25519` (Virtue-AI repo dead → vaibackup canonical). The user merges
  opt-6 via PR — do NOT push/merge unless asked.

## 6. Next steps (priority order)

1. **Watch the live run to completion** (§4). If design-prep converges + the frontend uses `/assets/`
   + visual fidelity improves → the feature is VALIDATED. Report the outcome.
2. If it aborts / stalls → diagnose live (containers UP = hot diagnosis). Common classes are in the
   memory file `project_envgen_material_prep_phase.md` (#1–#79). Use the STUCK/NO-CONVERGENCE ladder.
4. Continue `/loop 持续优化整个pipeline` — mine the field manual (`screenshot_diagnose.md`) + live-run
   diagnostics for the next env-agnostic fix. Remaining manual items not yet wired: font substitution
   (§9), Mica/translucent-material root-isolate pattern (§附录A).

## 7. Memory (persistent context — READ THESE)

`~/.claude/projects/-data-common-haibotong/memory/`:
- **`project_envgen_designprep_phase.md`** ← the full design-prep + this-session log. READ FIRST.
- **`project_envgen_material_prep_phase.md`** ← the #1–#79 pipeline fix log + STUCK-ladder patterns.
- `feedback_proactive_run_monitoring.md` — self-wake every 10–15 min during live runs (hot diagnosis).
- `MEMORY.md` — the index.

Standing user constraints: no `Co-Authored-By` trailer in commits; verify-cause before claiming a fix
(don't fabricate a fix for a transient/backend-correct signal); don't `docker down -v` a live env while
the user is testing; all fixes ENV-AGNOSTIC.

---

## 8. CONTINUATION DIRECTIVE (paste this into the fresh session)

```
/loop 持续优化整个pipeline

Context: continue the forgingground-gen pipeline optimization. READ FIRST:
/data/common/haibotong/forgingground-gen/HANDOFF_DESIGN_PREP_2026-07-05.md and the memory files it
names. The agent-driven Design-Prep feature is built on branch feat/pipeline-opt-6; a live Gemini
validation run is in progress (PID in the handoff §4, log ig_designprep_live.log).

Gemini key: source /tmp/envgen_key.sh ; PROVIDER=google MODEL=gemini-3.1-pro-preview-customtools OPENAI_API_KEY=dummy.
Python: /home/haibotong/miniconda3/envs/dt/bin/python.

Your job each iteration: (1) check the live run — if it's still going, monitor it (self-wake every
10–15 min while containers are UP for hot diagnosis); if it finished, verify the design-prep acceptance
criteria (handoff §4) and report; if it aborted, diagnose live + fix env-agnostically (verify-cause,
don't fabricate). (2) When no live run is active, continue mining the field manual
(/data/common/haibotong/screenshot_diagnose.md) + run logs for the next real env-agnostic pipeline
improvement, TDD each, commit to feat/pipeline-opt-6 (no Co-Authored-By trailer; user merges via PR).
Prefer deterministic/framework-owned fixes over prompt tweaks. Update the memory file
project_envgen_designprep_phase.md as you go.
```
