# Env-Generation Pipeline — Engineering Handoff & Optimization Brief

**Repo:** `forgingground-gen`  ·  **Owner of this doc:** continue the pipeline optimization
toward generating complete, reference-faithful, working full-stack apps end-to-end with
**no hand-fixing**.

---

## ⮕ SESSION UPDATE — 2026-06-22 (autonomous /loop, directive: "no env-specific; make it stable + robust")

**12 commits shipped; full suite green (3592 passed, 0 new failures — only the 9 documented
pre-existing test-pollution failures remain). The framework is hardened, functionally validated,
and the visual gate is now meaningful.** Highlights:

- **Generality (env-specific removal):** HIGH — instagram screen vocab was baked into the
  frontend remediation task the lane READS → now contract-derived. Removed the social API
  test-user journey (generic CRUD only). De-biased seed values (no video/music vocabulary),
  backend reference-mining + verifier few-shots (rotated cross-domain), search-by-column-type.
- **Robustness:** route_projector (dynamic `/me` user model; dead param-resolver reading phantom
  keys; search). Seed FK/PK type-match for text/uuid keys. Write-only pages render a real form.
  Verification chain no longer aborts on the first broken step. Route-parser resolves the page,
  not the guard wrapper. Frontend error contract single-sourced to FastAPI `{detail}`.
- **Empirical + QA fix:** ran the generated Outlook app → **functionally clean** (auth, CRUD, all
  pages render, no console errors, no dead buttons). Fixed a QA meta-bug: the browser test-user +
  visual gate authenticated as a fresh (empty, tenant-scoped) user → now they log in as the
  **seeded demo user**, so the §8.5 visual gate validates the POPULATED app.

**Remaining gap = visual fidelity of the REFERENCE screens (§6.1/§6.2/§8.5).** `/inbox` + `/calendar`
are rich (lane-authored where a reference exists); the secondary pages (`/contacts /events /folders`
…) are functional-but-generic framework fallbacks — exactly the routes WITHOUT a reference image.
This is now *enforceable* by the fixed visual gate, **but it needs a FRESH GENERATION RUN to fire**
(or coordination with the concurrent `fg-outlook-pr` session hand-editing the same env).

**DECISION POINT (autonomous loop is holding on this):** the safe, high-value framework work is done.
To make further progress on the goal: **(a)** approve a fresh `run_outlook.sh`/`run_youtube.sh` (≈$300,
disk at 95%) and the loop will launch + watch it, driving the now-meaningful visual gate; **(b)** direct
a §8.5 reference-aware-projector design effort; or **(c)** keep the loop on incremental safe items.
Full detail: memory `project_envgen_generality_audit_2026_06_22.md` + `AUDIT_FINDINGS_2026-06-22.md`.

---

## 0. What this pipeline is

A multi-agent system that turns a **text spec + reference screenshots** into a complete,
running full-stack app: **FastAPI + Postgres backend, React/Vite/Tailwind frontend,
OAuth2 (RS256 JWT), multi-tenant, an MCP server**, seeded data, and Docker. It runs as a
team of LLM "lanes" coordinated by an orchestrator, over a sequence of **milestones**
(M1, M2, …), each cut as a release (v1.0.0, v1.1.0, …).

The end goal: feed it `run_outlook.sh` (or any app spec) and get back an app that is
**功能完备 (functionally complete), interactive, multi-tenant, OAuth, and visually matches
the provided reference images** — automatically, without a human finishing the UI.

---

## 1. How to run

```bash
cd <repo>                      # forgingground-gen
export GOOGLE_API_KEY=...      # or put `export GOOGLE_API_KEY=...` in /tmp/envgen_key.sh
bash run_outlook.sh            # generates generated/outlook/  (Outlook spec + 9 ref images)
# logs stream to stdout; also generated/outlook/logs/
```
- Entry point: `agent/env_generator/llm_generator/main.py` (run via the script).
- Model: `gemini-3.1-pro-preview` (Google). Python: `/home/haibotong/miniconda3/envs/dt/bin/python`.
- Output: `generated/<name>/` — `app/backend/`, `app/frontend/`, `docker/`, `docs/`, `logs/`.
- Run a generated app: `cd generated/<name> && docker compose -f docker/docker-compose.yml up --build -d` → http://localhost:8080.
- Other specs: `run_youtube.sh`. Write a new one by copying `run_outlook.sh` and changing
  the DESCRIPTION + `--reference-dir`.
- **Tests** (local-only, gitignored under `agent/tests/`):
  `cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/ -q`.
- Commit conventions: code lives under `agent/env_generator/`; `agent/tests/` is gitignored;
  no Claude co-author trailer; push with SSH key `id_ed25519_virtueai`.

---

## 2. Architecture (where things happen)

All under `agent/env_generator/llm_generator/multi_agent/`:

- **`orchestrator.py`** — the spine. Runs the milestone loop, the coordination ticks, and
  **deterministic framework delivery** (`_maybe_framework_deliver`, the SOLE `create_release`
  caller — it delivers when the gate is clear even if the LLM orchestrator drifts).
- **Lanes** (`agents/`, prompts in `prompts/v3/`): `backend`, `frontend`, `verifier`,
  `debugger`, `knowledge`. Each wakes on events, runs one agentic pass, finishes.
- **Kickoff** (`runtime/kickoff/`) — a per-milestone "meeting": lanes declare their slice
  (endpoints/tables/ui_pages/predicates); the orchestrator synthesizes + registers the
  **contract** into RegistryHub.
- **By-construction projection** (the core idea): app code is **projected deterministically
  from the contract**, not hand-written by the LLM.
  - `runtime/route_projector.py` — FastAPI handlers from registered endpoints.
  - `runtime/backend_skeleton.py` — `main.py`, models, db, auth, seed wiring.
  - `runtime/frontend_scaffold.py` — page components + `App.jsx` routes from ui_pages.
  - `runtime/backend_audit.py` / `frontend_audit.py` — flip contract items `defined→implemented`
    by **auditing the code** (the lane cannot self-declare implemented; see §4 note).
- **Gates** (block/df delivery): `runtime/delivery_gate.py`, `runtime/deliverability.py`,
  `runtime/validation_runner.py` (api_smoke: docker up → probe every endpoint → contract tests),
  `runtime/visual_fidelity.py` (screenshot routes → LLM-compare to references),
  `runtime/page_build_gate.py` (bounded re-dispatch of fallback pages).
- **Heal / remediation** (`runtime/heal_pipeline.py`, `runtime/remediation_dispatcher.py`) —
  deterministic frontend reconciliation + routing gate-failures back to the owning lane.
- **Test-user** (`runtime/test_user_validation.py`, `runtime/test_user_runner.py`) — see §5.

---

## 3. Current state / progress

**Works reliably (validated on Outlook + YouTube, multiple runs):**
- Generates **end-to-end**: kickoff → contract → projected backend → docker → api_smoke →
  milestone releases → Generation Complete.
- **Backend / auth / data are solid**: register + login (RS256 JWT), multi-tenant
  (`tenant_id`), CRUD over all endpoints (verified live: `POST /api/messages` → 201,
  `GET /api/auth/me` → `{item}`), MCP server, seeded data.
- An Outlook build delivered M1+M2+M3 with no abort, and login/CRUD verified in a real browser.

**The weak spot is the FRONTEND UI** — see §4 and §6.

A working **handoff build** of Outlook (hand-finished UI) lives at `generated/outlook_HANDOFF/`
with its own `HANDOFF.md` + `UI_OPTIMIZATION_BRIEF.md`. That is a *manually polished* target,
not what the pipeline produces unaided — closing that gap is the optimization goal.

---

## 4. Solved this session (with the root cause — so you don't re-break them)

Backend / generation robustness (each was a real run-abort, now fixed + tested):
- **`5579bec`** — `GET /<x>/me` projected as a list; now a current-user singleton regardless
  of the resource segment (`/api/auth/me`).
- **`fd56c2e`** — `custom_routes.py` (lane's file) was overriding the SAFE projected handler
  for standard CRUD → a buggy lane handler 500'd. Now custom overrides **only** non-CRUD
  action endpoints (`/{id}/rsvp|reply|forward`); projected wins for collection/item/`/me`.
- **`88aa464`** — verifier chain step `GET /api/messages/${msg_id}` with an unsaved var →
  literal sent → 422 → `business_chain` failed forever. Now an unresolved path var falls
  back to the last captured resource id.
- Docker daemon clogging (243 images / 79 containers) caused a `docker_up` abort — *infra*,
  fixed by `docker container/image/builder prune` (run periodically on the host).

Frontend usability (deterministic fallbacks — the lane reliably does NOT author good pages):
- **`f799e20`** — generic GET fallback page is now a light **row-list** (not a dark
  16:9 video-card grid).
- **`e45d348`** — landing route projects a real navigable page (was a dead `<h2>` heading).
- **`881e5ad`** — projected data pages share a top-nav so the app is navigable.
- **`ad36e24`** — a routed page-import the lane never created now projects a real page matched
  **by route** to the contract endpoint (the lane routes to component names that differ from
  its registered ui_pages).
- **`4a9b159` + `ab7f0a4`** — `App.jsx` routes the lane wrote as inline placeholder divs
  (`element={<div>Login Page Stub</div>}`) are re-pointed to the real page component (incl. `/`).
- **`e1aa912`** — bounded **page-build gate**: detect fallback business pages → re-dispatch the
  lane to build them (≤3 attempts / 900s, then escape — no deadlock). `ENVGEN_PAGES_BLOCKING=1`.
- **`12c3b63` / `88c3f6f`** — the frontend + backend lanes can now actually **view the reference
  images** at build/kickoff (the tools were ranker-crowded-out of their tool surface).

Test-user / visual gate (the "can the pipeline catch bad UI itself?" line of work):
- **`e60b524`** — the visual gate maps reference filenames → routes; it was matching the FULL
  stem so `outlook_inbox` never matched `/inbox` (2/9 mapped → gate blind). Now matches trailing
  segments → 6/9 map (`inbox→/inbox`, `calendar→/calendar`, `landing→/`, `login→/login`).
- **`0cdc6f7`** — a **framework-driven browser test-user** engine (`test_user_runner.py`): drives
  a real headless browser, tests the auth flow, screenshots every route, flags blank/console-error
  pages, returns structured feedback. Validated against a live app.
- **`15263df`** — wired into the per-milestone flow: it now runs each milestone and routes UI
  defects back to the frontend lane as a P0 fix task.

> **Important architecture note** (a recurring source of confusion): a ui_page is marked
> `implemented` by the framework **audit**, not by the lane (the lane self-claiming is downgraded
> to `defined` — `registryhub.py` mechanism #54). The audit is *structural* (route wired +
> references an API + no dead controls) and does **not** look at the framework's own
> `_PAGE_MARKER`, so a framework scaffold passes as "implemented". This is why bad UI ships:
> the structural audit can't tell a real page from a scaffold. The page-build gate + the visual
> test-user are the intended backstops.

---

## 5. The test-user (post-milestone QA loop) — design & status

Intended loop (per the product owner): **each milestone end → orchestrator recruits a
test-user → it tests the declared features with web tools (click/type) → screenshots key
nodes and compares to the reference images → gives feedback → lane fixes → re-test.**

Built so far:
- `runtime/test_user_runner.py :: run_browser_test_user()` — the engine (auth flow + per-page
  screenshot + blank/console checks + `format_feedback()`).
- `runtime/heal_pipeline.py :: _run_browser_test_user()` — recruited per milestone inside
  `run_test_user_validation`; dispatches a P0 fix task on defects.
- `runtime/visual_fidelity.py` — `capture_route_screenshots` + `judge_screen_pair` (LLM compares
  a screenshot to its reference) already exist and work.

**Not yet wired (next step):** connect `judge_screen_pair` into the browser test-user so each
key-node screenshot is LLM-compared to its reference and the verdict ("inbox doesn't match
`outlook_inbox.png` — missing folder rail / wrong theme") is part of the feedback the lane gets.
Also: the API journey in `test_user_validation.py` is **hardcoded for a social app**
(`POST /api/posts`, "caption", like/comment) — make it generic (derive from the contract).

---

## 6. Open issues / known gaps (priority order)

1. **The frontend lane does not reliably author good pages.** It declares ui_pages but ships
   stubs / inline-div routes / mismatched component names. Today the deterministic projection +
   reroute fixes are the floor; the lane rarely improves on them. **This is THE central problem.**
   Two directions (pick/combine): (a) make the deterministic projection genuinely good +
   reference-aware so the floor *is* the product; (b) make the lane reliably author (better
   prompts + the page-build gate + the visual test-user feedback forcing iteration).
2. **Visual fidelity to the references is approximate.** The projection produces clean, generic
   pages; it does not reproduce the Outlook 3-pane / folder-rail / reading-pane layout. With
   `e60b524` the visual gate can now *judge* this; making it *drive* a faithful result is open.
3. **Seed realism is domain-blind.** `backend_skeleton.render_seed_data` fills every text column
   from one generic pool (Outlook folders came out named "Sunrise Timelapse over the Bay",
   `kind=video`). Make the seed domain-aware (column/table-name heuristics, or LLM-authored seed).
4. **Non-CRUD action endpoints** (`/{id}/rsvp|reply|forward`) are still mis-projected (treated as
   a create); `fd56c2e` lets the lane's `custom_routes` override them, but the projector itself
   should handle them.
5. **Page-build gate + visual gate are bounded-escape** (deliver below-threshold rather than
   deadlock). Good for liveness, but means a sub-par UI can still ship. Tuning the escape +
   making the test-user feedback a stronger driver is open.
6. **Validate the test-user loop end-to-end in a real run** (it's unit/integration-tested, but
   not yet observed firing inside a full generation).
7. **Infra:** host disk has run ~97% full; prune docker + watch disk before long runs.

---

## 7. Optimization goal (definition of done)

Run `bash run_outlook.sh` (and an unseen spec) and, with **no hand-editing**, get an app where:
- it generates + delivers end-to-end with no abort (✅ today),
- backend/auth/CRUD/multi-tenant/OAuth/MCP all work (✅ today),
- **every declared page renders the real, intended UI** (not a stub/fallback) — verified by the
  browser test-user,
- the **key screens visually match the reference images** (judged ≥ threshold by the visual gate),
- **seed data is domain-appropriate** so the app looks real on first load,
- the post-milestone **test-user loop** catches UI/flow defects and drives fixes automatically.

Keep every change **general (domain-agnostic)** — no app-specific hardcoding. The pipeline must
generate *any* app from its spec + references, not just Outlook.

---

## 8. Suggested next steps (in order)

1. Wire `judge_screen_pair` reference-comparison into the browser test-user feedback (§5).
2. Run a full generation with `ENVGEN_PAGES_BLOCKING=1` and watch: does the test-user fire, does
   it screenshot + judge, does it dispatch fixes, does the lane act? Iterate.
3. Make the seed generator domain-aware (§6.3).
4. Make the API test-user journey generic (§5).
5. Tackle the central problem (§6.1) — likely a reference-aware page projector (e.g. a
   per-page-type renderer: list / detail / form / calendar derived from the contract + the
   matched reference), so the deterministic floor is genuinely good.

Key reading order: `orchestrator.py` (`_maybe_framework_deliver`) → `route_projector.py` →
`frontend_scaffold.py` → `delivery_gate.py` → `visual_fidelity.py` → `test_user_runner.py` →
`heal_pipeline.py`.
