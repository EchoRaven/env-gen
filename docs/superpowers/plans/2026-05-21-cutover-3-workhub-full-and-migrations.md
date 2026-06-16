# Cutover 3 — WorkHub Full + CRDT Migration Wave

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Complete WorkHub's API surface (~15 missing methods per audit §2.3), then migrate the ~25 CRDT methods that WorkHub owns: dev_task lifecycle, plan / plan_index, update_page, set_project_*, share_implementation, escalate_to_lead, and agent_status → EventHub system topic. After this cutover, ~30 CRDTWorkspace methods are deleted and `crdt_dev_tasks.py` is empty enough to delete.

**Why now (audit ref):** Per `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.3 — WorkHub is the most incomplete hub. Per §3.1-3.2, this cutover absorbs **Class A (18 methods)** and the WorkHub portion of **Class B (~7 methods)**. Validation / build / table / artifact migrations stay for Cutover 4 (CodeHub).

**Out of scope (deferred to Cutover 4):**
- `update_table / get_tables / get_table` — APIHub `register_table` decision (audit open item 1)
- `record_validation_result / get_validation_results / get_validation_summary` — CodeHub.record_check
- `record_build_attempt / get_build_*` — CodeHub.record_check
- `update_artifact / get_artifacts` — CodeHub release attachments
- `get_verification_checklist` — CodeHub
- `create_dev_task_from_validation_failure / handle_validation_failure` — needs Cutover 4 to land first

**Out of scope (deferred to Cutover 5):**
- Token / performance / retry / health metrics — `system_tools.py`

**Source spec:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` §6.
**Audit:** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.3, §3.1, §3.2.

---

## Phase Map

| Phase | Scope | Approx tasks | Sub-PR option |
|---|---|---|---|
| A | WorkHub method completeness (15 new methods + accessors) | 8 tasks | Could be its own PR |
| B | dev_task migration (9 methods → WorkHub + delete crdt_dev_tasks.py) | 4 tasks | Bundled |
| C | plan / plan_index migration (6 methods) | 3 tasks | Bundled |
| D | page / project / share / escalate migration (8 methods) | 4 tasks | Bundled |
| E | agent_status → EventHub system topic (3 methods) | 2 tasks | Bundled |
| F | Final cleanup: delete crdt_dev_tasks.py, remove dual-write hooks, prompt updates, regression + e2e + ship | 4 tasks | Required end-of-cutover |

Total: ~25 tasks across 6 phases. Single PR is OK if it stays at ~25 commits; split into Phase-A-only + Phase-B-F if reviewers prefer.

---

## File Map (cumulative across phases)

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — ~15 new methods (Phase A)
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py` — possibly add stores for reactions/decisions (Phase A)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_dev_tasks.py` — delete methods + dual-write hooks (Phase B/F)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py` — delete plan / plan_index / page / project / share / escalate / agent_status methods (Phases C/D/E/F)
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_projection.py` — switch `update_page` callers (Phase D)
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py` — switch `set_project_info` / `set_project_phase` / `get_project_status` callers (Phase D)
- `agent/env_generator/llm_generator/tools/hub_tools.py` — extend WorkHub tool surface (Phase A)
- `agent/env_generator/llm_generator/tools/crdt_dev_task_tools.py` — **delete entirely** (Phase F)
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — widen workhub bundle, drop dev_task bundle (Phases A, F)
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — replace `crdt_dev_task_tools` references with widened `workhub_tools`
- `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` — add `record_agent_status` / `get_agent_statuses` helpers using system topic (Phase E)
- 5 prompt files in `prompts/v2/` — substitute `publish_dev_task` etc. tool names

**Create:**
- `agent/tests/test_workhub_completeness.py` — Phase A tests (~30 tests)
- `agent/tests/test_workhub_dev_task_migration.py` — Phase B parity + migration tests
- `agent/tests/test_workhub_plan_migration.py` — Phase C
- `agent/tests/test_workhub_page_project_share.py` — Phase D
- `agent/tests/test_eventhub_agent_status.py` — Phase E
- `docs/superpowers/migration-logs/04-workhub-and-migrations.md` — log

**Delete:**
- `agent/env_generator/llm_generator/runtime/crdt_dev_tasks.py` (Phase F)
- `agent/env_generator/llm_generator/tools/crdt_dev_task_tools.py` (Phase F)

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1: Branch from Cutover 2 tip**

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-3-workhub-migrations -b haibotong-cutover-3-workhub-migrations red-env-gen/haibotong-cutover-2-eventhub-bridge
cd .worktrees/haibotong-cutover-3-workhub-migrations
```

- [ ] **Step 2: Baseline**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_completeness agent.tests.test_eventhub_subscription_fanout agent.tests.test_eventhub_spawn_catchup agent.tests.test_messagebus_bridge agent.tests.test_apihub_accessors agent.tests.test_apihub_strengthen agent.tests.test_apihub_tools agent.tests.test_apihub_breaking_change_creates_task agent.tests.test_hub_architecture 2>&1 | tail -3
```

Expected: regressions 7 OK; hub suite 59 OK.

---

## Phase A — WorkHub method completeness

### Task 2: TDD — task lifecycle (`fail_task`, `cancel_task`)

**Why first:** dev_task migration (Phase B) needs `cancel_task` to map `cancel_dev_task` cleanly.

**Files:**
- Create: `agent/tests/test_workhub_completeness.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`

- [ ] **Step 1: Create test scaffold + 4 tests**

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.crdt import CRDTWorkspace  # noqa: E402


class WorkHubCompletenessTests(unittest.TestCase):
    def _hub(self, td):
        return CRDTWorkspace(Path(td)).hubs.workhub

    def test_fail_task_sets_status_and_reason(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            task = hub.create_task(title="Build feed API", assignee="backend",
                                    agent="orchestrator", domain="backend")
            hub.claim_task(task["id"], "backend")
            failed = hub.fail_task(task["id"], "backend", reason="Compile error in feed.js")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed.get("fail_reason"), "Compile error in feed.js")

    def test_fail_task_only_by_claimer(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            task = hub.create_task(title="t", assignee="backend", agent="orchestrator", domain="backend")
            hub.claim_task(task["id"], "backend")
            result = hub.fail_task(task["id"], "frontend", reason="not yours")
            self.assertIn("error", result)

    def test_cancel_task_sets_status_and_reason(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            task = hub.create_task(title="t", assignee="backend", agent="orchestrator", domain="backend")
            cancelled = hub.cancel_task(task["id"], "orchestrator", reason="superseded")
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled.get("cancel_reason"), "superseded")

    def test_cancel_task_unknown_id_returns_error(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertIn("error", hub.cancel_task("bogus", "orchestrator", reason="x"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm FAIL**

- [ ] **Step 3: Implement in `hubs/workhub/service.py`** (place after `complete_task`):

```python
    def fail_task(self, task_id: str, agent: str, reason: str = "") -> dict:
        task = self.stores.tasks.get().get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        if task.get("claimed_by") != agent:
            return {"error": "Only claimer can fail task", "claimed_by": task.get("claimed_by")}
        ts = Timestamp.now(agent)
        updated = dict(task)
        updated["status"] = "failed"
        updated["fail_reason"] = reason
        updated["failed_at"] = ts.wall_time
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.tasks.update(lambda m: m.set(task_id, updated, ts))
        self._emit("task_failed", updated, recipients=[task.get("created_by")] if task.get("created_by") else [],
                   priority="high")
        return updated

    def cancel_task(self, task_id: str, agent: str, reason: str = "") -> dict:
        task = self.stores.tasks.get().get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        ts = Timestamp.now(agent)
        updated = dict(task)
        updated["status"] = "cancelled"
        updated["cancel_reason"] = reason
        updated["cancelled_at"] = ts.wall_time
        updated["cancelled_by"] = agent
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.tasks.update(lambda m: m.set(task_id, updated, ts))
        recipients = []
        if task.get("assignee"):
            recipients.append(task["assignee"])
        if task.get("claimed_by"):
            recipients.append(task["claimed_by"])
        self._emit("task_cancelled", updated, recipients=sorted(set(recipients)), priority="normal")
        return updated
```

- [ ] **Step 4: PASS, commit**

```bash
git add agent/tests/test_workhub_completeness.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py
git commit -m "Add WorkHub.fail_task and cancel_task"
```

### Task 3: TDD — task read accessors

Add `get_task`, `list_tasks(filter dict)`, `available_tasks_for(agent)`, `tasks_by_stage(plan_id)` to WorkHub.

- [ ] **Step 1: Append 6 tests** covering each method's filter logic.

```python
    def test_get_task_returns_record(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            task = hub.create_task(title="t", assignee="backend", agent="orchestrator", domain="backend")
            got = hub.get_task(task["id"])
            self.assertEqual(got["id"], task["id"])

    def test_get_task_unknown_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertIsNone(hub.get_task("nope"))

    def test_list_tasks_filters_by_assignee_and_status(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            t1 = hub.create_task(title="t1", assignee="backend", agent="o", domain="backend")
            t2 = hub.create_task(title="t2", assignee="frontend", agent="o", domain="frontend")
            t3 = hub.create_task(title="t3", assignee="backend", agent="o", domain="backend")
            hub.claim_task(t3["id"], "backend")
            be_pending = hub.list_tasks(assignee="backend", status="pending")
            self.assertEqual({t["id"] for t in be_pending}, {t1["id"]})

    def test_list_tasks_filters_by_domain_and_plan(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            page = hub.create_page("Plan A", agent="orchestrator")
            plan = hub.create_plan(page["id"], stages=[{"id": "impl", "name": "Impl", "order": 0}],
                                    tasks=[{"task_id": "t1", "title": "T1", "assignee": "backend"}],
                                    agent="orchestrator", title="Plan A")
            self.assertGreaterEqual(len(hub.list_tasks(plan_id=plan["id"])), 1)

    def test_available_tasks_for_filters_domain_and_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            a = hub.create_task(title="A", agent="o", domain="backend")
            b = hub.create_task(title="B", agent="o", domain="backend", depends_on=[a["id"]])
            avail = hub.available_tasks_for("backend")
            ids = {t["id"] for t in avail}
            self.assertIn(a["id"], ids)
            self.assertNotIn(b["id"], ids)  # blocked by A

    def test_tasks_by_stage_groups_by_stage_id(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            page = hub.create_page("p", agent="o")
            plan = hub.create_plan(page["id"],
                stages=[{"id": "s1", "name": "S1", "order": 0}, {"id": "s2", "name": "S2", "order": 1}],
                tasks=[
                    {"task_id": "ta", "title": "TA", "stage_id": "s1", "assignee": "backend"},
                    {"task_id": "tb", "title": "TB", "stage_id": "s2", "assignee": "backend"},
                ],
                agent="o", title="p")
            grouped = hub.tasks_by_stage(plan["id"])
            self.assertEqual({s for s in grouped.keys()}, {"s1", "s2"})
```

- [ ] **Step 2: Implement** in `service.py`:

```python
    def get_task(self, task_id: str):
        return self.stores.tasks.get().get(task_id)

    def list_tasks(self, assignee: str = None, status: str = None, domain: str = None,
                    plan_id: str = None) -> List[dict]:
        out = []
        for task in self.stores.tasks.value().values():
            if assignee is not None and task.get("assignee") != assignee:
                continue
            if status is not None and task.get("status") != status:
                continue
            if domain is not None and task.get("domain") != domain:
                continue
            if plan_id is not None and task.get("plan_id") != plan_id:
                continue
            out.append(task)
        return out

    def available_tasks_for(self, agent: str) -> List[dict]:
        all_tasks = self.stores.tasks.value()
        out = []
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            if task.get("assignee") and task.get("assignee") != agent:
                # Allow shared-base agents (e.g., "worker_x" claims a "worker" task)
                base_a = (agent or "").split("_")[0]
                base_t = (task.get("assignee") or "").split("_")[0]
                if base_a != base_t:
                    continue
            # All dependencies completed?
            unmet = [
                dep for dep in (task.get("depends_on") or [])
                if (all_tasks.get(dep) or {}).get("status") not in {"completed"}
            ]
            if unmet:
                continue
            out.append(task)
        return out

    def tasks_by_stage(self, plan_id: str) -> Dict[str, List[dict]]:
        grouped: Dict[str, List[dict]] = {}
        for task in self.stores.tasks.value().values():
            if task.get("plan_id") != plan_id:
                continue
            sid = task.get("stage_id") or "_unassigned"
            grouped.setdefault(sid, []).append(task)
        return grouped
```

- [ ] **Step 3: PASS, commit**

```bash
git commit -m "Add WorkHub.get_task / list_tasks / available_tasks_for / tasks_by_stage"
```

### Task 4: TDD — page / block / plan accessors + `link_*`

Add `get_page(page_id, with_blocks=True)`, `list_pages(kind=None, status=None)`, `get_plan(plan_id, with_tasks=True)`, `list_plans(status=None)`, `link_task_to_pr(task_id, pr_id, agent)`, `link_task_to_apis(task_id, [endpoint_ids], agent)`, `comments_for(resource_id)`.

- [ ] **Step 1-3:** Same TDD pattern. Skipping detailed test code here — follow Task 3's template. Each method has 2 tests (positive + edge case).

- [ ] **Step 4: Implement** in `service.py`:

```python
    def get_page(self, page_id: str, with_blocks: bool = True):
        page = self.stores.pages.get().get(page_id)
        if not page:
            return None
        out = dict(page)
        if with_blocks:
            out["blocks"] = [
                b for b in self.stores.blocks.value().values()
                if b.get("page_id") == page_id
            ]
            out["blocks"].sort(key=lambda b: b.get("ord", 0))
        return out

    def list_pages(self, kind: str = None, status: str = None) -> List[dict]:
        out = []
        for page in self.stores.pages.value().values():
            if kind is not None and page.get("kind") != kind:
                continue
            if status is not None and page.get("status") != status:
                continue
            out.append(page)
        return out

    def get_plan(self, plan_id: str, with_tasks: bool = True):
        plan = self.stores.plans.get().get(plan_id)
        if not plan:
            return None
        out = dict(plan)
        if with_tasks:
            out["tasks"] = self.list_tasks(plan_id=plan_id)
        return out

    def list_plans(self, status: str = None) -> List[dict]:
        out = []
        for plan in self.stores.plans.value().values():
            if status is not None and plan.get("status") != status:
                continue
            out.append(plan)
        return out

    def link_task_to_pr(self, task_id: str, pr_id: str, agent: str = "") -> dict:
        task = self.stores.tasks.get().get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        ts = Timestamp.now(agent or "workhub")
        updated = dict(task)
        updated["linked_pr"] = pr_id
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.tasks.update(lambda m: m.set(task_id, updated, ts))
        self._emit("task_linked_to_pr", {"task_id": task_id, "pr_id": pr_id}, recipients=[])
        return updated

    def link_task_to_apis(self, task_id: str, endpoint_ids: List[str], agent: str = "") -> dict:
        task = self.stores.tasks.get().get(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}
        ts = Timestamp.now(agent or "workhub")
        updated = dict(task)
        existing = list(updated.get("linked_apis") or [])
        for eid in endpoint_ids:
            if eid not in existing:
                existing.append(eid)
        updated["linked_apis"] = existing
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.tasks.update(lambda m: m.set(task_id, updated, ts))
        self._emit("task_linked_to_apis", {"task_id": task_id, "endpoint_ids": endpoint_ids}, recipients=[])
        return updated

    def comments_for(self, resource_id: str) -> List[dict]:
        return [
            c for c in self.stores.comments.value().values()
            if c.get("resource_id") == resource_id
        ]
```

- [ ] **Step 5: Commit**

```bash
git commit -m "Add WorkHub page/block/plan accessors + cross-hub link methods"
```

### Task 5: TDD — block edit (`update_block`, `insert_block_after`, `archive_page`)

Blocks are append-only today; we add edit/insert/archive without changing the LWW conflict policy.

- [ ] **Step 1-4: Tests + impl.** `insert_block_after` recomputes `ord` to fit between two existing blocks (midpoint of their `ord` values). `archive_page` flips `page["status"] = "archived"`.

```python
    def update_block(self, block_id: str, content, agent: str = "") -> dict:
        block = self.stores.blocks.get().get(block_id)
        if not block:
            return {"error": f"Block not found: {block_id}"}
        ts = Timestamp.now(agent or "workhub")
        updated = dict(block)
        updated["content"] = content
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.blocks.update(lambda m: m.set(block_id, updated, ts))
        self._emit("block_updated", updated, recipients=[])
        return updated

    def insert_block_after(self, page_id: str, after_block_id: str, block: dict, agent: str = "") -> dict:
        if page_id not in self.stores.pages.value():
            return {"error": f"Page not found: {page_id}"}
        all_blocks = [
            b for b in self.stores.blocks.value().values()
            if b.get("page_id") == page_id
        ]
        all_blocks.sort(key=lambda b: b.get("ord", 0))
        prev_ord = None
        next_ord = None
        for i, b in enumerate(all_blocks):
            if b.get("id") == after_block_id:
                prev_ord = b.get("ord", 0)
                if i + 1 < len(all_blocks):
                    next_ord = all_blocks[i + 1].get("ord", prev_ord + 2048)
                break
        if prev_ord is None:
            return {"error": f"after_block_id not found in page: {after_block_id}"}
        if next_ord is None:
            new_ord = prev_ord + 1024
        else:
            new_ord = (prev_ord + next_ord) / 2.0
        block_with_ord = dict(block)
        block_with_ord["ord"] = new_ord
        return self.append_block(page_id, block_with_ord, agent=agent)

    def archive_page(self, page_id: str, agent: str = "") -> dict:
        page = self.stores.pages.get().get(page_id)
        if not page:
            return {"error": f"Page not found: {page_id}"}
        ts = Timestamp.now(agent or "workhub")
        updated = dict(page)
        updated["status"] = "archived"
        updated["archived_at"] = ts.wall_time
        updated["_updated_by"] = agent
        updated["_updated_at"] = ts.wall_time
        self.stores.pages.update(lambda m: m.set(page_id, updated, ts))
        self._emit("page_archived", updated, recipients=updated.get("attendees") or [])
        return updated
```

- [ ] **Step 5: Commit**

```bash
git commit -m "Add WorkHub.update_block / insert_block_after / archive_page"
```

### Task 6: TDD — comment thread (`reply`, `react`, `remove_attendee`, `record_decision`)

These were stubbed in spec but never built. Each is a small addition.

- [ ] **Step 1-4: Tests + impl.**

`reply(comment_id, body, agent, mentions=[])`:
- Find parent comment, write a new comment with `parent_id=comment_id` and `resource_id=parent.resource_id`.

`react(comment_id, reaction, agent)`:
- Append to `stores.reactions` (LWW map keyed by `{comment_id}:{agent}`).

`remove_attendee(resource_type, resource_id, agent_id, by)`:
- Find attendee record with composite key; mark `_removed=True` (CRDT soft delete).

`record_decision(page_id, title, options, chosen, reason, agent)`:
- Append a `block` of `type="decision"` to the page, content includes options + chosen + reason.

Also stores audit: add `reactions` and `decisions` stores to `WorkHubStores.create` if not already there.

- [ ] **Step 5: Commit**

```bash
git commit -m "Add WorkHub reply / react / remove_attendee / record_decision"
```

### Task 7: TDD — `update_plan_metadata` + plan task append

Allow editing plan title / status without recreating; add `add_task_to_plan(plan_id, stage_id, task_dict, agent)`.

- [ ] **Step 1-5: TDD + commit**

```bash
git commit -m "Add WorkHub.update_plan_metadata and add_task_to_plan"
```

### Task 8: Widen `workhub_tools` bundle + add new tool classes

Bring the new methods to the LLM tool surface. Add tool classes in `tools/hub_tools.py` for the most LLM-useful entries:

- `workhub_fail_task`
- `workhub_cancel_task`
- `workhub_list_tasks` (with filters)
- `workhub_available_tasks` (per-agent shortcut)
- `workhub_get_task`
- `workhub_get_page` (with blocks)
- `workhub_list_pages`
- `workhub_get_plan` (with tasks)
- `workhub_link_task_to_pr`
- `workhub_link_task_to_apis`
- `workhub_update_block`
- `workhub_comments_for`
- `workhub_archive_page`
- `workhub_record_decision`

Update `_bundle_workhub_tools` in `tool_bundles.py` to include them. Add them to `HUB_TOOL_CLASSES`.

- [ ] **Step 1-2:** Add the 14 tool classes (same pattern as existing `WorkHubCreatePageTool` / `WorkHubTaskTool`).

- [ ] **Step 3:** Widen bundle.

- [ ] **Step 4:** Run full suite.

- [ ] **Step 5: Commit**

```bash
git commit -m "Extend workhub_tools bundle with 14 new LLM-facing tools"
```

---

## Phase B — dev_task migration

### Task 9: TDD — Parity tests for dev_task family

Build the parity tests before deleting code so we catch any semantic drift.

**Files:**
- Create: `agent/tests/test_workhub_dev_task_migration.py`

- [ ] **Step 1-3:** Tests assert that legacy `workspace.publish_dev_task(...)` is reflected by `hubs.workhub.create_task` with stable id `dev:{task_id}`, and that `complete_dev_task` is mirrored by `workhub.complete_task`. The dual-write already runs (see `crdt_dev_tasks.py` Task 7's WorkHub mirror calls), so parity should be 100%.

- [ ] **Step 4: Commit**

```bash
git commit -m "Add WorkHub dev_task parity tests"
```

### Task 10: Switch callers to WorkHub directly

Find every `workspace.publish_dev_task` / `claim_dev_task` / `complete_dev_task` / `cancel_dev_task` / `get_*_dev_tasks` call in:

- `tools/crdt_dev_task_tools.py`
- `tools/reasoning_tools.py` (the `_sync_plan_tasks_to_dev_tasks` flow)
- `multi_agent/runtime/crdt_validation.py` (the `create_dev_task_from_validation_failure` flow)
- Any agent runtime mixins

Rewrite each to use `workspace.hubs.workhub.create_task(...)`, `claim_task(stable_task_id, agent)`, etc. Use the stable `dev:{task_id}` id space for migration (`workhub_id = f"dev:{legacy_dev_task_id}"`) so existing WorkHub records from the dual-write window remain accessible.

- [ ] **Step 1-3: Caller rewrites** (one commit per file is fine, or one big commit; recommended one commit). Run all hub + regression suites after each rewrite.

- [ ] **Step 4: Commit**

```bash
git commit -m "Switch dev_task callers from CRDTWorkspace to WorkHub directly"
```

### Task 11: Delete `crdt_dev_tasks.py` methods, drop mixin from CRDTWorkspace

Once no caller references legacy dev_task methods (confirmed by grep), delete the methods from `crdt_dev_tasks.py`. Remove `CRDTDevTaskMixin` from `CRDTWorkspace`'s class signature in `crdt.py:54`.

If `crdt_dev_tasks.py` becomes empty (only the file boilerplate), delete the file entirely.

```bash
grep -rn "publish_dev_task\|claim_dev_task\|complete_dev_task\|cancel_dev_task\|CRDTDevTaskMixin" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Expected after rewrite: zero matches in production code.

- [ ] **Step 1-3: Delete + verify + commit**

```bash
git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_dev_tasks.py 2>/dev/null || true
git commit -m "Delete CRDTDevTaskMixin and crdt_dev_tasks.py (migrated to WorkHub)"
```

### Task 12: Delete `tools/crdt_dev_task_tools.py` and bundle wiring

- [ ] **Step 1: Remove the file**

```bash
git rm agent/env_generator/llm_generator/tools/crdt_dev_task_tools.py
```

- [ ] **Step 2: Remove dev_task bundle references from `tool_bundles.py` and `agents_config.yaml`**.

Some agents have `crdt_dev_task_tools` in their `tool_bundles:` list. Replace with `workhub_tools` (already widened in Task 8).

- [ ] **Step 3: Verify imports + run tests + commit**

```bash
git commit -m "Delete crdt_dev_task_tools.py (replaced by extended workhub_tools)"
```

---

## Phase C — plan / plan_index migration

### Task 13: TDD parity — `update_plan` ↔ WorkHub `create_plan` + `update_plan_metadata`

**Files:**
- Create: `agent/tests/test_workhub_plan_migration.py`

- [ ] **Step 1-4: Parity tests + commit**

Tests assert:
- `workspace.update_plan(plan_id, {...})` → `hubs.workhub.get_plan(plan_id)` returns equivalent data (after upsert_plan_snapshot has had a chance to run).
- `workspace.claim_plan_task(plan, stage, task, agent)` → `hubs.workhub.claim_task("plan:{plan}:{stage}:{task}", agent)` parity.

```bash
git commit -m "Add WorkHub plan-migration parity tests"
```

### Task 14: Switch plan callers to WorkHub

Targets:
- `tools/reasoning_tools.py` (`plan(...)` tool's `_sync_plan_tasks_to_dev_tasks` flow)
- `multi_agent/runtime/crdt_projection.py` (if any plan writes)
- Any other site that calls `workspace.update_plan` / `claim_plan_task` / `update_plan_index`

Rewrite to use `hubs.workhub.create_plan` or `update_plan_metadata`; `claim_plan_task` becomes `claim_task` with stable id; `plan_index` is collapsed into plan metadata.

- [ ] **Step 1-3: Rewrite + verify + commit**

```bash
git commit -m "Switch plan / plan_index callers from CRDTWorkspace to WorkHub directly"
```

### Task 15: Delete legacy plan methods from `crdt.py`

Delete:
- `update_plan`
- `get_plan` (and `get_plans`)
- `claim_plan_task`
- `update_plan_index`
- `get_plan_index(es)`
- `_plans` and `_plan_indexes` stores (and `ensure_core_documents` entries)

- [ ] **Step 1-2: Delete + commit**

```bash
git commit -m "Delete CRDTWorkspace plan / plan_index methods + stores (migrated to WorkHub)"
```

---

## Phase D — page / project / share / escalate migration

### Task 16: Audit and migrate `update_page` callers

`update_page` is used for UI page status signals (e.g., `update_page("home", {"status": "implemented"})`). Per audit, recommend not building a KV-page adapter on WorkHub — instead, migrate semantics into `kind="ui_page"` blocks or fold into WorkHub `project` page.

Quick caller audit:
```bash
grep -rn "update_page\|get_pages\b" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Likely callers: `crdt_projection.py`, possibly orchestrator delivery gate. For each:
- If the page status is just "did frontend implement this UI?" → switch to WorkHub `kind="ui_page"` block with `content={"status": "implemented", "agent": "..."}` on the project page.
- If the page is purely a delivery-gate check → switch to `codehub_record_check(name="ui_page_{name}", status="passed", evidence={...})` (CodeHub already accepts arbitrary check names).

- [ ] **Step 1-3: Migrate each caller + commit**

```bash
git commit -m "Switch update_page callers to WorkHub blocks / CodeHub checks"
```

### Task 17: Migrate `set_project_info / set_project_phase / get_project_status`

These set a top-level project descriptor. Per audit recommendation, model as a special WorkHub page with `kind="project"`.

- [ ] **Step 1-3: Add WorkHub `set_project_info` / `set_project_phase` / `get_project_status` helpers** that internally upsert a page with `id="page:project:{name}"` and append phase-tracking blocks.

- [ ] **Step 4: Switch caller in `orchestrator.py:_enter_project_phase`** (around line 237) and `_spawn_core_agents` to use the WorkHub helpers.

- [ ] **Step 5: Verify, commit**

```bash
git commit -m "Migrate set_project_info / set_project_phase / get_project_status to WorkHub project page"
```

### Task 18: Migrate `share_implementation` to WorkHub block (`kind="knowledge"`)

- [ ] **Step 1: Add `WorkHub.share_implementation(title, content, agent, ...)` wrapper** that creates or finds a `kind="knowledge"` page and appends a block with the implementation snippet.

- [ ] **Step 2: Switch callers** in `tools/reasoning_tools.py`, `multi_agent/agents/runtime/sync.py` (`_process_knowledge_shares`), and any prompts that mention `share_implementation` directly.

- [ ] **Step 3: Commit**

```bash
git commit -m "Migrate share_implementation to WorkHub knowledge blocks"
```

### Task 19: Migrate `escalate_to_lead` to WorkHub comment

- [ ] **Step 1: Add a helper or document the pattern** — `workhub.comment(resource_id=plan_id, body=..., mentions=[lead_agent_id], agent=from_agent)` with `priority="urgent"` semantics in event metadata.

- [ ] **Step 2: Switch the existing `escalate_to_lead` caller** in `crdt_dev_tasks.py` (last method) — this should be one of the last lines of that file before Phase B deletes it. Switch it pre-deletion.

- [ ] **Step 3: Delete the method from `crdt_dev_tasks.py` (if not already done in Phase B)** + commit

```bash
git commit -m "Migrate escalate_to_lead to WorkHub mention comment"
```

---

## Phase E — agent_status → EventHub system topic

### Task 20: TDD — EventHub agent_status helpers

**Files:**
- Create: `agent/tests/test_eventhub_agent_status.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`

- [ ] **Step 1-3: Tests + helpers**

```python
    # Add to EventHub
    def record_agent_status(self, agent_id: str, status: dict) -> dict:
        return self.publish_event(
            source_hub="system",
            event_type="agent_status",
            payload={"agent_id": agent_id, **status},
            recipients=[],
            resource_type="agent",
            resource_id=agent_id,
            thread_id=f"thread:agent:{agent_id}",
            actor=agent_id,
        )

    def get_agent_status(self, agent_id: str):
        # Latest agent_status event by created_at for this agent
        latest = None
        for evt in self._events.value().values():
            if evt.get("source_hub") == "system" and evt.get("event_type") == "agent_status" \
               and evt.get("payload", {}).get("agent_id") == agent_id:
                if latest is None or evt.get("created_at", 0) > latest.get("created_at", 0):
                    latest = evt
        return latest.get("payload") if latest else None

    def get_all_agent_statuses(self) -> Dict[str, dict]:
        out = {}
        for evt in self._events.value().values():
            if evt.get("source_hub") != "system" or evt.get("event_type") != "agent_status":
                continue
            aid = evt.get("payload", {}).get("agent_id")
            if not aid:
                continue
            prev = out.get(aid)
            if prev is None or evt.get("created_at", 0) > prev.get("_event_created_at", 0):
                out[aid] = {**evt.get("payload", {}), "_event_created_at": evt.get("created_at", 0)}
        return out
```

- [ ] **Step 4: Commit**

```bash
git commit -m "Add EventHub agent_status system-topic helpers"
```

### Task 21: Switch `update_agent_status` callers + delete legacy methods

Targets: agents/base.py, agents/runtime/*, any health-check loops, observer callbacks.

Switch each call from `workspace.update_agent_status(id, status)` → `workspace.hubs.eventhub.record_agent_status(id, status)`.

Delete `update_agent_status` / `get_agent_statuses` / `observe_agents` and `_agent_status` store from `crdt.py`.

- [ ] **Step 1-3: Migrate + delete + commit**

```bash
git commit -m "Migrate update_agent_status to EventHub system topic, delete CRDT agent_status methods"
```

---

## Phase F — Final cleanup + ship

### Task 22: Audit remaining CRDT plan/page/project/share/escalate residues

```bash
grep -rn "workspace\.\(update_plan\|claim_plan_task\|update_plan_index\|update_page\|get_pages\|set_project_info\|set_project_phase\|share_implementation\|escalate_to_lead\)" --include='*.py' agent/ | grep -v __pycache__
```

Expected: zero matches. Any stragglers → fix in this task.

```bash
git commit -m "Final cleanup of legacy CRDT references" || true
```

### Task 23: Update 5 prompt files

Per audit and earlier cutovers, prompts reference legacy tool names. Update:
- `prompts/v2/orchestrator_agent.j2` — `set_project_info`, `set_project_phase`, `publish_dev_task` references
- `prompts/v2/design_agent.j2` — `update_page` (UI signaling) references
- `prompts/v2/database_agent.j2` — `update_table` (will defer to Cutover 4) and `publish_dev_task` references
- `prompts/v2/backend_agent.j2` — `publish_dev_task`, `share_implementation`
- `prompts/v2/frontend_agent.j2` — `publish_dev_task`, `share_implementation`
- `prompts/v2/verifier_agent.j2` — `publish_dev_task`, validation-failure flow (`create_dev_task_from_validation_failure` stays for Cutover 4)

Substitute with `workhub_create_task`, `workhub_link_task_to_pr`, `workhub_record_decision`, `workhub_comment` (for escalate), etc.

- [ ] **Step 1-4: Per file, edit + render-smoke + commit**

```bash
git commit -m "Update agent prompts to reference WorkHub tool names"
```

### Task 24: Full regression + e2e smoke

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest \
  agent.tests.test_workhub_completeness \
  agent.tests.test_workhub_dev_task_migration \
  agent.tests.test_workhub_plan_migration \
  agent.tests.test_workhub_page_project_share \
  agent.tests.test_eventhub_agent_status \
  agent.tests.test_eventhub_completeness \
  agent.tests.test_eventhub_subscription_fanout \
  agent.tests.test_eventhub_spawn_catchup \
  agent.tests.test_messagebus_bridge \
  agent.tests.test_apihub_accessors \
  agent.tests.test_apihub_strengthen \
  agent.tests.test_apihub_tools \
  agent.tests.test_apihub_breaking_change_creates_task \
  agent.tests.test_hub_architecture \
  2>&1 | tail -5
```

Expected: ~90+ OK total; regressions 7 OK.

E2E smoke (full LLM run is too long for cutover — defer to user). Minimum: confirm bridge still delivers via the same script from Cutover 2 Task 12.

### Task 25: Migration log + push

Create `docs/superpowers/migration-logs/04-workhub-and-migrations.md` with the full template (audit ref, scope per phase, commit list, test counts, gotchas, next).

```bash
git add docs/superpowers/migration-logs/04-workhub-and-migrations.md
git commit -m "Add Cutover 3 migration log"
git push red-env-gen haibotong-cutover-3-workhub-migrations -u
```

PR compare: `https://github.com/Virtue-AI/red-env-gen/compare/haibotong-cutover-2-eventhub-bridge...haibotong-cutover-3-workhub-migrations`

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer** on any commit (user preference, repo-wide).
- Use `dt` conda env Python: `/home/haibotong/miniconda3/envs/dt/bin/python`.
- Branch from `red-env-gen/haibotong-cutover-2-eventhub-bridge`.
- Each task = one commit (~25 commits).
- After this cutover, **the only remaining CRDTWorkspace responsibilities** are:
  - Tables (`update_table`, etc.) → Cutover 4
  - Validation / build / verification → Cutover 4
  - Artifacts → Cutover 4
  - Token / performance / retry / health metrics → Cutover 5
  - File coordination → Cutover 4 (delete + git)
  - The "shell" of `CRDTWorkspace` (`__init__`, `get_versions`, `snapshot`, `get_state_hash`, `wait_for_convergence`, `create_observer`) → Cutover 5

## Recovery Notes

If a phase explodes mid-cutover:
- Phase A is independent — can land on its own PR.
- Phases B-E are bundled but reversible per-task.
- Worst case: commit Phase A, revert B-F, and write a follow-up plan.
