# Post-kickoff pipeline — target architecture + stage plan

**Date:** 2026-06-03  **Author:** Claude (round-8h supervision loop)
**Status:** Living doc; supersedes ad-hoc patch plans starting at branch head `09699e68`.
**Anchors:** [`pipeline_supervision_charter.md`](pipeline_supervision_charter.md) §2-§5 (target SDLC + contract-first discipline) and [`plan_kickoff_refactor.md`](plan_kickoff_refactor.md) (roster + kickoff flow).

This doc covers what runs AFTER `kickoff_complete` fires. The kickoff machinery itself reached first-ever clean finalize at smoke #18 (2026-06-03 09:48) and is now considered stable; the downstream lane handoff has never worked end-to-end and is the active worksite.

---

## 1. Where we actually are (2026-06-03 PM, branch head `09699e68`)

Verified via direct workspace inspection on smokes #18, #19, #20.

| Phase | Status | Evidence |
|---|---|---|
| **Kickoff** (orchestrator chairs facilitator-led meeting; APIHub/WorkHub contract registered; 5 markdown docs landed) | ✅ stable | Smoke #18 finalize 65s; #20 finalize 79s; 4 endpoints / 2 tables / 6 tasks / 6 predicates / 0 failures |
| **Kickoff → implementation handoff** | 🟥 STRUCTURALLY BROKEN | `ImplementationBootstrapPolicy` requires `design/spec.{api,database,ui}.json` files; the (retired) design agent was the only writer; backend/frontend reject every `task_ready` with `design gate not ready` (smoke #20 nudge ×5, all rejected) |
| **Implementation** (backend/frontend reading hubs, writing code, opening PRs, recording artifacts) | 🟨 never reached | Blocked by row above |
| **Verification** (verifier records build:* + validation:* via `codehub_record_check`, fires bug events) | 🟨 never reached | Patch C tool exists (smoke #20 confirmed callable but no caller); verifier policy waits for explicit validation trigger that no upstream is producing |
| **Delivery gate** (`_validate_delivery_gate` aggregates RunHub + endpoint probes + visual review + seed + flow coverage) | 🟨 never reached | Code present at `orchestrator.py:1296-1607`; the gate never fired because lanes never produced inputs |

**Note on charter §9:** charter currently says "do not merge design+frontend"; code already merged (round-8e.1, predates the §9 reject). The current code state takes precedence; §9 needs an update or the merge needs to be reverted. **Open decision A** (see §6).

---

## 2. Target end-to-end pipeline

Single source of contract truth: **APIHub / WorkHub** (not the filesystem `design/spec.*.json` artifacts). Every gate that currently checks filesystem files must migrate to hub queries.

```
project_start
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ STAGE A — KICKOFF                                            │
│ runtime/kickoff/run_kickoff.py + facilitate.py + authoring.py │
│                                                              │
│  orchestrator.start_kickoff() → facilitator-led meeting      │
│  ↓                                                           │
│  finalize_kickoff()                                          │
│   - APIHub: register endpoints + tables + auth               │
│   - WorkHub: register tasks (assigned + depends_on)          │
│   - WorkHub: register predicates                             │
│   - EventHub: publish kickoff_complete                       │
│  ↓                                                           │
│  _author_kickoff_docs() — MILESTONE_M{n}.md + ROADMAP.md +   │
│                          BRIEFING_M{n}_{agent}.md            │
│                                                              │
│  STATUS: ✅ works                                            │
└──────────────────────────────────────────────────────────────┘
    │
    │ kickoff_complete event
    │ + workhub.task_created urgent events per assigned task
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ STAGE B — IMPLEMENTATION                                     │
│ resident lanes wake; backend/frontend produce code           │
│                                                              │
│ Bootstrap gate (NEW, replacing ImplementationBootstrapPolicy)│
│   ► Wake signal:  task_ready from orchestrator               │
│                   AND APIHub.has_endpoints(milestone=M{n})   │
│                       OR WorkHub.has_tasks(assignee=<lane>)  │
│   ► Not a wake:   filesystem files (retired)                 │
│                                                              │
│ Backend: reads APIHub endpoints + apihub_get_table data,     │
│   writes app/backend/ + app/database/, opens PR via          │
│   codehub_open_pr.                                           │
│                                                              │
│ Frontend: reads WorkHub pages + APIHub endpoints (for        │
│   api.js service layer), writes app/frontend/.               │
│                                                              │
│ Step pipeline auto-records artifact:* checks via             │
│ codehub.record_check on every file write.                    │
│                                                              │
│  STATUS: 🟥 blocked by stale design-spec gate (Stage 1 fix)  │
└──────────────────────────────────────────────────────────────┘
    │
    │ endpoint_implemented / table_implemented events
    │ + lane finish() → workhub_task status='completed'
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ STAGE C — VERIFICATION                                       │
│                                                              │
│ Trigger: orchestrator detects backend + frontend both        │
│   marked 'implemented' OR a validation-phase task_ready      │
│   carrying accepted_tags=['validation_phase'].               │
│                                                              │
│ Verifier:                                                    │
│   - docker compose up (runtime triggers run_start)           │
│   - codehub_record_check 'build:sql_syntax' /                │
│     'build:docker_build' / 'build:npm_install' /             │
│     'build:backend_start'                                    │
│   - run api_smoke + ui_smoke + ui_flow checks                │
│   - codehub_record_check 'validation:api_smoke' /            │
│     'validation:ui_smoke' / 'validation:ui_flow:<flow>'      │
│   - bug_create on failures (event-driven to debugger)        │
│                                                              │
│  STATUS: 🟨 unreached. Tool surface (Patch C) exists.        │
│         Trigger pathway (Patch B v2) exists. Needs Stage B   │
│         to actually produce something to verify.             │
└──────────────────────────────────────────────────────────────┘
    │
    │ verifier finish() with all checks 'success'
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ STAGE D — DELIVERY                                           │
│                                                              │
│ _validate_delivery_gate() composes:                          │
│   - required_files (app/{backend,frontend,database}/...)     │
│   - contract_alignment (APIHub vs code)                      │
│   - build_evidence (all build:* checks succeeded)            │
│   - validation_runtime (all validation:* checks succeeded)   │
│   - deliverability_aggregator (RunHub + probes + coverage    │
│     + seed + visual review + flow coverage)                  │
│                                                              │
│ Orchestrator lane calls deliver_project; gate enforces       │
│ ok=true; on success: complete_generation(success=true).      │
│                                                              │
│  STATUS: 🟨 unreached. Gate code present + sound by review.  │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Architectural invariants (non-negotiable)

Pulled forward from charter §2-§4 and the round-8h adversarial review:

| # | Invariant | How enforced |
|---|---|---|
| I-1 | **Contract lives in hubs, not filesystem.** APIHub owns endpoints + tables + auth; WorkHub owns tasks + pages + predicates. Filesystem `design/spec.*.json` is OBSOLETE. | Tests pin no policy reads files for bootstrap; code paths that read `design/spec.*.json` either delete or migrate to hub queries. |
| I-2 | **Bootstrap signal = `kickoff_complete` event + hub state.** Not file existence. | New `kickoff_bootstrap_gate` policy reads APIHub/WorkHub. Old `ImplementationBootstrapPolicy` removed. |
| I-3 | **No fallback path** (charter §8 + 用户原话 "fallback对系统不好"). Every gate failure is loud + actionable. | Existing `synthesize_fallback` only reachable on facilitator escalate; no silent retry / soft-degrade in the implementation path. |
| I-4 | **Closed-by-construction.** Every code fix has a unit test that pins the structural invariant the fix establishes. | Round-8h precedent: 51 new test pins across Patches A-D (Stage 1 adds ~10 more). |
| I-5 | **Vertical slices only.** Implementation produces a runnable slice each milestone; never "all backend then all frontend." | Backend + frontend tasks share a milestone DAG; verification runs against the slice. |
| I-6 | **Lane idle → loud, not silent.** A lane stalled past `idle_tick_count >= 6` (failforward) escalates; past 10 (halt) requires human. | `lane_idle_circuit_breaker` policy (already in place per agent). |
| I-7 | **Orchestrator dispatches task_ready for silent lanes** (round-8h smoke #19/#20 regression class). The runtime nudge (Patch B v2 wall-clock) is the safety net; the orchestrator LLM doing it via its prompt directive is the primary path. | New v3 prompt clause + new success_criteria + tests at `test_orchestrator_prompt_no_legacy_dispatch.py`. |

---

## 4. Stage plan (sequenced; each stage ships before the next starts)

### Stage 1 — Retire design-phase bootstrap gate (THE IMMEDIATE UNBLOCK)

**Why first:** structural deadlock between `ImplementationBootstrapPolicy` and the retired design agent. Stage 1 unblocks Stages 2-4.

**Scope:**

1. Remove `- kind: implementation_bootstrap` config blocks from `agents/agents_config.yaml` (backend at line 203-208; frontend at line 287-292). **Delete don't skip.**
2. Delete `ImplementationBootstrapPolicy` class + `_required_files_ready` helper + `_has_implementation_bootstrap_policy` + the `_implementation_bootstrapped` agent attribute from `workflow_policies.py`, `messaging.py`, `base.py`.
3. Add new `kickoff_bootstrap_gate` policy (~40 LOC in `workflow_policies.py`):
   - Decision: only accept `task_ready` from orchestrator
   - AND require `APIHub.list_endpoints()` non-empty OR `WorkHub.list_tasks(assignee=<lane>)` non-empty
   - Sets `_kickoff_bootstrapped = True` so subsequent calls fast-path
4. Wire `kickoff_bootstrap_gate` into the same backend/frontend yaml blocks the old policy lived in.
5. **Tests** (closed-by-construction):
   - `test_no_implementation_bootstrap_policy_in_config` — the obsolete kind doesn't appear in yaml
   - `test_kickoff_bootstrap_gate_rejects_when_no_apihub_contract` — pre-kickoff task_ready denied
   - `test_kickoff_bootstrap_gate_accepts_after_apihub_registration` — post-kickoff allowed
   - `test_design_spec_files_no_longer_required_by_runtime` — grep that no production code path checks `design/spec.{api,database,ui}.json` for bootstrap

**Out of scope:** the `design/` directory itself stays for now — `flow_coverage` / `deliverability` still read it; they degrade gracefully when missing (already proven by round-8h adversarial review). Stage 5 handles the cleanup.

**Acceptance:** smoke #21 reaches Stage B (backend writes `app/backend/` files; frontend writes `app/frontend/` files). Patches A/B/C/D test sweep still 2342+ green.

---

### Stage 2 — Validate Stage B (backend + frontend produce code)

**Why second:** Stage 1 removes the gate; this stage verifies the LLM actually writes code under the new gate.

**Scope:**
- Smoke #21 launch with branch head at Stage 1 commit
- Observe (Monitor + watcher): backend Lead emits >50 agent_status events; `app/backend/server.js` + routes appear; frontend emits >50 events; `app/frontend/src/` populated
- Per-lane prompt audit if either lane stays silent or writes <minimal scope
- Trace `codehub_record_check` calls: backend should record `build:sql_syntax` after writing schema; both should record `artifact:*` automatically via step_pipeline

**Acceptance:** smoke produces a complete `app/` tree matching the M1 walking skeleton (auth + posts + docker-compose). Verifier may not yet run (Stage 3 territory) but the implementation artifacts exist.

**Exit gate:** if the lanes still wedge for a NEW reason (e.g. prompt content, tool subset, hub permission), file as Stage 1.5 fix and re-run before Stage 3.

---

### Stage 3 — Validate Stage C (verifier runs build:* + validation:*)

**Scope:**
- After Stage 2 produces an `app/`, orchestrator must dispatch `task_ready` with `tags=['validation_phase']` or `phase='validation'` to satisfy `verifier_validation_trigger`
- Audit v3 orchestrator prompt: it should fire this dispatch when backend + frontend both mark `status='implemented'`
- Verifier runs `docker compose up`, records build checks, runs api_smoke + ui_smoke probes via RunHub
- All checks landed in CodeHub via `codehub_record_check` (Patch C)

**Acceptance:** smoke #21 (or #22 if iteration needed) shows verifier emitting agent_status, RunHub has a `last_successful_run`, CodeHub `list_checks(pr_id='main')` returns ≥6 entries (4 build + 2 validation minimum).

**Likely Stage 1.5 risk:** orchestrator prompt may need ANOTHER directive teaching it when to dispatch validation_phase task_ready (analogous to Stage 1's silent-lane recovery directive). If smoke proves it, file + fix.

---

### Stage 4 — Validate Stage D (delivery gate green; full pipeline closes)

**Scope:**
- After Stage 3 produces evidence, `_validate_delivery_gate()` should return `ok=True`
- Orchestrator lane calls `deliver_project(confirmation='CONFIRMED')`
- `complete_generation(success=true)` writes to checkpoint
- Live monitor shows `state='completed', rc=0`

**Acceptance:** ONE smoke produces a delivered M1 walking skeleton end-to-end. This is the charter §7 GOAL MET signal — the first such signal ever for env-gen.

**Anti-acceptance:** if `deliver_project` is called but the gate fails, surface every failed_check + iterate per check (each becomes a Stage 4.x fix).

---

### Stage 5 — Cleanup of stale `design/` references (post-GOAL-MET; deferrable)

Now that we've proven the hub-driven path works, retire the secondary stale references:

- `flow_coverage.py:63` reads `design/spec.ui.json` for critical_flows → migrate to WorkHub `list_pages(critical=True)` + per-page predicates
- `deliverability.py:109, 237` same data source → same migration
- `apihub.py:837 sync_from_design_spec(spec_path)` → DELETE (dead code post-kickoff)
- `orchestrator.py:885, 1510, 1568, 1815, 2175` `design_dir` checks → remove (gate report / suggestion text)
- Stale docstrings (`eventhub.py:317`, `base.py:211`, `verification_tools.py:1063, 1139`, `agent_interaction_tools.py:406`) → text-only sweep
- `agent/env_generator/llm_generator/specs/project_structure.py` `PROJECT_STRUCTURE['design']` → mark deprecated or delete

**Acceptance:** repo grep for `design/spec.` and `design_agent` returns only test-pin assertions about the retirement.

---

### Stage 6 — Charter §9 reconcile (governance-level)

Charter §9 still rejects the design+frontend merge; current code has done the merge. Either:
- (a) update charter §9 to reflect the merged reality + rationale for the round-8e.1 decision, OR
- (b) revert the merge (re-spawn design agent in agents_config.yaml + restore spec.*.json write responsibilities)

Decision required from user (see §6 Open Decisions).

---

## 5. Closed-by-construction test invariants (what we pin at each stage)

| Stage | Invariant pinned by | File |
|---|---|---|
| 1 | `ImplementationBootstrapPolicy` removed | new `test_implementation_bootstrap_retired.py` |
| 1 | `kickoff_bootstrap_gate` accepts iff APIHub has contract | new `test_kickoff_bootstrap_gate.py` |
| 1 | No production code path checks `design/spec.*.json` for lane bootstrap | grep-based test |
| 2 | Backend + frontend each produce ≥1 agent_status event within 180s of `kickoff_complete` | runtime integration test (or just smoke observation) |
| 3 | Verifier receives a `task_ready` carrying `tags=['validation_phase']` once both impl lanes mark `status='implemented'` | new orchestrator-prompt test pin |
| 3 | `codehub_record_check` called ≥6 times during a smoke (4 build + 2 validation) | smoke-log assertion (can be a Bash one-liner in `verify`) |
| 4 | `_validate_delivery_gate()` returns ok=True on a clean smoke | end-to-end smoke = the test |
| 5 | `grep -rE 'design/spec\.(api\|database\|ui)\.json'` matches only test files | grep-based test |

---

## 6. Open decisions from user

| ID | Decision | Default if no answer |
|---|---|---|
| A | Charter §9 reconcile: update §9 to reflect merged reality, OR revert the merge? | **Update §9** — the merge is in production code 4+ rounds and reverting would re-introduce the spec-drift adversarial cross-check (charter §9 rationale) that hasn't been a problem in practice |
| B | Should Stage 5 `apihub.sync_from_design_spec` be DELETED or kept as a migration helper for future external specs? | **Delete** — dead code per charter cleanup discipline (§6.C) |
| C | Stage 6 ordering — should it block Stage 1? | **No** — Stage 1 fixes a deadlock; §9 is governance. Run them in parallel. |

---

## 7. Resolved decisions — iteration loop architecture (D1–D5, user 2026-06-03)

User added the iteration layer that the original §2 was missing. Confirmed model:

> `project_start` → **Stage 0: global milestone plan** (M1..Mn from requirements) →
> **FOR each milestone N: [Kickoff_N → Impl → Verify → Deliver → Preview → Feedback]** →
> next iteration OR project complete

| ID | Decision | Implementation note |
|---|---|---|
| **D1** | Orchestrator drafts the global plan; other resident agents (backend/frontend/verifier) review and amend. PR-review pattern at project boot. | Stage 0 boots a tiny "plan_review_meeting" — orchestrator authors first draft, broadcasts for review, attendees post structured amendments, orchestrator finalizes. Far simpler than a full kickoff (no contract authoring, just milestone scoping). |
| **D2** | Kickoff for M_N reads accumulated user feedback + retro from M_{N-1} and may revise the global plan. The "user" includes both human users via live_monitor AND spawned user-simulator agents. | Add `plan_revision_section` decision kind to the kickoff meeting protocol; only fires when feedback signals scope/priority changes. Spawned user-sim is a new ephemeral role (see Stage 7). |
| **D3** | Stage E previews the running app to user via live_monitor port-proxy. | live_monitor reverse-proxies the frontend container's published port; UI shows a "Preview" pane with the live app + iframe sandbox. |
| **D4** | Stage F feedback mode is toggleable: default **sync** (user must signal "approve M_N → start M_{N+1}"); user can flip to **async** (timeout → auto next-milestone) via UI checkbox. | One env var (`ENVGEN_FEEDBACK_MODE=sync\|async`) + UI toggle that writes it. Sync blocks orchestrator main loop on a `user_feedback_received` event with budget cap (configurable, default 30min); async fires the same event from a timer. |
| **D5** | Feedback accepts BOTH free-text comments AND structured `change_requests`. | live_monitor surfaces 2 inputs: textbox + a small form (`{description, affects: [milestone\|feature\|file], priority: P0..P3}`). Both serialize into a single `milestone_retro` WorkHub page that the next kickoff reads. |

### Revised stage numbering (post-D5)

Stages 1-4 unchanged (M1 single-milestone close — necessary precondition).
NEW stages 5-9 cover the iteration layer; the original cleanup + charter-reconcile shift to 10 & 11.

| Stage | Goal | Depends on |
|---|---|---|
| 1 | Retire `ImplementationBootstrapPolicy` (immediate unblock) | nothing — START HERE |
| 2 | Smoke validates backend/frontend produce code under hub-driven bootstrap | Stage 1 |
| 3 | Smoke validates verifier records build:* + validation:* | Stage 2 |
| 4 | Smoke validates delivery gate green for ONE milestone | Stage 3 |
| **5** | **Stage 0 boot: orchestrator drafts global plan + attendee review (D1)** | Stage 4 — needs M1 close working first |
| **6** | **Milestone iteration loop driver** in `orchestrator.py` (M_N deliver → M_{N+1} start) | Stage 4 |
| **7** | **Preview + feedback UI** in live_monitor; spawned user-sim agent role (D3 + D2) | Stage 6 |
| **8** | **Feedback → next-kickoff handoff**: `milestone_retro` WorkHub page + kickoff prompt clause (D2 + D5) | Stage 7 |
| **9** | **Stage A plan-revision sub-flow** inside kickoff (D2) | Stage 8 |
| 10 | Cleanup stale `design/` references | parallel to Stages 5-9 |
| 11 | Charter §9 reconcile (governance) | parallel to all |

---

---

## 7. What's NOT in this doc (deliberately deferred)

- M2+ kickoff flow (re-kickoff at milestone boundary). Charter §3 covers it; no code work needed until M1 ships green.
- Knowledge agent quality rubric refinement. Operational, not architectural.
- live_monitor UI improvements. Orthogonal.
- Test-driven development of new agent prompts. Already covered by `superpowers:test-driven-development` skill + existing prompt-content test pattern.

---

*Update this doc first when the target shifts. The code follows the doc; the doc follows the user's intent.*
