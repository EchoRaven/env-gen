# Trajectory review round 2 — findings (2026-07-29)

Branch `feat/pipeline-opt-6`. Baseline for this round: `c9224a0`; shipped since:
`623726d` (#330), plus #331 (below). 6 parallel read-only review agents over
r91/r92/r93 (+ r94 live) and the non-tiktok corpus.

**Every P0 below was re-verified by me in source before being written down.**
Findings I have NOT personally verified are marked `UNVERIFIED`.

---

## THE HEADLINE: why the delivered UI is not similar to the reference

The user's #1 complaint has a causal chain, and it is entirely framework-side.
Reference implies 11-13 screens; shipped app carries 3-8.

| run | ref screens | measured screens | ui_pages in M1 | real pages at end |
|---|---|---|---|---|
| r91 | 11 | 11 | 4 | 5 (+4 ghost dup routes) |
| r92 | 11 | 11 | 4 | 8 (+11 `StubPage` routes) |
| r93 | 11 | 11 | 3 | **3** |
| r94 | 11 | 11 | 4 | (live) |

1. **UI-1 (P0) `#225` design-screen page seeding is a total NO-OP.**
   `frontend_scaffold.py:1929-1934` skips any screen whose `route` is missing
   (`if not route.startswith("/"): continue`). `design/design_system.json` in ALL
   FOUR runs has screen keys `['name','reference','layout','layout_metrics','components']`
   — no `route`, no `kind`. So 11/11 screens are skipped.
   `grep -c "#225 registered design-screen" gm_tiktok_r9{1,2,3,4}.log` -> **0,0,0,0**.
   Cause: the run takes the AGENT path, and `build_design_analyst_briefing`
   (`design_prep.py:666-686`) never asks for kind/route/requires_auth; those fields
   only exist in the unused single-shot fallback prompt (`design_prep.py:309-317`)
   and are optional there. `complete_design_system` has no deterministic backfill.
   Collateral: `visual_fidelity.load_screen_classifications` returns `{}` every run,
   so FIX #132's authoritative reference->route map silently degrades to filename
   heuristics.
   FIX: deterministic route/kind floor in `complete_design_system`; add the fields to
   the analyst briefing as required output; make `missing_design_screen_pages` fall
   back to `slug(name)` instead of `continue`; hard-assert
   `len(ui_pages) >= len(screens where kind==page)` at kickoff-finalize.

2. **UI-2 (P0) the milestone planner functionally DELETES 8 of 12 screens.**
   `reference_materials.py:550` states the invariant "every screen appears in exactly
   one milestone" but `plan_milestones` (:581-628) validates only name/version/
   non-empty description. All 4 runs split 12 screens 4/4/4 across M1/M2/M3 — and
   **0 of 4 runs ever authored an M3 page** (r91 died on the 21600s wall-clock cap with
   M1 still active; r93 M1 active; r92 M2 active). A screen assigned to M2/M3 has an
   empirical ~0% chance of being built.
   FIX: decouple SCAFFOLDING scope from IMPLEMENTATION scope — register a ui_page and
   project a routed page component for EVERY `kind==page` screen at M1; milestones then
   govern only which page gets FILLED. A truncated run then ships N partially-filled
   real screens instead of 3 real + 9 absent. Also validate slice-union == spec screens.

3. **UI-3 (P0) the visual-fidelity gate PASSES on zero screens.** VERIFIED.
   `visual_fidelity.py:957-958`: `_blocking = [r for r in results if not r.get("advisory")]`
   then `passed = all(r["passed"] for r in _blocking)` — `all([]) is True`.
   Live r92, verbatim: `Visual fidelity PASSED (login_modal=0.08): all 0 screens >= 0.65
   [advisory (overlay, non-blocking): login_modal(0.08)]`. The only capturable screen
   scored 0.08 and the gate said PASSED. `design/visual_gate/` holds 1 file (r93) / 3
   (r91,r92) out of 11 references. The more screens are MISSING, the easier the gate
   passes — the denominator is judged screens, not measured screens.
   FIX: compute over the measured set; an unreachable measured page screen scores 0 and
   BLOCKS with remediation "author this page"; require >=1 blocking screen for a PASS.

4. **UI-4 (P1) framework clobbers LoginPage/SignupPage from a hardcoded LIGHT template
   every tick.** `frontend_scaffold.py:3217` overwrites auth pages unconditionally;
   `_AUTH_PAGE_TEMPLATE` (:1688-1737) is fixed light (`bg-zinc-50`,`bg-white`,`bg-blue-600`)
   and takes NO `design` argument. Fights the #209 darkify pass every tick: r92 logged the
   14-swap darkify **57 times**, r91 10x. Final on-disk state loses the race — r93 routes
   `/login` to a white card with a blue button against a black/#FE2C55 reference. The lane's
   visible workaround was to author a SEPARATE `LoginModal.jsx` with the correct colors.
   FIX: thread `design` into the template (emit measured tokens, not literal zinc/blue);
   replace unconditional overwrite with a content contract (overwrite only if the auth
   assertion fails) so the tick loop converges.

5. **UI-5 (P1) measured palette projection drops 70-90% of measured tokens.**
   `frontend_scaffold.py:3463-3484` emits ONLY `bg`, `accent`, `accents.*`; `_HEX_RE_208`
   (:3445) additionally rejects `rgba(...)` which r93/r94 use for text/border/divider.
   Dropped every run: surface, surface_2, elevated, chrome_pill, hover, border, divider,
   text, text_2, text_3, text_muted, input_bg, chip_bg... `type_scale`/`radius_scale`/
   `shadow_scale` are measured and NEVER projected. Brand red is model-dependent:
   r91/r92/r93 shipped `#ea445a`, r94 shipped the correct `#fe2c55` — same references,
   same framework.
   FIX: project every colour-valued palette key (hex OR rgb/rgba/hsl); add fontSize/
   borderRadius/boxShadow from the measured scales; deterministic
   `accent = accent or brand_* or accents.red`.

6. **UI-6 (P1) 5 staged brand font files are referenced by NOTHING.** VERIFIED.
   `public/assets/fonts/` holds TikTokDisplayFont-Bold, TikTokFont-{Bold,Regular,Semibold},
   TikTokSans-VF in every run; `grep -rl "font-family|fontFamily|@font-face"` over
   `src/` + `index.html` returns **0 files**. Staging was implemented, wiring never was.
   FIX: emit `@font-face` per staged file in `render_measured_base_css` + set
   `body{font-family}` + mirror into tailwind `fontFamily.sans`. No fonts staged => no-op.

---

## P0 CORRECTNESS — framework-projected code that is wrong

7. **C-1 (P0) `served_routes()` cannot see ANY lane-authored route — the r91 killer.** VERIFIED.
   `backend_audit._included_modules` (:74) resolves ONLY `from <mod> import router as <name>`
   plus `include_router(<Name>)`. The framework's OWN emitted `main.py`
   (`backend_skeleton.py:849-867`) mounts via
   `import custom_routes as _custom_mod` (a plain `ast.Import`, never recorded) and
   `for _custom_router in _routers: app.include_router(_custom_router)` (a loop variable,
   not statically resolvable). So `_included_modules` returns `{}` for the framework's own
   file — 100% blindness in r91/r92/r93.
   Consequence: `sync_endpoint_statuses` takes the `not is_served and status=="implemented"`
   branch and silently demotes implemented->defined, attributed to "orchestrator". r91:
   26 lane routes declared, 0 seen; the backend re-registered the same 4 auth endpoints
   **56 times** over 5h41m, announcing "code was already there" ~9 times, and the run died
   on the wall-clock cap with them still `defined`. `grep -c "ENDPOINT LIFECYCLE"` = 0 —
   every demotion was silent.
   This is the iron law violated inside the framework: #127 fixed router MOUNTING at runtime
   and broke the STATIC auditor that reads the same file.
   FIX (preferred): ask the app — after boot, read `GET /openapi.json` (FastAPI always serves
   it) and use paths x methods as the code-truth surface; provider-agnostic and immune to any
   mounting idiom. If a static path must remain, handle `ast.Import` + loop-bound names, and
   add a REGRESSION TEST that runs `served_routes()` against the skeleton main.py THE FRAMEWORK
   ITSELF EMITS and asserts it sees the custom routes. Also: log every demotion at WARNING.

8. **C-2 (P0) owner-scoping is inferred from column NAMES, not the contract.** VERIFIED.
   `route_projector.py:44-51` `_OWNER_FK_NAMES` includes `account_id` and `sender_id` as
   "the authenticated caller" — a social-graph vocabulary. On a finance schema
   `transactions.account_id == user.id` compares an account id to a user id: both ints, HTTP
   200, canonical envelope, so `business_endpoints_reachable` + `_correct_shape` + `_shape_violation`
   ALL PASS while the user sees another account's ledger. On mail, `messages.sender_id` makes
   the INBOX filter to what the caller SENT.
   `_owner_fk` (:606-617) already contains the correct mechanism (FK target == users) but only
   AFTER the name list, so the name always wins.
   FIX: resolve by FK TARGET (`fks[col] == "users"`); use the name list only as a tiebreak among
   columns that genuinely reference the users spine; reject a name-list column whose declared FK
   points at a different table.

9. **C-3 (P0) `#288` primary-content exemption leaks private parents.** VERIFIED.
   `route_projector.py:775-781` skips the parent owner-filter when
   `parent_table == _primary_content_model(models)[0]`, and that model is elected BY SHAPE ONLY
   (:383-402 — non-spine + has a timestamp + prefers an owner FK + most columns). In a
   private-content app the private parent is normally the richest table, so it wins and loses
   its filter -> any authenticated user reads/writes another user's nested rows.
   The guard test is VACUOUS: `test_route_projector_nested_isolation.py` fixtures have no
   timestamp column, so `_primary_content_model` returns None and the #288 branch is unreachable.
   FIX: key the exemption on an EXPLICIT public declaration, not on shape. Add `created_at` to
   the existing fixture so the guard actually exercises the branch.

10. **C-4 (P0) `#320` silently neutered the `#271`/`#315` leak protection.** VERIFIED.
    `route_projector.py:1279-1281` sets `_owner_scoped = False` on an explicit
    `auth_required=False`, which then flows into `auth = resolve_endpoint_auth(...) or _owner_scoped`
    at :1293 — killing BOTH the force-auth AND the owner row-filter. The comment block at
    :1283-1291 still asserts the OPPOSITE invariant ("This DELIBERATELY overrides even an explicit
    auth_required=False ... owner_scoped wins here"), added after a real r58 leak. Code and its own
    comment now contradict each other: a framework-internal heal tug-of-war.
    NOTE: "public" and "owner-scoped" are genuinely contradictory (an owner filter needs an actor).
    The honest fix is to treat it as a CONTRACT CONFLICT and fail loud with an actionable
    remediation, not to silently pick a side. CAUTION: naively restoring `or _owner_scoped`
    re-breaks the tiktok public feed that #320 was fixing.

11. **C-5 (P1) dual-source seed merge leaves dangling FKs in every run.** UNVERIFIED (agent-computed
    against the runs' own artifacts). `backend_skeleton.py:1856-1895` `_load_rows()` replaces
    parent tables WHOLESALE from the framework dataset while leaving lane-authored child rows
    keyed to the discarded ids. r91 `likes.video_id` dangling for `['vid_001',...]` (string ids vs
    the dataset's integer ids); r93 `comment_likes.comment_id` dangling `[1,3,4,6,8,11,19,21]`,
    `messages.conversation_id` dangling `[1..6]`. Rows either fail to insert (leaving the table
    empty) or attach to the WRONG parent. Reads to a lane as "seeding is broken" and burns heal cycles.
    FIX: referentially-closed merge — assign explicit ids to id-less parent rows first, then for
    every `<singular_parent>_id` child column coerce type and remap unknown values into the parent
    id set; hard-fail the seed gate on any remaining dangling FK.

---

## COST — measured, caching-independent

12. **Cost-1 (P0) ~37% of ALL LLM calls return bare `ACTION_STATUS: continue` and nothing else.**
    r91 5,494/14,597 (37%, 598M of 1,491M ctx tokens); r92 3,597/8,996 (39%); r93 1,617/4,339 (37%).
    Non-orchestrator lanes measured separately: 60-68% of lane tokens are no-tool-call responses.
    Worst streaks: r91 Backend **37 consecutive** full-context calls, 0 tool calls, 6.30M tokens in
    4.5 minutes, with the model narrating `'MAKING TOOL CALL NOW:'`, `'Now.'`, `'I MUST call a tool.
    Doing so:'`. `action.py:331-340` treats `ACTION_STATUS: continue` + zero tool calls as legitimate
    progress; the only backstop (`no_action_tool_steps >= 12`, :528) never fires for background lanes,
    and a `finish()` counts as a tool call so it never trips either.
    FIX: per-step consecutive-no-tool-stage counter — nudge at 2, force `should_stop` at 3; stop
    counting `continue`-with-no-tool-calls as progress; log `no_tool_calls` (currently 0 log lines).
    NOTE: this is MUCH broader than #330 (which fixed one dead stage for one role).

13. **Cost-2 (P0) ~30% of all LLM calls pass `tools=[]`** and are structurally incapable of acting:
    `action.py:189` round-plan (once per action round, up to 15/step), `stages.py:183` planning
    (once per step), `stages.py:73` retrieve_context boolean. r91 = 7,041 such calls = 32% of all
    requests, 1.935G of 6.203G request chars. The planning stage's only output is `MODE: team|direct|stay`
    — `grep -c "MODE: team"` over r93 = **0**, and `delegate_team` tool calls = 0 across all
    non-orchestrator lanes in all 3 runs. The decision it exists to make is never taken.
    FIX: run the round-plan on round 0 only; skip the planning stage entirely for profiles that
    cannot enter team mode (profile-gated, not hardcoded).

14. **Cost-3 (P1) generalize #330's allowlist to the other dead stages.** Tool calls by category
    across all 3 runs: Design Analyst `communicate`=0, Browser Test-User `communicate`=0, MCP
    Test-User `communicate`=0, Verifier `edit_code`=141/4,540 (3.1%). Machinery + orphan guard
    already shipped in #330; only config is needed. MUST re-home categories (see #330's rationale).

15. **Cost-4 (P1) force-offer floor (30-52 tools/stage) overwhelms the 8-10 slot ranker budget.**
    `base.py:449-471` resolves to communicate=33, edit_code=35, run_checks=30, deliver=46, action=52
    while `stage_limit` is 8/10. ~38 tools/call ~= 6.6k tokens of schema per call ~= 97M tokens/run.
    Never called by any lane in 3 runs despite being force-offered: `zoom_compare`, `crop_reference`,
    `compare_with_screenshot`, `spawn_agent`, `create_team`. HIGHEST REGRESSION RISK — this set exists
    to prevent wedges; any trim must be precondition-driven and re-checked with
    `detect_orphaned_tool_offerings`. Do LAST.

---

## GATE / SIGNAL DEFECTS

16. **G-1 (P1) `validation:ui_flow` is a one-way ratchet — a flow that ever passed can never fail.**
    UNVERIFIED. Records scatter across 4 free-form `pr_id` namespaces (`main`, `agent/verifier`,
    `page:<flow>`, `page:ui:<flow>`) and `flow_coverage.py:300-336` collapses them "passed-wins"
    (`if prev == "passed": continue`). One stale success in ANY namespace pins the flow green forever.
    r91: 88 ui_flow records for 4 flows, with documented success->failure->success flip-flops, while
    the gate kept reporting "4 critical UI flows missing". Distinct mechanism from #327.
    FIX: canonicalize `pr_id` for any `validation:*` name; replace passed-wins with latest-wins by
    `recorded_at` + staleness window. A gate that can only ratchet green cannot detect regression.

17. **G-2 (P1) `deliver_project` is offered when the framework already knows it will reject it.**
    UNVERIFIED. 53 attempts across 3 runs, **0 successes**; 41 rejected by the milestone guard alone —
    a condition known at offer time (`_is_final_milestone` is already stamped). The 4-item checklist is
    self-asserted by the LLM (39/53 calls asserted all-true while the live gate reported
    `['business_chain_failing','deliverability_ui_flow_missing','incomplete_required_tasks']`).
    `force_deliver` is declared in the schema and bound in the signature and **never read in the body** —
    the framework handed the model a fabricated affordance.
    FIX: filter the tool out of the always-include set when `_is_final_milestone` is false; delete the
    self-asserted checklist and compute it from hub state; delete or implement `force_deliver`.

18. **G-3 (P1) the per-stage ranker hides GRANTED tools; 291 "tool not available to me" statements.**
    UNVERIFIED (r91 151, r92 84, r93 56). r93 Orchestrator: "I don't have `deliverability_check` in my
    tool list" — then called it 36 times over the next hour. r93 Frontend: "`workhub_comment` ... the
    integrity check suggests it but it's not actually available" — it is granted in agents_config.yaml
    AND `commit_gate.py:127` unconditionally recommends it.
    FIX: exempt `ACTION_STAGE_ALWAYS_INCLUDE` from the `stage_limit` truncation (force-offered tools
    should occupy slots ABOVE the cap); filter every remediation template's tool names against the
    role's actual grant.

19. **G-4 (P1) typed kickoff declares silently discarded when the gateway stringifies an int.**
    UNVERIFIED. All 48 `kickoff_declare_predicate` calls across runs passed `milestone_index` as a
    STRING; `workhub/service.py:1222-1231` does a strict `isinstance(int)` and raises. r92 Verifier:
    10/10 rejected, no retry -> **M2 ended with zero declared predicates** (a milestone verified against
    nothing). r91 "recovered" by dropping the param, so 19 predicates bound to no milestone. The error
    text names `add_meeting_decision`, a tool the verifier cannot see.
    FIX: generic JSON-Schema-driven scalar coercion at the tool-arg boundary (the repo already does this
    for seed data in #213); re-label downstream errors with the CALLED tool's name.

20. **G-5 (P1) repeated-identical-failure storms.** UNVERIFIED. ~90 identical `test_api 401` errors
    across runs (the error text lectures but nothing supplies a token); 74 `Connection refused` (no
    framework liveness signal); 35 `chain rejected` (404-path verification is legitimate but
    inexpressible); 60 `browser_fill` timeouts on guessed selectors.
    FIX: circuit-breaker in the tool dispatcher on the Nth byte-identical `(tool,args,error)` triple,
    replacing the result with a directive naming the specific alternative; return candidate selectors
    in a fill/click miss; wrap `browser_eval` in an async IIFE.

---

## GENERALITY — the framework is now tiktok-shaped

Corpus: 83 run dirs — tiktok **62 (75%)**, instagram 18, googlemaps 3. Every fix >= #276 cites a
tiktok run as its evidence.

21. **Gen-1 (P0) computed/aggregate routes get a hardcoded empty stub, then a HARD delivery block.**
    `route_projector.py:357` `_FEED_SHAPED_TOKENS = ("feed","explore","timeline","reels","discover","stream")`
    is the ONLY rescue for a path naming no table; `backend_audit.py:450-452` `_AGG` is the ONLY escape
    from the #173 hard blocker. Both are pure social vocabularies.
    Measured against the REAL gmrun4 contract (`/api/directions`, `/api/places/autocomplete`,
    `/api/places/search`, `/api/transit/departures`, `/api/users/{id}/contributions`): **0/5 on both
    lists**. Delivered `main.py` literally contains
    `@app.get("/api/directions") def ...: return {"items": [], "total": 0}`.
    Instagram run80 and tiktok score **100%** on the same vocabulary. NO googlemaps business table has
    any timestamp column, so `_primary_content_model` returns a 5-column join table (gmrun4) or `None`
    (gmrun7).
    The #173 remediation tells the lane to "declare the backing table" — unactionable for a computed
    endpoint. gmrun7 is literally named `2of3-forcedeliver`.
    FIX: replace both vocabularies with a DECLARED signal (`kind="computed"` / `backing_table: null`):
    never emit a fake list stub, and exempt from #173 by declaration rather than by word list.

22. **Gen-2 (P1) `{item}/{items}` is now a HARD delivery gate on a 2-word vocabulary.**
    `delivery_gate.py:744-749` concedes the projector "hardcodes that envelope and IGNORES any other
    key", then :1328-1330 BLOCKS the lane for declaring anything else. In both gmaps runs
    `GET /api/directions` (a singleton route plan) failed `business_endpoints_correct_shape`; the
    backend "fixed" it by returning an empty list — verbatim: *"ensure a consistent empty list is
    returned ... aligning with the expected shape for successful validation"*.
    FIX: allow `envelope: "raw"` + a response schema; validate against the schema, not a 2-word allowlist.

23. **Gen-3 (P1) `visual_fidelity._ROUTE_KEYWORDS` is a 10-entry social catalog.** The route assignment
    is guarded by `r in known` but the **auth flag is not** (:262-263), so every gmaps `*search*`
    reference is forced `requires_auth=True` by the `/explore` row and screenshotted logged-out ->
    similarity ~0 -> blocking `visual.needs_revision`. Non-social stems match nothing and are SILENTLY
    SKIPPED. The empty-state remediation copy emitted into a Google Maps run literally reads
    *"a reels page needs video posts"*.
    FIX: delete `_ROUTE_KEYWORDS`; use design-prep's per-screen classification (already authoritative)
    + the generic filename<->route match; report unmapped screens instead of guessing, and count them
    against gate coverage.

24. **Gen-4 (P1) auth is assumed universally** — 4 independent mechanisms hard-require a login:
    `frontend_scaffold.py:3114-3130` force-injects /login+/signup and DROPS lane pages on those routes;
    :3738-3746 patches global fetch to redirect on ANY 401; `frontend_audit.py:880-883` ->
    `deliverability.py:373` makes a bare `fetch('/api/..')` a delivery BLOCKER; `validation_runner.py:659-673`
    early-returns unless /auth/register|login mints an access_token. A no-auth app cannot deliver.

25. **Gen-5 (P1) the test-user hard gate assumes `/` lists human-named rows + a localStorage bearer token.**
    `test_user_runner.py:949-954` returns "defer" (overriding the bounded escape) on
    `not auth_ok or hollow_frontend or fallback_dom_pages or primary_dataless`. `_SEED_NOISE_COLS`
    excludes lat/lng/rating/price/count/url, so a maps or KPI home has 0 salient values -> hard defer on a
    CORRECT app. Magic counts `_DEFAULT_MIN_ROWS=5` / `_MIN_AUTHORED_TOTAL_ROWS=10` flag a legitimately
    3-row lookup table and then amplify it into fictional density.

**Dimension coverage.** cannot deliver: search/aggregate/report/analytics, no-auth, wizard/checkout.
Delivers but SILENTLY INSECURE/WRONG: private per-user content (mail/docs/CRM/health), finance/B2B.
Delivers only by force: maps/geo. Not expressible: real-time (`_HTTP_METHODS` is the closed HTTP verb set).
Fully covered: social/media feed.

---

## Cross-cutting

Four of the worst findings share one shape: **the framework holds a fact the agent cannot see, then
blames the agent for not knowing it** — a route the auditor can't parse (C-1), an int the gateway
stringified (G-4), a milestone guard evaluated after the call (G-2), a validation row filed under a
namespace the gate collapses wrong (G-1). In all four the trajectories show the model reasoning
correctly about the contradiction and being overruled. Per the doctrine, none is model quality. The
only item plausibly attributable to the model is browser selector-guessing — and even that is amplified
by an error message that withholds the available selectors.

## Recommended order

1. C-1 (r91 killer, and it silently reverses agent work)
2. UI-3 + UI-1 + UI-2 (the UI-fidelity chain; UI-3 is a 1-line gate fix that makes the rest visible)
3. Cost-1 + Cost-2 (the biggest caching-independent token cuts)
4. C-2/C-3/C-4 (silent data leaks; one root — infer from the contract, not from shape/vocabulary)
5. UI-6 + UI-5 + UI-4 (deterministic visual wins, no LLM dependency)
6. G-4, G-2, G-1, G-3, Cost-3
7. Gen-1/Gen-2/Gen-3 (needed before the next non-social env)

---
# ROUND 3 (2026-07-29, later) — 4 more agents: dead tools / ownership / prompts / bloat

Shipped since round 2: #330 623726d, #331 3827868, #332 530f0d3, #333 9aa212d,
#334 543c7dd, #335 bbc8971. All TDD, all zero-regress vs the c9224a0 baseline.

## ⚠ METHODOLOGY WARNING (invalidates some earlier "no caller" claims)
`grep` on this machine is a shell function wrapping `ugrep --ignore-files`, which
HONORS .gitignore — and .gitignore excludes `run_*.sh`, `launch_*.sh` and
`/agent/tests/`. Any "never set / no caller / dead" conclusion drawn from a plain
`grep -r` here may be reading filtered output. Use `command grep` or Python before
deleting anything on that basis.

## P0 — the framework DELETES the backend lane's routes from the lane's own file
VERIFIED BY THE AGENT against the delivered r93 tree; I have NOT re-verified.
`app/backend/custom_routes.py` is the ONE backend-lane-owned file, but framework-owned
`main.py` filters the lane's router AT IMPORT TIME (`backend_skeleton.py:870`), dropping
any route `_custom_route_overrides_projected` (:785-849) calls "standard CRUD", "nested
child resource", or a GET on an owner-scoped resource.
`_NESTED_CHILD_RESOURCES` (:1026) = every registered table name + "s" + rstrip("s").
On any social/feed domain the edge tables are named likes/saves/follows/comments — which
COLLIDE WITH ACTION VERBS in `/videos/{id}/like`. The classifier cannot tell an ACTION
from a CHILD COLLECTION by segment name.
r93 delivered: 8 of the 18 lane-authored routes dropped. The projected replacement makes
`GET /api/videos/{id}` 404 unless you authored the video — on an app where every video is
public. 282 log events across r91/r92/r93 chase that 404; the verifier filed >=9 separate
bugs on that one endpoint; r92's lane resorted to `app.add_api_route(...)` explicitly
"bypasses the include_router filter" plus an in-place monkey-patch of the auth middleware.
The backend said it verbatim: "My custom routes get DROPPED by
_custom_route_overrides_projected because /api/videos/{id}/like is a 'nested child
resource' and `like` IS in _NESTED_CHILD_RESOURCES."
No notice is ever emitted — the lane reads its own file and believes the route is live.
FIX: (a) emit a build-time route-ownership manifest + framework_notice on every drop;
(b) classify a nested CHILD only when the child table has an FK to the parent AND the
registered endpoint's response_key is a collection — an edge table keyed (actor,target)
is an ACTION; (c) apply the owner-scoped drop only when the endpoint is registered
auth_required=true and no public/feed endpoint reads that table.

## P0 — an anonymous-auth BYPASS was shipped into the delivered app
`auth_required` is a first-class prompt concept, but `backend_scaffold.py:380`'s
`_framework_auth_guard` 401s every `/api/` path outside a hardcoded prefix set and never
reads it, while `validation_runner.py:791` hard-fails `auth_enforced_401` unless the FIRST
GET business endpoint returns 401 — also without consulting it. The lane is squeezed
between a P0 blocker demanding 401 and a P1 bug demanding 200.
Both runs escaped from the one file they own:
  r91 custom_routes.py:1486 `_install_auth_optional_bypass()`
  r93 custom_routes.py:83-191 `_install_public_bypass()` — mints a real RS256 SYSTEM
  TOKEN (issuer="internal-anon-bypass", sub="0") and STRIPS the incoming Authorization
  header for 5 route patterns.
So the delivered r93 env authenticates anonymous traffic with a server-minted credential.
A security defect manufactured by an unsatisfiable prompt/gate pair.
FIX: the guard and `auth_enforced_401` must both read the registered contract; probe the
first GET with auth_required=true, and separately assert auth_required=false endpoints
return 200 anonymously.

## P0 — a heal pass rewrites lane source unconditionally and shipped regressions
`repair_fabricated_fallbacks` (frontend_audit.py:1195-1256) rewrites lane source using a
heuristic that calls a literal "fabricated" if it has a digit, has a space, or is
capitalized. Confirmed in delivered apps: r92 LoginPage.jsx:51 `setError((err.message ??
'—'))` — every login error now renders a bare em-dash; r91 AuthContext.jsx:20 display_name
fallback destroyed. The documented kill switch ENVGEN_INVENTED_FIELD_GATE=0 disables the
SAFE half (the gate) and leaves the DESTRUCTIVE half running (zero env guards).
FIX: delete the rewriter + narrow the classifier to digit-bearing literals, in ONE commit
(never the deletion alone — #191 exists because a lane thrashed 75min on this edit).

## THE SINGLE HIGHEST-LEVERAGE FIX (two agents converged on it independently)
A BUILD-TIME ASSERTION: every tool name appearing in a rendered prompt, a gate-remediation
string, or a dispatched task description must resolve to a registered tool that the
ADDRESSED role both holds AND is surfaced in the stage that will be active.
It closes, at once: `record_validation_result` quoted as a callable in delivery_gate.py:130/134/155
(it is a HubRegistry METHOD, agents attempted it 14x); `browser_wait_for` in the verifier's
canonical ui_testing template (not a tool); `eventhub.publish_api_requirement` as the entire
documented FE/BE shape-negotiation channel (a Python method, called 0 times);
`codehub_get_file_content(pr_id=...)` mandated 3x though 0 PRs exist in any run;
`register_visual_review_task` named 8x in the frontend prompt but absent from its
implementation:action allowlist; and 113 "tool not available to me" complaints.
NOTE: shipping it as a HARD failure would block the pipeline until ~113 violations are
fixed — land it first as a reporting test, then ratchet to hard.

## OTHER VERIFIED-BY-AGENT ITEMS (not re-verified by me)
- 143 of 270 granted tools (53%) never called in 200k calls; 20 are granted-but-hidden by
  the stage allowlist, which is what killed three whole subsystems (task-definition, MCP,
  visual-review). `stage_tool_allowlist` is AUTHORITATIVE and silently overrides both the
  category/bundle grant and the ACTION_STAGE_ALWAYS_INCLUDE pins.
- `capture_webpage`'s default dest is `screenshots/`, whose allowed_writers is
  frozenset() — nobody. 65% of its calls fail; 54 denials, 100% from the frontend lane,
  across 23 runs. FIX #110 exists so the frontend can SEE its own render; it lands in a
  read-only route. Fix: default to a writable route (design/captures/).
- 76 config flags, 4 ever set. 33 never set AND in no test. 5 mechanisms were written,
  gated OFF "until validated", and never enabled (ENVGEN_ISOLATION_GATE,
  ENVGEN_MILESTONE_SCOPED_GATE, ENVGEN_RESERVED_PATH_GUARD, ENVGEN_ENFORCE_REF_VIEW,
  ENVGEN_HUB_FOCUS). Also a real bug: ENVGEN_SYNC_STATUS_AT_FINISH is read with default "1"
  at preconditions.py:112 but with NO default at :154, so the correct message at :158-170
  is dead code and the lane gets the deadlock message the fix exists to prevent.
- 14 delivery-gate blocker tokens have NO owner in any map, including BOTH
  critical_visuals_* tokens. r92 logged "Delivery declined on gate check(s) with NO
  remediation owner: ['deliverability_dead_artifacts']".
- 69 of 91 gate remediations (76%) go to the verifier, which is hard-blocked from the tools
  every one of them names (registryhub_list_ui_pages, workhub_comment, update_memory_bank,
  register_visual_review_task, deliverability_check).
- `_chain_eid` collapses only NUMERIC path segments, so 35 of 43 chain-registration
  rejections are mis-scoped: deliberate not-found negative probes (which the remediation
  text literally demands) and non-numeric ids (usernames, uuids, slugs) — i.e. most apps.
- 347 silent `except: pass` handlers; this is the MECHANISM by which layers accrete (a heal
  pass that silently no-ops looks identical to one that succeeded, so the next failure gets
  a new layer instead of a fix).
- orchestrator.run is a 1229-line function wrapping a 1113-line try, max nesting depth 7,
  orbited by 21 independent anti-wedge counters all at default; which timer fires first is
  untested.
- Prompt: 72.7KB constant system prompt per role per turn; orchestrator system:task ratio
  is 153.8:1 and its whole task prompt carries NO project name, milestone, or failing check
  — it then polls deliverability_check 549 times for state the framework already holds.
  v4 templates (180KB) are reachable only via ENVGEN_PROMPT_VERSION, set nowhere.
- feature_inventory is specified THREE incompatible ways in one template, none matching the
  validator; its auto-repair derives flows from `user_flows`, which the same template
  forbids authoring. Kickoff cross-check failed 3/3 runs.
- Kickoff facilitation offers 3 actions of which 2 are unreachable (KICKOFF_MAX_ROUNDS=1
  makes `1 < 1` false); both runs fell through to synthesize_fallback, so the run's whole
  contract came from the fallback path.
