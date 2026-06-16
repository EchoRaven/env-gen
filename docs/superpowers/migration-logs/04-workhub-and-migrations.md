# Migration Log 04 — WorkHub Full Build + CRDT Migrations (Cutover 3)

**Date:** 2026-05-22
**Branch:** `haibotong-cutover-3-workhub-migrations`
**Base commit:** `d0dc56a3` (Cutover 2 migration log)
**Audit refs:** §2.3 WorkHub spec, §3.1 CRDT method inventory, §3.2 migration matrix

---

## Phase Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| A | 1–4  | WorkHub core: fail_task, cancel_task, get_task/list_tasks, page/block/plan accessors, cross-hub links |
| B | 5–8  | WorkHub extensions: update_block, insert_block_after, archive_page, reply/react/remove_attendee/record_decision, update_plan_metadata/add_task_to_plan |
| C | 9–12 | LLM-facing workhub_tools bundle (14 new tools), dev_task callers switched, CRDTDevTaskMixin + crdt_dev_tasks.py deleted |
| D | 13–17 | Plan/plan_index callers switched, CRDT plan stores deleted, update_page callers migrated, set_project_info/phase migrated |
| E | 18–21 | share_implementation migrated, escalate_to_lead audited (no callers), update_agent_status migrated to EventHub system topic |
| F | 22–25 | Final audit (0 residues), prompt updates, regression + e2e smoke, this log |

---

## Methods Added to WorkHub (~22 new methods)

- `fail_task`, `cancel_task`
- `get_task`, `list_tasks`, `available_tasks_for`, `tasks_by_stage`
- `get_page`, `get_block`, `list_pages`, `get_plan`, `list_plans`
- `link_page_to_endpoint`, `link_page_to_task`, `link_plan_to_task`
- `update_block`, `insert_block_after`, `archive_page`
- `reply`, `react`, `remove_attendee`, `record_decision`
- `update_plan_metadata`, `add_task_to_plan`

---

## Methods Migrated from CRDT (~30 absorbed)

From `CRDTDevTaskMixin` / `crdt_dev_tasks.py`:
- `publish_dev_task` → `workhub_create_task`
- `claim_dev_task` → `workhub_claim_task`
- `complete_dev_task` → `workhub_complete_task`
- `get_dev_tasks`, `get_pending_dev_tasks`, `get_my_dev_task` → WorkHub query methods

From `CRDTWorkspace` plan/plan_index stores:
- `update_plan` → `WorkHub.create_plan` / `update_plan_metadata`
- `claim_plan_task` → `workhub_claim_task(task_id="plan:...")`
- `update_plan_index` → collapsed into plan record (no separate index needed)
- `get_plan`, `get_plan_index` → `WorkHub.get_plan`

From `CRDTWorkspace` page/project/share/status stores:
- `update_page` → `WorkHub.add_block` / `codehub_record_check`
- `get_pages` → `WorkHub.list_pages`
- `set_project_info`, `set_project_phase`, `get_project_status` → `WorkHub.update_project_page`
- `share_implementation` → `WorkHub.add_block` (knowledge blocks)
- `escalate_to_lead` → `workhub_comment(..., mentions=["orchestrator"])` (0 callers found)
- `update_agent_status`, `get_agent_statuses`, `observe_agents` → EventHub system topic `agent.status`

---

## Files Deleted

- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_dev_tasks.py`
- `agent/env_generator/llm_generator/multi_agent/tools/crdt_dev_task_tools.py`
- CRDT internal stores removed from `crdt.py`: `_pages`, `_plans`, `_plan_indexes`, `_project`, `_implementations`, `_agent_status`

---

## Commit List (d0dc56a3..HEAD)

```
d5172fe2 Update agent prompts to reference WorkHub tool names
e4052f3c Migrate update_agent_status to EventHub system topic, delete CRDT agent_status methods
6e5079d0 Add EventHub agent_status system-topic helpers
a42bf0e6 Confirm escalate_to_lead has no remaining callers; fix crdt_tools.py update_page
f6644925 Migrate share_implementation to WorkHub knowledge blocks
da505bbf Migrate set_project_info / set_project_phase / get_project_status to WorkHub project page
cab2984f Switch update_page callers to WorkHub blocks / CodeHub checks
1fc42ef8 Delete CRDTWorkspace plan / plan_index methods + stores (migrated to WorkHub)
7711e812 Switch plan / plan_index callers from CRDTWorkspace to WorkHub directly
2c9db680 Add WorkHub plan-migration parity tests
d5fe2a06 Delete crdt_dev_task_tools.py (replaced by extended workhub_tools)
28fecfa2 Delete CRDTDevTaskMixin and crdt_dev_tasks.py (migrated to WorkHub)
be460364 Switch dev_task callers from CRDTWorkspace to WorkHub directly
4fcfe119 Add WorkHub dev_task parity tests
003bb7ee Extend workhub_tools bundle with 14 new LLM-facing tools
ea70372a Add WorkHub.update_plan_metadata and add_task_to_plan
d66facf2 Add WorkHub reply / react / remove_attendee / record_decision
a1fd06ed Add WorkHub.update_block / insert_block_after / archive_page
5c78bf15 Add WorkHub page/block/plan accessors + cross-hub link methods
16393a0b Add WorkHub.get_task / list_tasks / available_tasks_for / tasks_by_stage
57471481 Add WorkHub.fail_task and cancel_task
```

---

## Test Counts

- Hub tests: **175 OK** (Ran 175 tests in 9.2s)
- Regressions: **7 OK** (Ran 7 tests in 0.6s)

---

## Smoke Test Output

```
backend received 2 live event(s) via bridge
```

---

## Gotchas

1. **`insert_block_after` ordering** — WorkHub blocks use append-only CRDT lists internally; `insert_block_after` is a best-effort ordering hint. Consumers must sort by `position` if strict ordering matters.
2. **`plan_index` collapse** — The separate `_plan_indexes` store was redundant; plan records now include a `task_index` dict directly. Migration is lossless since no production caller used plan_index reads outside tests.
3. **`update_agent_status` → EventHub** — Moved to the `agent.status` system topic. The old CRDT polling pattern (`observe_agents`) had a 5-second lag; EventHub delivery is real-time via the bridge.
4. **`escalate_to_lead`** — Zero production callers existed at migration time; mapping to `workhub_comment` is documented but untested end-to-end.
5. **Jinja2 prompt smoke test** — Template parse-only (macros require runtime args); full render validation deferred to integration tests.

---

## Next: Cutover 4

- **CodeHub real git integration** — replace stub `codehub_*` methods with actual git operations
- **`file_coordination` store deletion** — migrate remaining CRDT file-locking patterns to EventHub-based coordination
- **`update_table` prompt migration** — deferred from this cutover; awaits CodeHub schema-tracking surface
