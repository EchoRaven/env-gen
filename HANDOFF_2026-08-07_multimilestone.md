# HANDOFF — forgingground-gen multi-milestone Netflix validation (2026-08-07)

> Written because the prior session's context was saturated. This is a complete,
> self-contained handoff. Read it top-to-bottom; everything you need to resume is here.

---

## UPDATE — 2026-08-10 (session 29): r130 FAILED (0 tags) — SYSTEMIC ROOT = lane owner-scoping variance

- **r130 = FAILED, rc=1, 0 tags — M1 itself wedged** (STUCK after 3 ticks). NOT a #566s/t/u regression:
  the wedge was the LANE's custom `_resolve_profile` (custom_routes.py) for GET my-list read-scoping,
  which the backend OSCILLATED: first too-permissive (`GET /api/my-list?profile_id=<other> → 200`, a read
  leak), then over-corrected to too-restrictive (`GET /api/my-list?profile_id=<OWN 24> → 403`), never
  converging. Plus `my-list → 404` (title_id FK). #566u (rating-409) rendered but M1 wedged before M2 so it
  wasn't re-validated e2e (still unit+render validated only).
- **★ SYSTEMIC ROOT (the recurring slow-draw wedge, r126–r130): LANE OWNER-SCOPING VARIANCE.** On favorable
  draws (r115/r118/r121/r125) the lane's custom owner-scoping (`_resolve_profile`/`get_my_list`/rating
  handlers) happens to be correct → clean multi-milestone. On SLOW draws the LLM backend writes/rewrites
  those custom handlers with OSCILLATING bugs (header-required ↔ auto-resolve; cross-user 200 ↔ own 403;
  create 409 ↔ upsert; title_id FK), the framework validation correctly flags them, and the backend can't
  reliably converge → M1/M2 wedge. My fixes #566s/#566t/#566u harden the FRAMEWORK-PROJECTED create
  handlers; the LANE CUSTOM handlers (which OVERRIDE the projected ones — custom_routes wins) are the
  remaining systemic gap.
- **★ THE REAL LEVER (architectural, fresh + careful): STANDARDIZE owner-scoping so the lane can't ship a
  buggy custom variant.** Options: (a) framework provides a CANONICAL `_fw_resolve_owner_scope(db, user,
  header, query)` (mirrors `_fw_owner_val`/`_fw_owns`: no id → auto-resolve/provision the caller's own;
  explicit id → verify ownership → 403 if foreign) and the scaffold/prompt REQUIRES the lane to call it
  (never hand-roll); OR (b) the framework PROJECTS owner-scoped READ handlers and prevents a lane custom
  override for owner-scoped resources (or heals a buggy lane resolver to the canonical one). This removes
  the LLM-variance from the single most wedge-prone surface. HIGH blast radius → design + validate over
  several runs; do NOT rush blind.
- **GIT: 21 fix commits (#566→#566u); 9 unpushed (#566m…#566u).** #566s/#566t validated e2e (r129); #566u
  unit+render validated (needs an e2e run that reaches M2).

---

## UPDATE — 2026-08-10 (session 28): #566u rating-409 UPSERT fix; r130 launched (validates #566s/t/u + captures rating-422 / my-list-404)

- **#566u (committed `8b393b2`)** — fixes r129 business_chain flap cause #1 (`rating → 409 "duplicate
  resource"`). Skeleton helper `_fw_upsert_on_conflict(db, cls, valid, user, owner_fk, subject_fks)`,
  called ONLY from the projected create's `except IntegrityError` branch: loads the caller's existing row
  by owner_fk + subject FKs (natural key, all in `valid`) and UPDATEs it (idempotent) → returns it; None
  → re-raise (409, old behavior). REACTIVE (only after a real unique conflict) + requires owner+subject
  match → a non-unique / non-state-write resource is never wrongly upserted. route_projector wires it into
  POST creates with an owner FK + ≥1 subject FK; non-owner creates untouched. Tests (4) + full suite
  **1263 passed**; #556/#566s/#566t green; render+compile validated.
- **r130 LAUNCHED** (gen 3514713, keeper 3519159, monitor 3519160) — validates #566s (IDOR) + #566t
  (rating value-null) + #566u (rating-409 upsert) end-to-end, and captures RUNTIME clarity on r129's 2
  remaining business_chain flap causes:
  - `rating → 422 "value is required"` — likely a REQUEST-schema-vs-chain mismatch (schema requires
    `value`, chain sends `{rating:…}`); 422 is request-validation (before the handler), so #566t can't
    catch it. Watch which handler/model raises it.
  - `my-list → 404 "referenced resource not found"` — `title_id` FK doesn't resolve (chain ${titleId} →
    non-existent id, or string-vs-int: my_list.title_id is Text FK to titles.id). Watch the resolved id.
  - + `verification_checklist` build:* flap + DB-accumulation across api_smoke retries.
- **GIT: 21 fix commits (#566→#566u).** Origin at #566l; **#566m…#566u (9) unpushed.**

---

## UPDATE — 2026-08-10 (session 27b): CORRECTION — r129 real wedge is FLAPPING/flakiness, not a deterministic bug

- **CORRECTION to session-27:** the my_list-user_id business_chain failure was a RED HERRING. Near the
  end, **business_chain PASSES** (log: "business_chain: **PASS** — 681 steps across 135 chains"; also
  633/128 earlier). The final gate OSCILLATES: `['business_chain_failing']` ↔ `['business_chain_failing',
  'verification_checklist_not_ready']` across evals.
- **REAL r129 wedge = FLAPPING / validation flakiness.** build:* and business_chain flip pass↔fail between
  validation runs (a flaky docker boot / a flaky chain step / a transient), so the delivery gate never
  observes ALL checks green in a SINGLE eval → no delivery → 75-min wedge. `verification_checklist`
  requires all four build:* = success in one eval (delivery_gate ~1428, with #566q); when a build:* flaps
  to non-success in an eval, the checklist flaps red. The #511/#120/#492 "STALE BUILD-CHECKLIST self-heal"
  FIRED 5× (record-the-truth) but the next flaky run re-recorded failure → un-healed.
- **⇒ This is an INTERMITTENT convergence-STABILITY issue, not a deterministic bug.** Hardest class:
  fixing it means (a) making validation runs DETERMINISTIC (kill the docker-boot / chain flakiness), or
  (b) LATCHING the gate's best recent result (once a check reaches success from a real run, a later
  TRANSIENT failure in the same session doesn't un-latch it unless the underlying code changed) — the
  #511 self-heal, made STICKY. RISK: latching can mask a genuine regression → must gate latching on
  "no code change since the success" + validate with a run. HIGHEST blast radius (the delivery gate).
- **NOT a #566s/#566t regression** — those are validated (IDOR/rating/my-list-GET/rating-value=0).
- **NEXT (fresh, careful):** pin WHICH check flaps + WHY (tail the per-run build:*/business_chain
  recordings across the ~6 validation attempts); then either stabilize the flaky validation step or make
  the record-the-truth self-heal sticky-within-session. Do NOT latch blind (masks real regressions).
  - **THE 3 SPECIFIC business_chain flap causes (semi-deterministic, data-dependent):**
    1. `POST /api/titles/1/rating → 409 "duplicate resource"` — a RE-rating hits a unique constraint; the
       rating handler CREATES instead of UPSERTING. A rating is a STATE-WRITE (user's rating is upserted,
       not duplicated) → it should use the #556 upsert path (INSERT … ON CONFLICT UPDATE / check-then-
       update), not the plain projected create. FIX: classify rating (and similar per-user state) as an
       upsert, or make the create idempotent on the (owner, subject) unique key.
    2. `POST /api/titles/1/rating → 422 "value is required"` — value-default (#566t) not applying on this
       path (a #556 upsert or a body sending value=null explicitly, which #566t's "absent" check skips).
    3. `POST /api/my-list → 404 "referenced resource not found"` — my-list create with a title_id FK that
       doesn't resolve (chain ${titleId} → a non-existent id / string-vs-int id mismatch: my_list.title_id
       is Text FK to titles.id).
  - Plus verification_checklist build:* flap + DB-state ACCUMULATION across the ~6 api_smoke retries within
    one validation (retries don't reset the DB → a 2nd rating create → 409). Each is a distinct fix.

---

- **r129 VALIDATED both fixes end-to-end.** In M2 (rating/my-list area that wedged r127/r128):
  **IDOR fails=0, rating-value-null=0, rating-400=0, my-list-GET-400=0.** The r127 cross-user IDOR and
  r128 rating-value-null are FIXED. `_fw_owns` + `_fw_fill_required_defaults` rendered into main.py
  (projected POST /api/my-list uses `profile_id` correctly via #566s/#566t). M1 delivered `1.0.0`.
- **BUT r129 = FAILED (rc=1, tags [1.0.0] only).** M2 wedged (~1h40m) on `business_chain_failing` +
  `verification_checklist_not_ready` — a SLOW-converging draw (M1 alone took ~2h on ui_flow/tasks):
  - **business_chain**: `(psycopg UndefinedColumn) column "user_id" of relation "my_list" does not exist;
    INSERT INTO my_list (user_id)…` + `POST /api/my-list → 404`. NOT the projected POST handler (that uses
    profile_id, no custom my-list POST exists, no RECENT user_id errors — the failures are stale/flapping).
    ⇒ **PINNED as chain-result STALENESS (delivery_gate.py:744-750):** the my_list chain broke EARLY
    (last user_id error 17:08, gen ended 20:48 — 3h40m stale), the app was FIXED (profile_id handler), but
    that chain's stale broken `last_result` was never refreshed → `not_passing` (status!='passing' OR
    last_result.broken) keeps firing `business_chain_failing`. #510 only excludes NEVER-run chains, not
    ran-then-fixed-but-not-rerun ones. A LATER whole-suite run_validation PASSED (13/13, 39 chains green)
    yet the gate still read the stale per-chain result.
  - **verification_checklist_not_ready** recurred (all build:* success, 1 record each — NOT the #566q
    AttributeError; the r124/r126 STALENESS again — cleared once mid-run then reappeared). SAME class.
  - **⇒ THE recurring root (r124/r126/r129): STALENESS — the gate reads stale check/chain records that do
    not reflect the current (fixed) state.** FIX DIRECTIONS (fresh + careful, HIGHEST blast radius — a
    wrong "is-stale" call SHIPS a genuinely-broken app): (a) verifier run_validation must RE-RUN + refresh
    `last_result` for ALL authored chains each pass (no chain goes stale); OR (b) the gate ignores a
    chain's `last_result`/`build:*` record whose `last_run_at`/`updated_at` predates the latest whole-suite
    run_validation session (treat as indeterminate → re-run), NOT as a failure. Needs the latest-session
    timestamp plumbed + a run to validate (real failures still block; only genuinely-superseded stale
    results are ignored). DO NOT implement blind at saturation.
    - **TRACED DEEPER (validation_runner.py:1031):** `run_chains(base, project_dir, business_endpoints)`
      runs chains for the CURRENT `business_endpoints`; earlier-milestone chains (my_list from M1) that
      broke-then-were-fixed aren't re-run → stale broken `last_result` persists. Plus a KNOWN worktree-vs-
      main-registry sync gap (validation_runner comment ~1035-1037: "chains pass live but the gate sees
      stale 'registered' → deadlock"). Candidate fix: run_chains/run_validation should re-run + record ALL
      authored chains each pass (not just current-milestone endpoints), and sync every result to the MAIN
      registry the gate reads. SAFE variant (re-run everything → fresh results → can't ship broken). Needs
      a run to validate perf + correctness.
  - **readback advisory=22** (continue-watching create → GET 0 rows, same-user) — the ORIGINAL read-back
    owner-scoping mismatch, non-blocking, NOT addressed by #566s/#566t (which fix cross-user + null-value).
- **These M2 wedges are DIFFERENT from #566s/#566t (which work).** They're this draw's own convergence
  tail (my_list #556/toggle owner-FK=user_id; verification_checklist staleness; same-user readback).
- **GIT: 20 fix commits (#566→#566t).** Origin at #566l; **#566m…#566t (8) unpushed.**
- **NEXT (fresh):** (1) my_list #556/toggle owner-FK mis-resolution to user_id → find the emitter that
  writes `valid["user_id"]` for a profile_id-owned table; (2) verification_checklist staleness (r124/r126/
  r129 — build:* all success yet gate red); (3) same-user readback owner-scoping (continue-watching
  create→GET empty). All app/framework-convergence, distinct from the validated #566s/#566t.

---

## UPDATE — 2026-08-10 (session 26): rating value-null FIXED (#566t); r129 launched (validates #566s IDOR + #566t)

- **#566t (committed `2d6054b`)** — the r128 M2 rating wedge. `POST /api/titles/{id}/rating → 400 "null
  value in column value"`: the verifier authored some rating bodies with the WRONG key
  (`{"rating":"thumbs_up"}` not `{"value":"up"}`), so the unknown field is filtered → ORM INSERTs NULL,
  even though the lane added `ALTER … SET DEFAULT 'up'`, because SQLAlchemy emits an explicit NULL for the
  unset non-null column (no MODEL default) → the DB default never fires. (The lane fought it with
  migrations + CHECK + a startup hook and still lost.)
  - Fix: skeleton helper `_fw_fill_required_defaults(cls, valid, db)` — for each NOT-NULL, no-model-default
    column ABSENT from the create body, read the column's DB default (information_schema) and apply it
    EXPLICITLY. Wired into the projected POST create handler (after `_coerce_body`, after the #566s owner
    check). Generalizable; best-effort; a well-formed body is untouched.
  - Validated: 3 unit tests (wired into POST create only; runs after _coerce_body; rendered main.py defines
    the helper + compiles); full suite **1259 passed**; #556/#566s green.
- **r128 outcome:** validated #566s IDOR (0 fails, M1 delivered) but M2 wedged on the rating value-null
  (now #566t). Torn down; relaunched.
- **r129 LAUNCHED** (gen 429977, keeper 433890, monitor 433891) — validates BOTH #566s (cross-user →403)
  AND #566t (rating value-less body →201) end-to-end + a clean multi-milestone delivery. Local tree has
  #566m…#566t.
- **GIT: 20 fix commits (#566→#566t).** Origin at #566l; **#566m…#566t (8) unpushed.**

---

## UPDATE — 2026-08-10 (session 25): IDOR FIXED (#566s owner-FK ownership check); r128 launched to validate

- **#566s (committed `09c8911`)** — implements the r127 cross-user IDOR fix (was documented as the
  next-session task; done now with unit tests + render-compile validation, end-to-end pending r128).
  - `backend_skeleton` `_MAIN_HEADER`: new runtime helper `_fw_owns(cls, col, fk_val, user)` — reuses
    `_fw_owner_val`'s PROVEN FK introspection (#134/#390/#391): True iff the client-supplied owner FK is the
    caller's own uid (direct user FK) or a sub-entity (profile/…) the caller owns (per-user sub-entity FK).
    Fail-OPEN only on an introspection/query FAULT; a clean "not owned" → False → handler 403s.
  - `route_projector._generate_handler` (the vulnerable `setdefault` create path, = r127 main.py:1046):
    emit `if body owner-FK present AND not _fw_owns(...) → 403; else setdefault(_fw_owner_val)`. Honors a
    caller's OWN non-default profile (multi-profile), resolves own when absent.
  - `_generate_upsert_handler` LEFT AS-IS — it OVERRIDES the owner FK (ignores the body) so it's already
    IDOR-safe; changing it broke the #556 shape tests, so reverted. (continue-watching/my-list upserts.)
  - Validated: 4 unit tests (emitter emits the 403 guard; emitted block compiles; rendered main.py defines
    `_fw_owns` + compiles — catches the "syntax breaks every app" risk); #556 state-write tests green;
    full suite **1256 passed** (73 pre-existing oauth only).
- **r128 LAUNCHED** (gen 2904528, keeper 2911552, monitor 2911553) to validate END-TO-END: cross-user
  write → 403, same-user write → 201 + read-back, business_chain green, clean multi-milestone delivery.
  ⚠️ docker-level behavior can only be confirmed by this run.
- **GIT: 19 fix commits (#566→#566s).** Origin at #566l; **#566m…#566s (7) unpushed.**
- **NOTE:** r127's CUSTOM my-list handler (`add_to_my_list` → `_resolve_profile_id`) already validates
  ownership; if a custom handler still leaks, that's lane code (framework projected path is now fixed).
  Watch r128's business_chain for any residual my-list IDOR.

---

## UPDATE — 2026-08-10 (session 24): r127 validated #566r; M2 exposed a REAL IDOR (create handlers trust body profile_id)

- **#566r VALIDATED** in r127: `bare_authed_fetch=0` all run (wrapper injected into index.html), **M1
  delivered `1.0.0`**, all prior fixes holding (profile-IDOR/rating/title_id=0, run_validation ~23s).
- **M2 wedged on `business_chain_failing` — and it is a REAL app IDOR, NOT a mis-authored test.** The
  failing steps (rating_upsert_and_isolation, my_list_toggle_and_ownership, mylist_add_and_isolation) do,
  as a SECOND user (tokenB), a write whose BODY carries the FIRST user's profile id:
  - `POST /api/titles/1/rating` tokenB body `{"value":"love","profile_id":"${profileA_id}"}` → expect
    **403**, app returned **201**.
  - `POST /api/my-list` tokenB body `{"profile_id":"${profileA}","title_id":…}` → expect 403, app 201.
  The create handlers TRUST the body `profile_id` without verifying the caller owns it → userB writes under
  userA's profile ⇒ **cross-user IDOR**. This ALSO explains the readback ABSENT advisory (userB's create
  lands under userA, so userB's own GET returns id=1 not the created id=10).
- **⚠️ NEAR-MISS:** I was about to add a chain_executor tolerance (#566s: widen a cross-user-denial probe
  to accept 2xx for rating/bare-collection creates) — inspecting the step BODIES first revealed they carry
  a cross-user `profile_id`, so that tolerance would have MASKED a real IDOR. Do NOT add it. The chain is
  CORRECT; the app is vulnerable.
- **FIX DIRECTION (security-critical, fresh + careful):** owner-scoped creates must REJECT (403) — or
  server-override — a body/owner-FK (`profile_id`/`user_id`/`owner_id`) the caller does not own. This lives
  in the owner-scoping machinery (`_fw_owner_val` for projected handlers; and the lane's CUSTOM
  create handlers in custom_routes.py that read `profile_id` from the body and insert it unvalidated).
  Preferred: the projected/custom create path validates `profile_id` belongs to `_fw_uid(user)` (mirror
  r125 `_require_profile`'s ownership check, but for the BODY owner-FK, not just header/query) → 403 on a
  foreign owner. Confirm with a run that (a) cross-user writes 403 and (b) same-user writes still 201 +
  read back (fixes both the business_chain IDOR steps AND the readback advisory).
  - **CONFIRMED ROOT (r127 main.py:1046, projected `_projected_post_api_titles_id_rating_13`):**
    `valid.setdefault("profile_id", _fw_owner_val(Rating, "profile_id", user))`. `setdefault` resolves the
    caller's own profile ONLY when the body omits profile_id; a body with a BOUND foreign profile_id
    (userA's, which #566m makes bind) is already in `valid` → setdefault no-ops → the row is written under
    userA ⇒ IDOR. The `${...}`-placeholder strip (line 1040) only guards the UNBOUND case. This projected-
    handler template is emitted by route_projector/backend_skeleton for EVERY owner-sub-entity create.
  - **EXACT FIX:** replace the `setdefault` with: resolve `_own = _fw_owner_val(...)`; if the body carries
    an owner-sub-entity FK, verify it belongs to the caller (a real ownership query, handling a user's
    MULTIPLE profiles — NOT just `== _own`) → 403 if foreign; else set it to `_own`. Add a framework
    helper `_fw_owns(sub_cls, fk_id, user)` (SELECT 1 FROM <profiles> WHERE id=:fk AND <user_fk>=:uid).
    Apply in BOTH the projected template AND heal the lane custom create handlers (or a global write guard).
    Note the #78 `_reverify_denial_via_fresh_intruder` treats a 201 as a leak, so an OVERRIDE-to-own (201)
    would STILL fail business_chain — the app must REJECT (403), matching the verifier's expectation.
  - **VALIDATION REQUIRED (must run):** wrong ownership query → 403s every legit write (breaks ALL apps)
    OR misses the IDOR. Highest blast radius + security-critical → do NOT implement blind at saturation.
  - **EXACT EMITTER TARGETS (route_projector.py):** line **1262**
    `body_lines += [f'    valid.setdefault("{ofk}", _fw_owner_val({cls}, "{ofk}", user))']` — the vulnerable
    create path (emits r127 main.py:1046); and line **1627**
    `f'    valid["{owner_fk}"] = _fw_owner_val({cls}, "{owner_fk}", user)'` — an always-OVERRIDE variant.
    NOTE: plain OVERRIDE is NOT a valid fix — it breaks MULTI-PROFILE apps (a user choosing their 2nd
    profile gets forced to their default `_fw_owner_val`). The `setdefault` exists precisely to honor the
    body's profile choice. So the fix MUST validate OWNERSHIP: keep the body owner-FK IF it belongs to the
    caller (any of their profiles), else 403; if absent, use `_fw_owner_val`. Emit a runtime helper
    `_fw_owns(db, sub_table, sub_user_fk, fk_id, uid)` (SELECT 1 FROM <sub_table> WHERE id=:fk AND
    <sub_user_fk>=:uid), deriving <sub_table>/<sub_user_fk> from `_orm_models` (owner_fk→sub-entity→users).
    For a DIRECT user-owned FK (owner_fk→users), the check is `fk_id == _fw_uid(user)`. This must be a RUN-
    validated change (multi-profile own-write → 201+readback; cross-user write → 403).
- **WHY NOT FIXED NOW (firmly weighed):** highest-blast-radius + SECURITY-CRITICAL owner-scoping path;
  a wrong change either masks the IDOR or breaks owner-scoping for every app. At extreme context
  saturation this is exactly the change that must be done fresh + validated, not blind. The pipeline still
  robustly builds (r125 = clean full 3-milestone; r127 delivered M1 + validated #566r).
- **GIT: 18 fix commits (#566→#566r).** Origin at #566l; **#566m…#566r (6) unpushed.** No #566s (correctly
  abandoned — would mask the IDOR).

---

## UPDATE — 2026-08-10 (session 23): r126 root FIXED (#566r bare_authed_fetch wrapper); r127 launched to validate

- **#566r (committed `f6078bf`)** — the deterministic fix for r126's 79-min abort cause
  (`deliverability_bare_authed_fetch`). Installs a GLOBAL `window.fetch` wrapper into `index.html <head>`
  that attaches `Authorization: Bearer <localStorage access_token>` to same-origin `/api/` requests
  (excludes /api/v1/; idempotent; try/catch → falls back to original fetch; survives vite build).
  `bare_authed_fetch_blockers` self-clears when the wrapper marker `__fw_auth_fetch__` is present;
  `deliverability._bare_fetch_blockers` installs it (idempotent) BEFORE the audit reads → the gate
  self-clears deterministically, independent of the lane/remediation/reconcile timing that wedged r126
  (fix reached the gate-read integration tree only after the abort; dispatched once, at the abort tick).
  Mirrors the #566b/#566e reconcile-before-gate pattern. Tests (4) + existing bare-fetch tests
  (#154/#233/#508) pass; full suite **1252 passed**.
- **r127 LAUNCHED** (gen 1002895, keeper 1010539, monitor 1010540) to validate #566r keeps
  bare_authed_fetch clear + a clean multi-milestone delivery. Local tree has #566m…#566r.
- **GIT: 18 fix commits (#566→#566r).** Origin at #566l; **#566m/#566n/#566o/#566p/#566q/#566r (6)
  unpushed.**
- **Prior deep fixes still validated:** #566q (gate-checklist multi-PR AttributeError), #566o/#566p
  (accurate login/readback diagnostics), r125 = clean full 3-milestone (#566l/m/n validated e2e).

---

## UPDATE — 2026-08-10 (session 22): #566q gate-checklist fix; r126 abort FULLY TRACED to bare_authed_fetch reconcile/dispatch timing

- **#566q (committed `a707df5`)** — real latent gate bug: `validate_delivery_gate`'s build-checklist
  reduction stored a STATUS STRING then called `prev.get("updated_at")` on it → AttributeError on the 2nd
  `build:*` record (list_checks() has no pr_id → build:* across ALL PRs) → swallowed → ready_for_delivery
  =False forever. Fix: store the check DICT. Tests (4) + full suite **1248 passed**.
- **#566o (`69fed9a`) + #566p (`ff6c1cf`)** — accurate diagnostics for the login + readback advisories.
- **r126 = ABORTED (rc=1) — FULLY TRACED (NOT #566q, NOT verification_checklist):**
  - Timeline: build error (api.jsx) fixed 10:57; build:* recorded SUCCESS 11:08:28; verification_checklist
    CLEARED at 11:08. The persistent blocker 11:08→11:26 was **`deliverability_bare_authed_fetch`** (a
    frontend bare `fetch('/api/…')` without the auth token, read from the INTEGRATION frontend tree).
  - It was dispatched to the frontend **only ONCE, at 11:26:06 — one second AFTER the 79-min no-convergence
    abort (11:26:05)** (dispatch count=1). So for ~18 min it was the sole blocker but the frontend was
    never told to fix it. And `bare_authed_fetch_blockers(integration src)` is **[] NOW** → the fix DID
    reach integration, but too late (after the abort).
  - **⇒ TWO compounding gaps:** (1) a worktree→integration reconcile-timing gap — the bare-fetch fix lived
    in a lane worktree (a SERVICE/COMPONENT file, e.g. services/api.jsx) but reached the integration tree
    the gate reads too late (#566b/#566e reconcile only PAGES + App.jsx, not services/components); (2) the
    remediation dispatcher did not RE-dispatch bare_authed_fetch when it (re)became the sole blocker after
    the 10:57 self-rewrite (dispatched only at the final abort tick). Intermittent — r121/r124/r125 cleared
    bare_authed_fetch fine.
- **FIX DIRECTIONS (fresh, careful — highest blast radius):** (a) a deterministic bare_authed_fetch HEAL at
  gate-poll time (like #566b/#566e): rewrite integration bare `fetch('/api/…')` to attach
  `Authorization: Bearer <localStorage access_token>` (merge into existing opts) so the gate self-clears
  independent of lane/dispatch/reconcile; OR (b) reconcile non-page frontend files (services/components)
  worktree→integration before the deliverability gate; AND (c) make the dispatcher RE-dispatch a
  persistent sole-blocker each coordination tick. Confirm with an instrumented run (log the integration
  file the gate reads vs the worktree fix + dispatch attempts per tick).
- **WHY PAUSED (firmly weighed):** the fix is in the delivery-gate / frontend-reconcile / remediation-
  dispatch coordination — the HIGHEST blast radius (gates ALL deliveries). The cause is intermittent and
  the exact 11:26 integration state is overwritten (can't fully confirm statically). Changing this core
  coordination on an unconfirmed timing hypothesis, at extreme context saturation, risks regressing the
  path that produced 4 clean multi-milestone deliveries (r115/r118/r121/r125, r125=full 3-milestone) — a
  net-negative vs the goal. Best done fresh with the instrumented confirmation above.
- **GIT: 17 fix commits (#566→#566q).** Origin at #566l; **#566m/#566n/#566o/#566p/#566q (5) unpushed.**

---

## UPDATE — 2026-08-10 (session 21): accurate diagnostics for the 2 r125 advisories (#566o login, #566p readback); r126 launched

- **#566o (committed `69fed9a`)** — `_ui_auth_flow` now captures `/auth/*` response statuses and reports
  the TRUE login failure mode instead of always "form not wired". r125's LoginPage IS wired
  (fetch('/auth/login')+token store); the old note misdiagnosed a 401 (UI login user not registered) or a
  shape issue as dead wiring. New note distinguishes: no /auth request = dead form; /auth ≥400 = wired but
  creds/backend; /auth 2xx + no token = response-shape.
- **#566p (committed `ff6c1cf`)** — the readback ABSENT note now includes the GET list size + seen ids, so
  `created X ABSENT` distinguishes (a) EMPTY list = not-persisted OR read scoped to a different owner than
  the write, from (b) OTHER ids = scope/owner mismatch. (r125 profiles id=26/28/29 ABSENT.)
- Both are DIAGNOSTIC-ONLY (no pass/fail change), low-risk, full suite **1244 passed**. They exist because
  the 2 remaining r125 advisories can't be pinned from code alone (both handlers scope via the same
  `_user_id`) — needed RUNTIME data to tell the failure modes apart.
- **r126 LAUNCHED** (gen 3926765, keeper 3932106, monitor 3932107) to capture the accurate #566o + #566p
  diagnostics → then the true root of each advisory becomes fixable. Local tree has #566m…#566p.
- **GIT: 16 fix commits (#566→#566p).** Origin at #566l; **#566m/#566n/#566o/#566p (4) unpushed.**

---

## ✅✅ SUCCESS — 2026-08-10 (session 20): r125 FULL 3-MILESTONE delivery — #566l + #566m + #566n all validated e2e

- **r125 = `*** MULTI-MILESTONE VALIDATED ***`** — tags `['1.0.0','1.1.0','1.2.0']`, GENERATION COMPLETE,
  rc=0. The "持续优化" loop produced a clean 3-milestone build validating the three fixes made this arc:
  - **#566l** (build offline-retry/fail-fast/skip-unchanged): max run_validation **29.6s** (r122 was
    1,201,439 ms) — build hang GONE.
  - **#566m** (chain `_dig` bare-list index): profile-IDOR = **0**.
  - **#566n** (nested-create + required typed columns): rating-400 = **0** (M2's `POST /api/titles/{id}/
    rating` now passes). title_id-null = 0, readback (denorm/#566k) handled.
  - All 14 fixes (#566→#566n) holding; 0 regressions.
- **ONE remaining ADVISORY (non-blocking): profiles readback.** `created profiles (id=26/28/29) is ABSENT
  from GET /api/profiles` — 3× across journeys, did NOT block the 3-milestone delivery. Code finding
  (custom_routes.py): POST `create_profile` returns a BARE `{id,...}` while GET `list_profiles` returns
  `{items:[...]}`; BOTH scope via `_user_id(user)` (POST inserts user_id=uid, GET filters user_id=uid), so
  the absence is NOT explicable from code alone — like the ORIGINAL read-back, it needs RUNTIME user_id
  correlation (POST-uid vs GET-uid for the same journey) to pin. Candidate causes to instrument: the
  max-5-profile cap (create_profile:866 → 403), `_ensure_post_seed()` re-seed interaction, or a `_user_id`
  edge. **NEXT:** an instrumented run (mirror #566h: log `_user_id` + created/queried profile ids) — a
  well-scoped, gated ~2-3h task, NOT a blind code change.
- **GIT: 14 fix commits (#566→#566n).** Origin at #566l; **#566m `fabbee2` + #566n `7d442f9` unpushed.**
- **STILL-OPEN (from r124, unseen in r125): `verification_checklist_not_ready` refresh-lag** after a lane
  vite build error is fixed (stale build:docker not re-flipped to success). Latent; did not recur in r125.

---

## UPDATE — 2026-08-10 (session 19): rating value-null (#566n) FIXED; r125 launched to validate

- **FIX #566n (committed `7d442f9`, unpushed)** — the r124 business_chain rating blocker. `POST
  /api/titles/{id}/rating → 400 (DB constraint on missing field)`: the create's required `value`
  (NOT-NULL numeric) wasn't in `schema.request` (probes/chains omitted it). `heal_create_endpoint_request_
  schemas` missed it — it SKIPPED path-param paths (nested creates) and only added subject FKs + generic
  TEXT columns. Fix: (a) `_orm_models` now parses nullability/pk/default → emits a `required` set
  (NOT-NULL, non-PK, no-default columns); (b) the heal now covers NESTED collection creates (skip only
  ITEM ops; require the last segment to NAME the resolved table so ACTION verbs aren't force-healed) and
  adds every `required` column TYPED from the ORM (Integer→int, Float/Numeric→float, Boolean→bool, else
  str), owner FK excluded. Precise (nullable=False only) → no over-send. Tests (11) + full suite **1244
  passed**; backward-compatible (models w/o `required` keep prior behavior).
- **r125 LAUNCHED** (gen 1935589, keeper 1939348, monitor 1939349) to validate #566n + observe the
  remaining tail. Local tree has #566m + #566n.
- **STILL-OPEN tail (r124): `verification_checklist_not_ready` refresh-lag** — after a LANE vite build
  error is fixed (r124: duplicate `export default`), `build:docker` stayed stale-FAIL and didn't refresh
  to success though run_validation went 13/13 green → checklist stuck ~55 min. Fix direction: ensure a
  passing api_smoke/run_validation records `build:*`=success (why didn't the #511 "record-the-truth"
  self-heal fire?). SENSITIVE gate area — do fresh, with a run. Not addressed in #566n.
- **GIT: 14 fix commits (#566→#566n).** Origin at #566l; **#566m `fabbee2` + #566n `7d442f9` unpushed.**

---

---

## UPDATE — 2026-08-10 (session 18): r124 validated #566m + #566l; remaining tail = rating nested-create schema + checklist refresh-lag (precise fix directions)

- **r124 VALIDATED #566m + #566l (0 regressions).** profile-IDOR=0 (#566m holds), longest run_validation
  ~23s (#566l holds, no build hang), title_id-null=0, readback_ABSENT=0. The app is fundamentally sound —
  **170× `run_validation` returned 13/13 green** in this run. M1 did NOT cleanly deliver (~2h) only because
  of a FLAPPING convergence tail (gate oscillated 4↔1), NOT a regression.
- **Remaining tail item #1 (highest value): rating NESTED-create schema gap.**
  `POST /api/titles/{id}/rating → 400 (DB constraint on missing field)` — the chain's positive step 400s
  because the rating create's required body field (`value`, a NOT-NULL numeric) isn't in `schema.request`,
  so probes/chains omit it. `heal_create_endpoint_request_schemas` (#566f/#566i) does NOT cover this: it
  (a) SKIPS path-param paths (`if any(seg.startswith("{"))` → nested creates like
  `/api/titles/{id}/rating` are excluded), and (b) only adds subject FKs (int) + generic TEXT columns
  (name/title/label/…), never a required NUMERIC column like `value`. **Fix direction:** extend #566f to
  (a) handle nested creates — resolve the CHILD table from the LAST non-param segment (`rating`), keep the
  parent id in the path; (b) add ALL required non-PK, non-owner, non-FK, non-defaulted, non-timestamp
  columns with typed placeholders (from `meta["types"]`), not just text names. RISK: over-sending
  optional/defaulted/timestamp columns → must skip DateTime/defaulted cols; can't live-test → needs a run.
- **Remaining tail item #2: `verification_checklist_not_ready` refresh-lag.** The gate computes readiness
  from the latest `build:*` CodeHub checks (delivery_gate.py:1401-1435). After the frontend FIXED a vite
  build error (r124: duplicate `export default` in BrowseHomePage.jsx — lane code error, drained from the
  bug queue at 05:48), `run_validation` went 13/13 green, but `build:docker` stayed stale-FAIL / didn't
  refresh to success, so verification_checklist stuck ~55 min. **Fix direction:** ensure a passing
  api_smoke/run_validation reliably records `build:*`=success (the #511 "record-the-truth" self-heal
  should flip a stale build:* when the build now passes) — investigate why it didn't fire in r124.
- **WHY PAUSED (transparent risk-weigh):** both fixes are in SENSITIVE, highest-blast-radius machinery
  (create-schema derivation that feeds every app's probes/chains/frontend; the delivery-gate checklist
  refresh). After an extraordinarily long autonomous session (r112→r124, 13 fixes), implementing multiple
  such changes while context-saturated risks regressing the 13 working fixes / core delivery — a net
  negative vs the goal. The pipeline ALREADY robustly builds the target (r115/r118/r121 = 3 clean
  multi-milestone deliveries; r124 = 170 green validations); these are the asymptotic hard-tail on a
  specific random draw. Best executed fresh, one at a time, with a validation run each.
- **GIT: 13 fix commits (#566→#566m).** Origin at #566l; **#566m `fabbee2` is the 1 unpushed.**

---

## UPDATE — 2026-08-10 (session 17): business_chain "profile IDOR" ROOT-CAUSED + FIXED (#566m); r124 launched to validate

- **The r123 blocker (7× "profile IDOR") is FIXED (#566m, committed `fabbee2`, unpushed).** Root cause:
  verifier chains bind the owner sub-entity via `save {"pid": "0.id"}` from GET /api/profiles, but r123's
  `list_profiles` returns a **BARE list** (`[ {id,...} ]`, not the `{items:[...]}` envelope), and
  `chain_executor._dig` couldn't resolve a numeric index against a bare list → `pid` unbound → `${pid}`
  fell back to a FOREIGN id (`1`) → every profile-scoped read 403'd (the strict ISO1 isolation CORRECTLY
  rejecting a foreign profile). The app + isolation were correct; the chain var-bind was the bug.
- **Fix (`_dig`/`_dig_path`):** resolve a numeric index into a BARE list AND a `{items|data|results|rows}`
  envelope (negative + bounds-checked; out-of-range → None, never a false bind); and `_dig` now
  progressively STRIPS wrong leading path segments (`items.0.id` on a bare list → `0.id`). Generalizable
  to any bare-array list endpoint. Tests: `test_dig_bare_list_index_566m.py` (5); full suite **1242
  passed**; existing `test_chain_*` all pass.
- **r124 LAUNCHED** (gen 472585, keeper 479009, monitor 479010) to validate #566m unblocks the
  business_chain + surface anything next. Local tree has #566m (runs regardless of push).
- **Still-open (advisory, lower priority):** title_id-null create-schema heal TIMING (the heal runs in the
  delivery-time loop, after the api_smoke journey → early continue-watching/my-list creates transiently
  400). Non-blocking. Fix direction: run the create-schema heal (or derive FKs in `_probe_body`) before
  the first journey.
- **GIT: 13 fix commits (#566→#566m).** Origin at #566l (user pushed through #566l); **#566m `fabbee2`
  is the 1 unpushed.**

---

## UPDATE — 2026-08-10 (session 16): r123 — #566l VALIDATED (hang gone); surfaced profile-IDOR chain issue + title_id heal-timing

- **#566l VALIDATED end-to-end.** r123's longest `run_validation` = **249,385 ms (~4.2 min) vs r122's
  1,201,439 ms (20 min)** — the build hang is GONE. `skip-unchanged` fired 5×, **0 build-hangs**. All 12
  prior fixes held: route-not-wired=0, ui_page_unwired=0, readback_ABSENT=0, auth-500=0.
- **NEW blocking issue — profile IDOR in the business_chain (14 fails).** Verifier: "business_chain FAILS
  with 7× profile IDOR errors." Evidence: `GET /api/continue-watching?profile_id=1 → 403 ("profile does
  not belong to caller")` and same for my-list, where the chain EXPECTED 200. BUT the r123 handlers look
  correctly USER-SCOPED (custom `list_profiles` `WHERE user_id=:uid`; continue-watching/my-list use
  `_resolve_profile`, which 403s a foreign/absent-mismatch X-Profile-Id per the ISO1 predicate). So the
  contradiction: either (a) the chain's IDOR test synthesizes a FOREIGN `profile_id=1` and mislabels the
  CORRECT 403 as an IDOR failure (chain-synthesis bug in chain_executor), or (b) `profile_id=1` is
  actually the caller's OWN profile and the 403 is a real bug (caller can't read own data). NOT resolved —
  contradictory evidence, needs the live DB (which user owns profile 1?) + the chain's exact IDOR-test
  synthesis. This is the **security-critical, highest-blast-radius area (chain_executor / profile
  isolation)** — deferred rather than rush a change while context-saturated. NOT a regression of the 12
  fixes.
- **title_id-null heal-timing (advisory, 2×).** continue-watching POST 400'd on title_id in EARLY
  journeys (03:12/03:17); the create-request-schema heal (#566d/#566f/#566i) fired 0× by then — it runs
  in the delivery-time heal loop, but the api_smoke/business_chain journey runs EARLIER. Fix direction:
  run the create-schema heal (or a probe-level FK derivation) BEFORE the first journey so early
  continue-watching/my-list creates don't transiently 400. Advisory (didn't block; gate was on IDOR).
- **GIT: 12 fix commits (#566→#566l), all pushed to origin (user pushed through #566l).** r123 added NO
  new commits (investigation-only).
- **NEXT (fresh, focused — not saturated-session):** (1) resolve the profile-IDOR chain semantics
  (inspect live DB profile ownership + chain_executor IDOR-test synthesis) — highest priority, security;
  (2) create-schema heal timing (run before first journey). Both need careful analysis in sensitive areas.

---

## UPDATE — 2026-08-10 (session 15): r122 (all 11 fixes: 0 regressions) wedged on a NEW build-hang — FIXED (#566l)

- **r122 = final validation of all 11 fixes. Every fix held: 0 signals** for title_id-null, name-null,
  route-not-wired, ui_page_unwired, auth-500, genre-404, docker_up-err, read-back ABSENT across ~1h49m.
  The 11 fixes are regression-clean.
- **BUT M1 wedged on a NEW, unrelated issue:** `run_validation` (`run_smoke_validation`) hung ~20 min —
  two `up -d --build` calls each hit the `_DOCKER_UP_TIMEOUT` (1200s) cap. docker_up/boot were clean;
  the build's NETWORK package installs (frontend `npm install`, backend `uv pip install`) re-ran every
  validation with no reuse, and a flaky registry/proxy window hung the install → `deliverability_no_
  successful_run` → the whole 7-check gate cascaded (incl. the pre-existing unowned `dead_artifacts`) →
  no delivery. NOT a regression of the 11 fixes; intermittent (r118/r121 built fine). Tore down r122 clean.
- **FIX #566l (committed `134230e`, unpushed)** — 3 fixes, all in `validation_runner.py` (BuildKit is
  pinned off, so cache-mounts were out; no risky Dockerfile edits): (a) OFFLINE/RESILIENT — `_build_with_
  retry` (`compose build` + retry; retries resume from the classic layer cache = offline for completed
  layers); (b) FAIL-FAST — dedicated `ENVGEN_DOCKER_BUILD_TIMEOUT` (900s) build + short
  `ENVGEN_DOCKER_UP_ONLY_TIMEOUT` (240s) up, `_compose_capture` turns a TimeoutExpired into a rc=124 with a
  clear "build hung on npm/uv (network)" diagnostic; (c) SKIP-UNCHANGED — `_app_source_fingerprint`
  (content hash of app/ + compose, excl. node_modules/dist/…) vs `docker/.last_build_fingerprint`;
  unchanged → `up -d` reuses the cached image (no rebuild, no network). Fail-safe: None-fingerprint →
  rebuild; skipped-build `up` failure → fall back to full rebuild+up (never ship stale). Env-overridable.
  Tests: `test_build_offline_failfast_skip_566l.py` (9); full suite **1237 passed**.
- **⚠️ #566l needs a LIVE-RUN to fully validate** — the unit tests cover the fingerprint/retry/timeout
  LOGIC (via mocked `_compose`), but the actual docker build/up behavior (skip-build image reuse, retry
  resume-from-cache) can only be confirmed by a real run.
- **GIT now: 12 fix commits** (#566 → #566l). Origin at #566e; **#566f…#566l are the 7 unpushed** (USER pushes).

---

## ✅ SUCCESS — 2026-08-09 (session 14): r121 validated #566j (2 tags, rc=0) + read-back FALSE-POSITIVE pinned & FIXED (#566k)

- **r121 = `*** MULTI-MILESTONE VALIDATED ***`** — tags `['1.0.0','1.1.0']`, `main() returned 0`, Status
  SUCCESS. **#566j VALIDATED end-to-end: `ui_page_unwired` = 0 the entire run** (the r117/r120 75-min
  abort did NOT recur). The detail-page clobber wedge is gone.
- **Read-back DEFINITIVELY root-caused via the #566h instrumentation.** r121 hit BOTH scoping paths
  (32 profile_id + 94 user_id resolutions); **profile_id was CONSISTENT (23 groups, 0 inconsistent)** yet
  the journey still reported "created X ABSENT" **13×**. So the read-back is **NOT `_fw_owner_val`, NOT
  profile scoping, NOT data loss** — it is a **FALSE POSITIVE**: a create returns the ENTRY id
  (POST /api/my-list → `{item:{id:<my_list row>}}`), but the DENORMALIZED list view keys items by the
  RELATED entity — GET /api/my-list returns titles (item `id` = TITLE id) with the entry id under a
  `my_list_id` alias. The journey's `_find_by_id` matched only on `id` → never found the entry id → false
  ABSENT. (The custom GET is even user-scoped/robust to profile mismatch — it was never a scoping bug.)
- **FIX #566k (committed `50153a7`, unpushed):** `_find_by_id` now also matches `new_id` against a
  resource-derived `<res>_id` alias (threaded from the journey's `base_col`; my-list→my_list_id,
  continue-watching→continue_watching_id, + depluralized variant), restricted to the resource's OWN alias
  so an unrelated FK can't false-match; backward-compatible without a res_key. Tests:
  `test_created_appears_denormalized_566k.py` (7); full suite **1228 passed**.
- **The read-back thread is CLOSED** — it was an advisory false positive (r121 delivered fine), now fixed
  so the journey stops mis-flagging working denormalized-list apps as BROKEN. `_fw_owner_val` was
  exonerated with runtime evidence; the #566h instrumentation stays in place.
- **GIT now: 11 fix commits** (#566 → #566k). Origin at #566e; **#566f/#566g/#566h/#566i/#566j/#566k are
  the 6 unpushed** (USER pushes).

---

## UPDATE — 2026-08-09 (session 13): M1 ui_page_unwired 75-min abort ROOT-CAUSED + FIXED (#566j)

- **r117/r120's M1 no-deliver abort on `deliverability_ui_page_unwired` is FIXED.** Ground truth (r120):
  the frontend built a REAL 230-line `TitleDetailPage` (worktree, fetches+renders detail), but
  `wire_detail_modal_534` OVERWROTE it in integration with an 11-line modal-mount stub (its only guard
  skipped when the page already mounted the modal, not when it was a genuine lane page). The audit then
  mis-flagged even that modal-mount as an inert "placeholder stub" because `_composes_child`'s regex
  (`components/\w+['"]`) didn't match a `.jsx`-extension import. Net: ui_page_unwired never cleared →
  75-min abort. #566b's reconcile missed it (its `_is_stub` checks placeholder/fallback markers, not this).
- **FIX #566j (committed `fc61cb2`, unpushed):** (a) `wire_detail_modal_534` NEVER clobbers a real lane
  detail page (skip when it has a real api call + no framework marker; only re-project a framework
  mis-projection/stub); (b) `frontend_audit._composes_child` regex is now extension-agnostic
  (`components/\w+(?:\.\w+)?['"]`) so a page mounting `<X/>` from `'../components/X.jsx'` isn't flagged
  inert. Tests: `test_detail_page_clobber_and_compose_566j.py` (3); full suite **1221 passed**.
- **GIT now: 10 fix commits** (#566 → #566j). Origin at #566e; **#566f/#566g/#566h/#566i/#566j are the 5
  unpushed** (USER pushes).

---

## UPDATE — 2026-08-09 (session 12): r120 hit the profile_id path — #566h PROVES read-back is NOT _fw_owner_val

- **r120 launched to hit the profile_id scoping path** (schema authoring is LLM-random; r120's LLM
  authored `MyList.profile_id`/`ContinueWatching.profile_id → profiles.id` — the buggy sub-entity path).
- **DEFINITIVE FINDING (the whole point of #566h):** across the actual profile_id path, `_fw_owner_val`
  resolved **CONSISTENTLY per user — 0 inconsistent out of 10 (table,uid) groups** (uid5→profile14,
  uid13→17, uid18→21, uid28→28, uid51→38, …; each uid → exactly ONE profile every call). So the r118
  read-back ("created X ABSENT from GET") is **NOT a `_fw_owner_val` owner-resolution inconsistency** —
  my earlier hypothesis is REFUTED with runtime evidence.
- **NARROWED next hypothesis:** the read-back most likely arises when a **CUSTOM read handler** resolves
  the profile differently than the **PROJECTED write handler**. r118's my-list GET was a custom handler
  (`_resolve_profile_id`) while its POST was projected (`_fw_owner_val`) → possible split; r120 had BOTH
  GET+POST projected (both `_fw_owner_val`) → consistent → (would-be) no read-back. To confirm needs a run
  with that custom-GET/projected-POST split that also reaches its milestone's journey.
- **r120 did NOT deliver:** M1 hit the 75-min no-deliver STUCK-ABORT on `deliverability_ui_page_unwired`
  (frontend never finished a page → nothing for #566b/#566e to reconcile → gate never green; rc=1, 0 tags).
  So M2 never ran and the journey's own "ABSENT" assertion wasn't observed this run. This slow-M1 /
  frontend-page-throughput livelock (also seen in r117) is a separate convergence concern, NOT a
  regression of the 9 fixes. Torn down clean (0 containers).
- **#566h instrumentation is permanent** — it will keep auto-capturing owner resolution on every future
  run; the profile_id-path evidence above is now on record.

---

## UPDATE — 2026-08-09 (session 11): read-back root-caused (profile_id-specific) via instrument #566h; profiles-400 FIXED #566i

Directive "能修复的都修复" continued. Launched instrumented **r119** to capture `_fw_owner_val` resolution:

- **#566h (committed `d83a023`) — instrumentation.** Added a best-effort, after-resolution
  `_fw_dbg("fw_owner_val.resolved", {table,col,uid,resolved})` in `backend_skeleton.py` `_fw_owner_val`
  (verified it propagates into rendered main.py; byte-identical when FW_DEBUG unset). r119 captured 80+
  lines.
- **READ-BACK ROOT CAUSE NARROWED (not reproduced in r119).** r119's LLM authored **per-`user_id`**
  scoping for my_list/continue_watching (NOT the per-`profile_id` sub-entity scoping r118 used). The
  instrumentation showed ALL resolutions `col='user_id'`, `resolved==uid`, consistent POST↔GET → the
  read-back **did NOT occur** (gone from r119's journey BROKEN list). This CONFIRMS the r118 read-back is
  specific to `_fw_owner_val`'s **sub-entity auto-create path** (profile_id→profiles FK); the direct
  user_id path is clean. To pin the exact profile_id mechanism, a future **profile_id-scoped** run will
  now auto-log it (instrumentation is permanent). Schema authoring is LLM-nondeterministic run-to-run.
- **#566i (committed `4127140`) — FIXED `POST /api/profiles → 400`** that r119 surfaced. Backend log:
  `IntegrityError 23502 null value in column "name"` (profiles.name NOT-NULL) → handler's "invalid field
  value" 400. `name` is non-FK, so #566f's subject-FK pass skipped profiles. Extended
  `heal_create_endpoint_request_schemas` to also add common REQUIRED non-FK TEXT columns
  (name/title/label/display_name/nickname) present in the table — same convention `_fw_owner_val`'s
  auto-create uses. Byte-safe, delivery-time path only. Tests updated (9); full suite **1218 passed**.
- **r119 STATUS: FINISHED rc=0.** Planner chose **1 milestone** (`M1-auth-profiles-browse-core@1.0.0`),
  so it was a clean SINGLE-milestone delivery (`FINAL DELIVERY: cut release v1.0.0`, `main() returned 0`)
  — validates the **user_id path end-to-end**. Instrumentation captured 81 `fw_owner_val.resolved` lines,
  all `col='user_id'`; the read-back did NOT occur (row visible; not in journey BROKEN). A quick check
  flagged 33/81 `uid!=resolved`, but that is int-vs-str TYPE COERCION on TEXT user_id columns
  (`resolved="6"` vs `uid=6`), not a value mismatch — confirmed by the passing read-back + successful
  delivery. Torn down clean (0 containers). r119 ran LAUNCH-time code so it lacks #566i (profiles-400
  persisted in-run, expected). **The profile_id read-back still needs a future profile_id-scoped run to
  pin the exact mechanism — the #566h instrumentation is permanent and will auto-log it.**
- **GIT now: 9 fix commits** (#566 → #566i). Origin at #566e; **#566f/#566g/#566h/#566i are the 4
  unpushed** (USER pushes).

---

## UPDATE — 2026-08-09 (session 10): login-wiring advisory FIXED (#566g); read-back localized (needs run data)

Directive: "能修复的都修复" (fix everything fixable). Two r118 advisories addressed:

- **#566g (committed `6ffaef8`, unpushed) — FIXED the "UI login form not wired" false positive.** The
  browser test-user filled inputs + clicked submit ONCE; a legitimate Netflix-style multi-step login
  (`LoginPage single=true`) advances a step on the first submit WITHOUT calling the API (reveals the
  password field only then) → one click stores no token / no navigation → mis-reported as a dead form.
  Confirmed the form IS correctly wired (onSubmit → `fetch('/auth/login')` → store token → navigate),
  the backend serves `/auth/login` (`include_router` bare + `/api`), and nginx proxies `/auth`. Fix:
  `test_user_validation._ui_auth_flow` now retries fill+submit up to 3 rounds (re-filling now-visible
  fields, stopping on token/navigation) so multi-step auth isn't mis-flagged. Generalizable, no app
  change; only fills VISIBLE inputs. 26 existing test_user_validation tests pass; full suite **1217
  passed**.
- **Read-after-write per-profile scoping ("created X ABSENT from GET") — LOCALIZED, not safely fixable
  statically.** Confirmed: same auth token for POST+GET (not a harness mismatch), and BOTH handlers use
  `_fw_owner_val(cls,"profile_id",user)` (main.py:876/886) — so the mismatch is inside `_fw_owner_val`
  (main.py:60-192: resolves caller's first profile by id, auto-creates one in a separate SessionLocal
  when none, falls back to raw user_id on exception). Every deterministic path (both resolve the same /
  both fall back) leaves the row visible; the "absent" outcome implies an INCONSISTENT resolution
  between the two requests that cannot be pinned without the actual written-vs-read profile_id. Did NOT
  guess-patch: `_fw_owner_val` is the core per-user owner-resolver (7+ layered fixes) every scoped
  read/write depends on. NEXT: an instrumented run (add a `_fw_dbg("fw_owner_val.resolved", …)` at the
  return + auto-create outcome, then capture container logs) to confirm the mechanism before any change.
- **GIT now: 7 fix commits** (#566 → #566g). Origin at #566e; **#566f `8c860d5` + #566g `6ffaef8` are
  the 2 unpushed** (USER pushes).

---

## ✅✅ SUCCESS — 2026-08-08 (session 9): r118 FULL 3-MILESTONE e2e delivery (all 6 fixes validated)

**The strongest result of the whole arc.** r118 (with all six fixes #566..#566f + the hardened keeper)
delivered a complete 3-milestone build:

- **Release tags: `['1.0.0', '1.1.0', '1.2.0']`** — M1 (`M1-foundation-auth-browse`), M2
  (`M2-catalog-verticals-search`), M3 (`M3-player-mylist-languages`), each `FRAMEWORK DELIVERY: gate
  fully clear → cut release`, then `FINAL DELIVERY: gate clear → cut release v1.2.0` (17:04:12).
- **`main() returned 0`**, `forcing exit (rc=0)`; monitor verdict `*** MULTI-MILESTONE VALIDATED ***`.
  Delivered app tree `agent/generated/netflix-web-r118/app/{backend,frontend,database}`. Torn down clean
  (0 containers). This exceeds r115 (2 milestones) — a full 3-milestone cumulative delivery.
- **ALL SIX FIXES VALIDATED e2e (signals = 0 the entire run):** #566 genre-404, #566b ui-page,
  #566c auth-500, #566d continue-watching title_id-null (journey "created continue-watching (id=20)"),
  #566e route-not-wired churn, #566f my-list title_id-null (journey "created my-list (id=23)"). Plus the
  keeper hardening: 0 docker_up infra failures (r116's mode did not recur).
- **Remaining advisory (non-blocking, did NOT stop any milestone cut):** the test-user journey still
  reports "created <my-list/continue-watching> is ABSENT from the subsequent GET" (v1.1.0 journey dipped
  to 4/7) — a read-after-write / per-profile-scoping consistency mismatch (POST creates under the session
  profile, the GET reads under a different/empty profile). Distinct from the title_id fixes; a good
  candidate for the next session if desired.
- **GIT: 6 fix commits** (#566 `3bb35b6`, #566b `cbf673b`, #566c `4e064f6`, #566d `290c015`,
  #566e `bc80128`, #566f `8c860d5`). USER pushes (agent egress 403). At session end #566f was the last
  unpushed; push `feat/netflix-generality-366-367` to land the full set.

---

## UPDATE — 2026-08-08 (session 8): my-list lane-schema gap FIXED (#566f)

- **#566f (committed `8c860d5`, unpushed)** closes the `POST /api/my-list` NOT-NULL `title_id` 400 that
  #566d did NOT reach: my-list is LANE-DECLARED (no `subject_fks`, no `schema.request`), so the test-user
  `_probe_body` omitted title_id. New `heal_pipeline.heal_create_endpoint_request_schemas` scans every
  registered POST create on a collection and adds its target table's non-owner FK columns to
  `schema.request` (flat `{fk:"int"}`), reusing the #556 derivation (`_fk_columns` − `_owner_fk`) via
  `_resource_model(path, _orm_models(backend_dir))`. Byte-safe (only adds missing non-owner FKs, excludes
  the server-derived owner FK, never overwrites). Runs in the **delivery-time heal loop only** — decoupled
  from the #557 R4 completeness-enforce path (a fleaky first cut piggybacked on `heal_state_write_endpoints`
  and regressed `test_r4_enforce_heal_then_block_557::test_enforce_on_no_gap_ok`; moved the call to the
  delivery-time site to keep R4 semantics intact). Tests: `test_create_request_schema_heal_566f.py` (8,
  gitignored); full suite **1217 passed** (73 pre-existing oauth network fails only — regression cleared).
- **GIT now: 6 fix commits** — #566 `3bb35b6`, #566b `cbf673b`, #566c `4e064f6`, #566d `290c015`,
  #566e `bc80128`, **#566f `8c860d5`**. Origin is at #566e (user pushed #566d+#566e); **#566f is the 1
  unpushed**.

---

## UPDATE — 2026-08-08 (session 7): mode-gating loop root-caused + FIXED (#566e route reconcile)

**The r117 "mode-gating loop" was misnamed — root cause + fix:**
- It was NOT a real stage gate. The frontend agent DID write GamesPage.jsx via `edit_code`; "need edit_code
  mode" was an LLM self-misdiagnosis. The real waste: **96 `finish` calls in ~9 min** churning on
  `deliverability_ui_page_unwired` = **"route `/games` not wired in App.jsx"**.
- Root cause: a frontend lane's committed **App.jsx route edit** reaches integration only via
  `merge_committed_agent_work` (aborts-on-conflict + SUPERSEDES lane edits to framework-touched files; the
  framework rewrites App.jsx every heal tick) → the route edit sits unmerged across every gate poll → the
  gate stays red → the dispatch guard re-arms every 8 declines (`orchestrator.py:3038`) → re-dispatch churn.
  #566b's gate-poll reconcile copies page COMPONENTS only, not App.jsx routes.
- **FIX #566e (committed `bc80128`, unpushed)**: `reconcile_integration_frontend_app_jsx` (heal_pipeline.py)
  additively wires every declared ui_page route into integration App.jsx before the audit reads, reusing the
  hardened `frontend_scaffold.project_missing_ui_routes` (additive/idempotent/never-raises, gate's exact
  `_route_is_wired` predicate). Hooked in `deliverability._ui_page_wiring_blockers` right after the #566b
  component reconcile. Route-not-wired now self-clears at gate-poll time → churn eliminated at the source.
  Tests: `test_appjsx_route_reconcile_566e.py` (6, gitignored); full suite **1209 passed** (73 pre-existing
  oauth network fails, unrelated). Optional churn-guard (reconcile-before-re-dispatch in orchestrator.py:3046)
  was DEFERRED as unnecessary (the primary fix clears the blocker before re-arm).
- **GIT now: 5 fix commits** — #566 `3bb35b6`, #566b `cbf673b`, #566c `4e064f6`, #566d `290c015`, **#566e
  `bc80128`**. Origin had up to #566c; **#566d + #566e are the 2 unpushed** (USER pushes).
- Remaining open levers (lower priority): `POST /api/my-list` NOT-NULL (lane-declared, no subject_fks); the
  75-min no-deliver budget vs M1 churn; a future e2e run (r118) to validate #566d+#566e end-to-end.

---

## UPDATE — 2026-08-08 (session 6): #566d fixed + validated; r116 infra / r117 timeout (goals MET, stopped)

**Read together with the session-5 SUCCESS block above (r115 remains the e2e proof).**

- **#566d (committed `290c015`, unpushed — USER pushes)** fixes the r115-advisory continue-watching/my-list
  `null value in column title_id` 400: `heal_state_write_endpoints` now emits `schema.request` from the
  subject FKs, so the test-user `_probe_body` (and chain synth / frontend) send `title_id`. Tests:
  `test_state_write_request_schema_566d.py` (3, gitignored); full suite **1203 passed**.
- **#566d VALIDATED e2e**: in r117 the `null value in column title_id` count was **0** (the 400 is gone).
- **r116 = INFRA failure (NOT #566d)**: `docker_up: unable to copy from source docker://node:20-alpine`
  — 4/5 base images evicted mid-run + the keeper's re-pull hit a mirror-cert issue → STUCK-ABORT rc=1.
  Root cause: the base-keeper did a raw `podman pull` without healing the mirror cert. FIXED the keeper
  (operationally, not committed): the keeper now runs `tools/ensure_base_images.sh` each cycle (heals cert +
  pulls). r117 confirmed the fix — base images 5/5, **docker_up errors 0** all run.
- **r117 = 75-min no-deliver TIMEOUT (variance, NOT a regression)**: M1 churned through title_detail,
  a ~12-min frontend **"mode-gating loop"** blocking GamesPage.jsx (`need edit_code mode`), then
  profile-scoping issues (`profile_id`-null, an isolation probe) and ran out of the 75-min budget with
  `business_chain_failing` still red → rc=1, 0 tags. r115 converged M1 in ~1h17m and delivered; r117 simply
  needed more remediation than the window allowed.
- **USER DECISION (2026-08-08): STOP — goals met.** #566d validated + r115 is the e2e multi-milestone proof.
  No further relaunch this session.
- **OPEN LEVERS for a future session (not blockers)**: (1) the frontend **mode-gating loop** (agent can't
  enter `edit_code` mode to write a page — wastes the convergence budget; the highest-value reliability fix);
  (2) the 75-min no-deliver budget vs. M1 remediation churn; (3) `POST /api/my-list` NOT-NULL (lane-declared,
  no subject_fks — separate contract-schema gap, unfixed); (4) the continue-watching profile-scoping (`GET`
  needs `X-Profile-Id`; backend auto-select landed in r117 but late).
- **GIT: fix commits on `feat/netflix-generality-366-367`** — `3bb35b6` #566, `cbf673b` #566b, `4e064f6`
  #566c, `290c015` #566d (origin had up to #566c after the user's pushes; **#566d is the 1 unpushed commit**).

---

## ✅ SUCCESS — 2026-08-08 (session 5): r115 MULTI-MILESTONE VALIDATED end-to-end (#566+#566b+#566c)

**THE VALIDATION IS COMPLETE.** r115 (with all three fixes) delivered a full multi-milestone Netflix build:

- **Release tags: `['1.0.0', '1.1.0']`** — M1 (`01:20:34 cut release v1.0.0`, gate fully clear) → advanced to M2
  (`01:21:11 Starting kickoff coordinator M2`) → M2 final (`01:34:52 FINAL DELIVERY: gate clear → cut release v1.1.0`).
- **`main() returned 0`**, **`Status: SUCCESS`**, Duration ~1h31m (5466.9s). Delivered app tree
  `agent/generated/netflix-web-r115/app/{backend,frontend,database}`.
- Planner chose 2 milestones this run, so `1.1.0` IS the final cumulative release (M1+M2 = complete app).
  Success criterion met: **≥2 progressive tags + final cumulative + rc=0**.
- **All three fixes validated e2e**: #566c (auth_ok=True, 0 auth-500), #566b (0 ui-page wedge; pages=14,
  blank=∅, hollow=False, login_wall=∅), #566 (0 genre-404 "NOT rejected" wedge in M2).
- The user-agent test loop ran throughout (BROWSER test-user + TEST-USER journey validation, `test_api`).
- Torn down cleanly (gen self-exited rc=0; keeper+monitor killed; 0 containers).

**Non-blocking advisory finding (for a future polish pass, NOT a blocker):** the M1 test-user journey showed
`POST /api/continue-watching → 400` (4/6 journey steps) — advisory for the milestone cut (didn't block 1.0.0),
but a real functional gap worth a follow-up (continue-watching likely needs a profile header/param).

**GIT: 3 fixes committed on `feat/netflix-generality-366-367`** — `3bb35b6` #566, `cbf673b` #566b,
`4e064f6` #566c (plus the earlier #561/#562/#563/#565). USER pushes (github 403 for agent). The gitignored
tests: `test_projected_nested_m2m_404_566.py`, `test_reconcile_frontend_pages_566b.py`,
`test_oauth_login_password_coercion_566c.py`.

**Trajectory (the whole arc):** r112 wedged on business_chain m2m scoping → #566; r113 wedged on ui-page
stale-read → #566b; r114 wedged on auth password coercion → #566c; **r115 delivered end-to-end.** Each run
surfaced exactly one framework false-positive/bug; fixing them in sequence converged to a clean multi-milestone run.

---

## UPDATE — 2026-08-07 (session 4): r114 — #566b VALIDATED; new framework auth-500 wedge FIXED (#566c)

**(historical) Read this FIRST; supersedes earlier updates where they differ.**

- **r114 launched with #566+#566b** (multi-milestone confirmed). Planner: **3 milestones** this time
  (`M1-foundation-auth-browse@1.0.0`, `M2-catalog-navigation-search@1.1.0`, `M3-personalization@1.2.0`).
- **#566b VALIDATED** ✅: the r113 ui-page stub-audit false-positive did NOT recur (0 `ui_page_unwired`
  the entire run). r114 got FURTHER than r113.
- **r114 WEDGED in M1 on a NEW framework bug**, torn down (user-approved; gen down, keeper+monitor killed,
  3 containers removed). #566 (genre-404, M2) still NOT reached e2e.
- **r114 root cause (framework-owned, team-confirmed)**: `POST /auth/login → 500` —
  `oauth_routes.py:373 auth_login: TypeError: unsupported operand type(s) for +: 'int' and 'str'`. The oauth
  template `oauth_as_templates/oauth_routes.py.tmpl` coerced email/username/tenant_id with `str(...)` but left
  `password = body.get("password") or ""` un-coerced (lines 333 register + 366 login), so a NUMERIC JSON
  password reached verify_user_password/create_user → `int + str` 500. Backend/verifier/orchestrator all
  flagged it framework-owned/unfixable-by-lanes; it blocked business_chain → heading to STUCK-ABORT.
- **FIX #566c (committed `4e064f6`, 1 unpushed — USER pushes)**: `password = str(body.get("password") or "")`
  in both handlers of `oauth_routes.py.tmpl`. Generalizable, no product literals; happy path unchanged;
  distinct from #555 (DB-readiness 503). Tests: `test_oauth_login_password_coercion_566c.py` (4, gitignored);
  full suite **1200 passed** (73 fails = pre-existing oauth_contract network tests, unrelated).
- **WATCH in r115 (possible downstream, NOT yet fixed)**: container logs also showed
  `POST /api/titles/{id}/rating → 400 null value in "value"` (projected-create may not bind `value`) and
  `POST /api/profiles → 404 profiles_user_id_fkey` (likely a cascade of broken auth → no valid user). The
  auth fix should unblock the FK cascade; the ratings null-value may be a separate projected-write bug.
- **PENDING**: user pushes #566c, then (their call) relaunch **r115**. Trajectory: r112 (business_chain m2m
  scoping) → r113 (ui-page stale-read) → r114 (auth password coercion) — each run gets further and surfaces
  ONE new framework false-positive/bug that we fix. Converging. STOP+report on any new wedge.

---

## UPDATE — 2026-08-07 (session 3): r113 (with #566) WEDGED on a NEW bug, root-caused + FIXED (#566b)

**Read this FIRST; supersedes the session-2 update and §0/§5/§8 where they differ.**

- **#566 pushed by user** (origin has #561–#566). r113 launched with #566 (multi-milestone confirmed).
  Planner: 2 milestones (`M1-auth-profiles-browse-core@1.0.0`, `M2-catalog-browsing-search-mylist@1.1.0`).
- **r113 FAIL-FAST ABORTED, rc=1, 0 releases** (~1h32m) — NOT r112's bug. Torn down (gen self-exited;
  keeper+monitor killed; 3 containers removed).
- **Proved working**: multi-milestone planning; M1 business surface complete (business_chain PASS, 14/14
  endpoints); self-heal fixed real M1 bugs (tenants 500, continue-watching profile header); browser test
  loop ran. #566's genre-404 NOT exercised (aborted in M1; genres are M2) → #566 valid but unvalidated e2e.
- **r113 root cause (NEW, generalizable)**: `deliverability_ui_page_unwired` STUCK-ABORT. The check audits
  the INTEGRATION tree (`deliverability.py:129`), but the frontend lane built the real 390-line
  `TitleDetailPage.jsx` in its WORKTREE; until a lane→integration merge landed the gate re-read the projector
  STUB for 7 cycles → FAIL-FAST (`orchestrator.py` `FWVAL_STUCK_ABORT_AFTER=7` `:164`; latch `:2905-2940`;
  raise `:1995-2004`). Abort fired ~1s AFTER the page flipped `app_wired=True` — a race (frontend filed a P0
  "framework FALSE POSITIVE").
- **FIX #566b (committed `cbf673b`, 1 unpushed — USER pushes)**:
  (a) `reconcile_integration_frontend_pages` (`heal_pipeline.py`, sibling to #324's seed reconcile) copies a
  REAL lane-worktree page onto integration when integration's is stub/fallback/missing; called in
  `deliverability._ui_page_wiring_blockers` BEFORE the audit read. Never clobbers a real page; reuses
  `frontend_audit` predicates; no product literals. (b) `orchestrator.py` latch: LAST-CHANCE reconcile before
  STUCK-ABORT when `deliverability_ui_page_unwired` is a blocker — surfaced unmerged work resets the counter
  (progress, not wedge). Tests: `test_reconcile_frontend_pages_566b.py` (7, gitignored). Full suite **1196
  passed**; 73 fails = pre-existing oauth_contract network tests (unrelated).
- **PENDING**: user pushes #566b, then (their call) relaunch **r114** to validate #566+#566b e2e. Note:
  r112→r113 each got FURTHER but hit a new deterministic-check false-positive (business_chain scoping →
  ui-page stub-audit). r114 may surface a third. STOP+report on any new wedge.

---

## UPDATE — 2026-08-07 (session 2): r112 launched, WEDGED, root-caused + FIXED (#566)

**Read this first; it supersedes §0/§5/§8 where they differ.**

- **r112 was launched** (multi-milestone confirmed via `/proc/<pid>/environ`: `ENVGEN_SINGLE_MILESTONE=0`).
  Planner chose **2 milestones** (agent-decided, generalizable): `M1-foundation-auth-browse@1.0.0`
  + `M2-catalog-nav-personalization-player@1.1.0` (no 1.2.0 — success is "≥2 tags + final + rc=0", not literally 1.2.0).
- **r112 WEDGED on M1** (~1h32m, no release cut) and was **torn down** (user-approved): gen + base-keeper +
  monitor killed, `podman rm -f -a` (0 containers). Token burn stopped.
- **Ground-truth wedge**: business_chain check `GET /api/genres/{missing}/titles returns 200, should be 404`
  never cleared → 4× failed `Framework validation attempt N/6` cycles, `dispatch queue FULL` ×1212,
  verifier blocked on 5 duplicate remediation tasks, LLM false-green (cancelled impl.page tasks).
- **Root cause (NOT #564)**: `/api/genres/{id}/titles` is MANY-TO-MANY (titles↔genres via `title_genres`),
  so `titles` has no `genre_id` FK → `_scope_fk` returned None → the projector's nested-collection branch
  was skipped → it fell through to the plain-collection branch (`db.query(Title).limit(100).all()`) → 200,
  unscoped, no parent 404. The backend's correct `@router.get` 404 fix was stripped by
  `_custom_route_overrides_projected` (projected-wins for nested child-resources, #528). #564 would NOT
  have fixed this (the framework already routes the blocker; the backend just couldn't override).
- **FIX #566 (committed `3bb35b6`)** in `route_projector.py` (+49 lines, generalizable, no product literals):
  new `_assoc_table()` (finds the join table from the contract FK graph) + a nested-collection branch for the
  `scope_fk is None` case that resolves the parent (404 if missing, keeps #288/#77 owner filter) and scopes
  the child list THROUGH the association table. Direct-FK + non-nested paths unchanged.
  **Tests**: 11 new `agent/tests/test_projected_nested_m2m_404_566.py` (gitignored/local) + 62 projector tests
  pass; **1189 total pass**. The 73 failures are pre-existing `ConnectionError` oauth_contract bundled_tests
  (need a live server; unrelated).
- **GIT: now 5 unpushed commits** (`ahead 5`): the four below **+ `3bb35b6` #566**. USER pushes (github 403 for agent).
- **PENDING (user chose to hold)**: push/merge #561–#566 first, THEN relaunch **r113** (same flags as §6b) in a
  later session to validate the fix end-to-end. r113 is NOT guaranteed to fully converge — #566 fixes the
  *observed* wedge; a latent downstream bug could stall elsewhere (STOP+report per guardrail).

---

## 0. TL;DR — THE ONE IMMEDIATE ACTION

**#565 (visual-scoping waste-cut) is DONE + committed (`fab4428`).** All prerequisite fixes
(#561, #562, #563, #565) are committed; working tree is clean; nothing is running. The single
remaining action is:

1. **Launch r112** — the full-stack multi-milestone validation run (exact command in §6b–6d).
2. **Monitor** it (cron template in §6d) and **watch for**: 3 milestone releases
   (`1.0.0`→`1.1.0`→`1.2.0`) + a final cumulative release + `main()` rc=0.
3. **Guardrail (USER INSTRUCTION):** if r112 wedges on a *new* bug, **STOP and report to the
   user before launching another run.** No open-ended grinding — each run is ~2–3h.

#565 was implemented by subagent `ab0e9cb649fafc744` and verified: **1180 tests pass**,
byte-identical on the final/single-milestone path (r107–r109 safe), safety guards in place
(empty/over-scope owned-set → falls back to full screen set). Per-milestone routes aren't stored
structurally, so #565 extracts them from milestone PROSE (generous/under-scope-biased; degrades
to no-scoping on a miss — safe by construction). If r112 shows the visual scoping mis-behaving,
that's the place to look, but it's advisory-only (cannot block delivery).

---

## 1. STANDING GOALS (from user `/goal`, enforced every turn)

- **PRIMARY (set 2026-08-07):** generated apps must be **functionally-complete + bug-free +
  UI-highly-similar + generalizable (泛化性)**. Mechanism the user named: a **user-agent test
  loop** (MCP + browser + API task construction/testing) that finds bugs + verifies
  completeness + iterates the app to bug-free. The old 0.65 visual gate is now SECONDARY.
- Every fix must **GENERALIZE** (no product literals; work for any app/contract, not
  Netflix-specific) and must **prevent token waste**.
- Memory: `~/.claude/projects/-home-haibotong/memory/` — see `goal-functional-correct-bugfree.md`,
  `netflix-multimilestone-delivery.md`, `netflix-partA-ceiling-is-api500.md`, and `MEMORY.md` (index).

---

## 2. CURRENT SUBTASK (what this session was doing)

Validating **multi-milestone delivery** for Netflix (task #88): the M1→M2→…→final-cumulative-release
path that ALL prior Netflix runs skipped (they ran single-milestone). User asked
"多阶段的milestone+delivery，最终release呢" and approved "Fix wedge + validate multi-milestone".

**Most recent user decision (AskUserQuestion, 2026-08-07):** *"Relaunch r112, validate
end-to-end"* — launch a fresh multi-milestone run with **#563 + the visual-scoping waste-cut**;
STOP+report if a new bug wedges. (User did NOT choose the riskier #564 hardening.)

Last user message: **"继续"** (continue), then a request for this handoff (context pressure).

---

## 3. RUNTIME STATE RIGHT NOW

- **No generation running.** r110 (killed — flag bug) and r111 (killed after diagnosis) are down.
  `ps -eo cmd | grep "[.]venv/bin/python -m env_generator"` → 0. `podman ps -q` → 0.
- **No active crons.** (`CronList` → none. The r110/r111 monitor crons were deleted.)
- **Base images present** (node:20-alpine, nginx:alpine, postgres:16, python:3.11-slim-bookworm).
- **Providers UP**: vertex `:8790` (real /v1/messages call OK; HTTP 404 on `/` = up),
  relay `:19080` (HTTP 400 on `/` = up). The launch script does its own cert-outage guard.
- **Subagent `ab0e9cb649fafc744` is running** — implementing #565. Resume/continue it with
  `SendMessage(to: "ab0e9cb649fafc744", ...)`. Do NOT Read its output-file (context overflow).

---

## 4. GIT STATE

- Branch: **`feat/netflix-generality-366-367`**, HEAD **`fab4428`**. Working tree CLEAN.
- Remote: `github.com/vaibackup/forgingground-gen`. **Agent egress to github is 403-blocked** —
  the USER pushes from their own shell. Their intent: push, then merge to main themselves.
- **4 UNPUSHED commits** (`ahead 4` of origin) — these are THIS validation session's fixes:
  - `fab4428` **#565** non-final-milestone visual-scoping (advisory judge scores only
    milestone-owned screens; byte-identical on final; 1180 tests pass). Cuts ~1h/non-final-milestone waste.
  - `f742221` **#561** thin-slice kickoff wedge (empty-slice tolerance + cumulative-contract
    predicate synth + serialize-drain) — unblocks multi-milestone M2+ kickoff.
  - `79839da` **#562** `ENVGEN_SINGLE_MILESTONE=0` was ignored (`bool("0")==True` truthy trap;
    now parses `1/true/yes/y/on` = single, else multi). This is why r110 ran single-milestone
    despite `=0`. Also `launch_netflix.sh:47` now respects the override.
  - `b8684b0` **#563** deliverability `app_root` fallback missed the `/app` segment → read a
    stale 6-row bootstrap seed → "only 6 structured rows" PERMANENT false-positive. Fix in
    `tool_bundles.py::_bundle_deliverability_tools` (descend into `<root>/app` when it has a
    real `backend/`; byte-identical for a correctly app-pointed app_root).
- **Uncommitted:** none (working tree clean). `agent/tests/test_visual_milestone_scope_565.py`
  is the new #565 test — GITIGNORED by design, present locally only.
- Commit convention: `git add -u` (+ explicit add for NEW tracked modules). `agent/tests/` is
  GITIGNORED by design (dev suites local-only); new runtime modules ARE tracked.
- Tell the user: **4 commits ready to push now** — `f742221` (#561), `79839da` (#562),
  `b8684b0` (#563), `fab4428` (#565).

---

## 5. WHAT r111 PROVED (the multi-milestone story)

Run r111 (`ENVGEN_SINGLE_MILESTONE=0`) with #561+#562, then hot-fixed live with #563:

### ✓ VALIDATED (working)
- **#562**: planner emits **3 milestones** — `M1-auth-profiles-browse-core@1.0.0`,
  `M2-category-pages-and-search@1.1.0`, `M3-personal-my-list-ratings-continue@1.2.0`.
- **#561**: M1 kickoff `feature_inventory.flows empty` escalation self-recovers via
  `synthesize_fallback` → "Kickoff FINALIZED (7 endpoints + 5 tables + 56 tasks)". No hard abort.
- **M1 business surface functionally complete**: 13/13 api_smoke green, 44/44 chain steps,
  137-row seed, zero bugs.
- **Self-healing remediation WORKS**: the backend auto-fixed a real `GET /api/my-list` needs
  `?profile_id=` bug (P1 `task_97459b164e`) via the verifier's business_chain-FAIL broadcast.

### ★ KEY ARCHITECTURE (non-obvious — took 2 subagent passes to establish)
- **The per-milestone release cut is ALWAYS FRAMEWORK-DRIVEN, never the LLM.**
  `_maybe_framework_deliver` (`orchestrator.py:2797`) cuts the tag at `orchestrator.py:3500-3509`
  (`ch.create_release` → the `codehub_releases.json` version key), called ~every 60s from the
  per-milestone loop (`orchestrator.py:1904`, and `:1759`). The loop is
  `for _m_idx, _milestone in enumerate(milestones, start=1)` (`orchestrator.py:1232`).
- **`deliver_project`/`submit_retro` are ABSENT from the orchestrator's non-final tool surface
  BY DESIGN** (`step_pipeline/tooling.py` `withhold_delivery_before_final_milestone`, anti-retry
  #361). So "orchestrator has no deliver tool" is a **red herring**, NOT a blocker. Do NOT
  "fix" it by surfacing the tool on non-final milestones (it rejects by precondition; regresses #361).
- **The false-green trap (THE convergence bug):** the LLM's `deliverability_check` =
  `compute_deliverability` (a SUBSET: ui wiring, seed, stubs, invented-fields). The deterministic
  cut gate = `validate_delivery_gate` (`delivery_gate.py:1292`, a SUPERSET adding
  `business_chain_*`, `verification_checklist`, api/ui `_smoke`, `contract_alignment`,
  completeness). So the orchestrator logs **"deliverable, 0 blockers"** (subset green) while the
  real cut keeps DECLINING on a superset-only check → **"Framework deliver declined: delivery
  gate has N failed check(s): [...]"** (`orchestrator.py:2832`). In r111 the last real
  cut-blocker was `business_chain_failing` (the my-list bug), which self-healed at ~13:18.
- Non-final milestones SKIP the page-build block (`orchestrator.py:3059`, `and _is_final_milestone`)
  and the visual-fidelity block (`orchestrator.py:3134`, `and _is_final_milestone`) — **M1 visuals
  are ADVISORY only** (they do NOT block M1 delivery; they DO churn the frontend — see #565).
- Non-final milestone has **NO post-loop create_release backstop** (final-only,
  `orchestrator.py:2102`) — if the in-loop gate never clears, it wedges with no fallback.

### ⚠ Likely-premature teardown
I killed r111 at ~13:20–13:26, and the backend had fixed the last real blocker (my-list) at
13:18 → "deliverable, 0 blockers" at 13:19. **M1 may have been minutes from cutting 1.0.0.**
That is the basis for the user's choice to just relaunch (r112) and watch — the machinery
looked close to converging once #563 removes the phantom-seed confusion.

---

## 6. THE PROCEDURE TO RESUME (after #565 lands)

### 6a. Commit #565 (after reviewing the subagent diff + green tests)
```
cd /home/haibotong/forgingground-gen
git add -u   # + explicit add for tests/ if the new test should be kept LOCAL (it's gitignored)
git commit -m "#565 non-final-milestone visual-scoping: advisory judge scores only milestone-owned screens"
```

### 6b. Launch r112 (EXACT command — matches how r110/r111 were launched)
```
cd /home/haibotong/forgingground-gen
ENVGEN_SINGLE_MILESTONE=0 FW_DEBUG=1 ENVGEN_VISUAL_MIN=0.65 \
  nohup ./launch_netflix.sh netflix-web-r112 > gm_netflix-web-r112.launch.log 2>&1 &
sleep 22
grep -iE "started pgid|ABORT" gm_netflix-web-r112.launch.log
```
- "started pgid=NNN" is authoritative. The gen main is `python -m env_generator.llm_generator.main
  --name netflix-web-r112`. NOTE: `pgrep -f "netflix-web-r112.*main --provider"` also matches the
  base-keeper's own command string (self-match false positive) — identify the REAL gen with
  `ps -eo pid,cmd | grep "[.]venv/bin/python -m env_generator" | grep netflix-web-r112`.

### 6c. Base-image keeper (bases get evicted mid-run; re-pull WITHOUT proxy)
```
nohup bash -c '
while pgrep -f "env_generator.llm_generator.main.*netflix-web-r112" >/dev/null 2>&1; do
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  for img in node:20-alpine nginx:alpine postgres:16 python:3.11-slim-bookworm ghcr.io/astral-sh/uv:python3.11-bookworm-slim; do podman pull "$img" >/dev/null 2>&1; done
  sleep 300
done' > /home/haibotong/forgingground-gen/r112_base_keeper.log 2>&1 &
```

### 6d. Monitor cron (set via CronCreate, recurring `10,40 * * * *`)
Prompt should check, token-leanly: (1) liveness + etime; (2) release tags:
`python3 -c "import json;d=json.load(open('agent/generated/netflix-web-r112/shared/hubs/codehub_releases.json'));print([k for k in d if k!='_meta'])"`
— want progressive `1.0.0` (M1), `1.1.0` (M2), `1.2.0` (M3); (3) the REAL blocker if stalled:
`grep "Framework deliver declined: delivery gate has" gm_netflix-web-r112.log | tail`;
(4) `grep -c UndefinedColumn` (want 0); (5) advance signals: `grep -iE "advancing to milestone|_await_prior_milestone"`.
**On terminal:** MULTI-MILESTONE VALIDATED = ≥2 release tags + final cumulative release +
`main()` rc=0 → celebrate + teardown (`podman rm -f -a`; kill keeper; CronDelete). On a NEW
wedge → STOP, diagnose ground-truth-first, report to user BEFORE another run.

### 6e. What "success" looks like
`codehub_releases.json` with MULTIPLE version keys (`1.0.0`, `1.1.0`, `1.2.0`), the last tag =
the final cumulative release containing the complete app, and the run process exits rc=0.
The delivered app tree is `agent/generated/netflix-web-r112/app` (backend/, frontend/).

---

## 7. DIAGNOSTIC PLAYBOOK (if r112 stalls — how r111 was cracked)

The delivery-gate wedges present as the orchestrator idling on "deliverable, 0 blockers" while
NOT cutting a release. GROUND-TRUTH-FIRST steps that worked:
1. **Real blocker** = `grep "Framework deliver declined: delivery gate has" gm_netflix-web-rN.log | tail`
   (the deterministic superset gate; NOT the LLM's "0 blockers").
2. **Seed false-positive?** find ALL `seed_data.json` under `agent/generated/netflix-web-rN/`
   and count dict rows per file. The gate reads `<app_root>/backend/seed_data.json`; a stale
   `<worktree>/backend/seed_data.json` (no `app/`) with ~6 rows = the #563 symptom. The REAL
   seed (137 rows) lives at `<worktree>/app/backend/seed_data.json`.
3. **business_chain FAIL?** check whether it's a REAL bug (endpoint/frontend contract) vs a
   chain-generation gap (chain doesn't pass a required query param). r111's was real
   (my-list needs `?profile_id=`) and the backend self-healed it.
4. Delegate deep code tracing to a subagent (preserve main context). The subagent
   `ab0e9cb649fafc744` already holds deep context on `orchestrator.py`, `delivery_gate.py`,
   `deliverability.py`, `visual_fidelity.py`, `tool_bundles.py`, `step_pipeline/tooling.py`.
5. **Narration ≠ marker:** agents narrate "M1 delivery complete / Awaiting M2" — that is NOT
   the release. The ONLY authoritative delivery marker is a version key in `codehub_releases.json`
   (+ `main()` rc=0). Never trust LLM DELIVER_PROJECT narration.

---

## 8. OPEN / CANDIDATE FIXES (NOT applied; user-gated)

- **#564** (NOT applied — user chose the minimal path): align the LLM `deliverability_check`
  signal to the `validate_delivery_gate` superset so the orchestrator stops idling on false-green
  and routes the real blocker (business_chain/checklist/smoke) to its owner. Subagent judged it
  SAFE (tightens the LLM signal, never loosens the cut; byte-safe for final delivery). Consider
  ONLY if r112 wedges on false-green non-convergence. Pointers: `deliverability_tools.py:35,53`.
- `ENVGEN_MILESTONE_SCOPED_GATE` (default OFF): if future-milestone endpoints/tasks ever get
  pre-registered, a non-final milestone could be permanently red on `incomplete_required_tasks`;
  enabling this env flag scopes the gate to the current milestone. Watch for it in r112.
- Minor Part-A UI variance (my_list/player/title_detail between-run) — not a blocker.

---

## 9. ENVIRONMENT CHEAT-SHEET

- Host is **code + can run gens** (`launch_netflix.sh`). cwd for the engine = `<repo>/agent`,
  `PYTHONPATH=<repo>/agent`. Run tests from `agent/`:
  `PYTHONPATH=. ../.venv/bin/python -m pytest tests/<file> -q`.
- Repo root: `/home/haibotong/forgingground-gen`. venv: `<repo>/.venv`.
- Launch inputs: `<repo>/.netflix_desc.txt`, `<repo>/.netflix_designinput.txt` (present).
- Model: `claude-opus-4-7` via vertex proxy `http://127.0.0.1:8790`. Providers: vertex `:8790`
  (404 on `/` = up), relay `:19080` (400 on `/` = up).
- Base images: `docker.io`/`ghcr.io` are agent-egress-blocked; the internal VMVM mirror serves
  them if you `unset http_proxy https_proxy` before `podman pull`. See memory
  `base-images-pull-without-proxy.md`.
- GitHub egress 403 for the agent → USER pushes. See memory `github-egress-blocked-for-agent.md`.

---

## 10. DISCIPLINE NOTES (things the user cares about)

- **GROUND-TRUTH-FIRST**: read the actual render/log/registry/verdict; overturn theories with
  evidence. Two of my hypotheses this session were REFUTED by ground truth (the visual-gate
  "stuck counter" theory, and the "missing deliver tool" theory). Verify before fixing.
- **Prevent token waste**: don't over-poll healthy runs; defer to cron intervals (~30 min).
  Don't keep a wedged run alive burning tokens once diagnosis is complete.
- **Delegate deep reading to subagents** to preserve main context.
- **Don't fabricate subagent results** — wait for the completion notification.
- **STOP+report before another 2–3h run** if r112 hits a new wedge (explicit user instruction).
- Single-milestone delivery is the PROVEN-reliable path (r107 0.7483, r108 0.68, r109 0.6817 —
  all rc=0 + release 1.0.0, R4-enforced, tenant-400=0, auth-500=0, continue-watching writable).
  Multi-milestone is the NET-NEW validation in flight.

---

## 11. TASK TRACKER

Task **#88** (`Multi-milestone Netflix validation`) holds the live status (in_progress). Its
description has the latest micro-state. Other pending tasks (#42, #62–66, #82–83) are older
Part-A/business-chain levers, lower priority than the multi-milestone validation + primary goal.
