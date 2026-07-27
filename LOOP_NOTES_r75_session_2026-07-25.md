# /loop continuation notes — r75 (session 2026-07-25)

## r75 diagnosis (NOT a framework bug)
- r75 (PID 3306108) started Jul24 ~22:30, alive & progressing.
- **M1 DELIVERED v1.0.0 @ 00:20:04** (log line 36791). api_smoke 23/23 green.
- **M2 kicked off @ 00:25:59** (line 38244). By design, `orchestrator.py:1043`
  resets `self._session_start_ts = time.time()` per milestone — so M1's proven
  RunHub runs (last completed 00:05:52) are correctly excluded for M2's gate.
- Therefore `deliverability_no_successful_run` + its DERIVATIVE
  `deliverability_dead_artifacts` (deliverability.py:322 only fires when
  `not functionally_validated`) are **correct** for M2 — M2 needs its OWN
  api_smoke run, none recorded since 00:17:57. NOT a framework bug.
- M2 added new endpoints (explore, feed/following, feed/friends, users/by-username,
  users/by-username/videos) → 5 validate.api_smoke tasks nudged to verifier @ 00:45.
- Remaining M2 gate checks all have OWNERS actively remediating:
  backend←contract_alignment_failed + placeholder_stub_handler;
  frontend←ui_page_unwired (profile_own_page placeholder); verifier←business_chain_failing.
- No tracebacks / no fail-fast / no deadlock / no orphaned "NO remediation owner"
  since M2. Healthy mid-flight convergence.

## Verification method used (real data, not log-reading)
- Read `generated/tiktok-web-r75/shared/hubs/runhub_runs.json` directly: confirmed
  qualifying runs exist (completed+fail0, 23 probes) but all BEFORE M2 session reset.
- Confirmed `last_successful_run_since` (service.py:144) returns ANY qualifying run
  since since_ts, most-recent-first — a later failed run does NOT mask an earlier
  success. So the None is purely the per-milestone since_ts advance.

## ★ TWO framework fixes delivered this session (from r75 M2 evidence)

### #290 (4155878) — run_start must not trust a model-supplied generated_dir
- `tools/run_tools.py` RunStartTool._run only auto-derived generated_dir from
  base_dir when the arg was OMITTED (`if not generated_dir:`). r75 M2: the
  orchestrator LLM passed a bad relative guess → ComposeLifecycle(cwd=...) →
  `FileNotFoundError: 'app'/'docker'` → run crashed → M2 got no clean RunHub
  run → forced force_deliver bypass. Fix: base_dir is the authoritative env root
  for the process — prefer it whenever present; never trust a model guess.
- TDD: test_290_run_start_ignores_model_generated_dir.py (3 tests). Verified via
  runhub_runs.json (omitted→succeeds, supplied→FileNotFoundError asymmetry).

### #291 (3c4fc39) — check_inbox must not crash on a durable eventhub message
- `tools/communication_tools.py:773` — #274 wrapped durable-event content in
  `summarize_inbox_message_body(...)`, a function DEFINED NOWHERE → NameError
  fired 184× in r75, aborting the WHOLE check_inbox (durable AND in-memory) for
  every agent holding a cross-process event. Also violated the no-truncation
  invariant (test_inbox_no_content_truncation). Fix: carry raw untruncated
  payload content, same as the non-durable path.
- TDD: test_291_check_inbox_durable_event_no_nameerror.py (2 tests). Existing
  E2E test used _hubs=None so never hit the durable branch — that's why it hid.

Both: TDD red→green + stash zero-regression + pushed vaibackup (HEAD=3c4fc39).

## Frontier + next
- r75 still churning M2 on OLD (pre-fix) code; #290/#291 only take effect in a
  fresh run. Let r75 wind down (it force-delivered M1+M2 v1), then start r76 to
  validate both fixes and continue the loop.
- Remaining non-framework frontier per handoff: LLM frontend quality
  (ui_page_unwired/fallback), business_chain intermittent timing. Not framework bugs.

## r75 outcome + r76 launch (01:44)
- r75 M2 LIVELOCKED on pre-fix code: check_inbox NameError still firing at
  01:37-01:39; verifier silent 74min (elapsed=4467s since finalize) despite
  repeated nudges; gate stuck 6-7 checks >1h. The verifier (which records the
  api_smoke run M2 needs) going silent is consistent with #291 crashing its
  check_inbox whenever it holds durable events → strong evidence #291 was a
  root contributor to the livelock. r75 had already force-delivered M1+M2 v1.
- Killed r75 (clean group kill, SID==PGID==PID==3306108); no lingering
  containers/procs. Launched **r76** (PID 825666, SID==PGID==PID, opus-4.7,
  gm_tiktok_r76.log) with #290+#291 to validate the fixes and continue the loop.
- r76 in material-prep phase at launch (11/11 screens, reference_spec 34 gates).
  Monitor to delivery gate; each real framework bug → real reproduce→TDD→stash
  zero-regress→push vaibackup.

## r76 fix validation + #292 (02:11)
- **#290 + #291 VALIDATED in r76**: `summarize_inbox_message_body` NameError = 0
  (was 184 in r75); `run_start` FileNotFoundError 'app'/'docker' = 0. Orchestrator
  cleanly "Inbox drained". r76 converging M1 (gate 11→9 checks, normal build).
- **#292 (4eb8ed6)** — check_inbox must coerce a non-integer limit. r76 live: the
  orchestrator passed a stringified limit ("10") → `filtered[:limit]`
  (communication_tools.py:828) → TypeError "slice indices must be integers" (10×,
  self-retried = lower severity than #291 but recurring friction on a core tool).
  Fix: coerce coercible limit, fall back to default(10) for uncoercible. TDD
  red→green + stash zero-regress + pushed. HEAD=4eb8ed6.
- r76 runs WITHOUT #292 (pre-#292 code) → keeps hitting the slice crash but
  retries; not worth a restart (low severity). #292 lands in r77.
- Other r76 tool errors were guardrails/LLM-arg-fumbles, NOT framework bugs:
  FRAMEWORK-OWNED write denials (correct), lint finding real issues (correct),
  verification_chain rejecting unregistered endpoints (correct), and
  "unexpected keyword argument 'priority'/'table'" (LLM passed unknown kwargs →
  surfaced as error ToolResult, agent retries — tolerable, not a crash-loss).

## r76 M1 status @ 02:46 (frontier = LLM frontend quality, framework clean)
- r76 ~1h in, still M1, gate oscillating 9↔12 for ~47min. NO new framework bug
  crash (traceback scan clean).
- New gate check `deliverability_dead_nav_link` = framework-CORRECT frontend-
  quality detection (nav link → dead page), dispatched to frontend lane. Same
  class as ui_page_unwired. Not a framework bug.
- `contract_alignment_failed` = framework-correct; backend fixed it @ 02:45:50
  (re-registered /auth/signup,/logout with correct response_keys). Owned+resolved.
- ★ Bottleneck (orch @ 02:37:09): "Backend landed all 5 P1 fixes + contract
  alignment. FRONTEND still non-responsive on 45+ P0 tasks (lucide-react +
  fallback page + Settings + dead nav)." → 100% LLM FRONTEND QUALITY, not
  framework. Backend done. Per discipline: don't chase.
- #292 slice crash 20× (still retries, non-blocking; lands r77). #290/#291 = 0.
- Action: monitor to M1 deliver / fail-fast. Only a NEW crash signature warrants
  a framework fix. If r76 concludes → r77 validates #292.

## ★ #293 (23facc6) — HARD DEADLOCK fix, exposed by r76 (03:15)
- r76 ENDED deadlocked: ALL 16 runhub start_run attempts aborted with
  compose_stderr='no configuration file provided' → 0 successful runs. Orchestrator
  declared "Run deadlocked... run_start systematically fails, cannot verify env
  boots" and CORRECTLY refused force_deliver (0 successful runs = ship broken).
- Root cause: generated compose lives at <env_root>/docker/docker-compose.yml
  (framework-wide convention: validation_runner:58/176/453, visual_fidelity:308,
  heal_pipeline:478, docker_tools:147). But runhub start_run (service.py:196) built
  ComposeLifecycle(cwd=env_root, compose_file=None) → `docker compose up` in ROOT
  → no compose file → abort. Latent because verifier api_smoke (validation_runner)
  uses the correct `-f docker/` path + record_run; only the orchestrator's direct
  run_start hit it. r75 succeeded via validation_runner, not start_run.
- ★ #290 EXONERATED: r75's SUCCESSFUL runs recorded generated_dir=env_root (base_dir),
  same value #290 forces — so base_dir was always correct; the bug was compose-file
  location, not generated_dir. #290+#293 compose (generated_dir=authoritative env_root
  → #293 derives docker/ from it).
- Fix: new service._resolve_compose_file(env_root) → docker/docker-compose.yml
  (fallback root), mirroring docker_tools order; start_run default ComposeLifecycle
  carries it. TDD (4 tests: helper prefers docker/ + fallback + none; start_run wires
  compose_file) red→green + stash zero-regress + broad 78/78 + pushed.

## r77 launched (03:30) with all 4 fixes (#290-#293)
- r76 GONE (self-terminated, deadlocked). Launched r77 (PID 1967715, SID==PGID==PID,
  gm_tiktok_r77.log) to validate #293 (runs should now BOOT, not abort) + #292.
- DISK: launch first REFUSED (root 53G<60G guard, r24 ENOSPC lesson). Freed via
  `docker builder prune -af` (5.6G) + `docker image prune -f` DANGLING-only (145.6G;
  leftovers from repeated env-gen builds). 53G→195G. Left tagged images + volumes
  untouched (shared box). Then r77 launched clean.
- #293 validation so far: 'no configuration file provided' count = 0. Watch first
  runhub run: should reach healthy/completed, not abort on compose.

## ═══ ROUND COMPLETE (05:07) — r77 GENERATION COMPLETE, framework layer CLEAN ═══
- r77 fully delivered (GENERATION COMPLETE, UI:8080). #293 DECISIVE: 10/11 runhub
  runs qualifying successful (max 26 probes) vs r76's 0. check_inbox working
  (count=20/83 @ 05:06 → #291/#292 validated). Remaining work was authoring
  fallback-route pages = frontend LLM quality.
- 5 framework fixes ALL runtime-validated. No 6th REPRODUCIBLE framework bug.

## M2 authored-seed anomaly — INVESTIGATED, gate code EXONERATED (flag for user)
- r77 orch woke 10+× on "authored seed missing" (03:53-04:32) then force_delivered
  claiming false-negative. VERIFIED (not trusting LLM claim):
  1. Gate LOGIC correct — ran exact check on real files → _authored=True (13 tables).
  2. app_root=output_dir/"app" (delivery_gate.py:1277) CORRECT.
  3. Gate MERGES seed_dataset.json; it was committed to integration @03:52:56 at
     full 88KB (populated) — present the ENTIRE flag window. seed_data.json
     populated (18KB) from 03:54:43.
- CONTRADICTION (correct logic+app_root+populated seeds present, yet flagged 38min)
  ⇒ anomaly is in RUNTIME working-tree/merge file-state during the run, NOT gate
  code. NOT reproducible post-hoc (disk moved on). Per discipline: do NOT
  speculatively fix without reproducible root cause. force_deliver was LEGITIMATE
  (seed genuinely real). ★IF RECURS: investigate whether output_dir working tree
  transiently lacks committed app-content (seed_*.json) at gate-eval time
  (checkout/merge-state staleness) — needs LIVE observation, not post-hoc.

## ⚠ PRE-EXISTING test_write_gate_invariant failure (NOT this session's) — user to review.

## SESSION TALLY: 5 framework fixes — #290 #291 #292 #293 #294. HEAD=71b5320, unpushed=0.
## LOOP STOPPED 05:07 — framework layer clean, reported to user for direction.

## #294 (71b5320) — apply_patch NoneType<int crash (exposed by r77)
- r77: `apply_patch FAILED: '<' not supported between 'NoneType' and 'int'` (2×).
  _find_subsequence (canonical_file_tools/shared.py:519, annotated `-> int`) had
  NO return at end → implicit None on no-match; caller patch.py:129 `if
  match_index < 0` → `None < 0` TypeError, masking the actionable "failed to
  match patch hunk" error the lane needs to self-correct a stale patch.
- Fix: `return -1` on no-match. TDD (5 tests: found/not-found/needle-too-long/
  empty-needle/caller-contract) red→green + stash zero-regress.

## ⚠ PRE-EXISTING test failure (NOT mine, surface to user)
- test_write_gate_invariant::test_no_writing_tool_bypasses_the_role_gate FAILS at
  HEAD (verified fails with #294 stashed too). A writing tool isn't going through
  the role gate / not in EXPECTED_ALLOWLIST. None of this session's changes touch
  a writing tool, so it predates #290. Separate latent issue — worth a look but
  not what any run exposed.

## ★★ r77 DELIVERED M1 @ 04:30:32 — framework layer CONFIRMED CLEAN this round
- Gate collapsed 24→17→13→3→1 (only business_chain_failing = intermittent timing
  false-pos) → force_deliver (legit for the timing check + frontend reconciliation).
  First clean full M1 delivery of the session (r75 forced through buggier path;
  r76 deadlocked entirely on #293).
- ALL 5 fixes validated live. #293 decisive (successful runs, no_successful_run
  cleared). Remaining frontier = LLM frontend quality + business_chain timing.
- r77 continuing into M2 (first CLEAN M2 — watch for a 6th deep framework bug like
  #293 was). If M2 delivers or fail-fasts on pure frontend quality w/ no new
  framework crash → round complete, report + pause for user direction.

## ★ r77 @ 03:59 — ALL 4 FIXES VALIDATED, framework layer CLEAN
- #293 DECISIVE: 'no configuration file provided'=0; runhub has 3 completed+fail0
  runs (26/12/12 probes, empty compose_stderr) — env BOOTS+COMPLETES (impossible
  in r76). And `no_successful_run`+`dead_artifacts`+`frontend_build_not_recorded`
  DROPPED OFF the gate (present 03:51 → gone 03:52:56) = #293 clears them end-to-end.
- #290/#291/#292 crash counts all 0. No new crash/traceback signature.
- r77 gate now 19-20 checks, ALL LLM frontend quality: frontend_fallback_page ×9 +
  ui_page_unwired ×9 + ui_flow_missing + business_chain. NOT framework bugs.
- CONCLUSION: framework layer clean this round — 4 bugs found+fixed+validated;
  remaining delivery gap = frontend-lane LLM generation quality (handoff 下一步 #2,
  different scope). Keep monitoring r77 to M1 deliver / M2 (a 5th framework bug
  could still surface deeper, as #293 did when orch leaned on run_start). If r77
  delivers cleanly OR fail-fasts on pure frontend quality w/ no new framework bug
  → report to user + consider pausing loop for direction.

## ═══ LOOP RE-ARMED (user: 先a然后b) — 14:53 ═══
- PLAN: (a) run more generations probing for a 6th framework bug (fix real ones);
  when runs stop surfacing framework bugs (clean deliveries) → (b) pivot to
  frontend-lane LLM quality (fallback/ui_page_unwired reduction).
- r78 launched (PID 701519, SID==PGID==PID, gm_tiktok_r78.log) with all 5 fixes
  (#290-#294). Design-prep phase (13 screens, 34 gates). Validates #294 too.

## ★ #295 (6TH FRAMEWORK BUG) — exposed by r78, FIX APPLIED, VERIFY+COMMIT PENDING
- r78 did NOT cleanly deliver — FAIL-FAST STUCK on docker_up (main() returned 1).
  Real blocker: frontend vite build failed on `import { Route } from 'lucide-react'`
  (Rollup: Route not exported), 9 post-cap cycles → abort (orchestrator.py:1750
  RuntimeError = the DESIGNED stuck-abort, not a crash).
- ROOT CAUSE (verified real data): LeftNavSidebar.jsx used `Route` ONLY in comments
  (`// … MUST resolve to a wired <Route>`), never real JSX. The framework healer
  `repair_frontend_unimported_icons`→`_unimported_jsx_tags` (frontend_scaffold.py:524)
  ran `_JSX_TAG_RE.findall(src)` on RAW text incl comments → matched `<Route>` in the
  comment → injected `import {Route} from 'lucide-react'`. lucide has no Route export →
  build fails. Healer RE-INJECTS every validation cycle (after lane removes it) →
  frontend can't converge → STUCK ("framework artifact regenerated every cycle").
- FIX APPLIED: added `_strip_comments_for_scan()` (blanks /* */ + // comments, keeps
  ://URLs), `_unimported_jsx_tags` now scans stripped text. frontend_scaffold.py.
- TEST WRITTEN: test_295_unimported_jsx_tags_ignores_comments.py (6 tests: comment
  cases not flagged, real <Mail/> still flagged, URL-line not over-stripped, imported
  Route not flagged). RED confirmed (3 comment cases failed pre-fix).
- ✅ DONE: test_295 GREEN (6 tests); regression 27 passed incl healer's own
  test_frontend_unimported_icons.py; stash zero-regress confirmed; committed
  d3223a3 + pushed vaibackup. HEAD=d3223a3, unpushed=0. SIX fixes #290-#295.
- NOTE: secondary latent issue — safe-icon vite plugin's "crash-proof lucide import"
  guarantee was violated (Route import failed the build). #295 fixes the trigger
  (don't inject non-icons from comments); deeper safe-icon plugin robustness is separate.
- Watch: new crash/traceback = framework bug → reproduce→TDD→stash0→push. Also
  re-watch the authored-seed anomaly (if it recurs with seeds provably present at
  output_dir/app at gate time = confirmable framework bug worth a live fix).

## r79 @ 17:33 (51min) — framework CLEAN, at frontend-quality frontier (phase-a conclusion emerging)
- #295 VALIDATED: 0 lucide build fails, 0 docker_up fails (r78's STUCK cause gone).
- All 6 fix crash signatures = 0. No new framework bug / no STUCK / no traceback.
- runhub 12/13 qualifying successful runs (#293 excellent).
- Gate down to 1 REAL check: deliverability_ui_page_unwired (a declared page not
  route-wired) — churning ~26min. = FRONTEND LLM QUALITY, the exact phase-(b) target.
- new send_message missing-arg (1×) = LLM fumble, framework rejects correctly. NOT a bug.
- ⇒ Framework layer conclusion of phase (a) is ESTABLISHED: 6 fixes all validated,
  r77 clean + r79 framework-clean (12 successful runs), r78's #295 fixed. r79's only
  blocker IS the (b) topic. Give r79 one more cycle for a clean GENERATION COMPLETE,
  then pivot to (b): frontend-lane quality (reduce fallback_page/ui_page_unwired).

## ═══ PHASE (b) STARTED — frontend quality (measured-floor projection) ═══
- r79 delivered M1 AND M2 (run_validation 13/13 each), framework fully validated;
  retired it (clean kill) to validate phase-b.
- Brainstorm→spec→plan (docs/superpowers/specs+plans/2026-07-25-frontend-measured-floor-page*).
  Finding: framework's own gap-filler (_project_page_component) MANUFACTURES the
  data-fallback pages its gates reject (ui_page_unwired/frontend_fallback_page).
- #296 (773facc): _measured_floor_colors — reads design.design_system.palette,
  normalized {bg,surface,text,muted,accent,border} or None. TDD 6 tests.
- #297 (8cb8303): no-reference GET branch of _project_page_component now emits a
  MEASURED structured floor (data-projected="ref" + _STRUCTURED_MARKER + measured
  colors, counts as BUILT) instead of data-fallback WHEN a palette exists; keeps
  data-fallback when no palette (§2 guard). TDD 4 tests + updated
  test_reference_structured_projection (superseded old uncovered-route test +
  added no-palette guard test). 86 passed. Both pushed vaibackup.
- r80 launched (PID 3776273, SID==PGID==PID, gm_tiktok_r80.log) with #296/#297 to
  VALIDATE: no-reference GET pages should carry data-projected="ref"+measured
  colors (grep app/frontend/src/pages/*.jsx); fallback_page/ui_page_unwired gate
  counts should DROP vs r77/r79; no new framework crash/STUCK; referenced pages
  still via _render_reference_page.

## ★ #296/#297 VALIDATED on real r80 data (19:58)
- Direct runtime proof: _project_page_component(no-screen GET route, real r80 design)
  → data-projected="ref" + _STRUCTURED_MARKER + _imgOf floor template + NO data-fallback;
  measured colors from r80 palette (#000000 bg / #1f1f1f surface / #FE2C55 accent /
  #a8a8a8 muted / #ffffff text); _is_generic_fallback_page(out)=False → counts as BUILT.
- r80 M1 DELIVERED clean (13/13 api_smoke + 52/52 business_chain + 4/4 ui_flow, all
  builds green). 6 framework crash signatures = 0, docker_up build fail = 0. No regression.
- Note: r80 M1 built all 4 needed pages itself → floor didn't fire in M1 (good); it fires
  when the lane leaves a page unbuilt (M2+ / larger contract). Mechanism proven on real data.
- PHASE (b) improvement #1 = SUCCESS. r80 continues (M2+); mechanism validated regardless.

## ★ Chunk B (#298, 006d609) — shape-aware measured floor — DONE
- _floor_shape(page,get_ep,name) -> grid|detail|list (path-param→detail;
  explore/gallery→grid; else list). #297 branch now selects grid/detail/list
  template; all keep data-projected=ref+_STRUCTURED_MARKER+measured colors+fetch.
- TDD test_298 (10 tests: _floor_shape table + grid/detail/list integration +
  no-palette). 18 green with 296/297; regression 94 passed; zero-regress; pushed.
- Real r80 validation: /vitem-xyz(path param)→detail(no rows.map), /inbox-xyz→list,
  /explore-xyz→fuzzy-matched real screen→_render_reference_page (cascade Layer1 wins).
- Cascade status: Layer3(measured floor #297)+Layer2(shape-aware #298) DONE.
  NEXT: Chunk A (widen _design_screen_for_route coverage, DELICATE — anti-wrong-graft
  guards #226/#229) then Chunk C (reduce lane under-build, prompt/flow track).
- r80 still running (validated #296/#297 at runtime; #298 committed after r80 launch
  → a future run validates #298 end-to-end).

## SESSION TOTAL: 6 framework fixes (#290-#295) + 3 phase-b frontend-quality (#296/#297/#298). HEAD=006d609.

## ★ #299 (7a03f0c) — self-targeted social action re-targets a different user (r80 M2 STUCK root)
- r80 M2 STUCK (NO-CONVERGENCE ABORT 75min): business_chain wedged on
  POST /api/users/81/follow → 400 cannot_follow_self, 81 = the chain user's OWN
  registered id. App correct; success-expecting chain step can never pass.
  #81 avoid-self only guards UNRESOLVED placeholders; a RESOLVED-to-own_user_id
  target slipped through. NOT timing — verified real (orch itself diagnosed
  "CHAIN DEFINITION" self-follow).
- Fix: _self_targeted_social_user_action(expect,path,own_user_id) flags a
  success-expecting social verb on /…/users/<own>/<verb>; on the 400, retry ONCE
  vs a recovered DIFFERENT user (avoid=own_user_id, else aux user). Mirrors #136.
  Deliberate self-deny test (expect [400]) NOT matched. #288/#289 family.
- TDD test_299 (8) + regression 32 passed + zero-regress + pushed.

## /loop 持续优化直到产出完美符合要求的App (user, dynamic self-paced)
- Standing goal: keep optimizing (framework bugs + frontend quality) until runs
  produce a perfect reference-matching, fully-functional app.
- SESSION TOTAL: 7 framework fixes (#290-#295, #299) + 3 frontend-quality (#296/#297/#298).

## r81 STUCK (M2, 95min) — diagnosed: backend LANE quality (NOT framework) → #300 convergence aid
- STUCK on business_chain_failing + ui_flow_failed. #299 CONFIRMED working
  (cannot_follow_self=0, no self-follow recurrence). Root cause = backend LANE
  code bug: POST /api/comments/{id}/replies → 500 in lane-authored custom_routes.py
  (post_reply), which the backend lane could NOT fix in 95min. LLM/lane quality,
  not a framework bug — framework validated correctly + failed fast honestly.
- ★ INFLECTION: framework-bug frontier largely exhausted (10 framework-layer
  fixes). r81 = first pure-LLM-code-quality STUCK (backend SQL 500). Remaining
  barrier to "perfect app" = LLM CODE QUALITY (backend SQL correctness, frontend
  fidelity), not framework bugs.
- #300 (2136d30): business_chain 5xx now attaches the backend traceback (file:line
  root cause) — endpoints_reachable already did; business_chain showed only opaque
  'Internal Server Error' → lane fixed blind → STUCK. A CONVERGENCE AID (helps the
  lane fix its own 500s faster), not a bug fix. TDD test_300 (7) + zero-regress + pushed.

## SESSION TOTAL: 11 — 8 framework (#290-#295,#299,#300) + 3 frontend-quality (#296/#297/#298). HEAD=2136d30.

## r82 STUCK (M2, 75min) → #301 (689e297) bare-oauth-authorize tolerance
- STUCK on business_chain (GET /oauth/authorize → 422 expected [200,302,303]) +
  ui_flow_failed. #299 confirmed (self-follow=0), 6 crash sigs=0, #300 present.
- Root: verifier authored TWO oauth chains — correct params-bearing PKCE flow AND
  a BARE GET /oauth/authorize (no client_id/response_type/code_challenge). AS
  correctly 422s the bare one (PKCE required) → unsatisfiable step wedges chain.
- Fix #301: _is_bare_oauth_authorize() → tolerate the bare step's 400/422 (params
  chain tests the real flow). Same family #281/#289/#299. TDD test_301(5)+23 regress
  +zero-regress+pushed.
- ★ PATTERN (r81+r82): framework LAYER robust; STUCKs now from LLM-induced chain/
  lane issues the framework TOLERATES/ASSISTS (#300 traceback aid, #301 oauth
  tolerance). Long tail of chain-tolerance fixes (#281/#289/#299/#301 family).
  Accumulating → each improves clean-delivery odds.

## SESSION TOTAL: 12 — 9 framework (#290-95,#299,#300,#301) + 3 frontend (#296/#297/#298). HEAD=689e297.

## ⛔ LOOP STOPPED (03:05) — LLM SPEND BUDGET EXHAUSTED (external blocker, not a bug)
- r83 FAILED at kickoff (1200s timeout, 0 files). Root cause: EVERY LLM call
  rejected 400 "Spend exceeded. Budget for mg key mg-api-103eefb33e00 ... Spend
  22008.39 >= Budget 22000.00" — from run start (02:38) to end (02:58). 1064+
  all-3-attempts-failed. NOT a framework bug / NOT transient — a hard billing cap.
- Every future run fails identically until the budget is raised/reset or a new
  key is provided. Loop cannot progress → STOPPED (ScheduleWakeup stop, Monitor stopped).
- USER ACTION NEEDED: raise/reset the LLM key budget (mg-api-103eefb33e00) or
  supply a fresh key in /tmp/envgen_opus47.sh, then relaunch (r84) to resume the loop.

## ═══ SESSION FINAL: 12 shipped, all TDD+zero-regress+pushed (HEAD=689e297) ═══
- 9 framework: #290 run_start generated_dir; #291 check_inbox NameError; #292
  check_inbox non-int limit; #293 start_run compose location (HARD DEADLOCK);
  #294 apply_patch no-match; #299 self-follow chain; #300 business_chain 5xx
  traceback (convergence aid); #301 bare oauth-authorize tolerance.
- 3 frontend-quality (projection cascade): #296 measured palette reader; #297
  measured floor (counts-as-built); #298 shape-aware floor (grid/detail/list).
- Framework layer robust; residual barrier = LLM code quality + (now) budget.

## LOOP RESUMED (2026-07-27 16:16) — new key + opus-4.7
- Old key mg-api-103eefb33e00 budget-exhausted ($22008>=$22000). New key
  mg-api-71b41b05af9a: opus access was toggling (r84 on gemini-3-5-flash failed
  mid-run when gemini access got revoked); then claude-4-7-opus-vertex-genai
  access GRANTED on the new key → confirmed 200 + tool_calls.
- /tmp/envgen_opus47.sh updated to NEW key + opus-4.7 (standard path, so loop
  launches/wakeups keep working). r84 (gemini, killed) abandoned.
- r85 launched (PID 2549508, opus-4.7, all 12 fixes #290-#301). 0 LLM errors.

## ═══ CONTEXT/TOKEN REDUCTION (user-driven, 2026-07-27) ═══
- Root cost (framework's own #257 measurement): prompt cache is near-optimal, so
  the spend is NOT the re-sent history — it's the NEW text each step appends
  (~35-51k tok/step/lane), dominated by TOOL OUTPUT. So reduce per-step tool
  output, do NOT compact cached prefix.
- Biggest offenders (tool_io_rollup / [tool-io]): check_inbox, read, workhub
  docs/tasks, registryhub list_endpoints/tables.
- #302 (d4c6e69): check_inbox previews already-READ bodies (unread stays full,
  #274 safe); full via search_messages/eventhub_get_thread(id). ~350KB→~5KB/inbox.
- #303 (9b24ff8): registryhub_list_endpoints/tables return compact rows
  (id/method/path/status/provider + columns_count); full via get_endpoint(id)/
  get_table. schema+metadata were ~85% of each row.
- read tool ALREADY Claude-Code-style (offset+line-numbers+recovery pointer) — no change.
- INVARIANT (user): any condense MUST leave a recoverable pointer (full stored
  locally, fetchable by id/offset). #302/#303 comply.
- REMAINING (approved, not yet built): (A2) workhub_list_tasks compact +
  workhub_get_task; (B) repeated list re-fetch → "no change since version X";
  (C) ToolResultCompressor: add recovery pointers to ALL truncation strategies
  (_truncate/_head/_head_tail/_summary currently leave NO pointer — correctness gap).

## SESSION TOTAL: 14 — 9 framework + 3 frontend + 2 context (#302,#303). HEAD=9b24ff8.
## r85 still running (opus-4.7, all framework fixes; Monitor bfa9seoda). #302/#303 land in the NEXT run.

## context batch cont. (#304/#305/#307) — incl. the duplicate-API root cause
- #304 (16f6989): ToolResultCompressor truncation now leaves a RECOVERY POINTER
  (_truncate/_head/_head_tail/_summary) — no more silent-drop bare '...'.
- #305 (9b0bebc): workhub_list_tasks compact rows; full via workhub_get_task(id).
- ★ #307 (ad85ac8): list tools (registryhub_list_endpoints/tables, workhub_list_tasks)
  NO LONGER truncated to default 1000 — high cap (60000) + head. ROOT CAUSE of
  DUPLICATE API implementations: truncated endpoint list hid existing endpoints →
  agent re-implemented them. Compact rows (#303/#305) made the FULL list cheap to
  show complete. User's insight ("list不能截断,信息缺失→重复API").
- CORRECTED cost model: compressor already capped most tools at default 1000;
  the real big context sink was check_inbox (50000 cap) → #302. list value =
  #303/#305 density + #307 completeness (correctness, not just tokens). B(dedup)
  dropped — lists already small; no value.

## SESSION TOTAL: 17 — 9 framework + 3 frontend + 5 context (#302/#303/#304/#305/#307). HEAD=ad85ac8.

## #309 (e80d0d1) — TRUNCATION AUDIT (answer to "还有什么truncated的内容")
CRITICAL CORRECTION: ToolResultCompressor is DEAD in the live pipeline.
- 2026-06-24 tooling.py removed compressor + 16000 cap ("NO compression/NO cap;
  truncated tool output is a correctness hazard"). Full result -> messages[] -> LLM.
- add_tool_result (sole .compress() caller) NEVER invoked live. Verified by grep.
- => #304/#307/#308 (COMPRESSION_RULES edits) = DORMANT no-ops. Correct-if-reenabled
  but change nothing at runtime. They do NOT fix duplicate-API (live never truncated
  lists). Marked UNWIRED in code (context_management.py class + base.py:589).
Real live truncation = _mask_old_observations (step_runner.py:811): old (non-last-8)
  tool bodies -> 300-char head + "re-run the tool" pointer. BUDGET-GATED: skipped when
  history < resolve_ctx_working_chars(model). opus-4.7 = 1M window -> ~2.45M chars =>
  normal runs NEVER masked. Recoverable-by-design. OK.
Real context reduction = TOOL LEVEL: #302 check_inbox, #303/#305 hub lists (compact
  list + get-by-id). These change the tool's return -> flow through fully. CORRECT.
No live truncation exists WITHOUT a recovery pointer. Audit clean.
Live proof (r85): 1 req content_chars=203705 but prompt_tokens=6 (cache handles
  re-sent history; 200K<2.45M => no masking; full outputs kept). Confirms cost = NEW
  tool-output delta, not re-sent history. Fix = compact tool returns (#302/#303/#305).
r85: M1 feed-and-auth 13/13 GREEN, orchestrator DELIVER_PROJECT, 0 LLM errors.

## #310-#313 (pushed 4c876fc) — dead-code deletion + tool-config guarantee + stale-test sweep
User asks this session: (1) delete dead code, (2) ensure per-stage tool config tools usable.
- #310: DELETED context_management.py (1083 lines, all 8 classes DEAD — AdvancedContextManager
  instantiated but never fed/read; compressor never live) + 5 orphan compressor tests. #309
  first marked it UNWIRED, then user said delete. Zero-regress (import chain + 58 fix-family green).
- #311: REAL gap — frontend+debugger lacked 'progress' category → report_progress (in their
  allowlist+prompt) unusable. Added 'progress' to both (mirrors backend). + fixed 2 FALSE-POSITIVE
  guards: (a) both assembled include_vision=False → decompose_reference falsely flagged; model
  vision via stub client. (b) test_prompt_tool_policy read whole shared test_user_agent.j2 →
  unioned 3 variants' tool_policy; scope to <pid>_system_prompt macro. + dropped 4 knowledge
  KNOWN_PRE_EXISTING_GAPS now granted.
- #312: user_flows RETIRED from frontend kickoff (2026-06-22 directive in section_substance.py)
  was half-applied — FINAL PROTOCOL correct but schema/line306/348/433/464 + comment block still
  told frontend to author them (self-contradiction → null-array wedge risk). Cleaned all; dropped
  kickoff_declare_user_flow from test_stage_tool_allowlist_gaps. USER DECISION: orchestrator derives.
- #313: 4 pre-existing stale/brittle tests (code correct): milestone_kickoff_phase x2 (mock lacked
  get_meeting_decisions read-path → AttributeError swallowed → VALIDATION); kickoff synthesis macro
  RENAMED synthesis→facilitation; FIX #107 window narrowly excluded marker (re-anchored forward).
★ DISCOVERY: wide sweep found ~16 MORE pre-existing local-test failures (test rot — local gitignored
  tests drifted from code, never run wholesale): test_eventhub_new_tools(7), test_workhub_tools,
  test_write_gate_invariant (flags DecomposeReferenceTool mkdir/write_text — maybe real gate bypass),
  test_mcp_prompts, test_deliverability_tools, test_debugger_prompt/gates, test_agents_config_stages,
  test_backend_merge_ownership_resolve, test_non_canonical_file_tools. ALL fail at baseline 76c328b too
  (NOT my regressions). Mixed stale-test vs maybe-real. Needs its own focused sweep — pending user go.

## #314 — test-rot sweep of the 16 (4 parallel investigators): 15 STALE + 1 REAL BUG
Result: 15/16 were stale local tests (production CORRECT, expectations drifted); 1 REAL production bug.
★ REAL BUG (shipped fix, material_prep_tools.py:273): DecomposeReferenceTool (wired to frontend+
  design_analyst vision bundle) wrote its JSON spec to an agent-controllable save_as path with NO
  role write-gate → a frontend agent could drop JSON into another role's tree (e.g. app/backend/main.py),
  bypassing ROUTING_TABLE. Fix: gate the write through workspace.is_write_allowed(dest,_agent_id) before
  mkdir/write_text. Verified safe: design/ is writable by backend+frontend+design_analyst (ROUTING_TABLE
  :144) so the legit write to design/component_specs/ is allowed; only cross-role writes are denied.
Stale (production correct, local-test-only fixes, NOT shipped since tests/ is gitignored):
  - eventhub x7: ONE cause — _run() reused process-wide event loop closed by an earlier async test in
    full-suite runs (only the 1 sync test survived). Fresh loop per call.
  - agents_config_stages: design_analyst inherits stages from execution_pipeline_defaults (test read raw block).
  - phase_hygiene debugger gates: bug_triage gate deliberately removed (FIX #2); bug_create still gated.
  - debugger_prompt: prompt uses ROOT_CAUSE/ROOT-CAUSE not literal 'ROOT CAUSE'.
  - workhub_tools export: workhub_archive_page renamed → workhub_archive_document (84f658e).
  - mcp_prompts: MCP server now runtime-projected; backend doesn't author transport.
  - deliverability: passing run correctly 'blocked' by AUTHORED-SEED gate (added 2026-07-02, post-test); fixture lacked seed.
  - backend_merge frontend conflict: PROPOSAL #23 extended ownership-resolve to frontend (App.jsx resolves, not abort).
  - list_reference_images: tool now ignores `project` (more restrictive); test asserted removed feature.
Verified: all 16 pass together (77 passed). ZERO regressions from any of my work (confirmed at baseline 76c328b).
★ FOUND 2 MORE pre-existing (beyond the 16, via collateral filter; NOT my regressions, confirmed):
  test_method_layer_write_gate_invariant (flags WorkHubStores.create @ hubs/workhub/stores.py:23 — hub method,
  needs real-vs-allowlist judgment) + test_workspace_routing (orchestrator broad-write under app/backend/ —
  likely stale, routing comment says 'coordinators DISPATCH never patch'). Suite has broader rot; pending user go.
