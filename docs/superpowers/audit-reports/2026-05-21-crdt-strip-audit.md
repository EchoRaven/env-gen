# CRDT Strip-Off Audit Report

**Date:** 2026-05-21
**Scope:** Audit the four hubs (CodeHub / APIHub / WorkHub / EventHub) for feature completeness against their analogs (GitHub / Apifox / Notion+Jira / Gmail+subscriptions), enumerate every remaining CRDT method, and produce a revised cutover roadmap that strips `CRDTWorkspace` entirely.
**Inputs:** Branch state after APIHub cutover (`haibotong-hub-cutover-1-apihub` at the time of audit), four-hub spec (`docs/superpowers/specs/2026-05-21-four-hubs-design.md`), APIHub cutover plan (`docs/superpowers/plans/2026-05-21-apihub-cutover.md`).
**Output:** Gap list + 5-cutover roadmap (1.5 → 5).

---

## 1. Method Census

Total public methods on `CRDTWorkspace` + mixins **before Cutover 1**: ~65.
Removed by Cutover 1 (APIHub): 13 endpoint/consumer methods.
Remaining: **~52 methods to migrate or delete.**

| Source | Public method count after Cutover 1 |
|---|---|
| `runtime/crdt.py` `CRDTWorkspace` | ~38 |
| `runtime/crdt_dev_tasks.py` `CRDTDevTaskMixin` | 10 |
| `runtime/crdt_validation.py` `CRDTValidationMixin` | 5 |
| `runtime/crdt_projection.py` | 3 (`_project_api_spec`, `_mark_stale_missing`, top-level helpers) |
| `runtime/file_coordination.py` | 787 lines, entire file targeted for deletion |

## 2. Hub Completeness vs Analog

Legend: ✅ complete · 🟡 partial · 🔴 core missing · 💀 not implemented.

### 2.1 CodeHub vs GitHub — 🔴 metadata shell, no real `git`

| Feature | Status | Notes |
|---|---|---|
| repo / branch / commit / PR / review / merge / release metadata | ✅ | `runtime/hubs/codehub/service.py:25-202` |
| Real `git` operations | 💀 | `record_commit` only writes JSON; `merge_pull_request` only flips status. Spec §7.1-7.7 requires `subprocess.run(["git", ...])` wrapper. |
| `register_agent_worktree` | 💀 | Spec §7.6 requires; current `register_agent_repo` only records metadata. |
| `get_diff(pr_id)` | 💀 | Reviewer agents cannot inspect changes; review is opaque. |
| `get_file_content(pr_id, path)` / `get_blob(commit_hash, path)` | 💀 | Cross-agent peek into code is impossible. |
| `resolve_conflict(pr_id, resolution_files, agent)` | 💀 | Spec §7.6. |
| `cleanup_worktree(agent_id)` / `push_more_commits(pr_id)` | 💀 | Lifecycle gaps. |
| `list_prs(status / author / reviewer)` | 🟡 | Snapshot returns all; no filtered query. |
| `record_check` ↔ `list_checks(pr_id)` / `get_check_status(pr_id, name)` | 🟡 | Writes work, reads are weak. |
| Inline comments bound to file:line | 🔴 | Model has `inline_comments` field, but no file/line schema. |
| Issues / Labels / Milestones | 💀 | Not in spec scope, optional. |

**Conclusion:** CodeHub is a GitHub-shaped JSON database with no git. This is **Cutover 4** territory. Critical for stripping `file_coordination.py` + CRDT file methods.

### 2.2 APIHub vs Apifox — ✅ mostly complete, missing accessors

| Feature | Status | Notes |
|---|---|---|
| Endpoint registration / schema / mock / example / consumer | ✅ | All 10 LLM tools wired post-Cutover 1. |
| Breaking-change detection (7 dimensions) + auto WorkHub task | ✅ | `runtime/apihub.py:184-231,242-273` |
| Contract test recording | ✅ | `record_api_test` |
| Deprecation + replacement pointer | ✅ | |
| Review request | 🟡 | `request_api_review` exists; **`submit_api_review(review_id, state, comments)` missing** — reviews stay pending forever. |
| Public read accessors | 🟡 | `get_endpoints` exists. **`get_consumers / get_dependencies_for_file / get_breaking_changes / get_contract_test_results` are only in the LLM tool layer (reaching into private stores like `apihub._consumers.value()`)** — bad encapsulation. |
| Schema history / diff view | 🟡 | `_schemas` store is wired but never written. |
| OpenAPI import / export | 💀 | Not needed for our use case. |
| Mock server runtime (live HTTP) | 💀 | We use mock dicts, not a server. Out of scope. |

**Conclusion:** Closest to complete. Needs ~5 small additions: `submit_api_review`, `get_consumers`, `get_dependencies_for_file`, `get_breaking_changes`, `get_contract_test_results`. **Cutover 1.5** target.

### 2.3 WorkHub vs Notion + Jira/Linear — 🔴 the largest gap

| Feature | Status | Notes |
|---|---|---|
| `create_page` / `append_block` / `create_plan` / `create_task` / `claim_task` / `complete_task` | ✅ | Core CRUD only. |
| `invite_attendee` / `comment` | ✅ | Single-level comments. |
| `upsert_plan_snapshot` | 🟡 | Legacy bridge for the old `update_plan` path; mark for deletion once callers migrate. |
| Block edit (`update_block`, `insert_block_after`) | 💀 | Append-only today; blocks cannot be amended or reordered. |
| Task advanced lifecycle (`fail_task`, `cancel_task`, `update_plan_metadata`) | 💀 | |
| Cross-hub linking (`link_task_to_pr`, `link_task_to_apis`) | 💀 | APIHub auto-creates tasks but can only stuff data into `metadata` blob; WorkHub has no first-class link concept. |
| Read APIs (`get_page(with_blocks)`, `list_pages(kind, status)`, `get_plan(with_tasks)`, `get_task`, `list_tasks(filter)`, `available_tasks_for(agent)`, `comments_for(resource_id)`) | 💀 | Only `snapshot()` exists — agents pull entire hub state and filter client-side. |
| `archive_page` / `remove_attendee` | 💀 | |
| `reply(comment_id, body)` / `react(comment_id, kind)` / `record_decision(...)` | 💀 | |
| Linear-style board view (tasks grouped by stage) | 💀 | `stages` is a flat array; no `tasks_by_stage(plan_id)` query. |

**Conclusion:** Most incomplete hub. Cutover 3 must build out ~15 missing methods **and** migrate the legacy `dev_task` / `plan` / `update_page` surface from CRDT. **Cutover 3** is the biggest single piece of work.

### 2.4 EventHub vs Gmail + Subscriptions — 🔴 dead-letter store, no async delivery

| Feature | Status | Notes |
|---|---|---|
| Persist events / threads / inboxes / subscriptions | ✅ | `runtime/eventhub.py` |
| `publish_event` / `list_inbox` / `mark_read` / `subscribe` / `thread_reply` | ✅ | |
| **`MessageBusBridge` (spec §8.6)** | 💀 | **Nothing pushes from EventHub to MessageBus.** Every hub `_emit` is a write to disk with no live delivery. Agents still rely on polling `MessageBus` directly. This is the spec's "source of truth + transport" claim that is **unfulfilled**. |
| Subscription-driven fan-out in `publish_event` | 🔴 | Current code only honors the `recipients` arg. Stored `subscribe(...)` entries are never consulted at publish time — subscribe is silently a no-op. |
| `unsubscribe` / `get_subscriptions(agent)` | 💀 | |
| `mark_delivered(agent, event_id)` | 💀 | Required by spec §8.8 (bridge marks delivery without flipping read state). |
| `mark_all_read(agent, before_ts)` | 💀 | |
| `get_event(event_id)` / `get_thread(thread_id)` (read APIs) | 🟡 | `thread_reply` exists; no read-by-thread. |
| `priority_floor` / event filter on delivery | 💀 | |
| Agent spawn catch-up integration (`agents/runtime/sync.py` calling `list_inbox` on first step) | 💀 | Spec §8.7 step 2 — not wired. |
| Event log compaction | 💀 | Spec marked as future, OK to defer. |

**Conclusion:** EventHub is the lowest-completion hub. **Cutover 2** must build the bridge + subscription-driven fan-out + spawn catch-up before WorkHub/CodeHub additions can use them meaningfully.

## 3. CRDT Residual Surface — Disposition Map

### 3.1 Class A: Hub already owns it, just delete CRDT version (~18 methods)

| CRDT method | New owner | Blocker |
|---|---|---|
| `update_plan` / `get_plan` / `get_plans` | WorkHub `create_plan` (+ needs `update_plan_metadata`, `get_plan`, `list_plans`) | WorkHub gaps |
| `claim_plan_task(plan, stage, task, agent)` | WorkHub `claim_task` (stable id format `plan:{plan_id}:{stage_id}:{task_id}`) | None |
| `update_plan_index` / `get_plan_index(s)` | WorkHub plan metadata field | None |
| `publish_dev_task` / `claim_dev_task` / `complete_dev_task` / `cancel_dev_task` | WorkHub `create_task` / `claim_task` / `complete_task` / `cancel_task` | WorkHub missing `cancel_task` 🔴 |
| `get_dev_task` / `get_available_dev_tasks` / `get_my_dev_tasks` / `get_all_dev_tasks` / `get_dev_task_summary` | WorkHub needs 5 new accessors 🔴 | Yes |
| `escalate_to_lead` | WorkHub `comment` (priority=urgent + attendee=lead) | Adapter logic |
| `publish_task` / `claim_task` / `get_pending_tasks` (legacy task layer pre-dev_task) | Dead code, drop with no replacement | None |
| `add_api_contract` / `get_api_contract` / `list_api_contracts` / `get_contracts` | APIHub (apparently unused now — verify caller-free) | Audit |

### 3.2 Class B: Hub needs extension to absorb (~15 methods)

| CRDT method | Where it goes | Required hub addition |
|---|---|---|
| `update_page` / `get_pages` (old key→dict-bag semantics) | WorkHub or audit caller. The old `update_page("home", {"status": "implemented"})` is **not** a Notion-style page; it's a KV signal that the `home` UI page is implemented. Recommend: **migrate semantics into UI-spec page (`kind="ui_page"`) blocks** rather than build a KV adapter on WorkHub. Audit `crdt_projection.py` callers. | WorkHub `update_page(kind="ui_page")` semantics |
| `update_table` / `get_tables` / `get_table` | **Decision needed**: spec did not assign a hub. Two options: (a) APIHub gets `register_table` family (table = data contract, like endpoint); (b) WorkHub `kind="table_schema"` page. **Recommend (a)** — table schemas are contracts between backend/database/frontend, mirror endpoint semantics. | APIHub `register_table` / `update_table_schema` / `list_tables` / `register_table_consumer` |
| `update_agent_status` / `get_agent_statuses` / `observe_agents` | Not a hub. Either **new PresenceHub** or EventHub system-topic. Recommend EventHub system topic to keep hub count at 4. | EventHub `publish_event(source_hub="system", event_type="agent_status", ...)` + read helper |
| `update_artifact` / `get_artifacts` | CodeHub (artifacts are build outputs, fit as release attachments) | CodeHub `attach_artifact(release_id, ...)` |
| `record_validation_result` / `get_validation_results` / `get_validation_summary` | CodeHub `record_check` already absorbs the write side. Read APIs missing. | CodeHub `list_checks(filter)` / `get_check_summary` |
| `create_dev_task_from_validation_failure` / `handle_validation_failure` | WorkHub `create_task` + cross-hub link to CodeHub check + APIHub endpoint | WorkHub `link_task_to_check` |
| `record_build_attempt` / `get_build_status` / `get_build_history` | CodeHub `record_check(name="build")` + filter reads | CodeHub `list_checks(name="build")` |
| `get_verification_checklist` | CodeHub (verification = aggregate of checks) | CodeHub `get_check_summary(pr_id)` |
| `set_project_info` / `set_project_phase` / `get_project_status` | WorkHub special page (`kind="project"`) **or** system_tools (project is operational state, not collab). Recommend **WorkHub project page** so attendees + comments work on the project itself. | WorkHub `update_page_metadata(kind="project", ...)` |
| `share_implementation` / `get_shared_implementations` | WorkHub `append_block(kind="knowledge")` | None (WorkHub already supports kind on blocks) |

### 3.3 Class C: Cross-hub metrics → `system_tools.py` (~10 methods)

These are observability concerns, orthogonal to hubs:
- `record_token_usage` / `get_token_usage` / `get_token_budget_status`
- `record_operation_time` / `get_performance_stats`
- `record_retry` / `get_retry_stats`
- `check_agent_health` / `get_stuck_agents`
- `get_progress_dashboard` / `get_summary`
- `increment_progress` / `get_progress`

Spec §9.1 already plans `system_tools.py` and `tools/hub_tools/system_tools.py`. **Cutover 5** target.

### 3.4 Class D: Delete outright, no successor (~12 methods + `file_coordination.py`)

git worktree + CodeHub.get_diff/get_blob is the replacement substrate.

| Method | Why delete |
|---|---|
| `publish_file_region` / `claim_file_region` / `complete_file_region` / `get_file_region(s)` | Git branches isolate writers per spec §7.10 |
| `reserve_file_anchor` / `record_file_anchor_op` / `get_file_anchor(s)` / `get_file_anchor_ops` | Same — no anchors needed when each agent has its own worktree |
| `record_file_read` / `record_file_write` / `sync_file_change` / `get_file_state` / `get_files` / `get_file_history` | `git log --name-status` is the answer |
| `record_projection_error` / `clear_projection_error` / `get_projection_errors` | **Keep as a CodeHub check** named `projection` — projection failures are a class of check |
| `sync_text_document_snapshot` / `get_text_document_snapshots` | Files are files |
| `get_state_hash` / `wait_for_convergence` | Single-process now; CRDT-level convergence is a non-issue |
| `create_observer` / `WorkspaceObserver` class | Push model via EventHub Bridge replaces polling |
| `runtime/file_coordination.py` (entire 787-line file) | Functionality moves to git |

### 3.5 Numerical summary

| Class | Method count | Cutover |
|---|---|---|
| A — direct migration | 18 | 3 (WorkHub) |
| B — hub extension needed | 15 | 1.5 + 3 + 4 |
| C — system_tools | 10 | 5 |
| D — pure deletion | 12+1 file | 4 |
| **Total** | **55+** | |

## 4. Revised Cutover Roadmap

The original spec had 4 cutovers. Audit findings split work differently:

| # | Name | Scope | Estimated effort |
|---|---|---|---|
| **1** | APIHub core (done) | 10 LLM tools + breaking-change cross-hub + 13 method removals | ✅ shipped (`e31e66a8`) |
| **1.5** | APIHub completeness | Add `submit_api_review`, `get_consumers`, `get_dependencies_for_file`, `get_breaking_changes`, `get_contract_test_results` as public APIHub methods; refactor tool layer to use them instead of private store access; add `register_table` family if option (a) is chosen for table migration | 1-2 days |
| **2** | EventHub + Bridge | Build `MessageBusBridge` per spec §8.6; subscription-driven fan-out in `publish_event`; `mark_delivered`, `mark_all_read`, `unsubscribe`, `get_subscriptions`, `get_event`, `get_thread`, `attach_bridge`; agent spawn catch-up wired into `agents/runtime/sync.py`; system topic for agent_status (absorbs `update_agent_status / get_agent_statuses / observe_agents`) | 3-5 days |
| **3** | WorkHub full + dev_task / plan migration | Add ~15 missing methods (block edit/insert, task cancel/fail, list/get accessors, cross-hub links, project page, decision/reaction); migrate `publish_dev_task` / `claim_dev_task` / `complete_dev_task` / etc.; migrate `update_plan` / `claim_plan_task` / plan indexes; migrate `share_implementation`; migrate `escalate_to_lead`; migrate `set_project_info` / `set_project_phase` / `get_project_status`; migrate `update_page` callers in `crdt_projection.py` | 1-2 weeks |
| **4** | CodeHub real git + file_coordination delete | Wrap `subprocess.run(["git", ...])` in `GitOps`; `register_agent_worktree`; `get_diff` / `get_blob` / `get_file_content`; `resolve_conflict`; `list_prs(filter)` + `list_checks`; migrate `record_validation_result` / `record_build_attempt` / `get_verification_checklist` into CodeHub.checks; **delete `file_coordination.py` entirely + all CRDT file-coordination methods + crdt_observer.py** | 1-2 weeks |
| **5** | system_tools + final purge | Build `tools/system_tools.py` for cross-hub metrics (token, performance, retries, dashboard, health); delete `crdt.py`, `crdt_dev_tasks.py`, `crdt_validation.py`, `crdt_projection.py`, `crdt_observer.py`, `hub_workspace.py`, all `crdt_*_tools.py`, `crdt_tool_base.py`; replace `CRDTWorkspace` reference in `Orchestrator.__init__` with a top-level `HubRegistry`; verify `git grep -i crdt -- ":!docs/"` returns zero matches | 3-5 days |

**Total remaining effort estimate: 4-7 weeks** (single developer + reviewer subagents).

## 5. Open Decisions

These need a yes/no before the relevant cutover starts:

1. **Table contract migration** — APIHub `register_table` (recommended) vs WorkHub `kind="table_schema"`?
2. **Agent presence** — EventHub system topic (recommended; keeps 4 hubs) vs new PresenceHub (cleaner but 5 hubs)?
3. **Project metadata** — WorkHub `kind="project"` page (recommended; comments + attendees) vs system_tools?
4. **`add_api_contract` family** — verify zero callers, then delete without replacement?
5. **Tool naming** — keep underscore (`apihub_register_endpoint`) as decided post-Cutover 1, or revisit during Cutover 5 cleanup?

## 6. Acceptance Criteria for "CRDT fully stripped"

A. `git grep -lE "from .*crdt|crdt_workspace|CRDTWorkspace" -- ":!docs/" ":!agent/tests/"` returns zero results in the runtime/agent source tree.
B. `runtime/crdt.py`, `runtime/crdt_dev_tasks.py`, `runtime/crdt_validation.py`, `runtime/crdt_projection.py`, `runtime/crdt_observer.py`, `runtime/hub_workspace.py`, `runtime/file_coordination.py`, `tools/crdt_tools.py`, `tools/crdt_dev_task_tools.py`, `tools/crdt_file_coordination_tools.py`, `tools/crdt_metrics_tools.py`, `tools/crdt_validation_tools.py`, `tools/crdt_tool_base.py` are deleted.
C. `Orchestrator.__init__` holds a `HubRegistry` directly (`self.hubs = HubRegistry(self.output_dir, self.message_bus)`), no `self.crdt_workspace`.
D. `agents_config.yaml` profiles do not list `crdt` in `tool_categories` and do not include `crdt`-named tool bundles.
E. End-to-end `run_facebook_generation.sh` completes; all hub-* tests + regressions green.
F. EventHub → MessageBus delivery confirmed in a live run (events emitted by APIHub/WorkHub/CodeHub reach online agents via `receive_message` within milliseconds, not requiring polling).
G. CodeHub `merge_pull_request` performs a real `git merge` and surfaces real merge conflicts as WorkHub tasks.

## 7. Recommended Next Action

Sequence:
1. **Land Cutover 1 PR** (the existing `haibotong-hub-cutover-1-apihub` work — 26 commits already pushed to `red-env-gen`).
2. **Cutover 1.5** as the next branch — small, safe warm-up that fixes APIHub's tool-layer ugliness and adds 5 accessors.
3. **Cutover 2 (EventHub bridge)** — biggest infra unlock; everything downstream depends on it.
4. **Cutover 3 (WorkHub full)** — largest single piece; needs Cutover 2's bridge to be live for cross-hub events to actually deliver.
5. **Cutover 4 (CodeHub real git)** — second-largest; depends on conflict-task creation working through Cutover 2's bridge.
6. **Cutover 5 (system_tools + purge)** — closing the book.

Plans for cutovers 1.5 / 2 / 3 / 4 / 5 will each get their own `docs/superpowers/plans/YYYY-MM-DD-cutover-N-*.md` file, written just-in-time before the cutover starts (avoids stale plans).
