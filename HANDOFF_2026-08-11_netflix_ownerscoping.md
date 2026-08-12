# HANDOFF — Netflix env-generator generality (owner-scoping arc)
**Date:** 2026-08-11 · **Author:** previous agent (sessions r119→r130) · **For:** next agent
**Branch:** `feat/netflix-generality-366-367` · **Repo:** `/home/haibotong/forgingground-gen`

> This is a **self-contained** handoff. Read top-to-bottom. Deep per-run history lives in
> `HANDOFF_2026-08-07_multimilestone.md` (sessions 10–29) — this doc consolidates the CURRENT state,
> the systemic root cause, and exactly what to do next. When in doubt, prefer THIS doc.

---

## 0. TL;DR (read this first)

- **Goal (泛化性 / generality):** the generator must produce apps that are functionally-complete +
  bug-free + UI-highly-similar + **generalizable**. All fixes must be **generalizable framework changes**,
  NEVER app-specific hacks / product literals. Success = a clean **multi-milestone** delivery
  (≥2 progressive tags, rc=0) on ANY random draw.
- **Standing directive from the user:** *“持续优化整个pipeline，直到能完美没有bug的构建我们目标的环境”*
  (keep optimizing the whole pipeline until it can perfectly, bug-free build the target environment).
  This authorizes an autonomous **launch → monitor → diagnose → fix + commit → relaunch** loop.
- **State right now:** nothing running, 0 containers, git tree clean.
- **Git:** on `feat/netflix-generality-366-367`, **10 unpushed commits (#566m→#566v)**. Origin is at
  `#566l`. **You (or the user) must push** — the agent's github egress is 403 (attempt once, harmless,
  then the USER pushes): `git push origin feat/netflix-generality-366-367`.
- **What's proven:** favorable draws deliver clean multi-milestone (r115/r118/r121/r125 — up to full
  3-milestone). #566s (IDOR) + #566t (rating value-null) validated end-to-end in r129. #566u/#566v are
  unit+render validated but **need an e2e run** that reaches the M2 rating/read-isolation chains.
- **★ SYSTEMIC ROOT — SUPERSEDED 2026-08-11 (session r131), read §5 before acting.** The "lane
  owner-scoping variance" story below is now believed to be largely a DOWNSTREAM ARTIFACT. The proven
  root is **#566x: a verifier coverage chain FACTORY-RESETS the database mid-validation-pass**, wiping
  the seeded catalog every later chain reads its `${...}` ids from. Fixed + committed; **r131 is the
  validating run.** §5 keeps the old theory for context and marks what it explains vs. what it doesn't.

---

## 1. What this pipeline is (30-second orientation)

- A multi-agent LLM generator (`agent/env_generator/llm_generator/…`) builds a full Netflix-like web app
  (FastAPI backend + React/Vite frontend + Postgres + nginx, in docker/podman) across **milestones**
  (M1, M2, M3). Each milestone is validated by a **delivery gate** and only ships (`cut release vX.Y.0`)
  when the gate is green. Multi-milestone success = the monitor prints `*** MULTI-MILESTONE VALIDATED ***`.
- **Two handler layers (CRITICAL to understand):**
  1. **Framework-PROJECTED handlers** — `route_projector.py` emits them into `main.py` from the contract.
     These are what the framework FULLY controls. #566s/#566t/#566u fixed these.
  2. **LANE-authored CUSTOM handlers** — the backend agent writes `custom_routes.py`. FastAPI registers
     the custom router **before** the projected routes, so **custom handlers WIN** (shadow the projected
     ones). This override is the crux of the remaining systemic problem (§5).
- **Verification chains:** the verifier agent authors business-flow chains
  (`registryhub_register_verification_chain`); `chain_executor.py` runs them; the delivery gate reads each
  chain's `last_result`/`status`. `business_chain_failing` blocks delivery.

---

## 2. How to run / monitor / tear down (exact commands)

**Environment facts:**
- Gen runs from the LOCAL tree (pushes do NOT affect a run — the code on disk is what runs).
- 5 base images must be cached for offline docker builds: `node:20-alpine`, `nginx:alpine`,
  `postgres:16`, `python:3.11-slim-bookworm`, `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`.
  `tools/ensure_base_images.sh` heals/caches them; the **keeper** loop re-runs it every 240s.
- Ports (liveness): vertex `:8790` (404 = up), relay `:19080` (400 = up).
- `BuildKit is pinned OFF` (`DOCKER_BUILDKIT=0`) in validation_runner — classic layer cache is the
  offline mechanism (do not "fix" this).

**Launch a run (rNNN = next number, e.g. r131):**
```
cd /home/haibotong/forgingground-gen
ENVGEN_SINGLE_MILESTONE=0 FW_DEBUG=1 ENVGEN_VISUAL_MIN=0.65 \
  nohup ./launch_netflix.sh netflix-web-rNNN > gm_netflix-web-rNNN.launch.log 2>&1 &
sleep 25 && grep -iE "started pgid|ensure-bases.*OK|proxy pong OK" gm_netflix-web-rNNN.launch.log
```
Gen log: `gm_netflix-web-rNNN.log`. Gen PID: `ps -eo pid,cmd | grep "[.]venv/bin/python -m env_generator" | grep netflix-web-rNNN | grep -v grep`.

**Keeper (base-image healer) + monitor:**
```
nohup bash -c 'while pgrep -f "env_generator.llm_generator.main.*netflix-web-rNNN" >/dev/null 2>&1; do
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  /home/haibotong/forgingground-gen/tools/ensure_base_images.sh >/dev/null 2>&1; sleep 240; done' \
  > r_NNN_base_keeper.log 2>&1 &
nohup ./r112_monitor.sh netflix-web-rNNN > netflix-web-rNNN_monitor.nohup.log 2>&1 &
```
Monitor writes `netflix-web-rNNN_monitor.TERMINAL` at the end with the VERDICT
(`MULTI-MILESTONE VALIDATED` / `NON-SUCCESS / WEDGE`), release tags, and rc.

**A full run takes ~2–3h** (favorable) and slow draws grind longer (r129 M1 alone took ~2h).
Confirm multi-milestone env is set: `tr '\0' '\n' < /proc/<PID>/environ | grep ENVGEN_SINGLE_MILESTONE=0`.

**Teardown (do this when a run is done/wedged):**
```
kill -TERM <keeper_pid> <monitor_pid>; kill -TERM <gen_pid>; sleep 2; kill -KILL <gen_pid> 2>/dev/null
podman rm -f -a 2>&1 | tail -1
```
**pkill FOOTGUN:** NEVER `pkill -f <pattern>` — it matches your own command. Kill by PID/pgid only.

**Quick status one-liner while monitoring:**
```
cd /home/haibotong/forgingground-gen
echo "gen: $(ps -o etime -p <PID> 2>/dev/null|tail -1||echo DOWN) | tags: $(python3 -c "import json;d=json.load(open('agent/generated/netflix-web-rNNN/shared/hubs/codehub_releases.json'));print([k for k in d if k!='_meta'])" 2>/dev/null)"
grep 'delivery gate has' gm_netflix-web-rNNN.log | tail -1
```

---

## 3. Fixes landed this arc (all committed + unit-tested; #566m→#566v = 10 unpushed)

| # | commit | what it fixes | validated |
|---|--------|---------------|-----------|
| #566m | fabbee2 | `chain_executor._dig`: numeric index into a BARE list + strip wrong path prefix (profile IDOR var-bind) | r125 e2e |
| #566n | 7d442f9 | create-schema heal: nested creates + REQUIRED typed columns (rating value-null business_chain 400) | r125 e2e |
| #566o | 69fed9a | test-user UI-auth: report the TRUE login failure mode (not "form not wired" for a wired form) | diagnostic |
| #566p | ff6c1cf | readback advisory shows GET list contents (persist-vs-owner-scope diagnosis) | diagnostic |
| #566q | a707df5 | delivery gate: fix `verification_checklist` AttributeError on >1 `build:*` record/component (multi-PR) | unit |
| #566r | f6078bf | `bare_authed_fetch`: global `window.fetch` auth-wrapper heal (fix r126 79-min abort) | r127 e2e |
| #566s | 09c8911 | **cross-user IDOR** in projected CREATE: reject/verify body owner-FK ownership (`_fw_owns`) → 403 | r129 e2e |
| #566t | 2d6054b | projected CREATE: apply DB column DEFAULT for a dropped NOT-NULL col (`_fw_fill_required_defaults`) | unit+render |
| #566u | 8b393b2 | projected CREATE: UPSERT owner-scoped state-writes on (owner,subject) conflict (rating 409) | unit+render |
| #566v | 0b6f935 | `chain_executor` read-isolation re-verify: tolerate SECURE-override reads (fix r130 oscillation) | unit |
| #566w | 4ab3000 | route-override policy: normalize kebab-case path segs to the table-name namespace — EVERY multi-word resource (`my_list`→`/api/my-list`) missed the #77/#528 "projected read wins" guard, so a buggy lane GET shadowed the safe projected read | unit (6 cases, render+compile) |
| #566x | a2381a1 | **chain executor: send the control-plane reset TENANT-SCOPED** — a bare `POST /api/v1/reset` took the FACTORY branch and wiped the shared seed fixture mid-pass (§5) | unit (7 cases, incl. r130 replay) |
| #566y | 76d17ea | **projected reads owner-scope a SUB-ENTITY-owned resource** without the contract flag — the create enforced ownership on the column while the read returned every persona's rows (live cross-user leak in r131; the other half of #566w) | unit (9 cases, ast+render+compile) |

**Test discipline used (follow it):** every fix has a unit test under `agent/tests/test_*_566X.py`
(NOTE: `agent/tests/` is **gitignored** — tests exist on disk but are not committed). For emitter/skeleton
changes, the test **renders a sample `main.py` via `render_skeleton_main` and `py_compile`s it** — this is
the critical safety net that catches "a bad emit breaks EVERY app's generation" BEFORE a 2–3h run. Always
add that render+compile assertion for any `route_projector.py` / `backend_skeleton.py` change.

**Full test suite:** `cd agent && PYTHONPATH=. ../.venv/bin/python -m pytest -q`
→ currently **1266 passed**, **73 pre-existing `oauth_contract/test_zoom.py` network failures** (UNRELATED
— they fail because of no network; ignore them). Any NEW failure is yours.

---

## 4. Framework owner-scoping helpers (the toolbox — reuse these, don't hand-roll)

In `backend_skeleton.py` `_MAIN_HEADER` (a big triple-quoted string rendered into every `main.py`; edit
the string text and it propagates — that's how #566h/#566s/#566t/#566u shipped):
- `_fw_uid(user)` — the caller's user id (type-coerced).
- `_fw_owner_val(cls, col, user)` — resolves (and AUTO-PROVISIONS if absent) the caller's OWN owner value
  for `cls.col`. Handles both DIRECT user-owned FKs and per-user SUB-ENTITY FKs (profile_id→profiles→users)
  via battle-tested FK introspection (#134/#390/#391). **This is the canonical "caller's own scope."**
- `_fw_owns(cls, col, fk_val, user)` (#566s) — True iff `fk_val` for `cls.col` belongs to the caller (own
  uid for a direct FK; an owned sub-entity for a per-user FK). Fail-OPEN only on introspection FAULT.
- `_fw_fill_required_defaults(cls, valid, db)` (#566t) — fills an absent NOT-NULL no-model-default column
  from the DB column default (information_schema).
- `_fw_upsert_on_conflict(db, cls, valid, user, owner_fk, subject_fks)` (#566u) — reactive upsert (called
  from the projected create's `except IntegrityError`): loads the caller's existing row by owner+subject
  and UPDATEs it; None → re-raise (409). Only on a real conflict → never wrongly upserts a non-state-write.

In `chain_executor.py` (validation layer):
- `_is_cross_user_denial(st)` — a step asserting THIS actor must be denied (expect 403/404, no 2xx).
- `_reverify_denial_via_fresh_intruder(base, method, path, body, expect)` (#78 + **#566v**) — on an
  apparent leak (denial step got 2xx), re-runs as a brand-new intruder. **#566v:** for a GET, a fresh
  intruder's 2xx is a real leak ONLY if `_response_has_rows()` (the foreign owner's data); an empty list =
  secure override → tolerate. Never masks a leak (a leak returns rows → kept broken).

---

## 5. ★ THE SYSTEMIC ROOT — REVISED 2026-08-11 (session r131)

### 5.0 THE PROVEN ROOT: a coverage chain factory-resets the DB mid-pass (#566x)

**Read this before acting on §5.1 — it reframes most of it.**

The fixed control surface (`control_plane.py`) contracts `POST /api/v1/reset` as *"scoped (X-Tenant-Id
→ that tenant's business rows) or **factory (no header)**"*. The verifier authors an infra-coverage
chain that POSTs it **bare** — which the delivery gate's api-coverage check actively pushes it to do,
since every REGISTERED endpoint wants exercising. That takes the FACTORY branch: `DELETE FROM titles,
genres, episodes, profiles, my_list, ratings, continue_watching`. **All chains run in ONE pass against
ONE shared database.**

The reset step itself **PASSES** (200 is the correct answer), so nothing is flagged where the harm
happens. It resurfaces in every chain that runs AFTER it, wearing application-level clothing:

| observed symptom | actual cause |
|---|---|
| `GET /api/titles → 200 {"items":[]}`, `save FAILED: titleId<-items.0.id` | catalog wiped |
| `POST /api/my-list → 404 "referenced resource not found"` | `${titleId}` starved → the placeholder ladder filled an unrelated id |
| `POST /api/titles/41/rating → 404 "parent resource not found"` | same (41 = a profile id from the same chain) |
| `rating db op failed: … ratings … foreign key` (r128) | title row gone |
| `DENIAL-PROBE got success` on a cross-user write (r127) | an emptied DB makes an isolation probe meaningless — the foreign owner no longer exists |

**r130 ground truth** (`agent/generated/netflix-web-r130/shared/hubs/registryhub_verification_chains.json`,
49 chains, one pass at 22:54:19): reset chain at index **20**; failing chain indices
`[24,25,27,28,29,30,31,39,40,41]` — **zero before the reset, all ten after it.** Same shape in r127
(reset@2, failing `[25,28,29,39,40]`) and r128 (reset@16, failing `[35,39,60]`): **18 of 18 failing
chains across the three runs sit after the first reset; none before.**

Because it is deterministic every pass, the gate can never see all chains green in ONE eval →
`business_chain_failing` → wedge. **This is also the better explanation for §6.1's "flapping"**: the
verifier re-authors/reorders chains between passes, so the SET of chains sitting downstream of the
reset changes → different checks red each eval, with no staleness involved. (Verified: in r130 every
chain carried the SAME `last_run_at` — nothing was stale; the failures were live.)

Corroboration that the app side already met this and could not fix it: the generated backend
hand-rolled a defensive 15-title backfill in `custom_routes._ensure_backfill` citing
`bug task_b41446c659` — but it is a **process-global one-shot** (`_BACKFILL_DONE`), so it never
re-fires after a mid-pass wipe. The fixture invariant is the framework's to own, not the lane's.

**Fix (#566x, committed `a2381a1`):** when a chain step targets the reset path, send `X-Tenant-Id` so
the handler takes its SCOPED branch. Scope preference — a tenant THIS chain created → the chain user's
registered tenant → a deterministic synthetic id that owns nothing (deletes nothing, still answers
200). Never harvested from `GET /api/v1/tenants`: its first row is typically the DEFAULT tenant that
owns the seed. Endpoint stays covered; only the blast radius changes; the rewrite is recorded in the
step's `autofilled` (never silent). `_CONTROL_PLANE_RESET` is derived from `CONTROL_SURFACE_ENDPOINTS`
(the #554 pattern), so a control-plane-less app yields an empty set and the guard is inert.

**Honest limits of the claim — do not overstate it:**
- The VALIDATED runs (r115/r118/r121/r125) also contain reset chains (2–6 each) and still converged,
  so "has a reset chain" is **not** sufficient for a wedge. Their final snapshots hold 0 failing
  chains, so the before/after metric cannot be computed for them. What #566x removes is the
  **variance** — whether a draw wedges should not depend on where the verifier happens to place its
  infra-coverage chain.
- #566x prevents the wipe only if the app's reset handler HONORS the header (r130's did; it is the
  framework's contracted behaviour). A lane that ignores the scope still wipes. If r131 shows that,
  the next rung is a **fixture-survival check**: after a destructive control-plane step, re-read a
  collection previously seen populated and, if now empty, record a FRAMEWORK defect — routing the
  cascade to the framework instead of misattributing it to the lane.
- `DELETE /api/v1/tenants/{id}` is the adjacent hazard on paper (contract: "ON DELETE CASCADE wipes
  its rows") and is authored just as often as the reset — 35 occurrences vs 35 across r115–r130.
  **Measured: it never fires.** All 34 executed calls returned **404** (the placeholder resolves to a
  tenant the chain created and already deleted, or to nothing); not one 2xx, so nothing ever
  cascaded. Deliberately NOT guarded — no evidence, and every speculative change costs a 2–3h
  validation run. Re-measure with the same query if a future run shows a cascade.
- A sweep of every mutating step authored across r115–r130 found only these two shared-fixture
  hazards. The rest (`DELETE /api/my-list/{id}` 46x, `PUT/DELETE /api/profiles/{id}` 26x) target
  OWNER-SCOPED rows — each chain's own — which is harmless by construction.

### 5.0b r131 — KILLED EARLY (46 min): #566w handed a read to a LESS SAFE handler (→ #566y)

r131 never reached a milestone. At 46 min its chain `profile_ownership_isolation` failed live on a
**real cross-user leak**: user B probing `GET /api/continue-watching?profile_id=<A's profile 17>`
got **200** with rows carrying `profile_id=1` — a third party's seeded watch progress.

Diagnosis (all read off the generated app, not the log): the response SHAPE (raw table columns
`id/profile_id/title_id/updated_at`) is the PROJECTED handler's, not the lane's — so #566w worked as
designed and took the route away from the lane. But the lane's own handler was **correct** (explicit
`profile.user_id != user["id"]` → 403), and the projected one was:

```python
@app.get("/api/continue-watching")
def _projected_get_api_continue_watching_6(db=..., user=...):
    rows = db.query(ContinueWatching).limit(100).all()     # no owner filter at all
```

An audit of every projected collection read in r131: `/api/profiles` SCOPED (direct `user_id` FK),
`/api/continue-watching` UNSCOPED, `/api/titles` + `/api/genres` correctly unscoped (shared catalog).
Root: the read gated on the contract's per-table `owner_scoped_reads` flag, which that draw set for
`profiles` but not `continue_watching` — while the CREATE for the same column enforced ownership
unconditionally (#566s 403 + `_fw_owner_val` auto-fill). **The framework wrote into your own scope
and read out of everybody's.** Unfixable by the lane (route shadowed, handler framework-emitted) →
deterministic wedge, so the run was killed rather than burn 2h. Fixed by **#566y**; relaunched as
**r132** carrying #566x + #566y.

Lesson worth keeping: **a route-precedence change is a safety change.** Diverting a read to the
projection is only an improvement if the projected handler is at least as owner-safe as what it
replaces. Check both handlers before moving a route.

### 5.0c r132 — KILLED at 1h03: #566y validated in flight; found the OSCILLATION ENGINE (→ #566z)

**#566y confirmed working at 20 min.** `GET /api/continue-watching` with tokenA returned ONLY the
caller's own row (`[{"id":9,"profile_id":16,…}]`, was every profile's), and the cross-user probes
(tokenB / tokenE) never appeared in any chain's `broken` list. The r131 leak is closed.

**★ Then r132 revealed what actually drives §5.1's "owner-scoping oscillation".** Both failures were
a SELF-CONTRADICTORY authored chain — the same actor issuing the SAME request twice with mutually
exclusive expectations:

```
[5] GET /api/continue-watching  auth=tokenA  expect=[200]   → 200  (passes)
[6] GET /api/continue-watching  auth=tokenA  expect=[400]   → 200  "DENIAL-PROBE got success"
```

The verifier plainly meant "with no profile selected → 400", but a chain step cannot carry headers,
so the two steps are literally the same request. No app can satisfy both. `_is_cross_user_denial`
classifies any no-2xx expectation as a denial probe, so a SAME-ACTOR authoring slip is reported as
a security failure — and the lane is dispatched to "fix" it.

**What happened next is the important part.** Left standing, the step does not merely wedge — it
**misteaches the lane**. Chasing the 400, the backend made `/api/continue-watching` REQUIRE an
`X-Profile-Id` header the harness cannot send. Every legitimate 200-expecting step then failed with
`{"detail":"X-Profile-Id header is required"}`, and the failing-chain count went **1 → 5** across two
churn cycles (verifier churn 1/8, source-edit churn 1/8, api_smoke attempt 6/6). Compare §5.1's r130
log: *"400 missing X-Profile-Id header (should auto-resolve) … then too-permissive … then
over-corrected too-restrictive."* **Same signature.**

> **So the oscillation has an ENGINE.** It is not lane incompetence and not (only) owner-scoping
> variance: an unsatisfiable authored expectation that the lane keeps rationally chasing, because the
> only way to produce a 400 for that request is to demand a header — which breaks the sibling step
> that demands 200. The lane cannot win. Neither can the verifier, unless it re-authors (it repaired
> ONE of the two chains, then added six more and left the other).

**#566z (committed `dc5c902`):** waive a no-2xx-expecting step when the SAME actor already received a
2xx for the IDENTICAL request earlier in the same chain; record
`unsatisfiable-duplicate-expectation-waived` in `autofilled`. **Cannot mask a cross-user leak by
construction** — the waiver requires the actor to be the one already entitled to a 2xx, so no second
identity is involved. `_request_identity` keys on verb + full path INCLUDING query + auth ref + body,
so a foreign-id probe (`?profile_id=999`), a different token, an unauthenticated probe or a different
body keeps every tooth. Successes are recorded AFTER the check (no self-waiver) and order matters (a
contradictory step placed first still breaks). Precedent: `oauth-authorize-incomplete-tolerated`,
`control-plane-public-denial-probe-waived`.

**Follow-up worth doing (NOT yet done):** a lane handler that 400s demanding a header is
untestable by chains BY CONTRACT (steps carry no headers) and contradicts the framework's own
`_fw_owner_val` auto-resolution. Surfacing that as a correctly-attributed framework/contract defect —
rather than a generic chain break — would catch the next variant of this even without #566z.

### 5.0d r133 — ★ M1 DELIVERED (tag 1.0.0) + M2 kickoff, then killed at 2h14 on a 3rd leak (→ #568)

**The best run of the arc, and the first hard proof the three fixes work.** With #566x + #566y +
#566z it delivered **M1 with release tag `1.0.0`**, authored `MILESTONE_M2.md`, and reached 58
chains with 0 failing. Compare r131 (leak at 46 min) and r132 (2 failing at 20 min).

Also settled two judgement calls empirically:
- Chains that failed mid-run (`my_list_add_remove` header-401, then a `/toggle` 500) were repaired
  **by the lane itself** — so killing r133 early would have been wrong, and the bounded churn
  design works when the failure is genuinely lane-fixable.
- Two "DENIAL-PROBE got success" failures were **mis-authored, provably**: `POST /api/my-list`
  auth=tokenB with body `{"title_id": …}` and NO owner FK is B writing into B's OWN scope —
  legitimate for any authenticated user. A real cross-user write must carry A's owner id, and
  #566s (`_fw_owns` → 403) already covers that. Do not "fix" those in the app.

**Why it was killed:** chain `auth_and_profile_isolation` exposed a THIRD, distinct leak —
`GET /api/my-list` returned another account's row. Ground truth: `registryhub_tables.json`
registered `my_list` with **`schema.columns == []`** (siblings `ratings` / `continue_watching`
registered in full) → `class MyList(Base): id = Column(...)` → the projected read had **no owner
FK to filter on** and served everyone's rows, while the lane's correct handler sat shadowed.
#566y could not help: it needs an owner FK to exist. Confirmed no self-heal over ~25 min — the
symptom the lane is shown ("GET → 200, expected 403") points at authorization, not at a table
that never declared its columns. Fixed by **#568**; relaunched as **r134**.

> **The lesson, third instance: a route-precedence change is a SAFETY change.** #566w moved reads
> to the projection; #566y made the projection scope a sub-entity owner; #568 makes it DECLINE
> when it has no schema to be safe with. Diverting a route is only an improvement if the
> receiving handler is at least as owner-safe as the one it displaces.

**Not yet done (root-most):** #568 stops the leak but not its CAUSE — whatever let the
orchestrator register a table with an empty column schema. A registration-time guard (reject or
flag `schema.columns == []`) would kill the class one level earlier. Deliberately deferred:
#568 is the security fix and is shape-derived, so it holds regardless of the cause.

### 5.0e ★★ r134 — *** MULTI-MILESTONE VALIDATED *** (3 tags, rc=0) — §10 DONE CRITERION MET

```
main-exit:        main() returned 0
GENERATION COMPLETE lines: 1 | Status: SUCCESS
release tags (3): [1.0.0,1.1.0,1.2.0]
rc verdict:       0
VERDICT:          *** MULTI-MILESTONE VALIDATED *** (>=2 tags + rc=0)
```

Full 3-milestone delivery in 2h47 with **75 verification chains, 0 failing**. M1 cut at ~51 min
and M2 at ~1h32, both with the delivery gate **fully clear (no failed checks)** — not a waiver.
Progression vs the same arc: r130 0 tags/rc=1 · r131 killed 46 min · r132 killed 1h03 · r133 1
tag then killed 2h14 · **r134 3 tags, rc=0**.

Owner-scoping verified in the DELIVERED app (the two reads that leaked in r131/r133):

| projected read | scoping |
|---|---|
| `/api/my-list` | `filter(MyList.profile_id == _fw_owner_val(…))` ✅ |
| `/api/continue-watching` | scoped ✅ |
| `/api/profiles` | scoped ✅ |
| `/api/titles`, `/api/genres`, `/trending`, `/top10` | open ✅ correct (shared catalog) |

**Honest scope of the claim.** This draw registered every table with columns
(`_DEGENERATE_RESOURCES = set([])`), so #568's guard never fired here — it is insurance against
the r133 draw, not something r134 exercised. And r134 delivered FAST, which suggests a
favourable draw; §10 asks for a slow/adverse one. What can be said precisely: each of the four
fixes removed a class that had DETERMINISTICALLY wedged an earlier run, and this is the arc's
first VALIDATED run. Repeatability across draws still wants more runs.

### 5.0f #569 — a leak found in r134's own DELIVERED app (fixed after the run)

Post-run audit of the delivered `main.py` found the projected `GET /api/search` querying
**`Profile`, unscoped** — every account's personas, `user_id` included. The resource-less search
resolver asked `_primary_content_model` first, which requires a timestamp; `titles` has none, so
the only timestamped owned table won. `_search_target_model` exists for exactly this (its
docstring names the Netflix `titles` shape) but sat unreachable behind an `or`.

r134 escaped it only because the LANE hand-wrote a workaround — HTTP middleware plus a runtime
mutation of `app.routes`, commented *"FRAMEWORK-OVERRIDE FIX: the projector emits a leaky
/api/search handler"*. **A lane workaround is not generality**; no other draw can be relied on to
reinvent it. Fixed in #569 (`0793dc9`) + `_is_user_persona_table`. Keep auditing the delivered
app after a green run: the gate passing does not mean the app is clean.

### 5.0g r135 — WEDGED (rc=1, 0 tags): repeatability DISPROVED, and #566z was too narrow (→ #570)

r135 aborted at 75 min: `DELIVERY-GATE NO-CONVERGENCE ABORT … business_chain_failing`. **So r134
was one success on a favourable draw, not a repeatable capability.**

One unwaived chain did it, and it was the #566z pattern I had just "fixed". Steps [6][7][8] of
`continue_watching_profile_scoped` are the SAME request by the SAME actor:

```
[6] GET /api/continue-watching  auth=tokA  expect=[400]  → 200   BROKEN
[7] GET /api/continue-watching  auth=tokA  expect=[200]  → 200   ok
[8] GET /api/continue-watching  auth=tokA  expect=[403]  → 200   waived (#566z)
```

[8] waived, [6] not — purely because [6] sat BEFORE the success. #566z shipped with a test that
pinned that order-dependence as deliberate ("no earlier success to contradict"); the reasoning
was wrong. The contradiction is a property of the AUTHORED CHAIN, and the waiver's safety (same
actor → no second identity) never depended on order. **#570** (`0e800b8`) pre-computes the
identities the chain expects to succeed anywhere, so position no longer matters. The old test
assertion was REPLACED, not extended — it encoded the bug.

### 5.0h ★ UI FIDELITY — measured, failing, and NOT enforced (→ #571)

r134's `design/visual_gate/verdict.json`: **`passed: false`, `min_similarity 0.65`,
`blocking_average 0.5533`** — 3 of 16 screens over the bar (landing/new_and_popular 0.72,
movies 0.70), `browse_home` 0.55, `login` 0.45, **`title_detail` 0.08**, coverage 0.60.

**It shipped anyway.** The log shows `DELIVERY DEFERRED: visual fidelity not passed (attempt 1/3
… 3547s deferred)` for ~an hour, then `FINAL DELIVERY: gate clear → cut release v1.2.0`. The
deferral budget expires and the milestone cuts regardless. **§10's "MULTI-MILESTONE VALIDATED"
therefore does NOT include UI similarity** — the pipeline's success criterion and the standing
goal have diverged. Whether to make the visual gate hard-blocking is a product decision; it is
open with the user.

**#571** (`0793dc9`→ next commit) fixes the worst screen at its root.
`_design_screen_for_route`'s fuzzy pass SKIPPED every non-page screen while its docstring says
"kind=='page' PREFERRED over overlays" — a preference implemented as a hard filter. So
`/title/:id` (screen `title_detail`, kind=overlay) could never reach its own reference and the
best remaining page won on route tokens: `player` (`/watch/:titleId`) shares {title,id}. r134
shipped **`Player.jsx` and `TitleDetailModal.jsx` byte-identical** apart from the function name.
r98 hit the same at 0.06 — 36 runs earlier — and #534's paper-over (mount the LANE's detail
modal, if it wrote one) has been load-bearing ever since. Now ranked, not filtered:
score → name-coverage → page preference.

> **Method note that produced §5.0h:** the visual verdict JSON carries per-dimension notes and a
> route per screen. A score near ZERO is not a styling gap — it means the wrong PAGE was
> captured or projected. Read the note before filing a design task.

### 5.0i ★ r137 — UI FIDELITY CROSSED THE BAR (0.5533 → 0.7067); killed on a gate FALSE POSITIVE

**#571 validated live.** Final visual read before teardown:

| screen | r134 | r137 |
|---|---|---|
| **title_detail** | **0.08** | **0.70** (≈9×) |
| login | 0.45 | 0.72 |
| my_list | — | 0.70 |
| browse_home | 0.55 | 0.60 |
| **blocking average** | **0.5533** ❌ | **0.7067** ✅ (bar 0.65) |

Structural proof alongside the score: r137's `TitleDetailPage.jsx` is still framework-projected
(`data-projected="ref"`, 87 lines) but carries **zero `<video>` and zero player controls**, with
Episodes/Cast/Genres markup — the detail reference finally reached the detail route.

Also green: 45 chains 0 failing, `run_validation` 13/13, ui_smoke 9/9, ui_flow clean.

**Killed at 1h30 anyway** — the browser test-user gate deferred delivery 6 times over 38 minutes
on a CORRECT app, and could not say why:

```
DELIVERY DEFERRED: browser test-user found the app UNUSABLE
(auth_ok=True blank=[] login_wall=[] hollow=False no_real_data=False fake_map=[])
```

Two defects, both now fixed:
- **#572** — `browser_report_unusable` keys on SIX signals; the message hand-listed FOUR. The two
  it never learned, `fallback_dom_pages` (#224) and `primary_dataless` (#231d), are exactly the
  ones that fired. Six P0s went to the frontend lane naming nothing to fix. The message is now
  DERIVED from the predicate, with a test that fails if the hand-listed format string returns.
- **#573** — the actual signal was `primary_dataless`: r137's `/` is a logged-out marketing
  landing (`LandingPage.jsx`, 198 lines, zero `fetch(`), so of course it rendered no seed value.
  #231d's premise ("the app's FACE is an empty shell") only holds for a page that ASKED for data
  and got nothing. Now requires ≥1 `/api/` request, measured from the Resource Timing buffer in
  the existing probe. r21's motivating case (a feed that DID fetch and still showed "No videos
  found") keeps firing; unknown counts keep the old behaviour.

> **Pattern worth naming:** three of this session's fixes (#566z/#570, #572, #573) are the same
> shape — **the framework blocking a correct app and being unable to say why.** When a gate holds
> N times with clean evidence fields, suspect the message before the app.

### 5.0j r138 — #572 validated live; found #574, the QA login has been using the WRONG PASSWORD

**#572 confirmed working.** The deferral line now names its evidence:
`(auth_ok=False, auth_redirect_pages=['profiles','browse_home_page',…], hollow_frontend=True)`
— compare r137's all-clean line for the same class of hold.

That named evidence led straight to **#574**, which is the best find of the session because it
is a framework bug that has been silently taxing every run:

`_seed_demo_login` read the EMAIL from the seed row and then **hardcoded** the password:

```python
return {"email": str(users[0]["email"]), "password": "password", ...}
```

The LOADER honours the row's own plaintext (`seed_data.py`):
`pw = row.pop('password', None) or 'password'` → `sha256(pw + salt)`.

r138's `seed_data.json` first user is `demo@netflix.test` / **`Demo!2345`**, so the DB held
`sha256('Demo!2345'+salt)` while every QA login sent `password`. **Verified against the live
container**: `POST /auth/login` with the default → `401 invalid credentials`, both salts
(`app_sandbox_salt_2024`) and both schemes (sha256) identical. The scheme was never wrong.

Consequences, all on an app whose auth was fine — 62 chains green:
- form drive fails → `auth_ok=False`; #504's direct-API corroboration fails too →
  `api_login_ok=False`, so **the escape hatch can never arm**;
- → `hollow_frontend` + 10 pages "bouncing to auth" → delivery hard-deferred **11 times /
  54 minutes**, and the frontend lane got 11 P0s for a defect it did not have;
- → and the walk browsed as a NON-populated user, so data pages looked blank — *exactly the
  failure `_seed_demo_login`'s own docstring says it exists to prevent.* The fix had the bug it
  was written to avoid.

> **Diagnostic note:** three hypotheses were killed by evidence before the real one — "the seed
> password doesn't match the harness" (the salted hash matched byte-for-byte), "the walk guesses
> a password" (it reads the loader's constant), "the login scheme differs" (both sha256, same
> salt). The decisive step was reading `seed_data.json` — the file the LOADER reads — instead of
> the embedded `_SEED` fallback in `seed_data.py`. Same lesson as §5.0h: read the artifact the
> system actually consumes.

### 5.0k ★★ r139 — SECOND `*** MULTI-MILESTONE VALIDATED ***`, on a DIFFERENT draw

2 tags (1.0.0/1.1.0), rc=0, **83 chains 0 failing**. r135 had disproved repeatability; two
independent draws have now reached VALIDATED (r134, r139).

**The delivered app audits CLEAN** on every leak class this arc shipped before:

| projected read | r134 | r139 |
|---|---|---|
| `/api/my-list` | leaked (r133) | `filter(MyList.profile_id == _fw_owner_val(…))` ✅ |
| `/api/continue-watching` | leaked (r131) | scoped ✅ |
| `/api/search` | **`db.query(Profile)`** — every account's personas | **`db.query(Title)`** ✅ |
| `FRAMEWORK-OVERRIDE FIX` hacks in custom_routes | 1 (lane worked around the projector) | **0** ✅ |

**Still short on UI: 0.6382 vs the 0.65 bar** — but the distribution is transformed:
`browse_home` 0.55→**0.85**, `login` 0.45→**0.78**, landing/movies 0.78. The gap decomposes into
three named defects, not a diffuse "looks different":
- `genre_category` **0.28** — no top nav at all, and a literal `"Genre Category"` title → **#576**
- `my_list` 0.55 — *"shows empty state so grid rows can't be judged"*: the score is capped by an
  EMPTY page, not by styling. Open: does the #574-corrected demo user actually own my_list rows?
- `player` 0.55 — the reference frame is an AD state ("Ad 12"); the implementation is normal
  playback. A reference-set problem, not an app one.

### 5.0l #576 — projected pages ship without the app's own chrome

`recover_agent_nav` (#440) only REWIRES a page that already renders the generic inline fw-nav; a
projected page rendering NO nav carries no marker and is invisible to it. r139 shipped
`GamesPage` and `GenreCategoryPage` identical but for one line (`<TopNav />` + `flex-col`).

Fixed by a late pass that discovers the shell from the app's OWN import graph. **The first draft
was wrong and the real app caught it**: "a majority of pages" returned `mounted: []`, because
auth/landing screens legitimately have no chrome (4 of 14) and poison that denominator. The rule
is now "shared widely AND dominates the runner-up", which is independent of how many chrome-less
screens an app has. Dry-run on r139's actual tree:
`{'mounted': ['GenreCategoryPage','MoviesPage','PlayerPage','ShowsPage'], 'nav': 'TopNav'}` —
exactly the four screens the judge penalised.

> **Method note:** every fix this session that touched generated code was dry-run against a REAL
> generated app before shipping, not just unit-tested. #576's majority rule and #568's
> column-count rule both passed their unit tests and both were wrong; the real tree caught them.

### 5.0m ★ THE VISUAL BAR IS PER-SCREEN, NOT THE AVERAGE — earlier readings measured the wrong thing

`visual_fidelity.py:2126`:

```python
_merged_passed = all(_sim(s) >= min_similarity for s in _blocking_merged)
```

`passed` requires **EVERY blocking screen ≥ 0.65**. `blocking_average` is a REPORTED metric
(#542a), not the gate. So "0.6382 vs 0.65 — a near miss" (r139) was the wrong comparison: the
real requirement is stricter, and an app can sit above the average bar and still fail on three
screens. Any future report of UI progress must list the screens BELOW the bar, not the mean.

### 5.0n r141 — a real cross-user WRITE (→ #577), and r142 — third VALIDATED, UI still short

**r141**: `POST /api/my-list` as tokenB with body `profile_id=<user A's>` returned **201** — the
row landed in A's profile while `user_id` auto-filled to B. #566s guards only the ONE column
`_owner_fk` returns, and this draw's `my_list` has BOTH `user_id` and `profile_id`. The lane's
own handler verified it (`_verify_profile_owned`); writes stay projected, so the safer handler
never ran — the displacement lesson again, on the write path. Fixed by **#577** (guard every
owner column, auto-fill only the primary). Ruled out first: #575 was NOT involved (no
`owner-fk-omitted` marker; `${profileA_id}` resolved to a real id).

**r142** — `main() returned 0`, **3 tags (1.0.0/1.1.0/1.2.0)**, **107 chains 0 failing**, and
the delivered app audits clean (my-list / continue-watching / profiles all owner-scoped,
`/api/search` → `db.query(Title)`). r141's three write-leak chains did NOT recur → #577 validated.
Third VALIDATED run, third distinct draw.

**Visual: `passed=False` on 3 screens** — `games` 0.62, `player` 0.50, `title_detail` 0.50
(average 0.6836, above the bar but irrelevant per §5.0m). `genre_category` went **0.28 → 0.72**.

**A transient that cost real cycles (→ #578):** mid-run, `TopNav.jsx` imported a momentarily
absent `./SearchOverlay.jsx`, `vite build` failed, and #440 was mounting TopNav into MORE pages.
Six screens scored **0.0** and the average fell 0.555 → 0.2773 before the lane repaired it.
#578 now requires a component's own relative imports to resolve before either #440 or #576
spreads it. (Two false leads were killed first: #576 never ran in r142 — log count 0 — and my
initial "GenreCategoryPage JSX is unbalanced" was a miscount that ignored 4 self-closing divs.)

### 5.0s ★ ROADMAP after the full offline review (2026-08-12) — every axis measured

Runs were stopped on cost. What follows replaces guesswork with measurement over the artifacts
of 56 runs. **Read the metric caveat first — three of my own rankings were wrong before it.**

**METRIC CAVEAT (cost me three wrong priorities).** Counting blockers across ALL log lines is
dominated by mid-build transients: it puts `deliverability_ui_page_unwired` first at 325, when
the gate already skips the route-less entries that produce it and it is the terminal blocker of
only 4 runs. Counting per line double-counts (one gate line repeated `frontend_fallback_page`
7×). And "the last decline" is not "the terminal state" — runs that later delivered still carry
one. **The only sound metric: join each run against its monitor TERMINAL verdict, keep the runs
that FAILED, dedupe per run.** On that metric (18 runs with a verdict, 7 PASS / 11 FAIL):

| terminal blocker | failed runs | status after this review |
|---|---|---|
| `business_chain_failing` | **8 / 11** | 22 of its 23 broken-step instances are covered by this arc's fixes; the 23rd is an app-level `POST /auth/login → 500` |
| `verification_checklist_not_ready` | 4 | 2 transient; **2 real** (r107, r130 blocked ~1 min AFTER all four `build:*` were `success` on disk) → **#585** makes it self-describing |
| `ui_flow_missing` / `dead_artifacts` / `incomplete_required_tasks` | 2 each | all the SAME two runs (r116, r122) — co-symptoms, not defects: r116 died on `docker_up`, r122 on a 7389s>7200s wall-clock cap |
| `bare_authed_fetch` | 0 | #566r closed it; audited clean on r137/r139/r142/r143 |
| `frontend_fallback_page` | 0 | — |

**Axes closed by measurement (no fix needed — recorded so they are not re-chased):**
- *Denial-probe family.* All 20 historical failures replayed against the current waivers: 9
  write probes → owner guards, 4 foreign-id/empty → #566v, 3 foreign-id/rows → real leaks kept,
  2 bare/empty → #580, 2 bare/rows → **still fail, correctly** (r133's returned user A's row —
  that is #580's safety line, proven on real data).
- *Expectation vs contract.* 850 denial steps scanned; **0** target an endpoint the contract
  declares public. The sub-class does not exist.
- *Write-guard vs read-scope asymmetry* (the shape behind #566y/#568/#577). Audited the
  DELIVERED apps of r134/r139/r142: `my-list`, `continue-watching`, `profiles` all guard and
  scope the same column. **No fourth instance.**
- *Contract degeneration.* 621 tables across 56 runs: 6 with 0 columns (consequence already
  neutralised by #568), 2 "no primary key" which are `title_genres` composite-key junctions —
  **my check's false positive, not a defect**. Phantom verb-tables (`toggle`, `check`) exist but
  r130's `toggle` 404 came from the LANE's handler and the #566x wipe, not from shadowing — no
  evidenced harm.

**Landed this review:** #584 (exact-route screen ranking — the actual cause of `title_detail`
0.50), #585 (checklist blocker explains itself), #586 (unsatisfiable chains rejected at
REGISTRATION, refined by replay from 17 hits/14 false to 5/0.3%), #587 (failing steps name the
route's owner), plus self-review fixes #575b and #576b.

**What is genuinely left, and who owns it:**
1. `player` reference frame depicts an ad state the app cannot reproduce — **user's call**;
   until it changes, the per-screen visual gate cannot pass on this app.
2. `POST /auth/login → 500` — one app-level defect, the lane's.
3. `games` 0.62 — content richness on a page with no backing API; lane styling.
4. Everything else above is either fixed, measured closed, or instrumented to identify itself
   on the next run.

### 5.0p ★ OFFLINE REVIEW (2026-08-12, no new runs) — mining 50 runs of artifacts

Experiments were stopped on cost grounds. What follows is mined from artifacts already on disk;
it is cheaper and, in two cases, MORE conclusive than another run would have been.

**1. Chain-failure taxonomy across 50 runs.** One class dominates: **`DENIAL-PROBE got success`,
20 occurrences across 8 runs** — more than the next three classes combined. Everything else
(`referenced resource not found` 12, `X-Profile-Id header is required` 11, `title not found` 8,
`rating db op failed: FK` 6) traces to a root already fixed this session (#566x / #566z+#573 /
#566x / #566x respectively).

**2. All 20 denial-probe failures REPLAYED against the current waiver logic.** This is the
validation another 3-hour run could not have given, because no single draw contains all 20:

| group | n | verdict now | correct? |
|---|---|---|---|
| cross-user WRITE probe | 9 | routed to the owner-column guards (#566s/#577) | ✅ r141's are exactly what #577 fixes |
| GET w/ foreign id param, EMPTY response | 4 | #566v tolerates (secure override) | ✅ |
| GET w/ foreign id param, ROWS returned | 3 | leak verdict KEPT | ✅ real leaks |
| BARE GET, EMPTY response | 2 | **#580 waives** | ✅ r143's two |
| BARE GET, ROWS returned | 2 | **still breaks** | ✅ **this is the safety line** |

The last row is the important one: r133's bare read returned user A's row (the leak #568 fixed)
and r135's returned profile 22's rows. **#580's "response must be empty" condition is what stops
those from being silently waived** — proven on real historical data, not a synthetic fixture.

**3. Two hypotheses tested and DISPROVED — do not re-chase them:**
- *"login is the worst screen (32 of 43 runs below the bar) so it needs a framework fix."* The
  aggregate is dominated by pre-fix runs. In r139/r142 login scores **0.78 / 0.80 — passing**,
  with only "form slightly left of centre" and "an extra card panel" left. Weight screen
  statistics BY RECENCY; a whole-arc aggregate points at problems that are already fixed.
- *"the brand wordmark is a text placeholder, which is why logo/style score low."*
  `design/assets/brand/netflix_wordmark.svg` is **real vector art** (`<path fill="#e50914">`,
  no `<text>`), it is copied into `public/assets/brand/`, and r142's login uses it correctly via
  `<img src="/assets/brand/netflix_wordmark.svg">`. The r134 complaint was that draw's own doing.

### 5.0r ★ CORRECTION — #579's mechanism is WEAKER than first claimed (verified offline)

#579 was described as "directly targeting `title_detail` 0.50". **That overstates it.** Verified
by feeding r142's real contract through the page scaffolder before and after the backfill:

```
BEFORE #579: TitleDetailPage.jsx lines=55 titles-by-id-fetch=0 episodes=0
AFTER  #579: TitleDetailPage.jsx lines=55 titles-by-id-fetch=0 episodes=0
```

Identical. A sweep of `runtime/` finds **no module that consumes `apis_used` to emit page
fetches** — it is contract/registry metadata read by the deliverability gate
(`deliverability_frontend_fallback_page`) and by the lane's briefing. r137's episodes-bearing
detail page came from the reference DECOMPOSITION (`data-projected="ref"` regions), not from
`apis_used`.

So #579 is still correct and worth keeping — a `/title/:id` page declaring only
`GET /api/profiles` is plainly wrong contract data, and two consumers read it — but it does NOT
by itself make the projected page fetch the title or render episodes. **Do not expect
`title_detail` to move on #579 alone.**

**And the lever is NOT the reference decomposition either** — that was this note's first guess
and it is also wrong. r142's `design/component_specs/title_detail.json` carries **17
components** including `synopsis_text`, `cast_genres_block`, `episodes_header`,
`episode_subheader`, `episode_row_1`: every section the judge reported missing is present in
the decomposition. (r137's had 13 and scored 0.70; more components did not help.)

**The loss is between DECOMPOSITION and EMISSION — and FOUR hypotheses about where were all
wrong.** Recording the eliminations, because each cost real time and the next person should not
repeat them:

| hypothesis | verdict | how it was killed |
|---|---|---|
| `apis_used` drives the page's fetches (#579 is the lever) | **wrong** | scaffolder output byte-identical before/after backfill |
| the reference DECOMPOSITION is missing the sections | **wrong** | r142's spec has 17 components incl. `episodes_header`, `episode_subheader`, `episode_row_1`, `cast_genres_block` |
| #547a didn't fire, so the page fetched `/api/genres` | **wrong** | that was r143's page; r142 line 27 fetches `'/api/titles/' + (params.id \|\| '')` — correct |
| #449 misclassified the modal as a PLAYER, so #448 skipped episodes | **wrong** | both predicates EXECUTED on both real specs: `is_player=False, has_episodes=True` for r137 AND r142 |

**Verified facts (executed, not inferred):**
- r142's decomposition carries every section the judge reported missing.
- `_screen_has_episodes_448` returns **True** for r142's real spec; `_screen_is_player_449`
  returns **False**. Neither gate excludes it.
- r142's emitted page fetches the correct item endpoint.
- Yet the emitted page is 61 lines with **no `<ul>`/`<li>`/`<h2>`** — r137's is 89 lines WITH
  them (`<li key={ei}>`).

**The emission path WAS then executed** (the step this note previously called "next"), and it
produced a quantitative match that pins the shape of the defect:

| screen dict handed to `_render_reference_page` | emitted |
|---|---|
| WITH the 17 components (from `design/component_specs/title_detail.json`) | **83 lines**, `<li>` present, 3 `episodes` refs |
| WITHOUT components (the shape `reference_spec.json` stores) | **62 lines**, no `<li>`, no `episodes` |
| **what r142 actually shipped** | **61 lines**, no `<li>`, no `episodes` |

r142's shipped page matches the components-less emission line-for-line. Also established by
execution: `get_ep` / `apis_used` changes nothing (83 lines either way — #579 is definitively
NOT the lever), and `_design_screen_for_route` correctly returns `title_detail` with all 17
components.

A FIFTH hypothesis died here too: `reference_spec.json` carries **zero** components for every
screen in r137, r139 AND r142 alike — so that file is not the discriminator, and the design
object the projector actually consumes is assembled at runtime.

A SIXTH hypothesis ("the components never reached the design object") also died: r142's
`design/design_system.json` carries **20 screens, all with components, `title_detail` = 17**.
The design was complete.

### ★★ THE ACTUAL ROOT CAUSE — #584: the page was rendered from the WRONG SCREEN

Found after #583, and it supersedes it as the explanation for the CONTENT being wrong.

Several screens share one route: r142 classifies BOTH `rate_dialog` (kind=page, 16 components)
and `title_detail` (kind=overlay, 17) as `/title/:id`. The exact-route pass returned the first
`kind == 'page'`, so **the title-detail page was projected from a RATING DIALOG's regions**:

| run | `/title/:id` resolved to | |
|---|---|---|
| r137 | `rate_dialog` (page, 17) over `title_detail` (overlay, 13) | WRONG |
| r142 | `rate_dialog` (page, 16) over `title_detail` (overlay, 17) | WRONG |
| r139 | `title_detail` | right, by luck — all three candidates were overlays |
| r137/r142 `/browse` | `card_hover_preview` (page) over `browse_home` (overlay) | WRONG |

**Executed proof, r142** — `(lines, <li>, episodes, <h2>)`:

```
shipped                      (61, 0, 0, 0)
rendered via rate_dialog     (62, 0, 0, 0)   <- matches what shipped
rendered via title_detail    (83, 1, 3, 1)   <- what #584 now selects
```

Why it stayed invisible: `browse_home` lost the same way yet scored **0.85**, because the lane
rewrites that page and masks the mismatch. **The defect only shows on pages the lane leaves
alone** — which is precisely the set the visual gate then blames the projector for.

Fixed in **#584** by ranking exact-route candidates on name coverage first (the #571 rule,
which the exact pass never had), then the page-over-overlay preference, then richness. Verified
across r137/r139/r142: every page now resolves to its own screen.

### CONTRIBUTING CAUSE — `frontend_scaffold.py` ~8478 (#583, still valid)

```python
# are projected only when missing (never clobber the lane's real UI).
if _is_auth_page(comp, page) or not target.exists():
```

**A page is projected ONLY when its file does not yet exist.** So a reference page emitted
early — before `decompose_reference` has landed the component specs — is FROZEN: the design
later gains all 17 components, the projector re-runs, sees the file, and skips. The thin
components-less page is what ships.

This is consistent with every elimination above, and it explains the r137/r142 split without
appealing to any difference in logic: both runs have the same code, the same design content and
the same matcher — they differ only in whether projection happened before or after the
decomposition landed. It also explains why the effect is per-screen and varies run to run.

> **One sentence: a reference page emitted before the decomposition lands is frozen, and the
> richer design never reaches it.**

**Fix direction, with the constraint that matters.** The guard exists for a real reason —
"never clobber the lane's real UI" — so a blanket re-projection is NOT acceptable. What is safe
is a LATE pass (same family as #440 / #534 / #576 / #578) that re-projects a page ONLY when all
of: the file carries the projector marker (`data-projected` / `_PAGE_MARKER`), the design screen
NOW has components, and the existing file demonstrably came from a components-LESS render.
Note for whoever builds it: r142's shipped page is 61 lines and the components-less render is
62 — CLOSE but NOT byte-equal, so an exact-equality gate will never fire. Use a structural
signal instead (e.g. the file has none of the region bands the screen's components require),
and verify the chosen signal against r142's real page before trusting it — five of the six
hypotheses above looked right on paper and were killed only by execution.

**Method lesson, dearly bought:** every one of the four was inferred from a partial `grep`.
The one that settled the question was *executing the predicates on the real inputs*. On this
codebase, run the function before believing a hypothesis about it.

### 5.0q Framework-error sweep across 107 logs (offline)

Aggregating `[E]` / exception lines across every run log surfaced two framework-side defects
that no experiment was needed to find:

- **`SyntaxError: Failed to execute 'querySelectorAll' … is not a valid selector` — 24x.** A
  model composing a CSS selector inside a JSON tool argument writes
  `input[placeholder=\"Email or phone number\"]`; JSON decoding removes one level and the
  browser rejects what is left. #362's candidate-listing (which exists so ONE selector miss
  answers "what is on this page") never fires, because a syntax error is not a miss — so the
  model just guesses again. **Fixed: #581**, unescaping `\"` / `\'` at both entry points that
  take a model-authored selector, leaving legitimate CSS escapes (`.foo\:bar`) alone.

- **`[LLM] All 3 attempts failed. Last error: [AssertionError]` — 2313 groups (~6900 calls).**
  Trigger sequence is visible in the log: the model rejects `temperature`, the client drops it
  and retries, and the retry dies on a BARE `AssertionError` (empty message) on the streaming
  path. `agent/utils/llm.py` contains no `assert`, so it originates in the SDK/transport.
  **Deliberately NOT fixed** — a blind change to the shared LLM client risks every run, and the
  volume is not what it first looks like: 711 of the 2313 are r10 and 657 are r126, while
  recent runs show 3–14 each. Worth instrumenting (log the traceback, not just the type) before
  attempting a fix.

### 5.0o Remaining UI work, per screen — and the honest verdict on each

**Current below-bar set is small and shrinking**: r139 had 5 (6 passing), r142 has **3**
(8 passing). `genre_category` went 0.28 → passing.

Persistent across both, and **neither has a safe framework-side lever**:

- **`player` 0.50/0.55 — the REFERENCE is an ad state.** Three independent judge notes say so:
  *"Reference shows an ad state with 'Ad 12' badge"*, *"Reference: 'Ad 12' and 'All American
  begins after ads'"*. The implementation renders a MORE complete player (progress bar,
  timestamp, rewind/forward, next-episode) and is penalised for having no ad system — which
  nothing in the spec asks for. **This screen is unpassable as specified**, and it has been
  below the bar in 24 runs. The fix is to curate that reference frame, which is the USER's
  call, not a code change.
- **`games` 0.62 — content richness on a page with no backing API** (there is no `/api/games`).
  "Missing the game-specific hero badge (game logo lockup + genre/players/duration metadata)."
  Lane styling work; no framework lever.

> Consequence worth stating plainly: with the `player` reference as it stands, **the per-screen
> visual gate cannot pass on this app** no matter how good the generator gets. Any future claim
> of "UI 高度相似 achieved" must either fix that reference or exclude it explicitly.

- `player` 0.50 — the REFERENCE frame is an ad state ("Ad 12", "All American begins after ads");
  the app renders normal playback. Not obviously an app defect; a reference-selection问题.
- `title_detail` 0.50 — was 0.70 in r137 with #571; regressed on this draw, cause not yet pinned.
- `games` 0.62 — closest to the bar.

### 5.1 The PREVIOUS theory (kept for context — largely a downstream artifact)

**Was believed to be the root cause of every slow-draw wedge (r126–r130): LANE OWNER-SCOPING VARIANCE.**
On favorable draws the LLM backend's *custom* owner-scoping handlers happen to be correct → clean
multi-milestone (r115/r118/r121/r125). On slow draws the backend writes/rewrites those custom handlers
(`_resolve_profile`, `get_my_list`, rating) with **oscillating bugs**, and because **custom_routes wins
route precedence over the projected handlers**, the framework's correct projected logic is shadowed. The
framework validation correctly FLAGS the bugs, but the backend can't reliably converge → M1/M2 wedge.

> **Caveat (2026-08-11):** every oscillation listed below was observed in chains that ran AFTER the
> reset chain — i.e. against a DB whose profiles/catalog had just been deleted while the chain's JWT
> stayed valid. `_fw_owner_val` auto-provisioning against vanished rows reproduces exactly this
> "too-permissive then too-restrictive" swing. Re-measure all of it on r131 before spending another
> arc on option A/B below.

Concrete oscillation observed (r130, wedged M1 entirely, rc=1, 0 tags):
- `GET /api/my-list` with no profile → 400 "missing X-Profile-Id header" (should auto-resolve), then
- swung too-permissive: `GET /api/my-list?profile_id=<foreign> → 200` (looks like a read leak), then
- over-corrected too-restrictive: `GET /api/my-list?profile_id=<OWN> → 403` (rejects the caller's OWN).

**#566v** attacks this from the VALIDATION side (tolerate secure-override reads so the lane can settle on
the simpler secure-permissive behavior instead of oscillating). **VALIDATE #566v with a run first** — it
may be enough to stop the read-isolation oscillation.

**If #566v alone is not enough, the REAL architectural lever is: make the framework OWN owner-scoping so
the lane cannot ship a buggy custom variant.** Design options (do ONE, carefully, one validation run per
iteration — this is the delivery-critical path, high blast radius):
- **(A) Canonical resolver + required usage:** add `_fw_resolve_owner_scope(db, cls, owner_col, user,
  explicit_id)` to the skeleton (absent → `_fw_owner_val`; explicit → `_fw_owns` → 403 if foreign; else
  the value). Seed it into `custom_routes.py` and make the scaffold/prompt REQUIRE the lane to call it and
  NEVER hand-roll `_resolve_profile`. Weakness: LLM may still rewrite it — mitigate by making the seeded
  version pass the isolation chains from the start so the backend has no reason to churn it.
- **(B) Project owner-scoped READS + prevent lane override for owner-scoped resources** (or HEAL a buggy
  lane resolver to delegate to the canonical one). This is the most reliable but touches the
  projection/lane-precedence model that currently makes favorable draws work — **validate carefully that
  you do NOT break r115/r118/r121/r125-style clean draws.**

**HARD SAFETY RULE for this area:** never tolerate an isolation probe (mask a possible IDOR) without a
re-verify that PROVES it returns the caller's OWN data (the #566v pattern). A wrong "is-stale"/"is-secure"
heuristic ships a real security leak. When unsure, keep the leak verdict (conservative).

---

### §5.0t — the `player` metric was INVERTED, and it was one root cause, not two (2026-08-12)

Two questions were open: (a) what to do about the `player` reference frame, (b) whether to swap the
visual composite from the judge's holistic number to the mean of its own dimensions. **Measurement
answered both, and they turned out to be the same root cause.**

**The composite question is closed: KEEP holistic, do NOT switch.** The gap (mean − holistic) over
450 screens is *not* a constant offset (avg 0.135, **sd 0.069**, range 0.001–0.364), so
"switch + raise the bar by the offset" is not identity: re-anchoring to hold the pass rate
(0.65 → 0.779) flips 9.8% of screens. But scored against the one *objective* build signal available
(#588's chrome checklist, 31 player screens), holistic agrees **12** times and the dimension mean
**6**. The mean flips `games` (a genuinely thin page) to PASS and blocks complete players harder.
The dimensions are computed against the same bad reference, so they inherit the same defect —
changing the composite was never going to fix a reference problem.

**The reference frame is the actual root cause, and its effect is an INVERSION, not noise:**

| chrome (objective) | n | mean sim | gate today |
|---|---|---|---|
| COMPLETE (all 8 emitted controls) | 26 | 0.605 (max **0.72**) | **all 26 BLOCKED** |
| SHELL r107 (7 of 8 missing) | | **0.92** | PASSED |
| SHELL r106 (5 missing) | | **0.85** | PASSED |
| SHELL r138 (2 missing) | | **0.80** | PASSED |

Every complete player scored below every passing shell. `references/player.jpg` is an **ad state**
(Back / flag / "Ad 12" / Pause / Volume / Fullscreen). r106 shipped *exactly* that control set and
scored 0.85; r107 shipped a subset and scored 0.92 with the verdict "Player chrome closely matches
the reference" and the fix "group the flag icon and Ad counter into one dark rounded chip". **The
frame is not just a bad yardstick — it is the spec the design analyst reads, so it steers generation
toward building an ad overlay instead of a video player.** (`Report` is emitted by `#544`; `Ad 12`
and "begins after ads" are ad-only.)

**RECOMMENDED ASSET FIX (user's call — it breaks score comparability with the 32 runs of history):**
`references/player_controls.jpg` is already staged into `design/references/` on **every run** and is
never scored by any screen. It carries **all 8 controls** the framework's own
`_player_controls_jsx_449` emits (pause / ±10s / volume / scrubber / next-episode / episodes /
subtitles / fullscreen) over a **black** content area — i.e. it removes the content-vs-chrome
confound *at the source* rather than compensating for it downstream. Screens map to frames by name,
so the swap is: make the `player` screen's frame that image.

**Landed instead (framework, no asset change): #589** — #588 only *demoted*, so it skipped every
screen above the bar and could not see the false greens above. Blocking cannot key on
`missing != []` (every ordinary page is "missing" all 8); the applicability test is the framework's
own `_screen_is_player_449`, the predicate that decided to emit the cluster. Replayed over all
history: 23 verdict changes, all on `player`, 3 false greens caught + 20 false reds demoted,
**0** blocks on any non-player screen. `_blocking_average` deliberately untouched.

> **Generalizable lesson:** #542a's `_TRANSIENT_STATE_RE` demotes screens whose **name** says
> hover/preview/ad. Here the ad-ness was in the **image**, invisible to every name-based guard, and
> it silently became the spec. When a reference frame and the framework's own emitter disagree about
> what a screen contains, **the emitter is the ground truth** — that asymmetry is what makes the
> checklist trustworthy in both directions.

---

### §5.0u — #568's root cause found; three more axes closed by measurement (2026-08-12)

**#590 (LANDED) — the cause behind #568.** #568 blocked the *consequence* of a PK-only projected
model. The cause is in `registryhub.register_table`: an incoming schema that normalizes to zero
columns was written as authoritative, DESTROYING a schema already on record. r133's event stream
for `my_list` (`event_type: table_registered`, the artifact to read is
`shared/hubs/eventhub_events.json`):

```
03:17:05  cols=4  by=orchestrator      registered at kickoff, with columns
04:37:21  cols=3  by=orchestrator
04:57:03  cols=0  by=BACKEND           <- the lane re-registered without columns
04:57:29  cols=0  by=orchestrator      <- the status flip propagated the empty schema
```

26s later the skeleton regenerated and baked in `class MyList(Base): id`. Sibling `ratings` was
never written again after 04:38 and kept all 4 columns — **the only difference between them is
who wrote LAST.** FIX #90 made an empty registration legal for a table nobody has described yet;
it must not also license destroying one. A table with zero columns cannot exist (database_scaffold
synthesises an `id` PK rather than raising), so empty carries no information and now behaves
exactly like `schema=None`. Over 56 runs: 2 wipes (r133 `my_list` 3→0, r119 `profiles` 5→0, both
by the backend lane); **r119 survived only by luck** — a later registration restored the columns
63s on. The wipe is fatal precisely when it is the LAST write before scaffolding. Column
REDUCTIONS (45 seen) are deliberately untouched — real revisions — and the 23 spine `users` 6→4
shrinks provably never reach the model (framework re-synthesises spine tables; checked
r103/r113/r115). Breadcrumb: `metadata.schema_wipe_prevented_by`.

**Three axes closed as NEGATIVE results — do not spend on them again:**

| axis | measurement | verdict |
|---|---|---|
| "`games` 0.62 because it has no backing API" | pages with a resolvable `apis_used` mean **0.619**, dangling **0.574** (n=10), none declared **0.674** | **unsupported** — an unbacked page does not predict low fidelity (the none-declared group is mostly login/landing, which correctly have none) |
| dangling `apis_used` (10 found) | every one is a path-PARAM-NAME mismatch (`/api/titles/{id}` vs registered `{title_id}`, `{item_id}`, `{genre_id}`), and `frontend_audit.audit_ui_page` already matches each `{param}`/`:param` as a **path-segment wildcard** against source | **no harm** — only `registryhub`'s endpoint-deprecation cascade rewrites `apis_used` by exact string and would miss these; downstream is param-agnostic and prompt text is unaffected |
| "make the generic #10/#263 body fallback denial-aware" (the #575b hazard, on the id path) | 9435 chain steps, **577** true cross-user denial steps via the repo's own `_is_cross_user_denial`; only **10** carry a `${var}` no step saved, and all 10 are `${rand}` — a documented BUILTIN random suffix, not the id fallback (r135: `DELETE /api/v1/tenants/${rand}` → `.../616508006` → 404, correct) | **0 of 577 exposed** — the hazard is real in principle but absent in every trajectory; no speculative code |

> The `DELETE /api/v1/tenants/${rand}` case is worth remembering as the shape to watch: had the
> id fallback reached it, the step would have deleted a REAL tenant listed two steps earlier and
> still been recorded as a coverage pass — the #566x failure mode exactly (a step that PASSES is
> the bug). `${rand}` is what prevents it today.

---

### §5.0v — what ACTUALLY keeps the UI gate red, ranked (2026-08-12)

The per-screen gate has never passed, and the arc had been chasing `games`. **`games` is the 6th
blocker.** Over the 40 runs with a scored gate, counting non-advisory screens below 0.65:

| screen | blocks | mean | best | status |
|---|---|---|---|---|
| **login** | **29/40** | 0.593 | 0.82 | framework-scaffolded → **#594** |
| **browse_by_languages** | **27/40** | **0.424** | 0.82 | **worst screen in the set — UNINVESTIGATED** |
| player | 20/40 | 0.625 | 0.92 | #588/#589 |
| title_detail | 20/40 | 0.580 | 0.85 | #584 |
| genre_category | 9/40 | 0.607 | 0.72 | — |
| games | 8/40 | 0.671 | 0.80 | see below |
| shows / my_list / movies | 6/6/5 | ~0.69 | 0.85 | — |

Only **4 of 40** runs had exactly ONE screen below the bar (`login` ×2, `my_list`, `browse_by_languages`)
— so no single fix flips the gate; this is a stack.

**`login` (#594, LANDED).** 282 deviations cluster as background/gradient 49, footer 48,
**card/border 42**, get help 39, register-link 35. Only card/border has a structural signal:
**39 of 45** measured `login` screens declare no card/panel region, yet the template wrapped the
form in `rounded-md border-white/10 bg-black/20` unconditionally. Now measurement-driven;
unmeasured (`None`) keeps the panel. Replay: 38 drop, 7 keep, 0 disagreements.

Ruled out on `login` — **do not re-chase**: the chrome slots ARE filled (reCAPTCHA line in
**42/43** delivered pages — an earlier "0/43" was a bad regex, the framework words it "not a bot"
with no product literal; `<footer>` 43/43; brand header 43/43; footer links median 6). `Get Help`
is missing in 15/43 but scores 0.592 with vs 0.596 without — **nothing**.

**Documented, not fixed — the discarded gradient.** `design_system.json` measures it
(`login: {"background": "#161616", "gradient_note": "top-left radial #3A1010 → transparent →
#000 bottom"}`, `player_controls: {"gradient": "bottom rgba(0,0,0,0.85) → transparent (top
40%)"}`) and `_screen_surface_bg` keeps only the flat hex — exactly the judge's "implementation
is flat black; reference uses a dark red gradient". But only **1 of 45** design systems records a
screen-level gradient (7 record one at `palette` level), so there is no basis for a projector
change yet. If screen-level gradient capture becomes reliable, this is the next lever.

**`games` — explained, not fixed.** Every dimension is 0.82–0.89 except `components` 0.610; the
deviations say "section titled 'New' with movie posters instead of 'Party Games' with game
tiles". **40 of 45 runs declare a Games page; 0 have a games table or endpoint.** Deterministic
contract gap: the design analyst reads `games.jpg` and declares the page, the backend contract
never gets the entity, and `synthesize_missing_tables` cannot help because there is no POST. So
the page renders `titles` — a user clicking Games sees Movies, which is a FUNCTIONAL bug, not
just a fidelity one. Not fixed here because synthesising a read-only entity is speculative
(what columns? what rows?); the honest options are (a) extend synthesis to read-only catalog
pages declared by the design, or (b) a contract-gap task, the read analog of
`test_user_squad`'s MISSING WRITE PATH.

**Closed as a NEGATIVE result:** "unbacked page ⇒ low score" is false — pages with a resolvable
`apis_used` mean **0.619**, dangling **0.574** (n=10), none-declared **0.674**.

**#593 (LANDED) while measuring the above.** The ui_page store is keyed by NAME, so
`<name>_page` (the #225 design-screen seed) and `<name>` (the contract) each created a record for
ONE route: **28 duplicate routes in 6 runs, all 28 disagreeing** on `apis_used`/`components`;
r142 (a VALIDATED run) carries 9, r133 carries 8. The router dispatches on the route, so every
consumer that iterates the store acted on whichever it hit first. Now merged by route.
**Stated honestly: this is hygiene, not a fidelity fix** — duplicate-route screens score 0.641
vs 0.624 and the within-run paired deltas swing +0.183 to −0.252. Merging is strictly not-worse:
both records were already live and already audited. Replay: 28 → 0, no route lost.

> **Next lever if this is picked up again: `browse_by_languages`, mean 0.424 across 40 runs** —
> by far the worst screen in the set and never investigated. Its dimensions are components
> 0.445 / layout 0.547 / copy 0.590, and its deviations name a dual dropdown vs a single one, a
> 6-col flat grid with captions vs 5-col category rows with TOP-10 ribbons, and a missing hover
> preview card.

---

## 6. Other KNOWN-OPEN issues — ALL FOUR CLOSED 2026-08-12

> **2026-08-12: every item below has a measured verdict. Nothing here is open.** Three were
> disproved as stated; the fourth was real, its stated hypothesis was wrong, and the residue is
> fixed by **#591**/**#592**. Items are kept (not deleted) so the next reader can see what was
> ruled out and how — re-opening one needs new evidence, not a re-reading.
>
> | item | premise | verdict |
> |---|---|---|
> | 1 | `last_result` goes STALE between validation passes | **DISPROVED.** `last_run_at` spread within a run is **0–4 s** over 42–141 chains (r129 141, r130 42, r134 74, r139 81, r142 106) — every chain is re-run every pass. Only *never-run* chains exist (1–7 per run) and #510 already excludes those. The proposed `run_chains` rework is **unnecessary**; do not build it. |
> | 2 | `rating → 422 "value is required"` | **GONE.** 0 failing 422 steps in r129 **and** r130. Arc-wide every persisted 422 has `ok=True` — the step's `expect` was a wide net, not a failure. (Chasing this is what surfaced **#591**.) |
> | 3 | `my-list → 404`: `title_id` string-vs-int, seed ids like `titles-1` | **REAL, hypothesis WRONG.** r130's model is `title_id = Column(Integer, ForeignKey("titles.id"))` against `Title.id = Column(Integer)` — both ints. Actual chain: `GET /api/titles` returned `{"items": [], "total": 0}` (an EMPTY catalog — #566x's reset), `save {titleId: items.0.id}` captured nothing, the ladder filled `${titleId}` with an unrelated id, the FK 404'd. Cause fixed by #566x; the **misattribution** by **#592**. |
> | 4 | profiles/continue-watching read-back advisory | **NOT REPRODUCED** in r134/r139/r142 (all three `*** MULTI-MILESTONE VALIDATED ***`, delivered-app audits clean). #566p's diagnostic is in place if it returns. |
>
> **#591 (LANDED), the mirror of #586.** #586 rejects an expectation nothing can *satisfy*; #591
> rejects one nothing can *falsify*. A BUSINESS step accepting both a 2xx and 401/403 passes
> whether the app served the data or refused the caller — it cannot detect a cross-user leak or a
> wrongly-denied owner, and still counts toward the green chain total. Arc-wide: **56 such steps
> in 16 runs**, on exactly the resources every owner-scoping leak lived on (`/api/my-list` ×26,
> rating ×8, `/api/continue-watching` ×6, `/api/profiles` ×2) — **r133** (the #568 live leak) has
> 12, **r142** (a VALIDATED run) has 13. Control-plane paths are exempt (654 of the 710 arc-wide
> wide-expectation steps are `/auth`, `/oauth`, `/api/v1/*`, `/health`, `/.well-known`, where
> "the surface answers sanely" is the real intent); 409 and 404 are not denial codes, so
> `POST /auth/register [200,201,409]` — the arc's most common wide expectation — is untouched.
> Replay over all 3533 authored chains: **139 rejected (3.9%)**, higher than #586's 0.3% and
> stated plainly; every rejected shape is genuinely blind.
>
> **#592 (LANDED).** #188 explains a failure when a var stayed literal; it was silent when the
> ladder DID produce a value, which is the worse case — the request looks well-formed and the
> status lands on the endpoint. Now the consuming step carries
> `SUBSTITUTED ${v} save failed at step '<upstream>' … fix that capture, not this endpoint` plus
> `autofilled: ladder-filled-after-failed-save:<v>`. Annotation, not reclassification (#587
> precedent). Discriminator is `v not in variables` — the ladder writes only into the outgoing
> request, so a var present in `variables` was really captured by a later step and its stale
> `save_failed_by_var` entry must not annotate.

1. **verification_checklist / build:* STALENESS + FLAPPING (r124/r126/r129).** The delivery gate reads
   each chain's `last_result` and the four `build:*` checks; on slow draws these **flap** pass↔fail across
   validation runs, so the gate never sees ALL checks green in ONE eval → wedge. `run_chains`
   (validation_runner.py:1031) runs chains for the CURRENT `business_endpoints`, so earlier-milestone
   chains that broke-then-were-fixed aren't re-run → stale broken `last_result` persists
   (delivery_gate.py:744-750; #510 only excludes NEVER-run chains). #566q fixed the multi-PR AttributeError
   but NOT this staleness. **Candidate fix:** run_chains/run_validation must re-run + record ALL authored
   chains each pass; OR make the #511 "record-the-truth" self-heal STICKY within a session. Also DB-state
   accumulates across the ~6 api_smoke retries within one validation (a 2nd rating create → 409 — mostly
   mitigated by #566u). SAFE variant: re-run everything (fresh results, can't ship broken); do NOT add a
   fuzzy timestamp heuristic that could ignore a real failure.
2. **rating → 422 "value is required"** (r129/r130 flap cause #2): a REQUEST-schema-vs-chain mismatch
   (schema requires `value`, chain sends `{rating:…}`). 422 is request-validation, BEFORE the handler, so
   #566t can't catch it. Investigate which handler/model raises it (projected handlers take
   `body: dict = None`, so no Pydantic validation — likely a lane model or the create-schema heal #566n).
3. **my-list → 404 "referenced resource not found"** (flap cause #3): `title_id` FK doesn't resolve —
   chain `${titleId}` → a non-existent id, or string-vs-int mismatch (`my_list.title_id` is Text FK to
   `titles.id`; seed ids look like `titles-1`). Watch the resolved id at runtime.
4. **profiles/continue-watching readback advisory** (same-user create → GET returns 0 rows or a different
   id). The ORIGINAL read-back owner-scoping mismatch. Non-blocking in most runs; #566s/#566t/#566u don't
   target it (it's a same-user read-scoping issue, related to §5). #566p added the diagnostic (list
   contents) so a future run's message tells persist-vs-owner-scope apart.

---

## 7. Recommended immediate plan for the next agent

> **STATUS 2026-08-11 (session r131):** steps 1–2 are DONE. 12 commits now unpushed (#566m→#566x);
> the push still needs the USER (agent egress 403 — attempted, confirmed blocked). **r131 launched**
> (gen PID 1686673, keeper + monitor attached) carrying #566u/#566v/#566w/#566x. Suite 1279 passed.
> The r131 watch-list is below, plus: `save FAILED.*titleId` (want 0 — #566x) and
> `reset-scoped->` in the chain step records (proves the guard fired).

1. **Push the 10 commits** (or ask the user to): `git push origin feat/netflix-generality-366-367`.
   Agent github egress is 403 — attempt once, then hand to the user.
2. **Launch r131** (`ENVGEN_SINGLE_MILESTONE=0 FW_DEBUG=1 ENVGEN_VISUAL_MIN=0.65 ./launch_netflix.sh
   netflix-web-r131`) to **validate #566u (rating-409 upsert) + #566v (read-isolation)** end-to-end and
   confirm they break the r130 oscillation. Start keeper + monitor. Watch (in `gm_netflix-web-r131.log`):
   - `rating → 409` count (want 0 — #566u), `my-list.*expected \[403` + "DENIAL-PROBE got success" (want
     0 / tolerated — #566v), IDOR create leaks (`POST.*→ 2[0-9][0-9] (expected \[40` — want 0 — #566s),
     `rating → 422`, `my-list → 404`, and the gate trajectory / `verification_checklist_not_ready`.
3. **Diagnose ground-truth-FIRST, then STOP + report before the NEXT 2–3h run** (hard guardrail). Do NOT
   blind-relaunch. If it wedges, pin the exact failing step from the log + the app code under
   `agent/generated/netflix-web-r131/app/…` (custom_routes.py, main.py, models.py).
4. If read-isolation still oscillates → begin the **owner-scoping standardization** (§5, option A first —
   it's the least invasive). One change → render+compile + unit test → full suite → one run → report.
5. Keep every fix **generalizable** (no `netflix`/product literals; decide by SHAPE — owner FK → sub-entity
   → users, etc.). Add a unit test with a render+compile assertion for any emitter/skeleton change.

---

## 8. Gotchas / hazards (learned the hard way)

- **★ START A POST-MORTEM AT THE CHAIN REGISTRY, NOT THE LOG** (how #566x was found in ~40 min after two
  arcs of log-grepping missed it): `agent/generated/<run>/shared/hubs/registryhub_verification_chains.json`
  holds, per chain, the authored `steps` AND the `last_result` (every step's status + `note` + the
  SUBSTITUTED path). Three cheap queries on it:
  1. **Index the failures.** Failing-chain indices vs. the index of any step with a destructive or
     state-changing effect. A block of failures that starts at one index and never recovers is a
     CASCADE, not N independent bugs — find what runs at the boundary. (r130: reset@20, first
     failure@24, zero before.)
  2. **Read the `note` field, not just the status.** `save FAILED (response lacks the path)` is the
     framework TELLING you a capture starved — the downstream 404 is the symptom, not the bug (#188
     built this; use it).
  3. **Compare a passing chain against a failing one with the SAME step shape.** Identical
     `save: {titleId: items.0.id}` passing at #18 and failing at #21 rules out "bad chain authoring"
     and points at shared state changing between them.
  Then confirm the mechanism against the app source in `agent/generated/<run>/app/backend/`.
- **A step that PASSES can be the bug.** Coverage steps against infra/control-plane endpoints have side
  effects on the SHARED database every other chain reads. Green ≠ harmless.
- **Custom routes shadow projected routes** — fixing a projected handler does nothing if the lane wrote a
  custom one for that path. Always check `custom_routes.py` first for the serving handler.
- **`agent/tests/` is gitignored** — your unit tests won't show in `git status`; that's expected.
- **The generated app dir persists after teardown** (`agent/generated/netflix-web-rNNN/app/…`) — use it to
  read the ACTUAL handlers/models the run produced when diagnosing.
- **Stale vs live errors:** grep the log with timestamps
  (`grep -oE "[0-9]{2}:[0-9]{2}:[0-9]{2}.*<pattern>"`) — many "failures" are STALE from early in the run
  (e.g., r130's `my_list user_id` was from 17:08, fixed by 20:48). Always check the LATEST occurrence.
- **business_chain can PASS then FLAP** — check for `business_chain: **PASS**` lines; a red gate may be a
  flapping/stale check, not a live failure (§6.1).
- **Skeleton helpers live INSIDE the `_MAIN_HEADER` triple-quoted string** in `backend_skeleton.py` — edit
  the string text; it renders into `main.py`. Verify with the render+compile test.
- **HANDOFF hazard:** when editing `HANDOFF_2026-08-07_multimilestone.md` with str_replace, don't drop a
  session header — it orphans the body (happened repeatedly).
- **The stop-hook enforces the "keep optimizing" directive** — expect it to push you to continue after
  each checkpoint. It's legitimate to pause ONLY to report before another 2–3h run, or when a change is
  genuinely risky (weigh it explicitly). Prefer making a real, safe, tested change each iteration.

---

## 9. Key files (with what each fix touched)

- `agent/env_generator/llm_generator/multi_agent/runtime/route_projector.py` — projected handler emitter.
  `_generate_handler` (create/read/update), `_generate_upsert_handler` (#556 state-write). #566s/#566t/#566u
  emit into the POST-create path (owner-FK check → fill defaults → upsert-on-conflict footer).
- `agent/env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py` — `_MAIN_HEADER` template +
  `_models_meta`, `render_skeleton_main`. Home of `_fw_owner_val`/`_fw_owns`/`_fw_fill_required_defaults`/
  `_fw_upsert_on_conflict`.
- `agent/env_generator/llm_generator/multi_agent/runtime/chain_executor.py` — chain runner.
  `_is_cross_user_denial`, `_reverify_denial_via_fresh_intruder` (#78+#566v), `_response_has_rows` (#566v),
  `_dig`/`_dig_path` (#566m), `run_chains`, `execute_chain`, `load_verifier_chains`.
- `agent/env_generator/llm_generator/multi_agent/runtime/delivery_gate.py` — the gate.
  `business_chain_blockers` (744-750 = stale last_result read), `validate_delivery_gate` (~1401-1435 =
  verification_checklist from `build:*`, #566q reduction).
- `agent/env_generator/llm_generator/multi_agent/runtime/validation_runner.py` — `run_smoke_validation`
  (line 1031 calls `run_chains`; comment ~1035-1037 = the worktree-vs-main-registry sync gap).
- `agent/env_generator/llm_generator/tools/validation_tools.py` — the `run_validation` TOOL; `_record_chain_results`
  (255-268) syncs chain results to the MAIN registry via `record_chain_result`; `_record_build_checks`.
- `agent/env_generator/llm_generator/multi_agent/runtime/frontend_audit.py` — `bare_authed_fetch_blockers`,
  `inject_auth_fetch_wrapper` (#566r), `_composes_child`.
- `agent/env_generator/llm_generator/multi_agent/runtime/test_user_validation.py` — test-user journeys;
  `_ui_auth_flow` (#566o), `_created_appears`/`_find_by_id` readback matcher (#566k, #566p).
- `HANDOFF_2026-08-07_multimilestone.md` — deep per-run history (sessions 10–29). Reference for detail.

---

## 10. Definition of done (for the standing directive)

A run prints `*** MULTI-MILESTONE VALIDATED ***` with ≥2 progressive tags and rc=0 **on a slow/adverse
draw** (not just a favorable one) — i.e., the owner-scoping variance no longer wedges M1/M2. Until then,
each iteration should land ONE generalizable, tested framework fix and validate it with a run, narrowing
toward the §5 lever. Do not declare done on unit tests alone — the run is the proof.
