# Whack-a-mole eradication — audit + plan (2026-07-31)

A 6-agent parallel audit (workflow) of the forgingground-gen framework produced **43 findings →
~9 roots → 2 meta-causes**. This is the systematic root-cause + eradication plan behind the
run-by-run bug stream (#384–#395).

## The two meta-causes

**① Silent `except Exception:` → degraded fallback (the *multiplier*).** ~20 broad
except/rollback/`pass` sites swallow the FIRST error and fall back, so a stack of latent bugs
in one path surfaces one-at-a-time (one ~50-min run per hidden bug). The rating-404 saga was a
single function (`_fw_owner_val`) hiding, in sequence: NameError (#392) → NotNullViolation
(#393) → InvalidDatetimeFormat (#394) → type-blind body (#395). Had the except *logged*, one run
would have shown all four.

**② The framework reasons over unreliable metadata and defends with fallbacks instead of
validating it.** (a) generated ORM ≠ DDL (nullable/pk/unique/FK embedded in the type string not
promoted — the #393 root); (b) LLM artifacts trusted as-is (design page/overlay `kind` inverted
#389, verifier chain bodies wrong-typed/wrong-field #395/#386, kickoff empty ui_page routes
#387); (c) loosely-typed data inserted without coercion (#388, #395).

## Ranked eradication plan (Prongs A/B/C)

| Rank | Action | Status |
|---|---|---|
| 1 | **Prong A** — instrument every silent swallow behind one `FW_DEBUG` flag so ONE run surfaces all hidden failures (generated-backend crown jewels: `_fw_owner_val` resolve/autocreate/python_type, seed loader per-row + commit, seed_if_empty; FW_DEBUG plumbed into the backend container via compose). | **DONE — #397 `35ab983`** (`_fw_dbg`/`_seed_dbg`, default-OFF no-op; `test_fw_debug_instrumentation.py`, 8) |
| 2 | **Prong C root** — shared inline-modifier promotion feeding BOTH renderers at the `_columns_of` chokepoint; never synthesize a phantom `id` PK. DB-free ORM/DDL parity test. | **DONE — #396 `e9e8341`** (parity test `test_orm_ddl_parity.py`, 8; 117 suite green) |
| 3 | Single-source `_fw_owner_val` — the projector emits a body-divergent copy (route_projector ~1371, `# noqa: F811`) that can re-activate the #390/#391 profile bug; import the canonical instead. | **DONE — #398 `2fa7bbb`** (guarded `try: _fw_owner_val / except NameError`; `test_projector_single_source_fw_owner_val.py`, 5) |
| 4 | Complete `_coerce_body` (Boolean/DateTime/Date/Time; skip Enum/UUID/JSON), call it on PUT/PATCH too, filter bodies against `__table__.columns` not `hasattr`, register a global `DataError→400` handler. | **DONE — #399 `00b0a8d`** (Boolean coercion; up-front so create+update; DataError re-raise + global 400; `test_backend_body_coercion_rank4.py`, 11. DateTime left to the 400 handler by design) |
| 5 | Seed propagation: distinct JSONDecodeError blocker (deliverability 439), stem↔table cross-check (material_prep 867), `seed_dataset.json` in `_BACKEND_FRAMEWORK_OWNED` + git-clean carve-out both branches (auto_commit), per-column coercion + drop-count in the seed loader (2409). | **partial** (#388 did coercion + design/dataset carve-out one branch) |
| 6 | ORM/DDL fidelity gaps: shared type map (uuid/jsonb/money/interval/bytea/text[]), FK `ondelete=CASCADE` in ORM, spine reconciliation, quote bare-word DDL defaults, preserve NOT NULL in the ORM-introspect heal. | **TODO** |
| 7 | LLM-artifact trust: typed 422 placeholders + DDL-derived body in the verifier (chain_executor 1979/676); deterministic screen kind/route over analyst `kind` (frontend_scaffold 1940 + design_prep 841); deterministic ui_page route backfill (run_kickoff 2173). | **partial** (#386/#387/#389 landed pieces) |
| 8 | Full render+boot+business_chain integration test + a `FW_DEBUG` observability meta-test, using the netflix per-profile shape + loosely-typed-rating body as the canonical fixture. | **DONE** (`test_backend_boot_business_chain.py`, 3: boot + rating-coercion + profile-autocreate/owner-scoping, SQLite stand-in; FW_DEBUG on/off meta-test in `test_fw_debug_instrumentation.py`) |

## Status (2026-07-31)

**Ranks 1, 2, 3, 4, 8 DONE** — the two meta-causes are structurally addressed: silent swallows are now loud under FW_DEBUG (rank 1), and the biggest unreliable-metadata roots (ORM≠DDL rank 2, divergent `_fw_owner_val` rank 3, loose body types + missing DataError mapping rank 4) are fixed. Full suite **144 green** (117 → 144 across #396–#399 + the integration/instrumentation nets). Commits on `feat/netflix-generality-366-367`: `e9e8341` (#396), `35ab983` (#397), `2fa7bbb` (#398), `00b0a8d` (#399). Tests are gitignored (never committed) — they are the local fast net.

**Deferred (lower leverage; each ideally validated by a live run):**
- **Rank 5** — seed propagation hardening (distinct JSONDecodeError blocker; stem↔table cross-check; `seed_dataset.json` carve-out both branches; per-column coercion + drop-count already made LOUD by #397's `_seed_dbg`).
- **Rank 6** — ORM/DDL fidelity gaps (shared type map uuid/jsonb/money/interval/bytea/array; FK `ondelete=CASCADE` in ORM; spine reconciliation; quote bare-word DDL defaults; preserve NOT NULL in the ORM-introspect heal).
- **Rank 7** — LLM-artifact trust (typed 422 placeholders + DDL-derived body in the verifier; deterministic screen kind/route; deterministic ui_page route backfill) — #386/#387/#389 landed pieces.

Next: **fresh run #20 with `FW_DEBUG=1`** on the eradicated pipeline to confirm the class is gone (no rating 4xx, no frontend-fallback, business_chain converges) and drive to delivery.

Full findings: workflow `wf_dfa698da-ed6` transcript.

## Next-highest-leverage generalizable fix — deterministic ui_flow recording (2026-08-02, evidence-based)

**Problem (the #1 recurring one-shot wedge):** `deliverability_ui_flow_missing`/`_failed` has
wedged r13/r19/r21/r22 and is live on r23 (0 `validation:ui_flow` records at etime 26m). Root:
ui_flow recording is **verifier-LLM-dependent** — the framework's `#232` path + the gate-fail
remediation both DISPATCH a task telling the verifier to "run the browser flow + WRITE a passing
`validation:ui_flow:<name>` record", but the verifier navigates (`browser_navigate` calls seen)
yet does NOT reliably write the record → the gate perpetually reads "missing" → STUCK/FAIL-FAST.
(#401 staleness-invalidation handles STALE FAILURES; this is the distinct "no record at all" case.)

**Evidence it's a framework gap, not agent quality:** the framework ALREADY drives a deterministic
playwright browser pass for VISUAL fidelity (`visual_fidelity.py:632-736` — chromium launch +
self-heal `#234`, token-alias injection `#103` so authed routes render, blank-shell probe
`_CAPTURE_BLANK_PROBE`, auth-bounce detection). It navigates the same routes ui_flow cares about,
but records visual-similarity, NOT `validation:ui_flow`. So the capability exists; it's just not
wired to produce ui_flow records.

**Fix design (generalizable, all apps):** make ui_flow recording DETERMINISTIC + framework-owned,
reusing the visual pass's per-screen render result. After `_maybe_run_visual_fidelity()` runs
post-api_smoke (framework_validation.py ~863, i.e. BEFORE the delivery-gate ui_flow check), write a
`validation:ui_flow:<screen>` record for each navigated screen: PASS if it rendered (not in
`blank_screens`/`auth_redirected`), FAIL otherwise. Flow-name matching to the gate's critical flows
is already suffix-folded (`#285`). This removes the verifier dependency for the #1 wedge class while
reusing proven infra (no new browser code). Idempotent with the verifier path (timestamped,
latest-wins per `#357`). Requires: expose the visual pass's blank/bounce per-screen result to the
caller, + a hub `record_validation_result('ui_flow:<name>', status, metadata={check:ui_flow,flow})`.

**Go/no-go:** implement once r23 gives the definitive signal — if r23 WEDGES on ui_flow_missing
(verifier never records) it's confirmed fatal; if r23 clears (verifier eventually records) the gap
is tolerable-but-flaky and the deterministic recorder still removes the flakiness. Either way it's
the right generalizable fix; hold the big change until r23's evidence lands (avoids a speculative
unvalidatable change mid-run).

## CONFIRMED generalizable class — delivery-gate STALE false-failures (2026-08-02, r23 live)

r23 evidence widens the ui_flow finding into a CLASS: the delivery gate false-fails on STALE /
pre-fix state, across multiple deliverability checks — not one-off bugs.
- **ui_flow** (#401 fixed): stale FAILURE record older than the latest build → false "failed".
- **frontend_fallback** (NEW, confirmed r23): gate flagged **7× deliverability_frontend_fallback_page**
  while the CURRENT frontend has **0 fallback pages** (25 pages, 0 markers, both worktree + merged
  trees) AND `build:frontend: PASS (…, 0 fallback pages)`. So the gate read stale/old fallback state,
  not the current build. Trend 2→2→1→7 = converged then a fresh eval re-flagged stale state.

**Generalizable fix (the #1 one-shot-blocker class):** every delivery-gate deliverability check must
reflect the CURRENT build, not a pre-fix snapshot/record. Two complementary moves:
  1) **Staleness-invalidation gate-wide** (extend #401 beyond ui_flow): a deliverability FAILURE
     whose evidence predates the latest successful build validation is demoted to "re-verify", never a
     hard fail.
  2) **Deterministic re-derivation**: where a check RECOMPUTES from a tree/records (frontend_fallback
     audits pages; ui_flow needs a browser pass), ensure it reads the CURRENT integration tree and
     re-runs post-build (framework-owned), removing the verifier-LLM dependency (see the
     ui_flow-determinism design above — same root: gate trusts stale/agent-produced state).

TODO before implementing: scope frontend_audit's `routed_fallback_page_blockers` /
`_is_generic_fallback_page` — is the 7-vs-0 gap a stale RECORD or the audit reading the WRONG/older
tree (possible #400 lane-merge tie-in)? Fix accordingly (staleness-demote and/or current-tree read).
Hold the change until r23's endgame confirms wedge-vs-clear (don't churn mid-run).

## CORRECTION (2026-08-02, deeper scope): frontend_fallback ≠ stale-record; it's cycle-churn

Scoping showed frontend_fallback RECOMPUTES from the current tree (deliverability.py:347 →
routed_fallback_page_blockers(app_root/frontend/src), rglob *.jsx). r23 fired 7 flags in ONE eval
with 0 in the 4 surrounding evals — a transient spike coinciding with "BACKEND SKELETON generated"
(a mid-run regeneration cycle). So it is NOT the ui_flow stale-RECORD class; it's the gate catching
the tree mid-transition during a regen/rebuild cycle. So the "generalized staleness-demote gate-wide"
idea is WRONG for frontend_fallback (it recomputes correctly; it just needs the eval to run on a
settled tree). Two distinct problems remain, not one class:
  * **ui_flow**: verifier-produced records → determinism fix (framework-owned browser recording).
  * **cycle-churn**: a delivery-attempt/gate eval that runs while a regen/rebuild is mid-flight
    catches a transient tree → false flags. Real question: WHY does a backend-skeleton REGEN happen
    mid-delivery + does it reset frontend progress (a churn/regression), or is the eval just racing an
    in-flight rebuild? Needs r23 endgame evidence + a look at what triggers the late regen.
Do NOT implement a blanket staleness-demote; investigate the regen/eval race first (evidence-driven).

## Residual UI-fidelity gap — next target (2026-08-02, evidence: r5 real code)

After #406 (route-sprawl) + #407 (NOT-NULL defaults), the remaining "UI 几乎完全一致" gap
(r5 visual 0.10–0.15 vs 0.65) traces to TWO roots, both needing #24's post-#406 scores to size
and one needing a user decision:

1. **Wrong endpoint binding (rank-7, generalizable).** r5 `BrowseHomePage.jsx` (the /browse
   catalog page) fetches `/api/my-list`, not `/api/titles` → shows the wrong data, can't match
   the reference. NOT `backfill_page_apis` (leaves no-name-match pages empty; doesn't mis-bind)
   — it's an LLM-declared `apis_used` / floor default. Candidate fix: a browse/home/catalog page
   with no name-matched endpoint should bind the PRIMARY CONTENT collection (`_primary_content_
   model`, cf #380), not a secondary user-scoped one. Needs care (semantic) — validate on #24.

2. **Single-collection floor vs multi-row reference (needs user go-ahead).** The projected floor
   renders ONE list from ONE endpoint; a Netflix browse needs multiple genre RAILS + a hero.
   That is structured-page-projection (frontend_page_projector, removed 2026-06-11 by user
   decision — do NOT reintroduce without explicit approval). This is likely the dominant fidelity
   ceiling; raise with the user before building.

Decision rule: measure #24's post-#406 visual scores first. If a real page (e.g. /browse) now
scores much higher → route-sprawl was the main issue, iterate on #1. If still low → the
single-row floor (#2) is the ceiling → user decision on structured projection.
