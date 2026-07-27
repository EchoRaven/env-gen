# HANDOFF — env-gen pipeline FULL open-problem review (2026-07-18)

For a fresh session to comprehensively check the WHOLE pipeline: open bugs, unfinished work, gate-quality gaps, and generation-time failure classes across ALL environments (not just TikTok). Evidence-backed — every claim cites a log line, `file:line`, or a delivered archive. Supersedes `HANDOFF_2026-07-18_tiktok_pipeline_issues.md` (TikTok is now §2/§9 here).

Branch **`feat/pipeline-opt-6`** HEAD `120f083` (#185), pushed to `vaibackup`. Python `/home/haibotong/miniconda3/envs/dt/bin/python`. Keys ONLY in `/tmp/envgen_key.sh` (GOOGLE_API_KEY + ENVGEN_UNSPLASH_KEY + ENVGEN_PIXABAY_KEY) — never committed. Model throughout: `gemini-3.1-pro-preview-customtools`.

> **★★IRON LAW (the pipeline's #1 recurring failure — mine, not the framework's):** "the code looks wired" ≠ "it works at runtime," and "the abort message says X" ≠ "X is the cause." This session I over-concluded **5+ times** (squad-broken, wrong-registry `cr.io`, thin-seed, r3-coordinator-death) — every one corrected by reading the actual log/DB/archive. **Verify every diagnosis against the specific artifact (playwright the delivered app / psql the DB / grep the exact log line) before acting or recording it.** The §9 corrections below are things I got wrong — do not re-inherit them.

Evidence was gathered by two sweep agents (run-log mining across 109 logs + 84 archives; source-gap audit of the runtime) plus direct log verification. Provenance is marked `(log)`, `(source sweep file:line)`, or `(verified)`.

---

## §0 TL;DR

- **The pipeline reliably delivers on the two mature envs** (googlemaps + instagram: many full multi-milestone SUCCESS runs). It does **NOT** yet reliably deliver a fresh env (**TikTok 0/3**). The gates are largely correct — they abort on real failures; the bottleneck is **Gemini codegen/agent variance** plus a handful of framework robustness/honesty gaps.
- **Biggest levers, in order:** (1) reduce Gemini-variance aborts (MALFORMED_FUNCTION_CALL exhaustion, API-hang silent-stalls, dispatch-queue saturation); (2) resolve the **HARD-vs-SOFT #173/#175 decision** (true-positive gates the lane can't clear abort otherwise-deliverable runs — this is what killed TikTok r3 and gmrun11); (3) harden **auth/login generation** (recurring 500/401/dup across tiktok/ig/outlook); (4) make **FAIL-FAST edit-aware** (it aborts ~20s before an active lane lands its fix); (5) push **visual fidelity** from "escapes via plateau/idle" to a real pass.
- **Two layers that MUST both stay on:** the deterministic browser gate is the ONLY reliable catch for blank/auth/no-real-data (the LLM squad passes those broken apps — proven 3 envs). Never disable `ENVGEN_TESTUSER_BROWSER_GATE`.

---

## §1 How to run / environment / disciplines

```bash
cd /data/common/haibotong/forgingground-gen/agent && source /tmp/envgen_key.sh
COMPOSE_PROJECT_NAME=<proj> nohup /home/haibotong/miniconda3/envs/dt/bin/python \
  -m env_generator.llm_generator.main --name <env>-<runN> --output ../generated \
  --design-input ../design_inputs/<env> --provider google \
  --model gemini-3.1-pro-preview-customtools --description "<one-paragraph spec>" \
  > ../<env>_run<N>.log 2>&1 &
```
- **Repo** `/data/common/haibotong/forgingground-gen` (generator, git). **Framework code** `agent/env_generator/llm_generator/multi_agent/`. **Tests** `agent/tests/` (gitignored, local-only, NEVER commit).
- **Push**: `git push vaibackup HEAD:feat/pipeline-opt-6` (default key `~/.ssh/id_ed25519`; repo pins `core.sshCommand`). **NOT** `id_ed25519_virtueai` (that Virtue-AI repo is dead → "Repository not found"). **User merges the PR** — you only commit+push. **No `Co-Authored-By` trailer.**
- **Design inputs ready**: `design_inputs/{google_maps,instagram,tiktok}/` (tiktok = 11 refs, 36 icons, 5 real fonts, 35 real videos+thumbs, dataset 9u/35v/295c/8s). Uber built manually as `rydr` (UI 8199/API 3011).
- **Disciplines**: TDD (write failing test first — see the superpowers TDD skill). One run at a time; `docker compose -p <proj> down -v` before archiving. Don't docker-reset a live env the user is testing. Keep the **run-9 gmaps demo on :8080** intact. Archive aborted runs as `generated/<name>.<runNN-cause>`.

---

## §2 Delivery ledger (what works vs what aborts)

| env family | delivered (SUCCESS) | aborted | read |
|---|---|---|---|
| **instagram** | run50–80 majority (run70/73/75/76/77/78/79/80 …) | run57(500+action)/58(401)/59(silent-stall)/60(200-envelope)/61(no-run)/65(checklist)/66(hang)/69(route-drift)/71(verifier-wedge)/74(hang) | mature; env-agnostic gates validated here |
| **googlemaps** | gmrun3/4/7/**9** (9 = full 4-milestone, validated #154–#171) | run1(chain)/2(kickoff-timeout)/5(transit-500)/6(models syntaxerror)/8(**3ms delivered→M4 docker_up stuck**)/10(gate-owner-deadlock)/11(#175-invented-abort)/12(kickoff-conflict)/13-squad(stub)/14-val(business_chain, 104min) | design-prep + quality-gate proving ground |
| **outlook** | run30/33/35/37/38 (opt-4 era) | run13/17/19/22/23/24/25/26/29/34/36/39/41/46/49/53/54/57/58/60/61/63/64 (DB-500s, literal-id, docker wedge, envelope) | oldest; DB-constraint + chain-literal heavy |
| **TikTok** | **0 / 3** | r1(frontend dup-LoginPage→docker_up), r2(backend /auth/login 500→business_chain), r3(**#175 fabricated-field no-convergence**) | NOT built; §9 |

**Reliable-delivery = googlemaps + instagram. Fresh-env (TikTok) = not yet.** Aborted dirs hold app code but no release.

---

## §3 Generation-time bug CLASSES (ranked by frequency — "generate 过程中发现的 bug")

Mined across 109 logs. Ranked; each has a representative excerpt (env `log:line`).

1. **Gemini `MALFORMED_FUNCTION_CALL`** — the single most frequent anomaly, in ~every log; counts up to **571** (`gm_val_run14`), 287 (ig79), 260 (gmrun1), 225 (tiktok-r3). Usually recovered on re-roll, but **can exhaust retries** → `gm_designprep_run10:20405 [verifier] DEGRADED STEP: planning stage FAILED with exhausted-retry MALFORMED_FUNCTION_CALL` (also hits frontend/verifier). Root: Gemini 3.1-pro-preview function-calling instability. **This is the dominant abort driver.**
2. **Dispatch queue saturation** — `dispatch queue FULL (100 pending) — dropping the ordinary-dispatch copy` up to **1668×** (`gm_val_run14`). Correlates with long/wedged runs; a symptom + amplifier of coordination overload.
3. **Gemini API hang** — `Still waiting for API response... elapsed=Ns` (max observed **237s**), up to 205× (gmrun3). Directly causes **silent stalls / manual kills** with no clean terminal line: ig_run59/60/66/74 all end mid-request (§ "unfinished"). Same family as the old run-40 (2026-07-02) "process silently died after a Gemini call."
4. **business_chain flags an HTTP-200 step as the blocker** — **225×** across logs, e.g. `business_chain: GET /api/auth/me → 200 ({"item":{...}})` marked *failed* (`outlook_run60`). Root: the chain can't capture an id/field from the `{"item":{…}}` envelope (or it's null) → a *downstream* step fails but the diagnostic surfaces the 200 step. **Triage-confusing gate-quality bug** — misleads both the lane and any human reading the log.
5. **Backend DB-constraint 500s** — `psycopg` `NotNullViolation` (×11, dominant: `null value in column "id"`), `ForeignKeyViolation` (×4), `DatatypeMismatch` (×4). Outlook-concentrated (run24=107 hits). Root: generated INSERT/model doesn't populate PK `id` / FK ordering.
6. **Frontend duplicate-component build break → `docker_up` wedge** — `X already declared` / two files named `LoginPage.jsx` / `Identifier 'api' has already been declared` / "Unexpected end of file" (gmrun3/5/7/8/11, tiktok-r1). Root: heal/codegen re-emits a component/const already defined. **Recovers sometimes, wedges to abort other times** (nondeterministic).
7. **Auth/login generation fragility** — tiktok-r1 (LoginPage dup), tiktok-r2 (`/auth/login → 500`), ig58 (`401 missing token`), outlook_run41 (`register 409 duplicate id=1`), outlook_run39/60 (`/auth/me 500`/shape). **Both TikTok runs died on auth** — a pattern, not one-off.
8. **Chain literal / unsubstituted path variable** — `GET /api/messages/${message_id_a} → 404` (15×), `/api/messages/{message_id} → 422 int_parsing` (18×), `POST …/${post_id}/like → 422` (8×). Outlook + instagram. (Runtime heal ladders exist — #136/#137/#144 — but the lane keeps reintroducing it.)
9. **Gate check with NO remediation owner** — `Delivery declined on gate check(s) with NO remediation owner: ['deliverability_dead_artifacts']` in EVERY gm run + all tiktok. Usually transient; when persistent = `run10-gateowner-deadlock`. `deliverability_dead_artifacts` / `deliverability_ui_flow_missing` lack `_GATE_OWNER` entries (memory-noted latent gap; #176 gave `ui_flow_missing` an owner — **verify dead_artifacts still lacks one**).
10. **Backend `models.py` SyntaxError (Gemini codegen)** — gmrun3/4 recovered, `run6-killed-modelsfromkeyword-syntaxerror` did not (a dataset keyword became an invalid identifier; #158 sanitizes column names — verify coverage).
11. **Route/version drift** — `/api/v1/*` duplicate variants (`gm_val_run14`, ig69). The #180 SOFT gate catches version-variant dup routes; **the #173 HARD gate can still abort the stub variant before #180 consolidates** (memory ★residual).

---

## §4 Gate-quality / honesty gaps (open)

- **★HARD `#173`/`#175` abort true-positives the lane can't clear** — the biggest single deliverability risk. TikTok r3 (`deliverability_fabricated_field_fallback`, 75-min no-convergence) and gmrun11 (`run11-invented0-abort`) both died here: the gate correctly flagged invented-data fallbacks, but the frontend lane thrashed and never cleared them → abort of an otherwise-progressing run. **★OPEN DECISION (user's call):** convert #173/#175 from HARD to SOFT/escapable (residual hit escapes-with-warning like the browser/route gates) vs keep HARD. run-12 M1 delivered clean under HARD → genuine trade-off. `#172` is already SOFT; `#180` is SOFT. See `contract_drift.py:163`, `deliverability.py` gate wiring.
- **LLM test-user squad is BLIND to objective breakage** — proven in **3 envs**: squad `verdict=PASS 0 P0` while the deterministic browser gate flagged the SAME app `UNUSABLE` (`gm_tiktok_run:35372`→37084 blank=7pages+auth; `gm_tiktok_r3:32601` no_real_data; `gm_val_run14` PASS ×3 → no_real_data ×3). #181 (sharpen squad goal text) is **verified ineffective** — agents visit blank pages and still pass. **Keep the squad for functional/subjective coverage; rely on the deterministic browser gate for blank/auth/no-data.** Candidate: make the blank/auth/no-data checks fully deterministic (the squad can't be prompted into reliability here).
- **force-deliver LLM reasoning is unreliable** — the orchestrator invents a "false-positive" and force-delivers on a check that isn't failing (`gm_designprep_run10:20554`, `run11:24896`, `run12:17560` all cite a phantom seed-check FP). **The delivery gate correctly held every time** (no confirmed gate false-positive on a healthy app). Lesson: **don't trust force-deliver log messages as diagnosis.**
- **Default-OFF flags that weaken the default posture** (source sweep — decide whether each SHOULD be default-on):
  - `ENVGEN_REQUIRE_UI_EVIDENCE=0` (`deliverability.py:309`) → `ui_validated == functionally_validated`, so **UI/visual/ui_flow gates are waivable by backend-only validation** — a blank-UI app can waive them unless this is ON.
  - `ENVGEN_ISOLATION_GATE=0` (`delivery_gate.py:649`) → **per-user data-isolation leakage is NOT gated** by default (cross-user read; smoke_feed_77 showed a cross-user MUTATE returning 200).
  - `ENVGEN_MILESTONE_SCOPED_GATE=0` (`orchestrator.py:3080`), `ENVGEN_RESERVED_PATH_GUARD` off (`registryhub.py:272`).

---

## §5 Quality ceiling (visual + assets)

- **Visual fidelity never truly PASSES** — score ceiling ~0.5–0.55; every milestone ships via **escape** (plateau/idle/anchor), not a real pass. `ENVGEN_VISUAL_MIN=0.65` (`visual_fidelity.py:746`) with `VISUAL_DEFERRAL_ESCAPE_S=3600` / `VISUAL_IDLE_S=600` release backstops (`orchestrator.py:174-188`). A1/A2/A2b landed (mandate staged assets, inline measured geometry, theme mechanism) but the ceiling stands. Root causes (from 07-13 handoff §5): real staged assets under-used, remediation plateaus, component_specs not hard-consumed. **This is the open "UI 视觉质量" front the user cares about.**
- **#185 real-font/video USAGE unvalidated end-to-end** — #183/#184 stage real fonts+videos into `design_system.assets[]` (validated at design-prep: r3 skeleton `{font:5, svg:36, jpg:68, video:35}`); #185 guides the lane to `@font-face`/`<video>` them. **Needs one delivered run to confirm the fonts render + videos play** (no delivered run has exercised it).
- **Rich-component real-render** — #172 asserts a real map ROOT (`.leaflet-container`) at runtime, but the 07-15 §6-3 item (assert tiles actually painted, count>0) is only partially covered; generalize to charts/canvas.

---

## §6 Known races / brittleness (source sweep — `file:line`)

- `validation_runner.py:463-469` — defers "to avoid a concurrent docker down/up race" — comment: "Trading a hang for a race is [what FIX #36's lock exists to prevent]."
- `registryhub.py:439-440` — "a fragile collection of lane finish-notifies — smoke #6 showed that heuristic **stalls forever** when a lane doesn't cleanly finish."
- `eventhub.py:975` — status-flip "naive get→modify→set would race"; `eventhub.py:332` — bridge errors swallowed (`best-effort: never let bridge errors block publish`).
- `test_user_runner.py:281` (#159) — "a Vite dev server serves index.html shell (HTTP 200) while the JS 500s" — known **false-green surface** (#159 mitigates by waiting for SPA mount).
- `framework_validation.py:596` — "flaky/idle verifier (outlook-seed1)" workaround; `:83` — fresh-smoke race ("the verifier's run won the race").
- **~80 `best-effort: never raises` swallow sites** across chain_executor/backend_scaffold/framework_validation/material_prep/design_prep/frontend_scaffold — deliberate liveness-over-completeness; each hides a lane bug rather than surfacing it.
- **Path-param write-time prevention missing** — runtime `path-param heal` fired **211× across 13 runs** because the lane rewrites `custom_routes.py` and re-introduces str/int annotation drift (07-13 §8-2). Still runtime-only; no write-time fix.

---

## §7 This session's fixes #178–#185 — validation status (corrected)

| # | commit | what | status |
|---|---|---|---|
| #178 | 73b9bfd | real Unsplash entity photos (was gray placeholders) | ✅ validated |
| #179 | 50be3c1 | test-user squad **default-ON** + port-transient retry | ✅ validated run-14 (fires+passes, ports clean) |
| #180 | 724edca | SOFT route-consistency gate (version-variant dup routes) | ✅ validated run-14 (no false-fire; fired accurately on run-13 archive) |
| #181 | 332760b | sharpen squad page goal | ⚠ **INEFFECTIVE** — squad still passes blank apps (§4) |
| #182 | ed4318f | STUCK-ABORT surfaces the real error line (not prefix-truncated `cr.io`) | ✅ validated r2 (showed real `/auth/login 500`) |
| #183 | 9a84b8c | design-prep stage **fonts** | ✅ validated r3 skeleton (5 fonts) |
| #184 | 7842cc2 | design-prep stage **video/audio** | ✅ validated r3 skeleton (35 videos) |
| #185 | 120f083 | frontend prompt: `@font-face` fonts + `<video>` media | ❓ **UNVALIDATED end-to-end** (§5) |

Local TDD tests (gitignored): test_squad_gate, test_version_variant_routes, test_salient_error, test_ingest_assets_fonts, test_frontend_prompt_asset_usage, test_seed_photo_sourcing, test_squad_page_goal_objective_signals.

---

## §8 Unfinished work / process debt

- **★Branch sprawl — nothing merged to `main` in a long time.** `main` is behind `vaibackup/main` by 23; **`feat/pipeline-loop` is +112 ahead of origin/main**; `feat/pipeline-opt-4/-5/-6`, `feat/uipage-registryhub-ownership` (−64), `feat/codehub-merge-robustness` (−66), `feat/unknown-tool-suggestions` (−60), `feat/workhub-claim-gate-trap` (−66), `feat/cost-instrumentation`, `feat/generation-task-db`, `feat/envforge-*`, `chore/drop-dead-chatmessage` all UNMERGED. Several are worktrees (`fg-cost-instr`, `fg-generation-task-db`, `fg-drop-chatmessage`). **A large amount of built work is stranded off main** — a reviewer should map which of these are still wanted and get them merged/closed. (User merges PRs.)
- **Prior handoff backlogs — status:**
  - `HANDOFF_2026-07-15` §6: **mostly CLOSED** — 6-1 bare-fetch-no-token = **#154**, 6-2 fresh-smoke-before-cut = **#155**, 6-4 nested-JSON-column = **#156**. **Open:** 6-3 (rich-component tile-render, partial via #172) + 6-5 (cross-env keyed validation).
  - `HANDOFF_2026-07-13` §8: #148 done. **Open:** path-param write-time prevention (§6), DELIVER_PROJECT LLM-drift throttling (150+×/13 runs — guards catch it, wastes tokens), cross-env validation.
  - `PIPELINE_FIX_PROPOSAL*.md` (#41 + archives): opt-4-era, likely superseded by the frontend baseline scaffold — treat as historical; confirm before actioning.
- **TikTok not built** — 3 aborts, 3 different stages (§2). Assets are ready; re-running needs no re-fetch.
- **Leftover containers** — aborted `ttweb3-*` on :8003/:8002/:8004: `docker rm -f ttweb3-{frontend,backend,database}-1`.

---

## §9 ★Corrections (iron-law) — what I got wrong; do NOT re-inherit

1. **TikTok r3 ≠ kickoff-coordinator death.** r3 aborted on **#175 fabricated-field no-convergence** (`gm_tiktok_r3.log:40360`, verified). The coordinator-death line is `gm_designprep_run12.log:1675` (googlemaps). My earlier `HANDOFF_2026-07-18_tiktok_pipeline_issues.md` and memory said r3=coordinator-death — **both corrected**. Consequence: r3 is evidence for the HARD-vs-SOFT #175 decision (§4), and kickoff-coordinator-death is a separate, rarer item (run12 only).
2. **"squad broken (modalities=None)"** — was a first-attempt port-not-ready transient, not broken (#179).
3. **`cr.io` wrong-registry** — a truncation artifact; real cause was the frontend dup-LoginPage build break (drove #182).
4. **"thin seed / seed-gate false-positive" (run-14)** — DB had 181 real places; `audit_authored_seed` passed; real blockers were verifier-drift. Force-deliver misattributes.

**Every one was caught by reading the actual artifact.** The framework's abort messages and the orchestrator's force-deliver reasoning are BOTH unreliable narrators — verify against logs/DB/archive.

---

## §10 Suggested comprehensive-check plan (for the reviewing session)

1. **Reproduce & attribute**: run 2–3 fresh generations (tiktok + one more env); log each abort's real cause `log:line` (don't trust the STUCK "Real blocker" line — grep the surrounding error). Confirm whether aborts are pure Gemini variance or cluster (auth/login is the top suspect).
2. **Decide HARD-vs-SOFT #173/#175** (§4) — the highest-ROI deliverability fix; TikTok r3 + gmrun11 both died here.
3. **Gemini-variance mitigation** (§3-1/3/2): MALFORMED_FUNCTION_CALL retry budget/backoff; API-hang watchdog that recovers instead of silent-stall (ig59/60/66/74); dispatch-queue backpressure.
4. **business_chain 200-as-blocker** (§3-4, 225×): fix the envelope/id-capture so the diagnostic names the real failing step.
5. **Auth/login generation reliability** (§3-7): both TikTok deaths + many outlook/ig — is the generated auth pattern fragile? (backend_scaffold auth handlers + frontend LoginPage codegen.)
6. **FAIL-FAST edit-awareness** (§ near-miss): r2 aborted ~20s before the backend lane committed its fix; the 7-cycle cap is edit-blind (`test_user_squad`/orchestrator STUCK logic).
7. **Kickoff robustness** (run12): coordinator-death → skeleton fallback; and kickoff-timeout classes (backend attendee never joins `awaiting`; synthesis `conflict`). Trace `coordination.py` + `orchestrator.py` kickoff flow first.
8. **Default-OFF gate posture** (§4): decide whether REQUIRE_UI_EVIDENCE / ISOLATION_GATE should default ON.
9. **Visual real-pass** (§5) + **#185 end-to-end** (needs a delivered run).
10. **Branch triage** (§8): merge/close the stranded branches.
11. Regression: run `agent/tests/` (~15 pre-existing test-debt failures are baselined — confirm via stash-baseline, don't mistake for new).

---

## §11 Key files map (`agent/env_generator/llm_generator/multi_agent/`)

| file | role |
|---|---|
| `orchestrator.py` | main loop, delivery-gate orchestration, STUCK/FAIL-FAST, visual/browser escape decisions, kickoff |
| `runtime/coordination.py` | kickoff meeting, lane-stall/nudge escalation (`ENVGEN_LANE_STALL_SEC=150`, `MAX_SILENT_NUDGES=4`) |
| `runtime/delivery_gate.py` / `deliverability.py` | delivery-gate checks + gate flags (#173/#175/#179/#180, REQUIRE_UI_EVIDENCE, ISOLATION_GATE) |
| `runtime/test_user_runner.py` | deterministic browser gate (#152/#153/#159/#172 map-surface, no_real_data, auth) |
| `runtime/test_user_squad.py` | LLM squad (#179 default-on; blind to objective breakage — §4) |
| `runtime/frontend_audit.py` | static UI audits (#151 mock-twin, #154 bare-fetch, #166 map, #175 fabricated-field) |
| `runtime/backend_audit.py` | #173 stub-handler gate |
| `runtime/contract_drift.py` | #180 version-variant dup routes (SOFT) |
| `runtime/framework_validation.py` | validation chain, #155 fresh-smoke, #182 salient-error diag |
| `runtime/material_prep.py` / `design_prep.py` | design-prep, asset/dataset ingest (#183/#184 fonts+video) |
| `runtime/remediation_dispatcher.py` | failure→owner routing (`_GATE_OWNER`, #148/#176) |
| `runtime/chain_executor.py` | business_chain (literal-id recovery #136/#137/#144) |
| `prompts/v3/*.j2` | lane prompts (#185 asset usage, frontend hard-rules) |

## Related memory
`~/.claude/projects/-data-common-haibotong/memory/project_envgen_runtime_surface_gates.md` (#172–#185 + all findings, now r3-corrected) · `project_envgen_designprep_phase.md` (#110–#171) · `project_envgen_material_prep_phase.md` (#1–#77).
