# env-gen kickoff-meeting refactor — plan

Living planning doc for the 2026-06-02 refactor. Captures the
phase-cleanup status, the target architecture, and the sequencing
plan so a reviewer can follow along.

## Status snapshot

**Phase machinery removal (in flight)**

| Layer | State | Notes |
| --- | --- | --- |
| `_role_gate.py` (allowlist + runtime gates) | ✅ unconditional | Drops `phase`/`phase_threshold` params + byte-identical message contract |
| Runtime hubs (schema_hub, apihub, mcp_registry, gate_registry, story_hub, codehub, runhub, eventhub, visual_similarity, deliverability) | ✅ unconditional | All `if _phase >= X.X:` wrappers removed; gates always on |
| `configurable_agent.py` | ✅ | Phase injection + per-phase template overlay deleted |
| 6 v3 prompt templates (design / backend / database / frontend / verifier / orchestrator) | ✅ | `{% if phase >= X.X %}` blocks collapsed; macros renamed |
| `elaboration_phase.py` + `_role_gate_trace.py` | ✅ deleted | |
| 38 `test_phase_*.py` + helpers | ✅ deleted | |
| `docs/{progressive_elaboration_refactor, phase_*, phantom_runtime_registry}.md` | ✅ moved to `docs/historical/` | `historical/README.md` explains the move |
| `live_monitor_server.py` codehub_open_pr comment leftover | ✅ replaced |
| Smoke import | ✅ | All hubs + `_role_gate` import cleanly under `dt` interpreter |
| Full pytest sweep | ✅ | **1803 passed, 0 failed** (2026-06-02). Three rounds of test fixes: legacy `agent="design"`/`"database"` actor IDs flipped to `"backend"` for registration calls (~12 files); `human_user_id="test_user"` added to HubRegistry() in human-chat tests (~9 files); direct `eventhub.publish_human_message()` calls in tests got `from_user="test_user"`; obsolete `test_o14_chunk1_caller_kwarg.py` deleted (tested pre-gate intermediate state). One benign socket-timeout warning in `test_run_log_stream.py` is pre-existing, unrelated. |

**Stashed for later** — `stash@{0}` Q1 read-gate WIP (`memory-bank/<peer>/` cross-agent file-tool gate). Resumes post-refactor.

## Target architecture — 7-agent core roster

User directive 2026-06-02: drop coupling, fewer agents.

| Agent | Scope | Replaces (current) |
| --- | --- | --- |
| **orchestrator** | Project management + kickoff meeting host + planning + milestone gate | (unchanged) |
| **design** | UI/UX only (spec.ui.json + design/README.md UI sections + reference image analysis) | Loses `spec.database.json` + `spec.api.json` ownership (already removed in v3 prompt) |
| **frontend** | UI implementation (React + Vite + Tailwind) | (unchanged) |
| **backend** | Backend (Express + JWT) + database (PostgreSQL schema + seed) merged | Absorbs the demoted `database` lane |
| **verifier** | Testing: contract checks (api_smoke) + UI smoke + visual fidelity (SSIM) + release_readiness. Visual review folds in here. | Absorbs `visual_reviewer` |
| **debugger** | Bug triage + fix plan + work assignment (the bug-level orchestrator) | Rename of `bug_triage_orchestrator` |
| **knowledge** | Cross-run pattern memory + context retrieval | (unchanged) |

**Removed (resident_lanes deleted; behavior folded as noted):**
- `database` — backend owns schema; backend may still spawn ephemeral `database_worker` via `define_team_agent` when seed work is heavy
- `architect_reviewer` — design-review function moves into orchestrator's kickoff meeting + milestone gate
- `visual_reviewer` — verifier handles visual fidelity (SSIM cross-check + critical-route screenshots)

**Tool / bundle / prompt impact** — agents_config.yaml resident_lanes list shrinks from 10 → 7. The 3 deleted profiles + their tool_bundles + workflow_policies are removed wholesale (no shim, no back-compat).

## Kickoff meeting flow

**Trigger**: orchestrator wakes on `project_start` (or equivalent) with raw user requirements.

**Step 0 — orchestrator preflight (solo).** orchestrator parses raw
requirements into a concise project brief (1–2 paragraphs + bullet
constraints). This becomes the agenda for the meeting.

**Step 1 — broadcast kickoff_request.** orchestrator creates a WorkHub
`page(kind='kickoff', id='kickoff_M1')`, posts the agenda, and
broadcasts `kickoff_request` to all 7 agents (incl. itself). Each
attendee gets the brief + their own contribution slot.

**Step 2 — agents draft their section in parallel.** Each agent reads
the brief and posts a draft section via `workhub_add_meeting_decision`:

| Agent | Section |
| --- | --- |
| design | `contract/ui_outline.md` — page list, primary interactions, reference-image map |
| backend | `contract/api.md` (endpoint list + I/O schema sketch) + `contract/data_model.md` (entities + key fields) + `contract/auth.md` (auth model + multi-tenancy rules) |
| frontend | proposed component inventory + state-shape outline |
| verifier | acceptance criteria per critical user flow (machine-checkable predicates) |
| debugger | (skip in M1 — only activates after first bug surfaces) |
| knowledge | retrieve relevant prior-run patterns (e.g. previous JWT auth scaffolds) |

**Step 3 — orchestrator synthesizes.** Reads all 6 drafts, resolves
conflicts via a deterministic arbitration table:

| Conflict | Authority |
| --- | --- |
| api shape vs frontend usage | backend wins (frontend revises) |
| api shape vs data model | backend wins (both sides) |
| ui pages vs user flows | design wins |
| test strategy coverage gap | verifier always revises own |
| tiebreak | alphabetical agent_id |

Orchestrator writes 4 contract files into `contract/` (workspace
root) and the M1 milestone page:

- `contract/api.md`
- `contract/data_model.md`
- `contract/ui_outline.md`
- `contract/auth.md`
- `workhub_page(kind='milestone', id='M1')` — goal, acceptance criteria,
  task tree root reference, related contract sections

**Step 4 — workflow as workhub task tree.** orchestrator creates the
M1 task tree:

- Each task has `agent` (owner) + `depends_on=[task_ids]` + `kind`
- Tasks with empty `depends_on` are ready → orchestrator broadcasts
  `task_ready` to their owners
- Tasks with deps wait; orchestrator's tick re-evaluates after each
  `task_done` event
- Concurrency: unlimited within the ready set (agents pace
  themselves; verifier may run while frontend builds Phase A)
- Mid-stream mutation: any agent can `workhub_create_task` to add
  follow-ups (review, spike, bug fix); debugger uses this for bug
  remediation plans

**Step 5 — kickoff close.** orchestrator calls `close_meeting` on the
kickoff page; emits `kickoff_complete` event → milestone work
proceeds.

**Spiral: M2+ kickoffs.** When M(N) completes (all tasks done +
verifier signoff), orchestrator opens `kickoff_M(N+1)` — same
protocol but with prior contracts + milestone-page evidence carried
in as input. Agents propose what changes; orchestrator synthesizes
the new contract delta + M(N+1) page.

**Fallback (handshake circuit breaker)**: if any agent misses the
kickoff_request deadline (T=600s nudge, T=1200s timeout), orchestrator
synthesizes from the available drafts + a templated fallback section
+ writes `kickoff_fallback_used: true` into:
1. workhub_page metadata
2. ROADMAP frontmatter
3. eventhub `kickoff_fallback_used` event

All three sites are written atomically via `close_meeting`. Provides
3 grep-points for incident analysis.

## Workflow + milestone model

**WorkHub becomes the workflow state machine.**

- Milestones = `workhub_page(kind='milestone')` — orchestrator-hosted,
  mutable, the source of truth for "what's M1 about + when is it done"
- Tasks = `workhub_task(milestone_id, agent, depends_on, kind, status)` —
  status: `pending` → `ready` → `claimed` → `done` / `blocked`
- Concurrency from `depends_on` is implicit — orchestrator only
  publishes `task_ready` for tasks whose deps are all `done`
- Mid-flight modification: anyone can `workhub_create_task` (e.g.
  verifier creates a "fix nav bug" task assigned to debugger);
  orchestrator's tick picks it up at the next sweep

**No separate workflow DSL.** The task tree IS the workflow. No yaml
manifest, no compiled state machine. Mutability cost = zero.

## UI progress bar (live_monitor)

Live_monitor frontend gets a top bar:

```
Facebook Clone — M2 of 4  [████████░░░] 73%   stage: impl (3 / 7)
```

- **Milestone count**: from `workhub.list_pages(kind='milestone')`
- **Milestone progress %**: `done_tasks / total_tasks` of the current
  milestone's task tree
- **Stage**: `kickoff` → `impl` → `verify` → `merge` → `done` —
  driven by event tags orchestrator emits on phase transitions

Animation: smooth-tween on % updates; pulse on stage transition; red
flash on blocker count > 0 (with click-through to the workhub page
listing blockers). "Fancy" per user — Tailwind gradient + glowing
ring on the active stage chip.

## Cleanup discipline (user directive)

**No fallback. No back-compat.** Across the refactor:

1. Drop legacy default values that point to phantom IDs (e.g.
   `HumanConsole` no longer falls back to `"human_user"` — empty
   default + EventHub gate)
2. Drop `try: import_legacy except: use_modern_default` patterns
3. Drop `if version < N: old_path else new_path` branches
4. Delete tests for removed behaviors entirely (don't gate them with
   `pytest.mark.skip`)
5. Delete commented-out code referenced by deleted features
6. Update prompts / docs to talk about the new world only — don't
   reference removed phases or removed agents

If a caller breaks because of this, fix the caller; don't shim the
removed feature.

## Sequencing plan

**Phase A — finish phase cleanup (✅ DONE).**
1. Resolve remaining pytest failures (HumanConsole publish-side
   breakage in tests that used `human_user` default)
2. Final sweep for `from .elaboration_phase` or `_role_gate_trace`
   residue
3. Commit phase-cleanup as a single "remove phase machinery" PR

**Phase B — agent roster reduction (✅ DONE 2026-06-02, 1776 passed).**
Roster reduced 10 → 7 (orchestrator/design/backend/frontend/verifier/debugger/knowledge). Tool bundles seed/data_engine/schemahub moved to backend; vision/reference/visual_review moved to verifier. v3 prompts for removed agents deleted; bug_triage_orchestrator renamed to debugger.

**Phase B-fix — review punch-list (✅ DONE 2026-06-02, 1783 passed).** Reviewer caught that Phase B's structural moves didn't propagate to gate `allowed_set` literals + prompt routing + tool defaults — tests passed with **legacy identities**, masking the dead refs. Then caught a follow-up: the v1 invariant excluded `prompts/` + `tools/` by design, so dead routing in design_agent.j2 + finish() tool description + mcp_registry_tools.py:102 + test_pipeline_edge_cases.py stayed live. Fixes shipped in two rounds:
- **Invariant test v1** (5 cases) — hub-layer `allowed_set` / `attendees` / `runtime_name` literals + subscription/workflow edges.
- **Invariant test v2** (11 cases total) — adds: prompt scans (`notify=[...]` / `to_agent=...` / `assignee=...` / `{"id": "<agent>"}` peer entries), tool phantom-default scans (`_agent_id ... or "<name>"`), AND named-constant resolution for `allowed_set=_FOO_ALLOWED`. Documented template placeholders (`parent` / `peer_workers` / etc.) explicitly allowlisted. Closes the class for prompts + tools.
- **Gate authorities re-pointed**: `submit_design_review` → `{orchestrator}` (the kickoff/milestone host); `submit_visual_review` → `{verifier}` (absorbed visual fidelity); `register_seed_data` → `{backend, database_worker}` (dropped legacy `database`); `register_visual_review_task` attendees → `["verifier"]`. `_REGISTER_STORY_ALLOWED` tightened to `{orchestrator}` (dropped reserved-future `product` / `planner` per no-phantom rule).
- **Phantom defaults removed** in `visual_review_tools.py` + `seed_tools.py` + `mcp_registry_tools.py:102` — all `or "<phantom>"` defaults dropped, caller must inject `_agent_id` (empty falls through gate to system path).
- **Prompt residue**: orchestrator + backend prompts purged of `to_agent='database'` / "Database Agent finished schema" / `assignee='database'` narratives. design_agent.j2: 7 `notify=['database',...]` → `notify=[...]` without database, peer entries for `database` + `architect_reviewer` dropped (merged into orchestrator's peer entry), narrative AWAIT references rewritten to orchestrator. knowledge_agent.j2 + verifier_agent.j2: database peer dropped. analysis_worker_agent.j2 bug_triage_orchestrator → debugger. finish() tool DESCRIPTION rewritten to document the 7-lane roster + correct routing examples.
- **Test enshrinement** (reviewer's #4): test_pipeline_edge_cases.py ApiHubRequestReviewLifecycleGate stopped using `architect_reviewer` as live-agents-provider fixture; uses `verifier` instead.
- **v2/ directory cleanup**: 9 unused v2 prompts deleted; only `v2/orchestrator_agent.j2` survives as a library import for v3's Cutover discipline blocks (will be inlined or replaced in Phase C). Stale comments in `agents_config.yaml` + `story_hub.py` updated.
- **.gitignore**: `agent/tmp/` + `/tmp/envgen_demo/` added; existing runtime scratch dirs removed from working tree.
- **Test churn**: ~12 test files updated to use new gate identities (`architect_reviewer` → `orchestrator`, `visual_reviewer` → `verifier`, `database` → `backend`); 4 obsolete prompt-content tests retired (database-only seed prompts, deleted v2 prompt-pinned cases).
1. Rename `bug_triage_orchestrator` → `debugger` (yaml + prompt + tool
   bundle + agent_subscriptions + tests)
2. Delete `database` resident_lane entry from agents_config.yaml +
   delete `database_agent.j2` (backend prompt absorbs the seed-data
   guidance)
3. Delete `architect_reviewer` resident_lane + prompt + bundle +
   subscriptions
4. Delete `visual_reviewer` resident_lane + prompt + bundle +
   subscriptions; absorb SSIM critical-route checks into verifier
5. Keep `knowledge` as-is
6. Update orchestrator + design + frontend + backend + verifier v3
   prompts to drop references to removed peers

**Phase C — kickoff meeting runtime.**
1. WorkHub primitives: `create_meeting`, `add_meeting_decision`,
   `close_meeting` + tools
2. Pure-Python helpers: `roadmap_validator`, `cross_check_suite`,
   `arbitration_table` (modular, no LLM)
3. `Orchestrator.run_kickoff(milestone_index, prior_artifacts=None)` —
   broadcast-and-collect with T=1200s timeout + 3-surface fallback
   evidence
4. Per-agent kickoff_response prompts (design / backend / frontend /
   verifier / knowledge)
5. orchestrator synthesis prompt → write 4 contract files +
   milestone page + initial task tree
6. Wire `run_kickoff(1)` into orchestrator boot before first
   `task_ready`

**Phase D — UI progress bar.**
1. New live_monitor endpoint `GET /api/projects/<id>/progress` →
   `{milestones: [...], current: {index, name, pct, stage,
   blockers}}`
2. Frontend top-bar component (React + Tailwind) consuming the
   endpoint via SSE (or 5s poll fallback)

**Phase E — Q1 read-gate (resume from stash).**

Each phase ships as its own landable PR; phases B+ can be
independently reverted. Tests stay small per user directive — no
exhaustive matrices, just close-by-construction regression tests for
each new mechanism.

## Open decisions / clarifications

- **Contract files: 4 separate vs 1 combined?** Plan above ships 4
  separate; agents only need to read their section. Reviewer: flag if
  combined is preferred.
- **Task concurrency cap?** Currently unlimited within `ready` set.
  If an agent runs > N concurrent tasks and quality drops, add a
  per-agent `max_in_flight=N` flag.
- **kickoff_fallback_used policy.** First fallback in a project =
  WARNING. Second fallback = orchestrator pauses + asks human
  (user/operator) via `publish_human_message` for direction. Worth
  formalizing as a `degraded_mode` flag.
- **debugger trigger.** Activates on `verifier/bug_found` event from
  verifier (existing channel). Does debugger participate in M1
  kickoff? Plan above says no — only joins from M2 onwards once
  there's bug history to plan against.

---

**Reviewer notes**: feel free to push back on any of the above before
or during implementation. The plan is the source of truth; if a
direction shifts mid-stream, update this doc first so the new state
is visible.
