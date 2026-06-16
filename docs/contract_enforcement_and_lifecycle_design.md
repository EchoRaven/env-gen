# Contract Enforcement, Release Lifecycle & Robustness — design proposal

> Grounded in a 6-dimension study (2026-06-05) of how the env-gen pipeline + hubs
> enforce things TODAY (code vs prompt). Goal: move constraints from *prompt
> instructions* to *code-enforced invariants* — the "API-contract spirit" — and make
> the milestone→release→incremental-completion model and multi-agent robustness real.
> Pairs with `docs/target_env_architecture.md` and the
> `feedback_envgen_api_consistency_by_construction` principle.

---

## 0. The core insight: three representations of the contract, only two reconciled

The pipeline holds the API/data contract in **three** places:

1. **The REGISTRY** — APIHub endpoints/tables/consumers + WorkHub pages. *Strongly* code-gated at write time (role gates, referential integrity, breaking-change detection, coverage).
2. **The DESIGN** — kickoff drafts. Cross-checked at kickoff (`api_vs_frontend`, `api_vs_data_model` fail kickoff on mismatch).
3. **The CODE** — the generated files (routes, SQL, `api.js`, MCP tools). **Only partially reconciled:** SQL-DDL ↔ registered-tables IS a hard delivery gate; backend-routes ↔ registered-endpoints is a **warning only**; **frontend-calls ↔ endpoints is NOT checked at all**; MCP-tools ↔ endpoints not checked.

**The whole "API-contract spirit" reduces to one move: make CODE a fully-reconciled third representation, with hard gates that `{registry} ≡ {code}` across every layer — and, better, generate the contract surface *from* the registry so the code can't drift in the first place.** Your example ("frontend uses API X ⇒ must be registered, enforced by code") is exactly the missing CODE-side gate.

---

## 1. What's ALREADY code-enforced (we extend, not reinvent)

Credit where due — the substrate is strong:

- **Hub writes are atomic + audited** (fcntl-lock, version counter, `os.replace+fsync`); `_meta` is write-protected. The one invariant that *structurally* cannot be violated.
- **Role gates** raise `PermissionError` on the owner-write methods (`register_endpoint` {backend,orchestrator}, `register_table`, `record_api_test` {verifier}, `RunHub.record_probe` runtime-only — agents cannot fabricate evidence).
- **Referential integrity** at write time: `register_consumer`/`register_table_consumer` refuse a consumer for a non-existent endpoint/table; `CodeHub.open_pull_request` requires `linked_apis`∈APIHub, `linked_tasks`∈WorkHub, ≥1 task, ≥2 reviewers, real git branch.
- **Coverage IS blocking at delivery** (Cutover 19): every registered endpoint/table/MCP-tool must have a *registered* consumer, else `dead artifact` blocks delivery.
- **Delivery gate** hard-requires artifacts + hub topology + **SQL-DDL ↔ registered-tables alignment** + runtime evidence (api/ui smoke pass, RunHub success, zero failed probes).
- **Kickoff bidirectional alignment**: `api_vs_frontend` fails kickoff if a design `api_call` targets an undefined endpoint OR an endpoint has no UI consumer.
- **Finish gates** (deterministic block/continue): `HubConsistencyPolicy` (wrote code ⇒ must own the hub entry), `ClaimAssignedTasksPolicy`, `RequiredFilesPolicy`, `kickoff_endpoints_implemented` (owned endpoints must be terminal). `LaneIdleCircuitBreaker` tier-3 takes a *deterministic* action so downstream `depends_on` always unblocks.

---

## 2. Theme A — Contract consistency by **construction** + **code-derived** gates

### A1. Deterministic projection (can't drift) — *prevent*
Generate the contract *surface* FROM the registry, like B1 already does for the DDL. The LLM writes business logic, not the contract surface.

| Artifact | Project from | Status |
|---|---|---|
| `init/01_init.sql` | registered tables | ✅ done (B1) |
| `models.py` / `schemas.py` | registered tables + endpoint schemas | **propose** |
| `api.js` method-per-endpoint skeleton | registered endpoints (+ `response_key`) | **propose** |
| MCP `@mcp.tool` stub-per-endpoint | registered endpoints | **propose (Phase 3)** |

Implement as deterministic runtime emitters (siblings to `_generate_database`), so DDL ≡ ORM ≡ schemas ≡ api.js ≡ MCP-tools by construction.

### A2. Code-derived reconciliation gates (catch drift the LLM still creates) — *detect*
Today `coverage_audit`/`contract_extract` derive the consumer graph from **`register_consumer` calls**, and only extract **backend routes + SQL** (Express/Postgres-hardcoded). Extend to parse the *actual* code and reconcile against the registry, as **hard** delivery checks:

- **Frontend-call extractor** (the centerpiece — your example made real): AST/regex parse `fetch`/`axios`/`api.js` calls in `app/frontend/**` → `{method, path}`. New hard check `frontend_call_unregistered`: **every frontend call MUST match a registered+implemented endpoint** (after path-normalize). And **derive consumers from code**, so a real call counts as a consumer (kills false-positive "dead endpoint") and an endpoint called by no code is flagged.
- **Promote backend-route ↔ endpoint from WARNING to ERROR** (today `_validate_contract_alignment` only warns) — symmetric with the table-DDL check that's already hard.
- **MCP-tool ↔ endpoint extractor** (Phase 3): every `@mcp.tool` maps 1:1 to a registered endpoint.
- **Make `contract_extract` stack-pluggable** (register extractors keyed by detected stack) — it's Express-hardcoded today and "silently wrong" on FastAPI (our new target!). **This is a blocker for the retarget** — without it, FastAPI routes read as "missing endpoint".
- Re-run `api_vs_frontend`/`api_vs_data_model` against the **final** hub state at delivery, not just kickoff drafts (endpoints added during impl aren't re-validated today).

### A3. Harden the registry gates — *close the holes the study found*
- **Close the empty-actor fallthrough** on contract writes: `require_allowed_actor` admits any `agent=''` caller, so role gates are advisory for identity-less writes. Inject the calling agent id at the tool layer (or raise on blank) for `register_endpoint`/`register_table`/`record_api_test`/`merge_pull_request`/`create_release`.
- **`status='implemented'` must be evidence-guarded**: today it's a free-form string — an endpoint goes "implemented" (fires events, completes the WorkHub task) with **zero** evidence. Require a `codehub_commit` touching the route file OR a passing `record_api_test` before accepting `implemented`; make the lifecycle a real state machine (`defined→implemented→tested(+deprecated)`); exclude `deprecated` as a gate-escape unless reason+replacement registered.
- **Make `response_key` required** for object-response endpoints (the frontend's extraction contract); **make the consumer schema-subset check mandatory** (today opt-in via `expected_schema`).
- **Hard breaking-change gate (opt-in)**: a breaking change to an endpoint with live consumers requires an approving `api_review` (today: recorded + notified *after* the write, never blocked).
- **Fail-closed, not fail-open**: several gates `swallow exception → return None` (silently disable) on a hub error — block-once-with-event instead.

---

## 3. Theme B — Milestone prototype → **release** → incremental completion

**Study verdict: M2..Mn is aspirational scaffolding that never executes.** `milestone_index` is hardcoded `=1`; nothing increments it or re-runs kickoff; there is **no version/release primitive**, **no contract freeze**, **no cross-milestone regression**; `deliver_project` is *terminal* (shuts down all agents — the structural opposite of "ship a release then keep building"). "Prototype first" is half-built (M1=skeleton encoded in `roadmap_validator`); "then incrementally complete" has no runtime.

### B1. Milestone-advancement lifecycle
Split today's terminal `deliver_project` into **`ship_milestone(n)`** (gate passes → *advance*: increment `milestone_index`, re-run `start_kickoff` for the next slice, keep agents alive) vs **`deliver_project`** (final). An orchestrator loop drives M1→Mn until the roadmap is complete or budget.

### B2. ContractRegistry versioning + superset-only evolution
- Stamp every `register_endpoint`/`register_table` with the `milestone_index` that introduced/last-touched it; persist an **immutable per-milestone contract snapshot** at `finalize_kickoff`.
- `roadmap_validator` check: **M{n>1} may only ADD or compatibly-extend** an M{<n} endpoint/table (forbid silent removal / incompatible change) — making "M2 extends M1's contract" a mechanically-enforced **superset** relation. This is "version pinning" + "gradually optimize based on release versions" as code.
- A first-class **release primitive**: semver/`M{n}` tag on each ship + a versioned release record (`docs/releases/RELEASE_M{n}.md` + hub release event + optional git tag).

### B3. Cumulative regression gate
Accumulate **all prior milestones' `acceptance_predicates`** into a persisted regression suite keyed by `generation_id`; the delivery gate (+ `synthesize_task_tree`'s `validate_*` emission) requires the **full cumulative** set to pass — so completing M2 can't silently break M1's critical flows. Promote `ROADMAP.md` from advisory markdown to the **enforced baseline** the validator loads for M{n>1}.

---

## 4. Theme C — Multi-agent robustness

**Study verdict: the deterministic recovery exists but is largely unwired.**

- **Wire the dead merge-conflict resolvers**: `resolve_merge_conflict_via_strategy` + `revert_commit_on_branch` have **ZERO non-test call sites** — recovery relies on a resident LLM calling `codehub_resolve_merge_conflict` (smoke #40: 508 orchestrator calls, *zero* conflict-resolutions). Add an orchestrator `merge_conflict` event handler (it already subscribes) that deterministically resolves after N failed LLM attempts.
- **Bounded auto-retry/re-create loop**: today `LaneIdleCircuitBreaker` tier-3 / `ClaimAssignedTasks` *fail/cancel* the stuck task to unblock downstream, leaving re-creation to the orchestrator LLM (silent fail-forward). Deterministically re-create the failed task once (retry-count on metadata) before surfacing a hard structural-failure event. *(This generalizes the B3 validation-retry need.)*
- **Promote AutoCommit failures to a finish-gate**: restage/commit/merge failures are *swallowed* (finish reports success even though work never reached integration — exactly smoke #2's empty-`agent/backend`). If `restage_written_files` staged 0-of-N or squash produced "nothing to merge" with non-empty `files_created` → block finish / emit a delivery-blocking event. *(My `restage_written_files` backstop is step 1 of this — make the failure loud.)*
- **Task-level `depends_on`**: today it's agent-level — the first `task_ready` marks an upstream "ready" permanently, so a downstream lane can start before the specific artifact it needs exists (the premature-validation race I hit in smoke #4). Gate on the specific upstream artifact (endpoint/table/commit) being registered.
- **Alive-but-stuck detector**: the silent-lane nudge only catches lanes with *zero* `agent_status`; a lane that heartbeats then wedges inside an agentic loop (never reaching `finish()`) escapes both the nudge and the per-finish breaker. Track per-lane wall-clock since last *productive* step (file write / hub-count increase) and escalate.
- **`KickoffBootstrapGate` should require the FULL finalize receipt**, not the first endpoint-or-task (today lanes can unblock mid-finalize against a partial contract).

---

## 5. Prioritized roadmap (folds into the retarget)

| Pri | Item | Theme | Why first |
|---|---|---|---|
| **P0** | Make `contract_extract` stack-pluggable (FastAPI routes + frontend calls) | A2 | **Blocks the retarget** — Express-hardcoded extractors read FastAPI as "missing endpoint" |
| **P0** | Frontend-call extractor + `frontend_call_unregistered` hard gate; code-derived consumers | A2 | Your exact ask; closes the biggest contract↔code hole |
| **P1** | Deterministic projection of `models.py`/`schemas.py`/`api.js`/MCP-tool stubs from registry | A1 | Prevents drift at source (consistency-by-construction) |
| **P1** | Promote backend-route↔endpoint to ERROR; re-run cross-checks on final hub state | A2 | Symmetric hard gate |
| **P1** | `status='implemented'` evidence guard + lifecycle state machine; close empty-actor write hole | A3 | "implemented" must mean implemented |
| **P2** | Milestone-advancement loop + contract versioning/snapshot + superset gate + regression gate | B | Makes "release → incrementally complete" executable + regression-safe |
| **P2** | Wire merge-conflict resolvers + bounded auto-retry + AutoCommit failure gate + task-level depends_on | C | Convergence robustness |

**Sequencing with the architecture retarget:** P0 items are prerequisites for validating the FastAPI/forgingground retarget (Phases 1-4) — without the stack-pluggable + frontend-call extractors, the delivery gate can't even check the new stack's contract↔code alignment. So P0 lands alongside Phase 3-4; A1 projection lands as each lane's surface is generated.

---
*Generated 2026-06-05 from a 6-agent study of apihub/workflow_policies/coverage_audit/kickoff/orchestrator/hubs. Mechanism names + file:symbol citations are from that study; verify against current source before implementing.*
