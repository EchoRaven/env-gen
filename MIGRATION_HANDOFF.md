# forgingground-gen — Migration & Continuation Handoff (2026-06-22)

> You are migrating this repo to a bigger machine to keep developing. This doc is the
> single source of truth for: **what the project is, the honest current state, what this
> PR contains, how to stand it up on the new machine, the architecture map, how to run/test,
> and exactly what to work on next.** Read §1 first — it corrects a misconception.

---

## 0. TL;DR

- **What it is:** a multi-agent generator that turns *a text spec + reference screenshots* into a
  complete running full-stack app — FastAPI + Postgres backend, React/Vite/Tailwind frontend,
  OAuth2 (RS256 JWT), multi-tenant, an MCP server, seeded data, Docker. App code is **projected
  deterministically from a contract** (endpoints/tables/ui_pages), not hand-written by the LLM.
- **This session:** 13 commits hardening the pipeline per the directive *"no env-specific
  hardcoding; make the whole pipeline stable + robust."* Full test suite green (3592 passed,
  0 new failures). See §2.
- **Migration:** branch `feat/pipeline-loop` is **111 commits ahead of `origin/main`** (all
  source; no logs/generated). This PR merges them to `main`. After you merge → on the new machine
  `git clone` + `git pull` and you have everything. See §3.
- **⚠️ Read §1:** the running `generated/outlook` you were shown is **~80% hand-edited**, NOT pure
  pipeline output. To see the pipeline's true current output, run a fresh generation (§6).

---

## 1. ⚠️ CRITICAL HONEST STATUS — the demo'd Outlook is hand-edited, not pipeline output

When validating "the pipeline produces a clean Outlook," I was unknowingly running the
**hand-optimized working tree** of `generated/outlook`, not pure pipeline output. The committed
base IS pipeline-generated, but the working tree carries large uncommitted hand-edits (a parallel
session's UI polish + multi-tenant work):

| file | pipeline original | hand-edited |
|---|---|---|
| `InboxPage.jsx` | **109 lines** | **420 lines** |
| `CalendarPage.jsx` | thin | +389 lines (≈rewrite) |
| `LoginPage/SignupPage/LandingPage` | thin | +135 / +108 / +122 |

Total ≈ **12 files, +1298 / −211** uncommitted hand edits, plus `HANDOFF.md` +
`UI_OPTIMIZATION_BRIEF.md` (a manual UI-optimization brief). **So "the pipeline already produces a
reference-faithful Outlook" is NOT established.** What IS established: backend/auth/CRUD/seed and
the *functional* layer are solid; the open gap is **front-end visual fidelity to the references**,
and the pipeline's *unaided* page output is thinner than the polished demo.

**To see the real thing:** `PROJECT_NAME=outlook_fresh bash run_outlook.sh` → inspect
`generated/outlook_fresh` (a fresh run was started this session, then stopped to migrate).

---

## 2. What this PR contains — this session's 13 commits (newest first)

All under `agent/env_generator/llm_generator/`. Driven by the audit (§7) of 47 confirmed findings.

| commit | what it fixes |
|---|---|
| `44e4294` | **mcp** — collision-free MCP tool names. `tool_op_id` stripped both `api/v1/` and `api/`, so `GET /api/tenants` and `GET /api/v1/tenants` both → `get_tenants` (server emitted two same-named tools; one shadowed the other). New `_resolve_tool_names` dedups deterministically. |
| `0fc8941` | **qa** — validate the POPULATED app. The browser test-user + visual gate logged in as a *fresh* user → under multi-tenant scoping they saw EMPTY pages → compared empty screens to populated references. Now they log in as the **seeded demo user** (`visual_fidelity._seed_demo_login`). This is what makes the §8.5 visual gate meaningful. |
| `3542f21` | **audit** — `_route_element` returns the PAGE component, not the guard wrapper (`<ProtectedRoute><InboxPage/>` → `InboxPage`), with balanced-brace parsing. |
| `f4f7421` | **chain** — one broken step no longer aborts the whole verification chain; only steps depending on its unsaved vars are skipped (reports all real failures). |
| `a903def` | **frontend** — write-only pages (PUT/PATCH/DELETE-only) render a real form instead of an inert stub. |
| `af68643` | **seed** — FK/PK type-match: text/uuid primary keys get a deterministic matching key instead of an integer (was producing broken FKs → blank child tables). |
| `f1cace7` | **prompts** — de-bias backend reference-mining + verifier api-test few-shots (rotate cross-domain examples; SHAPE-only caveat). |
| `6c13982` | **pipeline** — domain-neutral seed values (no video/music vocab) + single-sourced frontend error contract to FastAPI `{detail}`. |
| `0f8a7db` | **test-user** — remove the hardcoded social API journey; generic contract-derived CRUD only. |
| `908406e` | **pipeline** — the one HIGH finding: instagram screen vocab baked into the lane's frontend remediation task → now contract-derived; + 3 route_projector fixes (dynamic `/me` user model, dead param-resolver reading phantom keys, search-by-column-type). |
| `3bd1e59` | **test-user** — generic contract-derived CRUD journey (not just social apps). |
| `2b713ee` | **test-user** — stop false-flagging working staged (Microsoft/Google) logins as "auth broken" (register via API, then drive the login UI generically). |
| `e613063` | **test-user** — LLM-compare each key-node screenshot to its reference (`judge_against_references`). |

Plus earlier branch work (the 111 total includes the framework decomposition, kickoff, projector,
gates, etc. — all already on `feat/pipeline-loop`).

**Not in this PR (by design / repo policy):** `agent/tests/` (gitignored, local-only),
`generated/` outputs, logs, run-time scratch. Confirmed: 0 `.log`/`generated/` files tracked.

---

## 3. Git state & migration mechanics

- **Remote:** `git@github.com:Virtue-AI/forgingground-gen.git`. **SSH key is pre-configured** in
  the repo: `core.sshCommand = ssh -i ~/.ssh/id_ed25519_virtueai`. The new machine needs that key
  (or set its own via `git config core.sshCommand`).
- **Branch:** `feat/pipeline-loop` @ `44e4294`, **111 commits ahead of `origin/main` (`22b85a1`)**,
  fast-forward over `origin/feat/pipeline-loop`.
- **This PR:** `feat/pipeline-loop` → `main` (one PR, all 111 source commits).
- **After you merge → on the new machine:**
  ```bash
  git clone git@github.com:Virtue-AI/forgingground-gen.git
  cd forgingground-gen          # main now has everything
  # (or, on an existing clone:)  git checkout main && git pull
  ```
- **Conventions (keep these):** commit CODE only (`agent/tests/`, run-scripts, `generated/` stay
  local/gitignored); **no `Co-Authored-By: Claude` trailer**; push with `id_ed25519_virtueai`.
- **Uncommitted on the OLD machine, NOT in the PR (decide if you want them):**
  `app/hub_reader.py` (a demo-only Env-Forge edit), and untracked local docs
  (`AUDIT_FINDINGS_2026-06-22.md`, `PIPELINE_HANDOFF.md`, `stage_youtube_*.py`). Copy any you want.

---

## 4. New-machine setup

Requirements: **Python ≥ 3.11**, **Docker** (the generator builds + validates each generated app
in docker), git, and the GOOGLE API key.

```bash
# 1. Python env (the old machine used /home/haibotong/miniconda3/envs/dt — recreate equivalently)
python3.11 -m venv .venv && source .venv/bin/activate      # or conda create -n dt python=3.11
pip install -e .                                            # installs engine + Env-Forge deps from pyproject.toml
pip install pytest                                          # for the test suite (if you recreate tests)

# 2. API key (NOT in the repo). The run scripts source /tmp/envgen_key.sh:
echo 'export GOOGLE_API_KEY=<your-gemini-key>' > /tmp/envgen_key.sh

# 3. Model/provider default to gemini-3.1-pro-preview / google (overridable via env: MODEL, PROVIDER).
```

`pyproject.toml` pins the engine deps (fastapi, uvicorn, sqlalchemy, pydantic, jinja2, pyyaml,
httpx/requests/aiohttp, **mcp/fastmcp**, **google-genai/openai/anthropic**, pillow/numpy, pyjwt).
The GENERATED apps carry their own manifests (python-jose, bcrypt, psycopg, …) — not engine deps.

**Tests:** the engine's unit tests live in `agent/tests/` which is **gitignored (local-only)** — so
they do NOT travel with this PR (you asked to exclude tests). This session's fixes each had a
local test under `agent/tests/` (e.g. `test_seed_demo_login.py`, `test_mcp_op_id_dedup.py`,
`test_route_element_parse.py`, `test_chain_executor_dependency_aware.py`, …). If you want them on
the new machine, copy `agent/tests/` separately. Run with:
`cd agent && python -m pytest tests/ -q -p no:cacheprovider`.

---

## 5. Architecture map (where to work)

All under `agent/env_generator/llm_generator/multi_agent/`:

- **`orchestrator.py`** — the spine: milestone loop, coordination ticks, **deterministic framework
  delivery** (`_maybe_framework_deliver`, sole `create_release` caller).
- **Lanes** (`agents/`, prompts in `prompts/v3/*.j2`): backend / frontend / verifier / debugger /
  knowledge. Each wakes on an event, runs one agentic pass, finishes.
- **Kickoff** (`runtime/kickoff/`) — per-milestone "meeting"; lanes declare their slice; the
  orchestrator synthesizes + registers the **contract** into RegistryHub.
- **By-construction projection (the core idea):**
  - `runtime/route_projector.py` — FastAPI handlers from registered endpoints.
  - `runtime/backend_skeleton.py` — `main.py`, models, db, auth, **seed** wiring.
  - `runtime/frontend_scaffold.py` — page components + `App.jsx` routes from ui_pages.
  - `runtime/backend_audit.py` / `frontend_audit.py` — flip contract items defined→implemented by
    auditing the CODE (the lane cannot self-declare implemented).
- **Gates:** `runtime/delivery_gate.py`, `runtime/deliverability.py`,
  `runtime/validation_runner.py` (api_smoke: docker up → probe every endpoint → contract tests),
  `runtime/visual_fidelity.py` (screenshot routes → LLM-compare to references),
  `runtime/coverage_audit.py`, `runtime/page_build_gate.py`.
- **Heal/remediation:** `runtime/heal_pipeline.py`, `runtime/remediation_dispatcher.py`.
- **Test-user (post-milestone QA):** `runtime/test_user_runner.py` (browser engine),
  `runtime/test_user_validation.py` (API/MCP journey). **Both now log in as the seeded demo user.**
- **MCP:** `runtime/mcp_scaffold.py`. **Chains:** `runtime/chain_executor.py`.
- **Web service (Env Forge API + live monitor):** `app/` (FastAPI) + `live_monitor_server.py`.

Run a generation: `agent/env_generator/llm_generator/main.py` (via the run scripts).

---

## 6. How to run + watch a generation

```bash
cd <repo>
# generate (output → generated/<name>/). Use a fresh name to avoid clobbering an existing dir:
PROJECT_NAME=outlook_fresh bash run_outlook.sh        # Outlook (9 pages, mail+calendar+MCP)
# or:                       bash run_youtube.sh        # YouTube (2nd target)
# logs stream to stdout + generated/<name>/logs/.  A run takes ~40 min – 2 h.
```
After it delivers, run the generated app:
`cd generated/<name> && docker compose -f docker/docker-compose.yml up --build -d` → http://localhost:8080.
**Log in as the SEEDED demo user** (e.g. the first user in `generated/<name>/app/backend/seed_data.py`,
password `password`) — a freshly-registered user sees EMPTY pages under multi-tenant scoping.

**Live monitor:** `live_monitor_server.py --workspaces-root <repo>/generated --port <p>` serves a UI
that watches the `generated/` workspaces in real time (the Env-Forge frontend at
`agentsuite-red-frontend`, vite, proxies to it). Remote access = SSH-forward that port.

---

## 7. Open work / roadmap (priority order)

1. **★ Visual fidelity to the references (§6.1/§6.2/§8.5) — THE central remaining problem.** Rich
   pages get authored only where a reference image exists (inbox/calendar); reference-less routes
   (contacts/folders/events) fall back to a generic list page. The visual gate is now *meaningful*
   (logs in as the demo user) and can drive fidelity — but it needs a **fresh generation run** to
   fire. Likely real fix: a **reference-aware page projector** (per-page-type renderer: list /
   detail / form / calendar, derived from the contract + the matched reference).
2. **Non-CRUD endpoint envelope** (`route_projector.py` ~498-769 + `registryhub.py` 273-283 +
   `delivery_gate.py` 409). The single-resource `{item}/{items}` shape is the only one; media /
   watch / aggregate / action / redirect endpoints get mis-projected. **Verify on a live non-CRUD
   run BEFORE generalizing** (don't build the kind-taxonomy speculatively). YouTube's `/watch`
   surfaced this empirically: `WatchPage` fetches `/api/videos/{params.id}` but the route is
   `/watch` (no `:id`) → "Failed to fetch".
3. **Remaining LOW findings** (pure-purity, low value): delegation-rubric examples, orchestrator
   worked examples, `control_plane` `/api/v1/` prefix, `run_kickoff` heuristics,
   `frontend_scaffold` field-guess envelopes. Do only if free + safe.

---

## 8. Gotchas

- **Demo-login, not register:** validate as the seeded demo user (multi-tenant read-scoping makes
  a fresh user's pages empty). This is why the QA tooling looked like it found "blank pages."
- **Docker port collisions:** generated apps' compose binds host `8080/3001/5433`; only one stack
  at a time. `generated/outlook` and `generated/youtube` share compose project name `docker` +
  image names — bring up a fresh one with an isolated project: `docker compose -p <name> up --build`.
- **gemini `MALFORMED_FUNCTION_CALL`:** the pipeline re-rolls (temperature lowered) — normal, not
  fatal.
- **Parallel session:** another worktree (`fg-outlook-pr`) was hand-editing `generated/outlook` and
  occasionally `docker compose down`-ing its stack. On the new (clean) machine this won't apply.
- **Disk:** a run needs a few GB for builds/output; prune docker periodically
  (`docker builder prune`, `docker image prune`).

---

## 9. Pointers (local files on the OLD machine — copy if wanted)

- `AUDIT_FINDINGS_2026-06-22.md` — the full 47-finding generality/robustness audit (file:line +
  fix + risk). The HIGH + all MEDIUM + genuine-robustness LOWs are DONE (this PR); the rest are §7.
- `PIPELINE_HANDOFF.md` (top section) — prior-session optimization brief + this session's update.
- `generated/outlook_HANDOFF/` + its `UI_OPTIMIZATION_BRIEF.md` — the manually-polished UI **target**
  (reference for the §8.5 fidelity work).
- Claude memory: `~/.claude/projects/-data-common-haibotong/memory/` — esp.
  `project_envgen_generality_audit_2026_06_22.md`,
  `project_envgen_testuser_staged_login_falseneg.md`,
  `feedback_envgen_no_env_specific_pipeline.md`.
