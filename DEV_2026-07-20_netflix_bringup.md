# DEV 2026-07-20 — Netflix env bring-up: deep codebase review + issue analysis + plan

> **Author's note.** This is my own development document, written after a deep 5-agent review of
> the engine, to prepare bringing up a NEW generation target: **Netflix** (streaming: auth →
> "who's watching" profile gate → browse rails → title detail/hero → player → search → my-list).
> It is the counterpart to `HANDOFF_2026-07-20_delivery_stability.md` (which covered the TikTok
> delivery-stability arc `#219–#242`, now merged to `main` via PR #7, HEAD `84aafd2`).
>
> Every claim below is anchored to `file:line` and was spot-verified against the current tree.
> Paths are relative to `agent/env_generator/llm_generator/` unless noted.

---

## 0. TL;DR

- The engine is a multi-agent generator: **contract → deterministically projected full-stack app**
  (FastAPI+Postgres, React/Vite/Tailwind, OAuth2, MCP, Docker). It was hardened against **TikTok**
  (a social video *feed*). Netflix is a **catalog/rails + playback** product — a different shape.
- **This host is code-only.** The engine source is present and current, but everything needed to
  *run* a generation is gitignored/local and **absent here** (run scripts, `design_inputs/`, the key,
  the `dt` python env, engine deps, playwright). See §2. We cannot run a generation until it's
  provisioned; resources are coming from the user.
- **Top Netflix risks (structural, will block or blank a delivery), ranked in §4:**
  1. **N1 — response envelope hard-locked to `item`/`items`** (`registryhub.py:217`,
     `delivery_gate.py:717`). Netflix's natural `rows`/`titles`/`sections` keys both **block delivery**
     and **ship blank pages**.
  2. **N2 — the projector can only express one resource per endpoint.** `/browse` (many rails),
     `/watch/{id}`, `/my-list`, `/titles/{id}/similar` all mis-project (`route_projector.py`).
  3. **N3 — chain verification can't recover STRING path params** (`{slug}`/`{username}`);
     numeric-only ladder at `chain_executor.py:1337`. (This is the handoff's existing open P0.)
  4. **N4 — no reference-aware frontend projector** (removed 2026-06-11,
     `frontend_page_projector.py:1`). Lanes author 100% of a visually demanding UI, gated only
     generically — high fidelity risk for a rails/hero/player product.
- **The good news:** the design-prep pipeline already ingests real `.mp4/.webm` video + a `dataset/`
  of real rows (`material_prep.py:681-693,792`), `poster`/`cover` image backfill works
  (`backend_skeleton.py:1337-1348`), and `~/.env-gen/knowledge/` (the cross-env memory leak vector)
  is **absent on this host** — no stale TikTok knowledge to purge.

---

## 1. What the system is (1-paragraph refresher)

A run compiles a `--design-input` (spec + reference screenshots + assets + dataset) into a binding
design system, then loops over milestones. Per milestone the lanes hold a **kickoff meeting** and
declare a contract slice; the orchestrator **synthesizes + registers** the contract
(`endpoints`/`tables`/`ui_pages`) into RegistryHub (`kickoff/run_kickoff.py:1493,1829`). The app is
then **projected deterministically** from that contract — handlers from endpoints
(`route_projector.py`), models/DDL/seed from tables (`backend_skeleton.py`,
`database_scaffold.py`), and — for the frontend — only *infra* (the lane authors all UI). A stack of
**gates** (`delivery_gate.py`, `deliverability.py`, `validation_runner.py`, `flow_coverage.py`,
`visual_fidelity.py`) must pass before the orchestrator's `_maybe_framework_deliver`
(`orchestrator.py:2467`) cuts the sole in-loop `create_release` (`orchestrator.py:3040`).

---

## 2. Environment status on THIS host (blocker to running)

| Needed to run a generation | Present here? | Source |
|---|---|---|
| Engine source + current `main` (HEAD `84aafd2`, `#219–#242`) | ✅ | git |
| `HANDOFF_2026-07-20_delivery_stability.md` | ✅ | pulled |
| Engine deps (`jinja2`, `google-genai`, `mcp`, playwright…) | ❌ not installed | `pyproject.toml` |
| Python env (handoff used `miniconda3/envs/dt`) | ❌ (only system `python3.12`) | — |
| `/tmp/envgen_key.sh` (`GOOGLE_API_KEY`, unsplash/pixabay) | ❌ | user-supplied, never in repo |
| `run_*.sh` launch scripts | ❌ gitignored (`.gitignore` `run_*.sh`) | local-only |
| `design_inputs/netflix/` | ❌ gitignored (`.gitignore` `design_inputs/`) | **to create — §3** |
| `~/.env-gen/knowledge/` stale cross-env memory | ✅ absent (clean) | — |

**Implication:** the handoff's run/verify/autopsy loop (§1/§4/§5 there) assumes a fully provisioned
host. Here we can (a) do **engine code work** with focused unit tests once deps are in a venv, and
(b) prep the Netflix inputs — but we **cannot run an end-to-end generation** until the env is stood
up. Disk is fine: `/` has 640G free (42% used).

**Provisioning checklist (when resources arrive):**
```bash
cd /home/haibotong/forgingground-gen
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e .                 # engine deps from pyproject.toml
python -m playwright install chromium
echo 'export GOOGLE_API_KEY=<key>' > /tmp/envgen_key.sh   # + unsplash/pixabay keys
```

---

## 3. Netflix `design_inputs/netflix/` contract (what to provide)

`resolve_design_input` (`runtime/design_prep.py:36-71`) reads four optional channels:

```
design_inputs/netflix/
  references/   *.png|jpg|jpeg|webp|gif|bmp   ← one screenshot PER screen to build; the filename
                                                stem BECOMES the screen name and the visual-fidelity
                                                gate compares against that exact file.
                                                Suggested: login, profiles (who's watching),
                                                browse_home, title_detail, player, search, my_list.
  docs/         *.md|txt|rst|html|htm|pdf     ← optional feature/API write-ups → reference_spec gates
  assets/       logos, icon set, fonts, AND real *.mp4/*.webm trailers + audio
                                                (staged to public/assets/, material_prep.py:681-693)
  dataset/      <table>.json | *.csv          ← optional REAL rows; columns define the table schema
                                                (assemble_seed_dataset, material_prep.py:832)
```

Also put the API/table contract into `--description` as structured lines so the FIX #42 backstop
(`kickoff/run_kickoff.py:403`) guarantees a non-empty contract if a lane stalls:
```
- GET /api/titles            - GET /api/titles/{id}        - GET /api/titles/{id}/similar
- GET /api/browse            - POST /api/my-list           - DELETE /api/my-list/{id}
- table: titles: id, name, poster, year, maturity_rating, genre, runtime, synopsis
- table: profiles: id, user_id, name, avatar, is_kids
- table: my_list: id, profile_id, title_id
```
If per-profile private data is intended, phrase "each profile sees only its own list" to trigger
`owner_scoped_reads` (`run_kickoff.py:533-565`).

**Run command (once provisioned):**
```bash
cd agent/env_generator/llm_generator
python -m env_generator.llm_generator.main \
  --name netflix-web-r1 --design-input design_inputs/netflix \
  --provider google --model gemini-3.1-pro-preview-customtools
# recommended first runs: ENVGEN_SINGLE_MILESTONE=1  (avoid the multi-milestone kickoff wedge)
```

---

## 4. Issue analysis — ranked by Netflix impact

Severity: **N‑P0** = will block delivery or ship a broken/blank app for Netflix; **N‑P1** = degrades
quality or causes false-negative gate churn; **N‑P2** = robustness / infra / generality.

### N‑P0‑1 — Response envelope is hard-locked to `item`/`items`
- **Where:** `registryhub.py:208-217` (`_canonical_response_key`: `single = m!="GET" or last=="me"
  or is_param` → `item` else `items`), enforced on every `register_endpoint` (`:332`). Gate:
  `delivery_gate.py:686-740` (`_CANONICAL = {"items","item"}`, `:717`) →
  `business_response_key_noncanonical` (`:1275`). Projector emits only these two shapes
  (`route_projector.py:881-882` list, `:714/732/807/866/988` item).
- **Why it bites Netflix:** a browse/home response is naturally `{"rows":[{title,items:[…]}]}` or
  `{"sections":[…]}`. If the backend lane registers `response_key:"rows"/"titles"/"results"`, delivery
  is **blocked**; if it registers `items` but the frontend reads `data.titles`, pages render **blank**.
- **Fix direction:** add a `response_shape` taxonomy beyond the binary. Let a contract-declared
  shape drive both `_canonical_response_key` and the projector; introduce a `sections`/`rails`
  envelope `{"sections":[{title, items:[…]}]}`. Keep `item`/`items` as the default. (See N‑P0‑2.)

### N‑P0‑2 — One-resource-per-endpoint projection can't express rails / playback / derived collections
- **Where:** `route_projector.py` — `_resource_model` (`:405-489`), `_FEED_SHAPED_TOKENS`
  (`:357` = `feed,explore,timeline,reels,discover,stream` — **no `browse`/`home`/`for-you`**),
  action-verb/suffix/prefix join fallbacks (`:418-489`), pattern dispatch (`:707-1066`).
- **Netflix mis-projections:**
  - `/browse` → no `browse` table, not a feed token → collapses to a single flat `{items}` of one
    table (`_primary_content_model`, `:380`). **All rail structure lost.**
  - `/watch/{id}` → GET-by-id `{item}` of a `titles`/`watch` row; a `POST /watch/{id}` (record
    progress) with no `watch` table → #124 action-unmapped 404 stub (`:960-971`).
  - `/my-list` → `-` is **not normalized** in `_match_model` (`:335-347`), so it won't match a
    `my_list` table; toggle/owner semantics lost.
  - `/titles/{id}/similar` → tries `title_similar[s]`/joins, else resolves to the **parent `titles`**
    — not a list of *similar* titles. No "derived/edge collection" concept.
- **Fix direction (largest single work item):**
  1. Hyphen→underscore in `_match_model` segment matching (`:335`).
  2. Generalize `_FEED_SHAPED_TOKENS` to include `browse,home,catalog,for-you` — or better, drive
     "feed-shaped" from a contract flag, not a hardcoded list.
  3. Add a **derived-collection** pattern for `/<res>/{id}/<derived>` (`similar`/`related`/
     `recommended`/`episodes`) that returns `{items}` of the target type via an edge/mapping table
     instead of collapsing to the parent.
  4. Add **membership-toggle** handling (`/my-list` add/remove) generalizing the child-toggle
     handler (`:734-763`) + `_target_fk` (`:565-580`) over a `(owner,target)` join.
  5. Add `profile_id` to `_OWNER_FK_NAMES` (`:44-48`) and teach `_fw_owner_val`
     (`backend_skeleton.py:603-622`) about a per-profile principal (Netflix scopes by profile, not
     account).
- **Verify empirically first** (per iron law): confirm on a live Netflix run which endpoints actually
  mis-project before building the full taxonomy — don't build it speculatively.

### N‑P0‑3 — Business-chain verification can't recover STRING path params
- **Where:** `chain_executor.py:1337,1339,1362` — the literal-id recovery ladder (#136/#144) triggers
  and rewrites only on `r"/\d+(?=/|$)"` (numeric). Capture is id-only too: `_extract_resource_id`
  (`:743`), `_harvest_resource_ids` (`:908`), `load_seed_ids` (`:627`) read only `id`. The chain
  user's own `username` is never saved (only `own_user_id`, `:1549-1550`).
- **Why it bites Netflix:** detail routes keyed by `{slug}`/`{titleSlug}`/`{username}` 404 →
  `business_chain_failing` blocks delivery. Even the placeholder ladder (`:1196-1250`) substitutes a
  wrong-typed numeric id into a `{slug}` path.
- **Fix direction:** (1) capture typed business keys — add `_extract_resource_key(payload, prefer)`
  returning `slug`/`username`/`handle`/`uuid` by param NAME, extend `_harvest_resource_ids` +
  `load_seed_ids` to keep a `{id,slug,username}` map per resource. (2) Widen the ladder trigger/rewrite
  to a literal non-numeric segment that the CONTRACT declares as a `{param}` (align via
  `control_exercise.norm_method_path`/`_path_matches_template`, `control_exercise.py:39,84`), guarded
  so static action suffixes (`/like`,`/publish`) are never clobbered. (3) Capture the chain user's own
  `username` alongside `own_user_id`. **This is already the handoff's open P0 #1** — do it first, it's
  pure code + unit-testable without a live run.

### N‑P0‑4 — No reference-aware frontend projector (lanes author 100% of the UI)
- **Where:** `frontend_page_projector.py:1-24` — the page projector, fallback catalog, and
  list/detail/form templates were **removed 2026-06-11** (the header itself cites the removed
  "Instagram catalog, /feed landing, dark-zinc aesthetic"). Quality is enforced only by gates:
  `frontend_audit.audit_ui_page` (`:262-466`), `routed_fallback_page_blockers` (`:549-587`),
  `invented_field_fallback_blockers` (`:1121-1231`), plus `visual_fidelity.py`.
- **Why it bites Netflix:** the rail-grid browse, hero detail, player, my-list grid, and profile
  picker are visually demanding and now 100% lane-authored with only generic gates + the visual gate
  to catch a flat `<ul>` masquerading as rails. Highest *fidelity* (not delivery) risk.
- **Fix direction (choose one):**
  - **Reintroduce a reference-structured floor** for high-value page types that emits
    `data-projected="ref"` (the audit *already* treats this as a passing floor,
    `frontend_audit.py:121`) — a measured-region rail/grid/hero/player scaffold beats scratch.
  - **Or**, minimum: add a **rail-grid quality gate** analogous to the map-lib gate
    (`frontend_audit.py:779-829`) that flags a browse page rendering a flat list instead of
    horizontal rails, plus Netflix-aware prompt guidance.

### N‑P1‑5 — Visual route mapping uses social vocabulary
- **Where:** `visual_fidelity.py:54-65` `_ROUTE_KEYWORDS`: `("video","reel","watch")→/reels`,
  `("saved","bookmark","collection")→/saved`, etc. `/browse` is in **no** tuple.
- **Impact:** a `netflix_watch.png` reference risks mapping `watch→/reels` (a route Netflix doesn't
  serve) → capture skip / false 0.00. Partially saved by the generic filename→known-route match that
  runs first (`:253-259`).
- **Fix:** rely on `load_screen_classifications` (`:171`) — `design_system.json` `route`/`requires_auth`
  per screen already **wins** over heuristics (`:229`); ensure design-prep labels `/browse`,
  `/watch/:slug`, `/title/:slug`, `/profiles`. De-prioritize the `watch→/reels` mapping.

### N‑P1‑6 — Test-user walk skips slug detail routes (zero coverage)
- **Where:** `test_user_runner.py:177-178` — `resolve_param_route` returns `None` unless the param
  name ends in `id`/`pk`; string params (`:slug`,`:titleSlug`) are deliberately not resolved.
- **Impact:** `/watch/:slug`, `/title/:slug`, `/browse/:genre` are **never walked or screenshotted**
  → no ui_flow evidence, no visual capture on Netflix's core pages.
- **Fix:** resolve a string param from a real list row's matching string field (`slug`/`handle`),
  URL-encoded (`:207`) — the id-only guard exists to avoid fabricating `/posts/7` from `/posts/:slug`;
  the safe version resolves from a real `slug`, not from `id`.

### N‑P1‑7 — Profile-gate ("who's watching") breaks auth-ok detection
- **Where:** `test_user_runner.py:449-474` (auth flow), `:856` (`clean_ui_flow_passes` requires
  `auth_ok`), `:679-681` (`hollow_frontend`). `auth_ok = token and navigated`, where `navigated` means
  the URL left an auth route (`_AUTH_ROUTE_SEGS`, `:61`).
- **Impact:** if Netflix interposes a profile-select screen between `/login` and the app,
  `_drive_auth_form` may store a token but not reach an app route → `auth_ok=False` → the whole
  clean-pass unblocking (the #240/#241 delivery-ceiling fix) is forfeited on a healthy app.
- **Fix:** make the auth flow profile-gate aware — after a token is stored (`:466`), if the URL is a
  profile-select screen, click a profile before asserting `navigated`/`auth_ok`.

### N‑P1‑8 — Fabricated-field gate false-blocks natural streaming literals
- **Where:** `frontend_audit.py:1044-1069` + `deliverability.py:385`. Flags `x || 'literal'` where the
  literal has a digit / is multi-word / a proper noun.
- **Impact:** `title.year || '2023'`, `title.matchScore || '97% Match'`, `title.rating || '4.5'` (all
  natural for a catalog) → blocked → 75-min convergence churn. Auto-repair `repair_fabricated_fallbacks`
  (`:1170-1231`) rewrites to `(x ?? '—')` but has its own build-break history (#239).
- **Fix:** prompt the frontend lane to use honest empty states for catalog fields; escape hatch
  `ENVGEN_INVENTED_FIELD_GATE=0` if it proves noisy on Netflix.

### N‑P1‑9 — Media-poor seed data
- **Where:** `backend_skeleton.py` — `_SEED_TITLES` (`:1275-1276`) are neutral office-doc strings
  ("Getting Started", "Weekly Summary"); `profiles`/`cast` not in `_PERSON_TABLES` (`:1287-1291`).
- **Impact:** seeded "titles" read like documents, not movies → weak visual fidelity even when the app
  is functionally correct. (`poster`/`cover` image backfill via `_IMAGE_WORDS` `:1337-1348` DOES work.)
- **Fix:** supply real rows via `dataset/*.json` (preferred — becomes the schema + seed), and/or add a
  media-shaped seed pool + `profiles`/`cast` to `_PERSON_TABLES`.

### N‑P2‑10 — Tool-surface bloat → MALFORMED_FUNCTION_CALL (orchestrator + knowledge lanes)
- **Where:** orchestrator (`agents_config.yaml:85`) and knowledge (`:1143`) have **no**
  `stage_tool_allowlist`, so their 30-bundle pools run through the ~10-slot ranker
  (`step_pipeline/tooling.py:228-230`) + the hand-maintained `ACTION_STAGE_ALWAYS_INCLUDE` union
  (`base.py:449-471`). A prompt-mandated tool the ranker drops → orphan → MALFORMED_FUNCTION_CALL
  (`base.py:376-379`). `validate_orphaned_tool_offerings` (`tool_surface.py:445`) only logs INFO; 26
  dead allowlist entries were found by `validate_stage_allowlists` (`:139-169`).
- **Fix:** add explicit `action`/`kickoff:action` allowlists to orchestrator + knowledge (raises their
  effective cap to 48 curated tools); split the orphan validator to warn LOUDLY for allowlisted lanes;
  clear the 26 dead entries. Env-agnostic — benefits every target, do it before the first Netflix run.

### N‑P2‑11 — ui_flow failure evidence is bare `{flow:name}`
- **Where:** reader side is hardened (`hub_registry.py:382-393` derives `check`/`flow` from the name),
  and the framework walk writes rich PASS records (`heal_pipeline.py:626-641`). But the verifier's
  FAILURE write path emits a reason-less `{flow:name}`, so remediation dispatch
  (`remediation_dispatcher.py:430,458` reads `detail`) produces an un-actionable P0.
- **Fix:** enforce a minimum evidence contract in `record_validation_result` (`hub_registry.py:318`):
  on failed/error, require/synthesize a `summary`/`reason` + `broken_step`/`console` artifact.

### N‑P2‑12 — Env-tunable timeouts for a heavy frontend
- **Where:** `validation_runner.py:378` — `up_timeout=300s`, health `90s`, not env-tunable.
- **Impact:** a video-heavy Netflix frontend cold-build under contention can exceed 300s → `docker_up`
  fail → churn. Also the `.smoke_validation.lock` 600s serial wait (`:440-470`) dominates a busy host.
- **Fix:** plumb build/health timeouts to env vars (mirror the FWVAL/visual env gates).

### N‑P2‑13 — Multi-milestone kickoff wedge
- **Where:** milestone planning is LLM-decided (`orchestrator.py:986-1004`); a thin later-milestone
  kickoff can hard-abort the whole run (`:968-980`, `:1366-1380`).
- **Fix:** `ENVGEN_SINGLE_MILESTONE=1` for the first Netflix runs (`orchestrator.py:981`); enable
  agent-planned milestones only once the env delivers end-to-end.

### N‑P2‑14 — Residual single-domain bias in prompts
- **Where:** `prompts/v3/frontend_agent.j2:61` (a fully spelled-out **Instagram** worked example,
  scoped but the strongest remaining anchor), `prompts/v3/design_analyst.j2:95` (literal IG nav
  specifics: "Messages = paper-plane… no stories bar"). De-biasing (#908406e/#f1cace7) is otherwise
  largely complete — no domain endpoints/tables leak into the contract path.
- **Fix:** genericize the IG worked example (or add a Netflix-parallel one) and trim the IG nav
  specifics before the first Netflix run.

### N‑P2‑15 — Cross-env memory contamination (currently clean here)
- **Where:** the `knowledge` lane writes to `~/.env-gen/knowledge/*.jsonl` (`base.py:548-562`), a
  cross-project home path (14-day TTL). Working lanes are project-scoped (`base.py:564`) — safe.
- **Status on this host:** `~/.env-gen/knowledge/` is **absent** → no action needed now. If TikTok
  runs ever populate it, purge/namespace before a Netflix run.

---

## 5. Proposed development plan (phased)

**Phase A — provision + smoke (needs user resources).** Stand up venv + deps + playwright + key
(§2); assemble `design_inputs/netflix/` (§3); do a first `ENVGEN_SINGLE_MILESTONE=1` run to observe
where Netflix *actually* breaks (don't fix speculatively). Capture the autopsy per handoff §5.

**Phase B — code fixes that don't need a live run (do now, TDD):**
- **N‑P0‑3** string path-param recovery in `chain_executor.py` (self-contained, unit-testable).
- **N‑P2‑10** orchestrator/knowledge tool allowlists + clear 26 dead entries.
- **N‑P2‑11** ui_flow writer evidence contract.
- **N‑P2‑12** env-tunable docker timeouts.
- **N‑P2‑14** prompt de-bias trims.
- Small projector generality: hyphen normalization + `profile_id` owner FK + `_FEED_SHAPED_TOKENS`
  additions (N‑P0‑2 sub-items 1,2,5).

**Phase C — structural, validate against the live Netflix run (Phase A output):**
- **N‑P0‑1 / N‑P0‑2** response-shape taxonomy + derived-collection + membership-toggle patterns.
- **N‑P1‑5/6/7** visual route classification, slug walk coverage, profile-gate awareness.
- **N‑P0‑4** reference-structured frontend floor (or rail-grid gate) — the biggest fidelity lever.

**Phase D — fidelity polish:** N‑P1‑9 media seed data, N‑P1‑8 catalog-literal handling, visual-gate
tuning.

---

## 6. Iron laws (carried from the handoff — do not violate)

- **Env-agnostic**: prefer contract-driven/config over per-target constants; every projector/gate
  change must not special-case "netflix" any more than it special-cases "tiktok".
- **TDD**: `agent/tests/` is **gitignored, never committed**; each change gets a local test.
- **Commit CODE only** (no `generated/`, logs, run scripts, `design_inputs/`); **no `Co-Authored-By`
  trailer**; **the user merges PRs**.
- **Never runtime-trust a static gate**: delicate app-behavior bugs must be reproduced against a
  running app (needs the provisioned host). Two runs never concurrent; never `docker up/down` while a
  run is live; read the real port from the generated `docker-compose.yml`.
- **Verify empirically before generalizing** a projector taxonomy — the non-CRUD envelope work must
  be driven by an observed Netflix mis-projection, not built speculatively.

---

## 7. Key file:line index

- Envelope: `registryhub.py:208-217,332`; `delivery_gate.py:686-740,1275`.
- Projection: `route_projector.py:44-55,357,405-489,707-1066`; `backend_skeleton.py:354-410,603-622,
  1275-1348`; `database_scaffold.py:40-141`.
- Chains: `chain_executor.py:743,908,1196-1250,1323-1368,1549-1550`; `control_exercise.py:39,84`.
- Frontend: `frontend_page_projector.py:1-24`; `frontend_audit.py:103-129,262-466,549-587,779-829,
  1121-1231`.
- Test-user/visual: `test_user_runner.py:126,177-178,220-239,449-474,838-877`;
  `visual_fidelity.py:54-65,171,198,746,829-840`.
- Kickoff/contract: `kickoff/run_kickoff.py:403,583,1493,1829`; `kickoff/roadmap_validator.py:655`;
  `kickoff/contract.py:222,304`.
- Design-prep: `design_prep.py:36-71,181,613,725`; `material_prep.py:681-693,792,832`;
  `reference_materials.py:246,461`.
- Delivery spine/gates: `orchestrator.py:981,2467,3040`; `deliverability.py:274-545`;
  `validation_runner.py:372-808`; `flow_coverage.py:218-256,298`.
- Tools/memory: `agents/base.py:449-482,545-583`; `agents/agents_config.yaml:85,1143`;
  `tool_surface.py:139-169,445-489`; `hub_registry.py:318-400`.
</content>
</invoke>
