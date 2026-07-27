# Session Handoff — env-gen pipeline debugging (2026-06-19)

> Read this end-to-end before touching the pipeline. It captures the goal, every
> fix shipped this session (with file:line + why + tests), the validation-run
> outcome, the prioritized backlog with investigator-ready diffs, the hosted demo
> you must not kill, and the operational gotchas.

---

## 0. TL;DR

- **North star:** get the multi-agent env generator to produce a working app **end-to-end** (first clean agent-driven `deliver_project` through all milestones).
- **Biggest win this session:** the run `bsb900gpt`'s **fatal deadlock is GONE**. The latest re-run (`/tmp/smoke_run_postfix.log`) **released M1 (1.0.0) cleanly and reached M2 docker-validation with no `get_skill`/deliver deadlock, no decision-key loop, no kickoff wedge**. That validated ~8 fixes end-to-end.
- **Where it failed:** M2 **frontend vite build** broke (`symbol "App" already declared`) → wedged on `docker_up`. **Now fixed** (BLOCKER F + G below).
- **Next action:** a fresh re-run to confirm F + G + the reserved-name guard carry the run through to a clean M2 delivery. **Fixes apply to the NEXT run only** (a running process already loaded the old code).

---

## 1. Where things live / how to run

- **Repo:** `/data/common/haibotong/forgingground-gen` — branch **`feat/pipeline-loop`** (UNMERGED).
- **Engine:** `agent/env_generator/llm_generator/` (tracked). **Tests:** `agent/tests/` (GITIGNORED — local-only; never committed). Run scripts at repo root are also gitignored/local.
- **Python:** `/home/haibotong/miniconda3/envs/dt/bin/python`
- **Run the smoke (the canonical repro):**
  ```bash
  cd /data/common/haibotong/forgingground-gen
  export MODEL=gemini-3.1-pro-preview PROVIDER=google OPENAI_API_KEY=dummy-unused-for-google
  export ENVGEN_GEMINI_INCLUDE_THOUGHTS=1 ENVGEN_MAX_WALLCLOCK_SEC=2400 ENVGEN_MAX_TICKS=120
  nohup bash run_smoke_notes.sh > /tmp/smoke_run_postfix.log 2>&1 &
  ```
  - `run_smoke_notes.sh` hard-checks `OPENAI_API_KEY` even for google → pass a dummy. The real key is `GOOGLE_API_KEY` in `/tmp/envgen_key.sh` (sourced by the script).
  - `--fresh` wipes `generated/smoke-notes`. Output + ports logged at top (`API=3001, UI=8080, DB=5433`).
  - Thinking-logs (`ENVGEN_GEMINI_INCLUDE_THOUGHTS=1`) are decisive for diagnosis — keep them on.
- **Run tests:** `cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/ -q -p no:cacheprovider`
  - **Known pre-existing failures (NOT from this session — verified by stashing code):** `test_condensation_keeps_coding_momentum.py` (7, they PASS in isolation = test-pollution), `test_mcp_prompts.py::test_mentions_transport_options`, `test_observability_e2e.py::test_aggregate_real_logs...`. Everything else is green (~3380 pass).
- **After killing a run:** `docker rm -f docker-frontend-1 docker-backend-1 docker-database-1` to free 8080/3001/5433. **KEEP** `igpreview*` and the youtube-preview container (the hosted demo).
- **Conventions:** commit CODE only (tests/run-scripts gitignored); NO `Co-Authored-By: Claude` trailer; SSH key `id_ed25519_virtueai`; no backticks in `git commit -m`.

---

## 2. Fixes shipped this session

All under `agent/env_generator/llm_generator/` unless noted. Each has tests in `agent/tests/`. The whole batch is suite-green except the 3 pre-existing pollution failures above.

### Phase 1 — the bsb900gpt failure classes (shipped before the re-run)

| # | File | Change | Why |
|---|---|---|---|
| **1+5 (FATAL)** | `multi_agent/agents/runtime/step_pipeline/tooling.py` `_stage_tool_names` (~L164) | Union the `"action"` `ACTION_STAGE_ALWAYS_INCLUDE` set into every **action-inner** sub-stage | The orchestrator runs action-internal sub-stages (communicate/edit_code/run_checks/deliver) as **separate LLM calls**; the force-offer set was keyed by the bare sub-stage name, so `get_skill`/`submit_retro`/`deliver_project`/`deliverability_check` (registered under `"action"`) never reached the `run_checks` menu → the model fired `deliver_project` from run_checks, hit the release-readiness/retro gate, couldn't call `get_skill`/`submit_retro` → **deadlock, run killed**. (A parallel investigator overturned my earlier "pool absence" theory with log evidence: the pool HAD get_skill; it was a per-sub-stage MENU gap.) |
| 1 backstop | `multi_agent/agents/runtime/preconditions.py` `_require_skill_consulted` | Auto-consult + pass when the agent has no `get_skill` in `_tool_instances` | Defense-in-depth: a skill-consult gate must never be unsatisfiable. (Reviewer-confirmed safe: `deliver_project` still needs `delivery_phase_reached` + the deterministic `delivery_gate`.) |
| **2** | `multi_agent/runtime/kickoff/section_substance.py` `non_contract_keys` | Accept aux keys `done_def`/`feature_inventory*` (`_AUX_KICKOFF_KEYS`/`_is_aux_key`); still reject framework-owned `auth*` | The frontend prompt's FINAL PROTOCOL tells agents to record `done_def`/`feature_inventory` via `add_meeting_decision`, and the reconcile READS them — but the validator rejected them as "non-contract keys" → 18× resend loop. |
| **4** | `multi_agent/agents/runtime/preconditions.py` `endpoints_implemented_with_code` | Satisfiability backstop: if the lane lacks `write`+`registryhub_register_endpoint`, no-op | Hardens #58 (bsb900gpt predated it): a finish gate demanding code the lane can't write only wedges finish, independent of `_active_phase`. |
| **6** | `multi_agent/workflow_policies.py` `RequiredFilesPolicy.handle_finish` | Filter framework-owned paths (`workspace.is_framework_owned`) before the existence check | The gate demanded `app/frontend/package.json` etc. that the framework owns + the lane is write-denied on → contradiction/deadlock (same rationale already excludes `app/database/`). |
| **3** | `tools/file_tools.py` `_resolve_workspace_path` + new `_redirect_bare_memory_bank` | Redirect bare `memory-bank/<file>` → `memory-bank/<agent_id>/<file>` when it exists | Agents guessed the flat path; the bank is per-agent. NOTE: implemented without `.replace()` (that string method trips the write-gate AST scanner — see `test_write_gate_invariant`). |
| 7 | (reverted) | — | Screenshots `screenshots/` write perms — REVERTED, broke a deliberate read-only-by-design test. Deferred. |
| 8 | (deferred) | — | Generated UI has no findable submit button (TEST-USER journey) — generated-app quality, deferred. |

### Phase 2 — live-run bugs (found by the user watching the run)

| Bug | File | Change |
|---|---|---|
| **A — glob path-leak** | `multi_agent/runtime/path_routed_workspace.py` `resolve()` | Redacted host roots (`base=/data/...`) from the escape error messages. |
| **B — `/app/backend` leading-slash** | same `resolve()` | Re-root a leading-slash path as project-relative (chroot) when the re-rooted target **or its parent** exists; `/etc/passwd` still rejected (no in-workspace counterpart). 69 containment tests green — security invariant preserved. |
| **C — milestone over-declaration** | `multi_agent/orchestrator.py` (~L882-889) | Scope the full-spec append to **M1 / single-milestone only** (`_m_idx == 1 or not _slice`). Was appended to EVERY milestone → M1's "auth-and-list" slice got all 8 endpoints marked binding → declared the whole CRUD → **M2 had 0 new** → its frontend submitted empty `screens` → substance-gate rejection. Spec-scan test updated (`test_reference_materials.py`). |
| **D — M2 empty-screens** | (resolved by C) | M2 now gets only its slice → frontend declares the editor screens. |
| **E — release preview (config part)** | `multi_agent/orchestrator.py` new `_write_preview_config()` | Framework-writes `<output_dir>/config.yaml` `preview_url: http://localhost:<ui_port>/` at release via raw `Path.write_text` (integration root, **outside agent worktrees → agent-invisible**, not an agent surface). `app/hub_reader.py:_preview_url` reads it. |

### Phase 3 — the M2-build blockers (the run's actual failure)

| Blocker | File | Change |
|---|---|---|
| **G — build error truncated + mis-routed** | `multi_agent/runtime/validation_runner.py` `_compose` (~L40) | Pin `DOCKER_BUILDKIT=0` + `COMPOSE_DOCKER_CLI_BUILD=0`. **BuildKit elides per-step logs to a non-TTY pipe**, so esbuild's file:line code-frame was LOST AT THE SOURCE — every lane saw only `[vite:esbuild] Transform failed with 1 error` and re-ran the build blindly. Every other build path already pins classic; this one was missed. |
| G companion | `multi_agent/runtime/remediation_dispatcher.py` `_CHECK_OWNER` | Added `"docker_up"` → **verifier** (the only lane with `docker_build`/`docker_logs`). The build error had dead-ended on the backend (no docker tools, no bash menu). |
| **F — duplicate `App` symbol** | `multi_agent/runtime/frontend_scaffold.py` `_render_routed_app` + `project_missing_ui_routes` | `_safe_import_alias` aliases page imports that collide with App.jsx idents (`App`→`AppPage`, plus `Routes`/`Route`/`React`/`BrowserRouter`). **Verified: `vite build` now passes (`✓ built in 1.35s`).** Root: an agent registered a ui_page component literally named `App`, so the projector emitted `import App from './pages/App.jsx'` next to `export default function App()`. |
| F structural | `multi_agent/runtime/registryhub.py` `register_ui_page` | **Reject** a reserved component/name for AGENT actors (raise `ValueError` w/ rename guidance); the orchestrator FINALIZE path is exempt (raising would crash finalize — the projector alias is the backstop there). |
| F prompt | `multi_agent/prompts/v3/frontend_agent.j2` | Added: "NEVER name a ui_page component `App` (nor router idents) … registration of a reserved name is REJECTED." |

**Net layering for the App.jsx-collision class:** prompt says don't → registration rejects it (agent) → projector aliases anything that slips through (finalize) → build can't break.

### New test files this session (all green)
`test_skill_consult_satisfiability.py`, `test_preview_config.py`, `test_validation_compose_buildkit.py`, `test_app_jsx_reserved_alias.py`, `test_ui_page_reserved_name_guard.py` — plus updates to `test_skill_consult_precondition.py`, `test_endpoints_implemented_with_code.py`, `test_section_substance_user_flows.py`, `test_reference_materials.py`.

---

## 3. The validation re-run (what it proved + how it died)

- Log: `/tmp/smoke_run_postfix.log`. Outcome banner: **`Status: FAILED`**, Duration ~2554s.
- **Proved:** the deadlock fixes hold — M1 (1.0.0) released via the healthy path, M2 fully implemented + reached docker-validation, agents progressed through BOTH milestones, **no `get_skill`/deliver deadlock**.
- **Died on:** M2 frontend `vite build` → `src/App.jsx:16:24: ERROR: The symbol "App" has already been declared` → framework wedged on `docker_up` for 7 post-cap cycles → `RuntimeError: STUCK`. **F + G fix exactly this.**
- The generated app is at `generated/smoke-notes/`; the broken `app/frontend/src/App.jsx` (now manually aliased for the F verification) still shows the original projector output shape — good reference for what the projector emits.

---

## 4. Deferred backlog (prioritized — do these next)

1. **★ Fresh re-run** (cmd in §1) to confirm F + G + reserved-name guard carry the run to a **clean M2 delivery**. This is the immediate next step the user wanted ("rerun吧").
2. **BUG C Change-2** (the investigator's optional backstop, NOT yet applied): deterministic prior-endpoint subtraction + a new `status:"collapsed"` from `try_synthesize` (`runtime/kickoff/run_kickoff.py` ~L1315-1326) so a milestone that declares **0 new business endpoints** is SKIPPED, + orchestrator wiring to handle `collapsed` (~`orchestrator.py:1026` driver, mirror the milestone-rejected `continue` at ~`:850`). Full proposed diff is in the session transcript (investigator `ac7863d573276d921`). Change-1 (shipped) fixes the user-visible symptom; this removes the redundant M2 backend work.
3. **BUG E companion** (preview actually renders): the released app must be RUNNING at `ui_port` for the iframe to load, but `validation_runner` tears the stack down (`teardown=True`, ~L553). Plan: leave the release-path stack up (or re-up on a **dedicated preview port** separate from validation to avoid the next-milestone port conflict), so `config.yaml`'s `preview_url` points at a live app. This is a docker-lifecycle feature, not a one-liner — do it carefully.
4. **Dedicated A/B path-resolve regression tests** (the 69 containment tests cover the security invariant; add explicit `/app/backend`-re-roots + error-no-leak cases).
5. **Class 7** (screenshots `screenshots/` write perms) — needs the deliberate read-only-by-design test (`test_attempt_4_output_path_gating.py`) reconsidered before flipping.
6. **Class 8** (generated UI no submit button → TEST-USER journey fails) — generated-app quality.
7. **Class G' (latent):** the build-repair agent still lacks a *bash menu* during run_checks (the menu-narrowing class). G's truncation fix means it no longer NEEDS bash (it can read the full error), but if a future repair genuinely needs a shell, the frontend/verifier menus may still not offer their bundled exec/docker tools. Watch for it.

---

## 5. The YouTube demo — HOSTED, do not kill

A fancy, fully-functional YouTube clone demo for the Env Forge UI, frozen at **M3 of 5** (in-generation status).

- **Public:** `https://youtube-envforge.ngrok.app/env-forge/youtube` (UI) + `https://youtube-preview.ngrok.app` (preview). Reserved ngrok domains, persisted in `~/.config/ngrok/ngrok.yml` (tunnels `yt_ui`/`yt_preview`, added to the already-running agent — do NOT restart it; it also serves `robinhood.ngrok.app`).
- **Local:** `:22100` (agentsuite-red-frontend vite) → proxies env-gen routes to `:8095` (`uvicorn app.main:app` = the Env Forge API) and `/api` env-pool to `:8090`. The fancy preview app is static HTML on `:8092` (`generated/youtube/app/frontend/public/`, served by a `python -m http.server 8092`).
- **Staging scripts (re-run to refresh; agent "active" dots decay after 180s):**
  `stage_youtube_deepen.py` (all hubs) → then `stage_youtube_panels.py` (chat/approvals/knowledge/refs). Real reference screenshots + the 12 bundled skills are copied into `generated/youtube/`.
- **`app/hub_reader.py` was changed for the demo (and these are real fixes, keep them):**
  - `env_summary`: `delivered` = **all** planned milestones released (not ≥1) → a mid-roadmap env reads `generating`, not `delivered`.
  - `_preview_url`: reads top-level `preview_url` from the env's `config.yaml` (this is what BUG-E's writer feeds).
  - `_metrics`: emits `by_agent` + `by_milestone` UsageRow breakdowns (reads a reserved `_by_milestone` key + per-agent `requests`).

---

## 6. Process notes (what worked)

- **Parallel investigators**: dispatch 1 general-purpose subagent per independent bug class with the exact evidence; have it return root-cause + a precise file:line diff + test sketch + regression risk; then vet against the cited code and apply yourself. Used ~6× this session. **One investigator OVERTURNED my own already-applied fix (Class-1 pool-absence theory) with concrete log evidence — always verify, the cheap fix is often wrong.**
- **Review-gated handshake**: for a risky change, dispatch a reviewer told to REFUTE on specific axes before banking. (Class-1 backstop was refuted-then-confirmed on 4 axes.)
- **Stash-test to attribute failures**: `git stash push -- agent/env_generator` then run the suspect tests → distinguishes "my change broke it" from pre-existing pollution.
- **Surface-before-fix**: BLOCKER F was invisible until G (BuildKit pin) surfaced the real esbuild error. When an error is truncated, fix the truncation first.

---

## 7. Memory pointers (auto-loaded each session)

See `~/.claude/projects/-data-common-haibotong/memory/MEMORY.md`, especially `project_bsb900gpt_run_failure_8classes.md` (this thread's failure analysis + fix list). This handoff supersedes/extends it with F + G + the reserved-name guard + BUG-E config writer.
