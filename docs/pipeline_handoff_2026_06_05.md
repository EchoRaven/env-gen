# env-gen pipeline handoff — 2026-06-05

> Handoff doc for the next person. State after 9 structural fixes
> shipped to `haibotong-0527-hub-focus-and-tooling-cleanup` (head
> `272ec461`, pushed to `red-env-gen`).

## TL;DR

**Pipeline is structurally complete but produces incomplete environments.**

Kickoff → backend impl → frontend impl → integration merge → verifier
wake all work end-to-end. But across ~10 smoke runs **no run has yet
produced a complete `app/{backend,frontend,database}/` tree with
working `docker-compose up`**. The remaining gap is LLM-output
quality + missing database lane + no retry loop, not pipeline
plumbing.

Branch not merged to main. No release. No PR opened (would normally
go via `gh pr create`, but `gh` CLI is not available in this env).

## What works (verified across smokes #38-49)

| Stage | State |
|---|---|
| Kickoff (initial → comment → reply → facilitator → finalize) | ✅ runs to completion |
| `synthesize_task_tree` (backend + verifier validation tasks) | ✅ |
| `finalize_kickoff` registers endpoints to APIHub + tables to SchemaHub-via-APIHub | ✅ |
| Backend wakes on task_ready, claims impl tasks, writes Express+JS code | ✅ (variance: sometimes skips Dockerfile/package.json) |
| Frontend wakes, writes React/Vite UI | ✅ (variance: sometimes only writes `src/`, no `package.json`) |
| `merge_agent_branch_to_main` (agent/X → integration) survives untracked-file collisions | ✅ (Fix A) |
| Verifier woken on its own `task_created` events | ✅ (Fix G — was the longest wedge) |
| Verifier sees `docker_up` / `test_api` / `browser_navigate` in per-step surface | ✅ (Fix C+H — `_VALIDATION_FLOW` ALWAYS_INCLUDE) |

## What does NOT work yet

| Issue | Root cause | Evidence |
|---|---|---|
| **Database module never generated** | No lane owns `app/database/Dockerfile` / SQL. v3 merged design+database into backend, but backend prompt has no concrete "write database/" step. Compose file declares `services.database.build: ../app/database` but the dir doesn't exist. | Smoke #38-49: `app/database/Dockerfile` count = **0/10** |
| Backend file completeness | LLM follows recipe partially; sometimes ships only `src/`, no `Dockerfile`/`package.json`. No runtime guard checks "did backend ship all required files before finish()". | Smoke #49: `app/backend/` only had `src/` |
| Frontend file completeness | Same pattern. Variance: sometimes complete (#42), sometimes only `src/`. | Smoke #42 only run with `package.json` written |
| Verifier doesn't claim its own validate_* tasks | Tasks created (Fix E) and verifier wakes (Fix G) and recipe says to claim (Fix H), but LLM in practice calls `workhub_list_tasks` then ignores the claim step. | Smoke #48: 7 list_tasks, 0 claim |
| `docker_up` fails because dependent `app/<svc>/Dockerfile` missing | Symptom of all above + no retry loop. | Smoke #49: `lstat /tmp/.../app/database/Dockerfile: no such file or directory` |

## The 9 fixes already shipped (in chronological order)

All on branch `haibotong-0527-hub-focus-and-tooling-cleanup`. Suite 2451/0 throughout.

| # | Commit | Layer | Problem | Fix |
|---|---|---|---|---|
| A | `05ffef3f` | `auto_commit.py:merge_agent_branch_to_main` | git refuses merge when untracked memory-bank files would be overwritten | Parse stderr for the colliding paths, `git clean -f --` them, retry the merge |
| B | `05ffef3f` | `base.py:ACTION_STAGE_ALWAYS_INCLUDE` | per-step ranker drops `codehub_resolve_*` so orchestrator can't actually resolve conflicts | New `_CONFLICT_FLOW = {codehub_resolve_conflict, codehub_resolve_merge_conflict, codehub_force_merge}` pinned to action stages |
| C | `cbc5801f` | `base.py:ACTION_STAGE_ALWAYS_INCLUDE` | verifier sees `run_start`/`browser_navigate` in `focus_hub` return text but they're filtered out of actual tool schema | New `_VALIDATION_FLOW` (7→14 tools, see Fix H) pinned. Bundle-intersection means backend doesn't see browser_* |
| D | `90273f14` | `agents_config.yaml:verifier_validation_trigger` | policy keywords required literal `"validation phase"`, LLM wrote `"execute validation"` so it didn't match | Broadened to `validation`/`validate`/`api_smoke`/`ui_smoke`/`ui_flow`/etc |
| E | `743e34d8` | `schema_tolerance.py:synthesize_task_tree` | workhub had 0 verifier-assigned tasks after kickoff | Emit `validate_api_smoke` per endpoint, `validate_ui_smoke` per critical page, `validate_ui_flow` per critical flow — all owner=verifier with `depends_on=[impl_endpoint_task_id]` |
| F-bis | `f819686e` | `workflow_policies.py:VerifierValidationTriggerPolicy.allow_resident_wakeup` | task_created-for-self also suppressed | Read `message.payload` (not `inbox_msg["content"]` which is `str(dict)` repr) and admit if `assignee == agent_id` |
| G | `a5f540d8` | `messaging.py:_maybe_schedule_resident_message_wakeup` | even with F-bis, DependsOnPolicy fired next and blocked task_created | Move the task_created-for-self exemption UP to the messaging layer; skip all policies for that case. The task_created event is by definition a legitimate wakeup signal for the assignee lane |
| H | `69177aa4` | `verifier_agent.j2:verifier_task_prompt` + `base.py:_VALIDATION_FLOW` | recipe didn't mention claiming workhub-tracked tasks; flow set missing tools the recipe actually called | Recipe now starts with `workhub_list_tasks(assignee=verifier)` + claim, each validation step completes its matching `validate.*` task. `_VALIDATION_FLOW` extended from 7→14: docker_up/docker_status/test_api/apihub_record_contract_test/deliverability_check/bug_create/capture_webpage all added |
| I | `272ec461` | `docker_tools.py:DockerUpTool.execute` + `verifier_agent.j2` | docker_up didn't pass `--remove-orphans`, leaving prior-smoke containers in current compose project; verifier read them as "current services failed"; also `build=False` default meant fresh image never built | `--remove-orphans` always passed; verifier prompt step 6 calls `docker_up(build=True)` |

Suite test: `2451 passed, 1 skipped, 156 subtests passed` consistently.

## Architecture quick reference

### Lanes (resident, all task_ready-triggered)
- **orchestrator** — coordinator; hosts kickoff meeting; dispatches remediation; calls `deliver_project`
- **backend** — owns API + DB schema (post-v3 single-owner merge); writes `app/backend/*` + (intent) `app/database/*`
- **frontend** — owns UI design + impl; writes `app/frontend/*` (two phases: static UI / API integration)
- **verifier** — runs validation (docker_up, test_api, browser_*); records `validation:*` results; emits `bug_create`
- **debugger** — bug triage; routes remediation to owning lane
- **knowledge** — observer; mostly idle (this is a source of stall_escalation noise)

### Hubs (post the SchemaHub merge — see commit `df7be452`)
- **APIHub** — owns endpoints + tables + seed + table_consumers (all in `apihub_*.json` stores). `hubs.schema_hub` is a back-compat alias for `hubs.apihub`
- **WorkHub** — pages (incl. kickoff meeting), tasks, decisions
- **CodeHub** — git repo + PRs
- **EventHub** — pub/sub
- **RunHub** — probe / run records
- **MCPRegistry** — separate registry (PR 4 split, NOT merged back)
- **GateRegistry** — separate (PR 3 split, NOT merged back)

### Kickoff flow (`runtime/kickoff/run_kickoff.py:finalize_kickoff`)
1. `apihub.register_endpoint` per canonical endpoint
2. `schema_hub.register_table` (i.e. apihub.register_table after merge) per table
3. `workhub.create_task` per task_tree entry (NOW includes verifier validate_* tasks per Fix E)
4. `workhub.add_meeting_decision` for predicates
5. `workhub.close_meeting`
6. `eventhub.publish_event("kickoff_complete")`

### Workflow policy stack
Each agent's `workflow_policies` list (in `agents_config.yaml`) gates task_ready / finish. Key ones:
- `kickoff_bootstrap_gate` — refuses task_ready until kickoff finalized
- `verifier_validation_trigger` — refuses task_ready unless from orchestrator with validation-related metadata
- `depends_on` — refuses until named upstream lanes have called `task_ready`
- `hub_consistency_gate` — refuses `finish()` unless `>= N` codehub commits + expected hub state present
- `claim_assigned_tasks` — refuses `finish()` if assigned workhub tasks are still pending

`task_created-for-self` events bypass all policies (Fix G).

### Per-step tool surface
The LLM only sees top-K tools per step (ranker filters). `ACTION_STAGE_ALWAYS_INCLUDE` in `agents/base.py` pins critical tools so the ranker can't drop them. Bundle intersection means tools not in agent's bundle never appear regardless of always-include.

Three pinned flow-sets:
- `_CLAIM_FLOW` (commit `508adf7b`): `focus_hub`, `workhub_list_tasks`, `workhub_cancel_task`
- `_CONFLICT_FLOW` (Fix B): `codehub_resolve_conflict`, `codehub_resolve_merge_conflict`, `codehub_force_merge`
- `_VALIDATION_FLOW` (Fix C+H): 14 tools (run_start, docker_up, docker_status, test_api, apihub_record_contract_test, browser_navigate, browser_screenshot, browser_click, capture_webpage, execute_task_suite, register_visual_review_task, deliverability_check, bug_create)

## Next-step priorities (in order of leverage)

### B1 — Database lane: make backend actually produce `app/database/`

Most-blocking issue. Compose file declares `services.database.build: ../app/database` but no lane writes there.

Concretely:
- Backend prompt step 8 lists "Implement: src/server.js, src/routes/*.js, ..., Dockerfile, package.json". Database is missing.
- Add a Step 8.5: "Author `app/database/Dockerfile` (postgres:16-alpine base) + `app/database/init/01_schema.sql` (CREATE TABLE per registered table)".
- Backend's tool bundle needs `seed` category (already in `tool_categories`).
- Consider: `synthesize_task_tree` could emit `impl.database.dockerfile` + `impl.database.schema` tasks so backend has explicit work-items.
- Consider: spawn a `database_worker` via `define_team_agent` — `database_worker` exists per `_role_gate.py` allowed_set, but no one spawns it.

Locus: `agent/env_generator/llm_generator/multi_agent/prompts/v3/backend_agent.j2` + `agent/env_generator/llm_generator/multi_agent/runtime/kickoff/schema_tolerance.py:synthesize_task_tree`.

### B2 — File-presence guard

Add a `RequiredFilesPolicy` that blocks `finish()` unless named files exist in worktree. Configure per agent:

```yaml
backend:
  workflow_policies:
    - kind: required_files
      paths:
        - "app/backend/Dockerfile"
        - "app/backend/package.json"
        - "app/backend/src/server.js"
        - "app/database/Dockerfile"
        - "app/database/init/01_schema.sql"
```

When `finish()` fires, check the worktree. If any path missing, return failure → backend retries. Pair with `lane_idle_circuit_breaker` so it can't loop forever.

Locus: new policy class in `agent/env_generator/llm_generator/multi_agent/workflow_policies.py`.

### B3 — Validation retry loop

When verifier records a failed `validation:api_smoke` etc., orchestrator should dispatch a remediation task to the owning lane (this is what `bug_create` partly does, but Debugger triage doesn't auto-fire a re-validation). The loop should be:

1. Verifier records validation result `failed`
2. Debugger triages → creates remediation task
3. Owning lane completes remediation
4. Orchestrator re-dispatches validation task_ready to verifier
5. Repeat up to N times before failforward

Currently steps 4-5 don't exist. Verifier finishes once and goes silent.

### B4 — Agent → PR → merge-to-main → preview release chain

User explicitly called out this is broken. The orchestrator at delivery time should:

1. `codehub_open_pr` from `integration` → `main` (this tool exists in CodeHub but verifier-style chain doesn't reliably reach it; smoke logs show "codehub_open_pr unavailable in this session" complaints)
2. Run final delivery gate (`_validate_delivery_gate`)
3. If passing: merge PR, tag a release, write the release artifacts to a preview location

Concretely missing:
- `codehub_open_pr` needs to be pinned in `_VALIDATION_FLOW` or a new `_DELIVERY_FLOW` so orchestrator's per-step surface has it (smoke #46 verifier wrote "codehub_open_pr is unavailable" → ranker dropped it)
- A `release_to_preview` tool or runtime hook that copies the generated `app/`, `docker/`, `design/` tree to the user-visible preview dir
- The chain should be wired into `orchestrator.deliver_project` so it runs deterministically once gate passes

Locus: `agent/env_generator/llm_generator/multi_agent/agents/base.py` (add `_DELIVERY_FLOW`), `agent/env_generator/llm_generator/multi_agent/orchestrator.py:deliver_project`, possibly a new tool in `agent/env_generator/llm_generator/tools/`.

### B5 — Stop knowledge-lane stall escalation noise

Smoke runs show `Stall escalation: dispatched urgent task_ready to silent resident lanes ['knowledge']` firing every 60s forever. Knowledge is observer-only; it's supposed to be silent. The stall escalation should exempt observer lanes.

Locus: `agent/env_generator/llm_generator/multi_agent/orchestrator.py:_nudge_silent_resident_lanes` (around lines 730-780 — search for `Stall escalation`).

## Repo state

```
branch:      haibotong-0527-hub-focus-and-tooling-cleanup
head:        272ec461 (pushed to red-env-gen)
ssh key:     id_ed25519_virtueai (default key auths as wrong account)
test runner: /home/haibotong/miniconda3/envs/dt/bin/python -m pytest tests/
suite:       2451 passed, 1 skipped, 5 warnings, 156 subtests passed
smoke:       cd agent/env_generator/llm_generator && bash launch_m1_smoke.sh
monitor:     http://127.0.0.1:4500 (admin / cg_vJvy0RGkl)
```

User project conventions (from auto-memory):
- NO `Co-Authored-By: Claude` trailer on commits
- No `--no-verify`, no force-push to main, no destructive ops without authorization
- Charter §8: "fallback对系统不好" — no silent fallback paths

## Smoke run inventory (this session)

| # | Result | Notes |
|---|---|---|
| 29-37 | Kickoff wedges in various places | All resolved by Fixes shipped before this handoff |
| 38 | First clean kickoff; backend wrote code; APIHub all `implemented` | Verifier never reached validation |
| 39-46 | Iterative wedges (each one resolved by next fix) | See "9 fixes" table |
| 47 | Fix G working (task_created suppression=0); verifier did docker_up | docker_up failed: orphan containers (Fix I addresses) |
| 48 | Fix H working (verifier called docker_up/contract_test) | But misread orphan as failure (Fix I addresses) + 0 task claims |
| 49 | Fix I + H both deployed | Backend only wrote `src/`, missed Dockerfile; `app/database/` never existed → docker_up failed |

No smoke has produced a complete env. No smoke has reached the delivery gate.

## Open questions for the next maintainer

1. Is `database_worker` (the v2 lane) supposed to be revived? `_role_gate.py` still admits it but no one spawns it.
2. Should `synthesize_task_tree` emit `impl.database.*` tasks owned by backend (or a spawned worker), with `validate.api_smoke.*` then having `depends_on=[impl.endpoint.*, impl.database.*]`?
3. The verifier's `depends_on=[frontend, backend]` config requires BOTH lanes to call `task_ready(verifier)`. Frontend's prompt says "Phase B finish notifies verifier" but Phase A finishes notify orchestrator. In runs that only do Phase A, verifier never gets the second `_upstream_ready_agents` entry. Either drop frontend from depends_on or have frontend always notify verifier.
4. The pipeline is observer-able via the live_monitor UI at :4500 but no one-glance "smoke succeeded / failed at <stage>" indicator. Worth adding a summary view.

## Handoff complete
