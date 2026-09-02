# HANDOFF — envgen pipeline trajectory review + optimization (2026-07-29)

Self-contained handoff for a fresh session. Repo: `/data/common/haibotong/forgingground-gen`
(NOT a git repo at `/data/common/haibotong`; the git repo is `forgingground-gen/`).
Branch: `feat/pipeline-opt-6`. **HEAD = `c9224a0`** (all work below already committed + pushed).

---

## 1. What this session did (why we're here)

The tiktok env-generation `/loop` was running r93 (opus-4.7). At ~09:57 the shared **metagen LLM
key hit its $10k spend cap** → every LLM call 400s `Spend exceeded. Budget for mg key
mg-api-71b41b05af9a`. The run became a zombie (~11k rejected retries); I killed it. **No working
key exists on the machine** — all `/tmp/envgen_*.sh` share the SAME exhausted key (opus + gemini,
one $10k budget).

> **UPDATE (later same day): budget RAISED to $22k and LIVE-CONFIRMED.** The metagen key
> `mg-api-71b41b05af9a` works again — verified with a curl probe (returned a normal completion,
> no "Spend exceeded"). r94 is **unblocked and ready to launch now** (§3). Re-verify with the §5
> curl before a long run, but as of this handoff the key is good.

The user then asked: **review ALL prior generations' trajectories and optimize the pipeline.**
I fanned out **6 parallel review agents** over r91/r92/r93 (`.agent_logs/<Agent>/*.jsonl` +
`gm_tiktok_rNN.log` in the REPO ROOT) — one per lane (orchestrator/verifier/backend/frontend) +
a cross-run cost reviewer + a helper-agent auditor. **3 independent reviewers converged on the
same top bugs.** Full findings are in `scratchpad/review_findings.md` of the ORIGINAL session's
scratchpad — reproduced in §4 below so this doc is self-contained.

---

## 2. SHIPPED this session (TDD, committed + pushed to vaibackup feat/pipeline-opt-6)

All six have local tests under `agent/tests/` (gitignored) and passed with zero new regressions
(the only failing tests in the suite are ~8 PRE-EXISTING seed-waiver / condensation / temporal /
uuid failures, proven pre-existing by stash-compare — NOT ours).

| # | commit | file(s) | one-line |
|---|--------|---------|----------|
| #324 | 5945fa7 | runtime/deliverability.py | reconcile lane seed BEFORE the authored-seed read (dominant sink) |
| #325 | 0b4bd06 | runtime/frontend_scaffold.py | api-path reconcile no longer strips `/api/videos/`+id → 404 |
| #326 | 32aab43 | utils/llm.py + multi_agent/orchestrator.py | circuit-breaker: terminal spend/auth 400 → run abort ~60s |
| #327 | 38ba793 | runtime/framework_validation.py | regression-guard poisoned-snapshot escape (r92 68% livelock) |
| #328 | 60bbb70 | runtime/remediation_dispatcher.py | dedupe failed_checks → one P0 task per distinct check |
| #329 | c9224a0 | prompts/v3/orchestrator_agent.j2 | state milestone auto-advance semantics (stop rediscovery) |

Tests (one per fix): `test_324_seed_reconcile_before_read.py`, `test_325_api_path_reconcile_concat.py`,
`test_326_terminal_llm_error_circuit_breaker.py`, `test_327_poisoned_snapshot_escape.py`,
`test_gate_level_check_dispatch.py::test_duplicate_check_names_dispatch_one_task`.
(Earlier this session, before the review: #323 `0fdcd2c` — chain_executor middle-segment param +
owner-scoped self-view recovery — also shipped.)

---

## 3. IMMEDIATE NEXT STEP (budget is LIVE — ready now)

1. Budget is already restored ($22k, live-confirmed — see §1 UPDATE). Sanity-check with the §5
   curl before a multi-hour run; if it ever returns "Spend exceeded" again, the cap re-tripped —
   raise it (finance POC via `internalfb.com/metagen/tools/entitlements/mg-api-71b41b05af9a?t=Budget`)
   or drop a fresh key into `/tmp/envgen_opus47.sh` (`ENVGEN_LLM_KEY`).
2. **Launch r94** to validate all 6 fixes end-to-end (see §5 for the exact command). Watch for:
   - #324: `grep "authored seed missing"` should NOT wedge M1 (seed reconciles on first poll).
   - #327: `grep "REGRESSION GUARD"` restores ≤2 then "poisoned" — no 38-cycle livelock.
   - #329: orchestrator should NOT log "KEY DISCOVERY" milestone rediscovery / spam deliver_project at M1.
   - #326: (only if budget dies again) run aborts ~60s with "LLM provider budget/auth exhausted".
   - #325: inspect delivered `generated/tiktok-web-r94/app/frontend/src/services/api.js` — paths like
     `request('/api/videos/' + id)` must keep the slash.
3. If r94 reaches a clean 3-milestone COMPLETE → **browser-test the delivered app** (playwright MCP
   or curl; port from the compose file, NOT `docker ps|grep backend`): signup/login/feed work? UI
   fidelity vs the TikTok reference (the user's #1 concern "UI不够相似" — see FE-F5 backlog item).

---

## 4. BACKLOG — real, evidence-backed, but NEEDS A LIVE RUN to validate (do after r94)

Ranked by impact. Full evidence + file:line in the original scratchpad; key pointers here.

**COST (highest leverage):**
- **Orch-F1 — per-role stage allowlist.** 42% of orchestrator LLM calls are dead-stage no-op filler
  ("Not an edit_code task", "Skipping") = ~45% of its tokens. `base.py:153` ACTION_INTERNAL_STAGES
  loops the coordinator through edit_code/delegate_team stages it can't act in; the fast-skip at
  `step_pipeline/action.py:308` never fires because orch's memory/reference tools map to the
  edit_code category (`base.py:162`). Fix: per-role stage allowlist — Orchestrator = (communicate,
  run_checks, deliver); gate `action.py:448` to `continue` WITHOUT an LLM call for disabled stages.
- **No prompt caching — PROBED, verdict NO on metagen (do not spend more effort here until a
  metagen-team answer).** Zero `cache_control` repo-wide; the #255 prefix-stability machinery
  (`utils/llm.py:650`) was built for GEMINI implicit caching and does nothing on the Anthropic/Vertex
  provider actually used. **I probed the metagen OpenAI-compat endpoint directly (~15 calls, 3 request
  shapes, streaming + headers, 8k & 28k prefixes):** `cache_control` is silently accepted (never 400s)
  but INERT — no `cache_read_input_tokens`/`cached_tokens`/`prompt_tokens_details` anywhere (body,
  stream-usage, or headers), and `total_tokens` is IDENTICAL on repeated identical prefixes (no
  discount). `prompt_tokens` is hardcoded-broken at 6. Latency is flat ~1s for 8k AND 28k prefixes
  (backend likely caches for SPEED, but that's not billed-cheaper and can't be counted). **Conclusion:
  no usable/verifiable cache on this transport — stamping `cache_control` would be a no-op.**
  To unblock, one of: (a) metagen team confirms they forward `cache_control` to Vertex, bill cached
  input at a discount, AND expose `cache_read` in usage (an email draft covering these 3 questions was
  written for the user to send — check with them); OR (b) route opus through an Anthropic-native
  endpoint (first-party Messages API / direct Anthropic-Vertex client) that reports+bills `cache_read`
  at ~0.1×, then stamp `cache_control` on the folded system block + #255 prefix boundary and assert
  `usage.cache_read_input_tokens>0`. Full evidence: memory `reference_envgen_metagen_key_budget`.
- **Observation-mask disabled on opus-4.7.** `model_limits.py:106` maps opus→1M-tok window, so
  `_mask_old_observations` (`utils/llm.py:636`) early-returns the FULL history every call. Fix: add
  `ENVGEN_CTX_SOFT_CHARS` (~120k) that trims old tool-output bulk even when it "fits" the 1M ceiling.
- **prompt_tokens=6 blind accounting** — gateway returns a placeholder; framework can't see its own
  input cost. Fix: estimate chars/4 when usage implausible; feed run_budget so aborts are cost-aware.
- design-prep re-encodes full-size reference PNGs (27M-char single messages) every send = 30-45% of
  char volume. Fix: downscale+cache each ref image <4.5MB once at staging; attach only the
  component-relevant image per call.

**LIVELOCK / CORRECTNESS (source-side of what #327/#324 patched downstream):**
- **V-F2 — freeze-on-green is NAME-keyed, never fires** (`frozen:true`=0 all runs). Verifier registers
  near-synonym chain names (reply_share_sound_flow vs reply_share_and_sound_flow) → each a fresh
  un-frozen chain re-introducing the bug. `registryhub.py:1628` freezes only when name in existing.
  Fix: freeze on STEP-SIGNATURE (`_fwval_chain_signature` at framework_validation.py:219); reject a
  newly-registered chain whose normalized step-set duplicates an already-green one. (This prevents the
  churn at the SOURCE; #327 is the safety-net that already breaks the loop.)
- **Orch-F3 — no per-milestone deadline; churn defeats stuck-abort.** `_abort_grace_should_defer`
  (`orchestrator.py:272`) defers abort whenever source changed, so a lane making non-converging edits
  defers fail-fast forever. Fix: per-milestone hard deadline (mirror visual escape_s at
  orchestrator.py:318); key the progress signature on the FAILING-CHECK-SET changing, not raw source bumps.
- **Backend-F4 — framework /auth/register drops `username`** (oauth_scaffold.py:79-84 contract is
  {email,password,name?,tenant_id?}, no username persisted/echoed). TikTok keys social endpoints on
  username → keystone bug the backend can only band-aid via a response wrapper (#321/#323 were runtime
  bandaids for THIS). Fix: register scaffold persists+echoes declared-extra `users` columns present in
  both the request and `registryhub_list_tables()["users"]`.

**DEAD / HOBBLED HELPERS (cost + false architecture):**
- Debugger Agent: registers an 86-tool surface every run, receives **0 tasks** both runs (orch spawns
  Analysis Workers directly). Fix: route bug_create P0s through it OR delete from the resident roster.
- Knowledge Agent: wakes, finds nothing, `finish` with no write, both runs — retrieval bypasses it
  (`knowledge/tools.py:40` hits the store directly). Fix: drop it OR emit its trigger events.
- MCP test-user gated on SOURCE-DIR not compose-reachability (`test_user_squad.py:403`) → spawns a full
  ~49k-token agent to rediscover "MCP not reachable". Fix: gate on compose declaring an mcp service + a
  TCP probe; else emit ONE deterministic deliverability bug.
- Test-users file DUPLICATE bugs (no dedup in `bug_tools.py`) → dup fix tasks + inflated P0 counts.
- Analysis Worker (stall_diagnostic) lacks workhub/registryhub read tools → diagnoses blind.

**COORDINATION / OTHER:**
- Backend-F2: vestigial `seed_data.registered=0` (`deliverability.py:194,197`) → orch hallucinates a
  nonexistent `register_seed_data()` code symbol + files phantom P0s. Fix: drop the field. ⚠ check
  nothing asserts on `report.seed_data["registered"]` before removing.
- FE-F3: frontend told to `docker compose build` but has NO docker/bash tool → 25-min stale-bundle
  loop. Fix: `run_validation` (verifier) rebuilds `--no-cache frontend` before asserting bundle contents.
- **FE-F5 (user's UI concern): dead-nav "remove is cheapest" gutted the app to 3 routes.** Delivered r93
  App.jsx wires only /login /signup / * though the reference has 10+ screens; remediation
  (`frontend_audit.py:503-510`) steers toward deleting nav items. Fix: when a dead-nav target maps to a
  reference screenshot, flip remediation to "author this page"; scope those ui_pages at kickoff.
- Orch-F6: silent-lane nudge counter resets on any agent_status → per-episode cap never bites for
  slow-alive lanes (`coordination.py:153,191`). Fix: cumulative per-(lane,task); suppress re-nudge while
  the lane holds the same task in_progress.
- Verifier-F4: redundant `run_validation` re-runs (r92=204, 94 back-to-back <30s) — debounce on
  app-source+chain signature; gate CONVERGING-GRACE on failing-STEP identity not set size.

On "review ALL prior generations": r91/r92/r93 carry the latest fixes so their remaining bugs ARE the
current framework bugs; earlier runs (r1-r90) and other envs mostly re-expose already-fixed classes
(diminishing returns at real token cost). Sample a specific earlier/other-env run only if chasing a
particular angle.

---

## 5. OPS — how to run/test/push (exact)

- **Python**: `/home/haibotong/miniconda3/envs/dt/bin/python`. Run pytest FROM `agent/`.
  - `cd /data/common/haibotong/forgingground-gen/agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/<file> -q -p no:cacheprovider -p no:randomly`
- **Tests are gitignored** (agent/tests/ local-only). One test file per fix, TDD (red→green).
- **Launch a run** (needs ≥60G disk; `docker builder prune -af` if low — currently ~87G free):
  - `cd /data/common/haibotong/forgingground-gen && setsid bash -c 'source /tmp/envgen_opus47.sh && ./run_tiktok_designinput.sh 94 > gm_tiktok_r94.log 2>&1' < /dev/null &`
  - (setsid REQUIRED — plain nohup child dies on session rotation.)
  - orchestrator PID: `pgrep -f "main.*tiktok-web-r94"`. Logs in REPO ROOT `gm_tiktok_r94.log`.
- **Key probe before launching** (confirm budget restored):
  - `source /tmp/envgen_opus47.sh && curl -s -m 30 -X POST "$ENVGEN_API_BASE/chat/completions" -H "Authorization: Bearer $ENVGEN_LLM_KEY" -H "Content-Type: application/json" -d "{\"model\":\"$ENVGEN_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":5}"`
  - If it returns "Spend exceeded" → still dead.
- **Push**: `GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes' git push vaibackup HEAD:feat/pipeline-opt-6`
  - ⚠ **NO Claude co-author trailer** in commit messages (user preference). Commit per-fix, TDD.
- **Monitoring a live run** (user directive): timed **20-min ScheduleWakeup is the PRIMARY heartbeat**,
  re-armed EVERY turn (survives session rotation); don't rely on Monitor/watcher (lost on rotation).
  Token-lean each wake: 1-line `ps -p <pid>` + grep terminal/milestone marker; deep-dive only on a real
  terminal/wedge. Cold-start "persists" 10-15min is NORMAL, not a deadlock.

---

## 6. Framework-first doctrine (user, load into working memory)

With a strong model (opus-4.7/4.8), a run failure defaults to a FRAMEWORK problem (unenforced
contracts, gate false-positives, heal tug-of-wars, synthesized-probe defects) — NOT "LLM quality".
The ONLY legitimate LLM-quality axis is UI visual fidelity. Every fix must be generally correct
(projected/framework code has no lane to fix it). See memory
`feedback_strong_model_framework_first_diagnosis` + `feedback_framework_projected_code_must_be_correct`.

Relevant memory files: `project_envgen_trajectory_review_opt` (this work),
`reference_envgen_metagen_key_budget` (the $10k cap), `feedback_proactive_run_monitoring`,
`project_envgen_designprep_phase`, `project_envgen_frontend_zero_fallback_findings`.
