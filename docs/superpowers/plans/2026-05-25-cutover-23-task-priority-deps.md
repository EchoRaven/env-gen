# Cutover 23: Task Priority + Dependency Graph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make WorkHub tasks first-class scheduled work. Add `priority` field (`P0|P1|P2|P3`, default `P2`). Enforce `depends_on` at `claim_task` time (refuse claim if any dep isn't completed). New helpers `list_ready_tasks` / `list_blocked_tasks` / `get_blockers_for`. Extend `hub_pulse` to surface assigned tasks sorted by (priority ASC, ready-first, created_at ASC). Orchestrator prompt teaches priority + dep discipline.

**Architecture:** Tasks already have `depends_on: List[str]` field (Cutover 10 era). Today it's metadata only — claim doesn't check. This cutover wires the enforcement. Priority rides on existing `metadata.priority` (mirrors how `severity` rides on metadata for bugs in Cutover 10). No new entity store. No new agent. All changes are surface-extensions and a new ordering helper.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Pure stdlib.

---

## Context for Worker

### Why this cutover exists

After Cutover 22 we have rich routing (bugs → triage → owner) and structural gates (coverage / visual / seed / mcp). What we DON'T have:

- **Priority signal**: orchestrator can't say "do P0 first." All tasks look equal in the queue.
- **Dep enforcement**: agent can `claim_task` and start building task B even when task A (which produces a needed schema/PR/file) isn't done. B produces wrong intermediate; cascade breaks.
- **Schedulability**: nothing tells an agent "this task is ready" vs "this task is waiting on others."

Real engineering coordination relies on both: priority signal (do important first) + dep graph (do prerequisites first). Without these, agents pick tasks in arrival order, often the wrong order.

### Schema additions (no new store)

Tasks already have:
- `depends_on: List[str]` (Cutover 10 schema; unused at claim time)
- `metadata: dict` (existing)

This cutover adds:
- `metadata.priority`: `"P0" | "P1" | "P2" | "P3"`, default `"P2"`
- (No new field needed for `blocks` — derived from reverse-lookup over `depends_on`)

### Claim enforcement

`claim_task(task_id, agent)` adds pre-check:
```python
for dep_id in task.get("depends_on", []):
    dep = self.stores.tasks.get(dep_id)
    if dep is None:
        return {"error": f"depends_on references missing task: {dep_id!r}"}
    if dep.get("status") != "completed":
        return {"error": f"task blocked: {dep_id!r} status={dep.get('status')!r}"}
```

This is the ONE behavioral change to existing flow. Everything else is additive.

### New helpers

- `list_ready_tasks(assignee=None)` — tasks where status=`pending` AND all deps complete; optionally filter by assignee
- `list_blocked_tasks(assignee=None)` — tasks where status=`pending` AND at least one dep incomplete; filter by assignee
- `get_blockers_for(task_id)` — list of incomplete deps for a given task (returns `[]` if ready)
- `get_blocked_by(task_id)` — reverse: list of tasks whose `depends_on` includes `task_id`

### Priority queue (hub_pulse)

`hub_pulse` already surfaces "assigned bugs" sorted by severity (Cutover 10 Task 9). Mirror that for tasks:

In `_pulse_assigned_tasks(hubs, agent_id)`:
- Get `list_ready_tasks(assignee=agent_id)` + `list_blocked_tasks(assignee=agent_id)`
- Sort ready by `(priority_rank, created_at)`
- Render `## YOUR TASK QUEUE` with ready tasks first (top-priority on top), then `## BLOCKED ON OTHERS` showing blocked tasks + which dep they wait on

Renders for ALL agents (not just orchestrator).

### LLM tool surface

- Existing `workhub_create_task` extended with `priority` kwarg
- Existing `workhub_claim_task` already exists — no signature change (error message changes when dep blocks)
- New tools:
  - `workhub_list_ready` / `workhub_list_blocked` — for explicit queries
  - `workhub_set_priority(task_id, priority)` — orchestrator can adjust mid-flight

### Out of scope (deferred)

- **SLA / staleness escalation**: tasks that sit in inbox for N steps without claim
- **Load rebalancing**: redistribute when one agent has too many tasks
- **Cross-priority preemption**: pause a P2 to handle a P0 mid-flight
- **Deadline / due-date fields**

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python`
- No Claude trailer; no emojis
- TDD throughout; bite-sized commits; no push until Task 7
- Both baselines green at every task: regressions 7 OK; discover 862 OK after Cutover 22

---

## File Structure

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — extend `create_task` with priority validation; gate `claim_task` on deps; add `list_ready_tasks` / `list_blocked_tasks` / `get_blockers_for` / `get_blocked_by`
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py` — add `_pulse_assigned_tasks` + `## YOUR TASK QUEUE` render
- `agent/env_generator/llm_generator/tools/workhub_tools.py` (or wherever `workhub_create_task` lives — re-grep) — extend with `priority` param + add `workhub_list_ready` / `workhub_list_blocked` / `workhub_set_priority`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — PRIORITY + DEPENDENCY DISCIPLINE block

**New files:**
- `agent/tests/test_workhub_task_priority.py`
- `agent/tests/test_workhub_task_deps.py`
- `agent/tests/test_hub_pulse_task_queue.py`
- `agent/tests/test_orchestrator_priority_prompt.py`
- `agent/tests/test_task_priority_e2e.py`

---

## Task 1: Worktree + baseline + recon

**Files:**
- Create: `docs/superpowers/cutover-23-baseline.md`

- [ ] **Step 1: Verify worktree + run baselines**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-23-priority-deps
git status
git log --oneline -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: clean worktree; 7 OK / 862 OK. If missing: `git worktree add -b haibotong-cutover-23-priority-deps .worktrees/haibotong-cutover-23-priority-deps haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Locate `workhub_create_task` LLM tool**

```bash
grep -rnE "class .*CreateTaskTool|NAME = .workhub_create_task" agent/env_generator/llm_generator/tools/ | head -5
```

Record path. Task 4 will extend it. (Likely `tools/hub_tools.py` since other workhub_* tools live there.)

- [ ] **Step 3: Confirm Cutover-16 `_pulse_assigned_bugs` anchor in hub_pulse.py**

```bash
grep -nE "_pulse_assigned_bugs|_pulse_open_bug_queue" agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py
```

Task 5 inserts `_pulse_assigned_tasks` next to these.

- [ ] **Step 4: Baseline note + commit**

Create `docs/superpowers/cutover-23-baseline.md`:

```markdown
# Cutover 23 Baseline (Task Priority + Dependency Graph)

## Test counts
- regressions: 7 OK
- discover: 862 OK

## Current state
- WorkHub tasks have depends_on field (Cutover 10) but claim_task doesn't enforce it
- No priority signal — all tasks look equal in queues
- hub_pulse surfaces assigned bugs (Cutover 10) but not assigned tasks

## Approach
- Add metadata.priority {P0|P1|P2|P3, default P2}
- Enforce depends_on at claim_task: refuse if any dep incomplete
- New helpers: list_ready_tasks, list_blocked_tasks, get_blockers_for, get_blocked_by
- Extend hub_pulse with ## YOUR TASK QUEUE + ## BLOCKED ON OTHERS sections
- Extend workhub_create_task tool with priority param; add list_ready/blocked + set_priority tools
- Orchestrator prompt teaches PRIORITY + DEPENDENCY DISCIPLINE

## No new entity stores; no new agent; all additive
```

```bash
git add docs/superpowers/cutover-23-baseline.md
git commit -m "Cutover 23: record pre-flight baseline (regressions 7 OK, discover 862 OK)"
```

Verify no Claude trailer.

---

## Task 2: WorkHub priority validation + claim_task dep enforcement

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_task_priority.py`
- Create: `agent/tests/test_workhub_task_deps.py`

- [ ] **Step 1: Write failing tests (priority)**

Create `agent/tests/test_workhub_task_priority.py`:

```python
"""Tests for WorkHub task priority (Cutover 23)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CreateTaskPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_pri_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_priority_is_P2(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch")
        self.assertEqual((t.get("metadata") or {}).get("priority"), "P2")

    def test_explicit_priority_stored(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", priority="P0")
        self.assertEqual((t.get("metadata") or {}).get("priority"), "P0")

    def test_invalid_priority_rejected(self) -> None:
        result = self.reg.workhub.create_task(
            title="x", agent="orch", priority="urgent")
        self.assertIn("error", result)
        self.assertIn("priority", result["error"].lower())

    def test_priority_round_trips_through_metadata(self) -> None:
        for p in ("P0", "P1", "P2", "P3"):
            t = self.reg.workhub.create_task(title=p, agent="orch", priority=p)
            self.assertEqual((t.get("metadata") or {}).get("priority"), p)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write failing tests (dep enforcement)**

Create `agent/tests/test_workhub_task_deps.py`:

```python
"""Tests for WorkHub dependency enforcement at claim time (Cutover 23)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class ClaimTaskDepsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_deps_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claim_succeeds_when_no_deps(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", assignee="backend")
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertEqual(result.get("status"), "in_progress")

    def test_claim_blocked_when_dep_pending(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)
        self.assertIn("blocked", result["error"].lower())

    def test_claim_succeeds_after_dep_completed(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        self.reg.workhub.claim_task(dep["id"], agent="backend")
        self.reg.workhub.complete_task(dep["id"], agent="backend", result={"ok": True})
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertEqual(result.get("status"), "in_progress")

    def test_claim_blocked_when_any_dep_pending(self) -> None:
        a = self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        b = self.reg.workhub.create_task(title="b", agent="orch", assignee="backend")
        self.reg.workhub.claim_task(a["id"], agent="backend")
        self.reg.workhub.complete_task(a["id"], agent="backend", result={"ok": True})
        # b is still pending; task with deps [a, b] should be blocked
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend",
            depends_on=[a["id"], b["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)

    def test_claim_error_message_names_blocker(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn(dep["id"], result["error"])

    def test_claim_missing_dep_id_rejected(self) -> None:
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend",
            depends_on=["task_nonexistent"])
        result = self.reg.workhub.claim_task(t["id"], agent="backend")
        self.assertIn("error", result)
        self.assertIn("nonexistent", result["error"])


class ReadyBlockedHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_ready_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_ready_empty_when_nothing_pending(self) -> None:
        self.assertEqual(self.reg.workhub.list_ready_tasks(), [])

    def test_ready_includes_pending_with_no_deps(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", assignee="backend")
        ready = self.reg.workhub.list_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["id"], t["id"])

    def test_blocked_separates_from_ready(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        blocked = self.reg.workhub.create_task(
            title="b", agent="orch", assignee="backend", depends_on=[dep["id"]])
        ready = self.reg.workhub.list_ready_tasks()
        blocked_list = self.reg.workhub.list_blocked_tasks()
        ready_ids = {t["id"] for t in ready}
        blocked_ids = {t["id"] for t in blocked_list}
        self.assertIn(dep["id"], ready_ids)
        self.assertIn(blocked["id"], blocked_ids)
        self.assertNotIn(dep["id"], blocked_ids)
        self.assertNotIn(blocked["id"], ready_ids)

    def test_list_ready_filters_by_assignee(self) -> None:
        self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        self.reg.workhub.create_task(title="b", agent="orch", assignee="frontend")
        backend_ready = self.reg.workhub.list_ready_tasks(assignee="backend")
        self.assertEqual(len(backend_ready), 1)
        self.assertEqual(backend_ready[0]["title"], "a")

    def test_get_blockers_returns_incomplete_deps(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        t = self.reg.workhub.create_task(
            title="t", agent="orch", assignee="backend", depends_on=[dep["id"]])
        blockers = self.reg.workhub.get_blockers_for(t["id"])
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["id"], dep["id"])

    def test_get_blocked_by_returns_dependents(self) -> None:
        a = self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        b = self.reg.workhub.create_task(
            title="b", agent="orch", assignee="backend", depends_on=[a["id"]])
        c = self.reg.workhub.create_task(
            title="c", agent="orch", assignee="backend", depends_on=[a["id"]])
        dependents = self.reg.workhub.get_blocked_by(a["id"])
        dep_ids = {t["id"] for t in dependents}
        self.assertEqual(dep_ids, {b["id"], c["id"]})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_task_priority -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_task_deps -v 2>&1 | tail -15
```

Expected: priority tests fail because `priority` validation isn't enforced; dep tests fail because `claim_task` doesn't gate AND helpers don't exist.

- [ ] **Step 4: Extend `create_task` with priority validation**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, find the existing `create_task` method. After the signature, add priority validation BEFORE the task dict is built:

```python
    _VALID_PRIORITIES = ("P0", "P1", "P2", "P3")
    _PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
```

(Add as class constants near other WorkHub class constants if any, otherwise at the top of the class.)

In `create_task`, at the top of the method body:

```python
        # Cutover 23: priority validation
        priority = metadata.pop("priority", "P2") if isinstance(metadata, dict) else "P2"
        if priority not in self._VALID_PRIORITIES:
            return {"error": f"invalid priority {priority!r}, must be one of {self._VALID_PRIORITIES}"}
```

Wait — `metadata` is `**metadata: Any` in the signature. So `priority` is just a kwarg. Adapt:

```python
    def create_task(
        self,
        title: str,
        description: str = "",
        assignee: str = None,
        plan_id: str = None,
        depends_on: Optional[List[str]] = None,
        agent: str = "",
        task_id: str = None,
        **metadata: Any,
    ) -> dict:
        # Cutover 23: priority validation
        priority = metadata.pop("priority", "P2")
        if priority not in self._VALID_PRIORITIES:
            return {"error": f"invalid priority {priority!r}, must be one of {self._VALID_PRIORITIES}"}
        metadata["priority"] = priority
        # ...rest of existing impl stores `metadata` dict into the task...
```

(The existing `create_task` already does `"metadata": metadata or {}` in the task dict; the `priority` re-insertion ensures it survives.)

- [ ] **Step 5: Extend `claim_task` with dep enforcement**

Find `claim_task` (line 461 per Task 1 recon). After the existing `if not task` / `if task.get("status") != "pending"` / `if task.get("assignee")` checks, add:

```python
        # Cutover 23: enforce depends_on
        for dep_id in (task.get("depends_on") or []):
            dep = self.stores.tasks.get(dep_id)
            if dep is None:
                return {"error": f"task blocked: depends_on references missing task: {dep_id!r}"}
            if dep.get("status") != "completed":
                return {"error": f"task blocked: dep {dep_id!r} status={dep.get('status')!r} (must be 'completed')"}
```

- [ ] **Step 6: Add 4 new helpers**

Find a good anchor (near `list_tasks` at line 624 or near `claim_task`). Add:

```python
    def list_ready_tasks(self, assignee: str = None) -> list:
        """Pending tasks whose deps are all completed."""
        out = []
        all_tasks = self.stores.tasks.value() or {}
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            if assignee is not None and task.get("assignee") != assignee:
                continue
            blockers = [d for d in (task.get("depends_on") or [])
                        if (all_tasks.get(d) or {}).get("status") != "completed"]
            if not blockers:
                out.append(task)
        # Sort by (priority_rank, created_at)
        out.sort(key=lambda t: (
            self._PRIORITY_RANK.get((t.get("metadata") or {}).get("priority", "P2"), 99),
            t.get("created_at", 0.0),
        ))
        return out

    def list_blocked_tasks(self, assignee: str = None) -> list:
        """Pending tasks with at least one incomplete dep."""
        out = []
        all_tasks = self.stores.tasks.value() or {}
        for task in all_tasks.values():
            if task.get("status") != "pending":
                continue
            if assignee is not None and task.get("assignee") != assignee:
                continue
            blockers = [d for d in (task.get("depends_on") or [])
                        if (all_tasks.get(d) or {}).get("status") != "completed"]
            if blockers:
                out.append(task)
        out.sort(key=lambda t: (
            self._PRIORITY_RANK.get((t.get("metadata") or {}).get("priority", "P2"), 99),
            t.get("created_at", 0.0),
        ))
        return out

    def get_blockers_for(self, task_id: str) -> list:
        """Return list of incomplete dep tasks for the given task."""
        task = self.stores.tasks.get(task_id)
        if not task:
            return []
        out = []
        for dep_id in (task.get("depends_on") or []):
            dep = self.stores.tasks.get(dep_id)
            if dep and dep.get("status") != "completed":
                out.append(dep)
        return out

    def get_blocked_by(self, task_id: str) -> list:
        """Reverse lookup: tasks whose depends_on includes task_id."""
        out = []
        for task in (self.stores.tasks.value() or {}).values():
            if task_id in (task.get("depends_on") or []):
                out.append(task)
        return out
```

- [ ] **Step 7: Verify all tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_task_priority agent.tests.test_workhub_task_deps -v 2>&1 | tail -25
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 priority + 12 deps = 16 OK; 7 OK / 878 OK (862 + 16 new).

If existing tests break (e.g., a Cutover-10 bug test that creates a task with stale `priority="urgent"` metadata or a test that claims a task with un-completed deps), update them minimally to satisfy the new rules.

- [ ] **Step 8: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_task_priority.py agent/tests/test_workhub_task_deps.py
git commit -m "WorkHub: validate task priority (P0-P3) + enforce depends_on at claim + add list_ready/blocked + get_blockers/blocked_by"
```

---

## Task 3: hub_pulse `## YOUR TASK QUEUE` + `## BLOCKED ON OTHERS`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`
- Create: `agent/tests/test_hub_pulse_task_queue.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_hub_pulse_task_queue.py`:

```python
"""Tests that hub_pulse renders TASK QUEUE + BLOCKED ON OTHERS sections (Cutover 23)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse, build_hub_pulse_prompt  # noqa: E402


class HubPulseTaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_task_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pulse_renders_ready_task_sorted_p0_first(self) -> None:
        self.reg.workhub.create_task(
            title="low priority", agent="orch", assignee="backend", priority="P3")
        self.reg.workhub.create_task(
            title="critical", agent="orch", assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("TASK QUEUE", rendered.upper())
        # critical (P0) should appear before low (P3) in the rendered output
        p0_idx = rendered.find("critical")
        p3_idx = rendered.find("low priority")
        self.assertGreater(p3_idx, p0_idx,
                            "P0 task should be rendered before P3 task")

    def test_pulse_renders_blocked_section_when_deps_incomplete(self) -> None:
        dep = self.reg.workhub.create_task(
            title="dep", agent="orch", assignee="frontend")
        self.reg.workhub.create_task(
            title="waiting", agent="orch", assignee="backend",
            depends_on=[dep["id"]])
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("BLOCKED", rendered.upper())
        self.assertIn("waiting", rendered)

    def test_pulse_omits_section_when_no_assigned_tasks(self) -> None:
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        # No section header when there's nothing to render
        # (this can be relaxed if the prompt always shows the header)
        self.assertNotIn("TASK QUEUE", rendered.upper())

    def test_pulse_priority_label_in_render(self) -> None:
        self.reg.workhub.create_task(
            title="urgent task", agent="orch", assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("[P0]", rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_task_queue -v 2>&1 | tail -10
```

Expected: failures (no task queue rendering yet).

- [ ] **Step 3: Extend `hub_pulse.py`**

In `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`:

Add a helper (near `_pulse_assigned_bugs`):

```python
def _pulse_assigned_tasks(hubs, agent_id):
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_ready_tasks"):
        return [], []
    try:
        ready = wh.list_ready_tasks(assignee=agent_id)
        blocked = wh.list_blocked_tasks(assignee=agent_id)
    except Exception:
        return [], []
    return ready, blocked
```

In `collect_hub_pulse` (or whichever the canonical collector is), add to the returned report:

```python
    ready, blocked = _pulse_assigned_tasks(hubs, agent_id)
    report["ready_tasks"] = ready
    report["blocked_tasks"] = blocked
```

In `build_hub_pulse_prompt`, add render after the existing `## ASSIGNED BUGS` section:

```python
    ready = report.get("ready_tasks") or []
    blocked = report.get("blocked_tasks") or []
    if ready:
        rows = "\n".join(
            f"- [{(t.get('metadata') or {}).get('priority', 'P2')}] "
            f"{t.get('title')} ({t.get('id')})"
            for t in ready
        )
        sections.append(f"## YOUR TASK QUEUE\n{rows}")
    if blocked:
        rows = []
        for t in blocked:
            blockers = [d for d in (t.get('depends_on') or [])
                        if d != t.get('id')]
            rows.append(
                f"- [{(t.get('metadata') or {}).get('priority', 'P2')}] "
                f"{t.get('title')} ({t.get('id')}) — waiting on: "
                f"{', '.join(blockers[:3])}"
            )
        sections.append("## BLOCKED ON OTHERS\n" + "\n".join(rows))
```

(Adapt to match existing render style — the sections-list builder pattern is used by `## ASSIGNED BUGS` (Cutover 10 Task 9) and `## RECENT RUN` (Cutover 11 Task 9). Mirror that.)

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_task_queue -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 882 OK (878 + 4 new). Existing pulse tests should remain green (new fields default empty).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py agent/tests/test_hub_pulse_task_queue.py
git commit -m "hub_pulse: surface YOUR TASK QUEUE + BLOCKED ON OTHERS (priority-sorted, dep-aware)"
```

---

## Task 4: LLM tools — priority kwarg + list/set helpers

**Files:**
- Modify: tool file containing `workhub_create_task` (found in Task 1 Step 2; likely `tools/hub_tools.py`)
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` (if new tools need wiring)
- Create: `agent/tests/test_workhub_priority_tools.py`

- [ ] **Step 1: Read the existing `workhub_create_task` tool**

```bash
grep -nA 30 "class .*CreateTaskTool" agent/env_generator/llm_generator/tools/hub_tools.py | head -50
```

Note the existing signature + how `metadata` is built.

- [ ] **Step 2: Write failing tests**

Create `agent/tests/test_workhub_priority_tools.py`:

```python
"""Tests for workhub LLM tools with priority support (Cutover 23)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class WorkhubPriorityToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_pri_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _find_tool(self, name: str):
        from tools.hub_tools import create_hub_tools
        for tool in create_hub_tools(agent_id="orch", hub_workspace=self.reg):
            if getattr(tool, "NAME", "") == name:
                return tool
        raise AssertionError(f"tool not found: {name}")

    def test_create_task_tool_accepts_priority(self) -> None:
        tool = self._find_tool("workhub_create_task")
        result = _run_async(tool._run(
            title="urgent", assignee="backend", priority="P0"))
        self.assertTrue(result.success)
        task_id = result.data["task"]["id"]
        task = self.reg.workhub.stores.tasks.get(task_id)
        self.assertEqual((task.get("metadata") or {}).get("priority"), "P0")

    def test_set_priority_tool(self) -> None:
        tool_create = self._find_tool("workhub_create_task")
        result = _run_async(tool_create._run(title="x", assignee="backend"))
        task_id = result.data["task"]["id"]
        # set priority via new tool
        tool_set = self._find_tool("workhub_set_priority")
        result = _run_async(tool_set._run(task_id=task_id, priority="P0"))
        self.assertTrue(result.success)
        task = self.reg.workhub.stores.tasks.get(task_id)
        self.assertEqual((task.get("metadata") or {}).get("priority"), "P0")

    def test_list_ready_tool(self) -> None:
        self.reg.workhub.create_task(title="a", agent="orch", assignee="backend")
        self.reg.workhub.create_task(title="b", agent="orch", assignee="backend")
        tool = self._find_tool("workhub_list_ready")
        result = _run_async(tool._run(assignee="backend"))
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["ready"]), 2)

    def test_list_blocked_tool(self) -> None:
        dep = self.reg.workhub.create_task(title="dep", agent="orch", assignee="backend")
        self.reg.workhub.create_task(
            title="blocked", agent="orch", assignee="backend",
            depends_on=[dep["id"]])
        tool = self._find_tool("workhub_list_blocked")
        result = _run_async(tool._run(assignee="backend"))
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["blocked"]), 1)
        self.assertEqual(result.data["blocked"][0]["title"], "blocked")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Implement tool extensions**

In `tools/hub_tools.py` (or wherever `workhub_create_task` lives):

**(a)** Find `class CodeHubCreateTaskTool` (or `WorkHubCreateTaskTool` — exact name from grep). Update its `PARAMETERS` to add `priority`:

```python
        # Add to existing PARAMETERS["properties"]:
        "priority": {"type": "string",
                      "enum": ["P0", "P1", "P2", "P3"],
                      "default": "P2",
                      "description": "Task priority (P0=urgent, P3=nice-to-have)"},
```

And update the `_run` signature to accept `priority="P2"` and forward to `create_task(..., priority=priority)`.

**(b)** Add 3 new tool classes in the same file (or sibling file — match existing convention):

```python
class WorkhubSetPriorityTool(HubTool):
    NAME = "workhub_set_priority"
    DESCRIPTION = "Adjust an existing task's priority (P0|P1|P2|P3)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
        },
        "required": ["task_id", "priority"],
    }

    async def _run(self, *, task_id: str, priority: str) -> ToolResult:
        task = self._hubs.workhub.stores.tasks.get(task_id)
        if not task:
            return ToolResult(success=False,
                              error_message=f"task not found: {task_id}")
        if priority not in ("P0", "P1", "P2", "P3"):
            return ToolResult(success=False,
                              error_message=f"invalid priority: {priority}")
        updated = dict(task)
        meta = dict(updated.get("metadata") or {})
        meta["priority"] = priority
        updated["metadata"] = meta
        import time as _t
        updated["_updated_by"] = self._agent_id
        updated["_updated_at"] = _t.time()
        self._hubs.workhub.stores.tasks.update(
            lambda m: m.set(task_id, updated, self._agent_id),
            change_info={"agent": self._agent_id})
        return ToolResult(success=True, data={"task": updated})


class WorkhubListReadyTool(HubTool):
    NAME = "workhub_list_ready"
    DESCRIPTION = ("List pending tasks whose deps are all completed, sorted "
                    "by (priority, created_at). Optionally filter by assignee.")
    PARAMETERS = {
        "type": "object",
        "properties": {"assignee": {"type": "string"}},
    }

    async def _run(self, *, assignee: str = None) -> ToolResult:
        ready = self._hubs.workhub.list_ready_tasks(assignee=assignee)
        return ToolResult(success=True, data={"ready": ready})


class WorkhubListBlockedTool(HubTool):
    NAME = "workhub_list_blocked"
    DESCRIPTION = ("List pending tasks waiting on incomplete deps. "
                    "Each entry shows which deps block it.")
    PARAMETERS = {
        "type": "object",
        "properties": {"assignee": {"type": "string"}},
    }

    async def _run(self, *, assignee: str = None) -> ToolResult:
        blocked = self._hubs.workhub.list_blocked_tasks(assignee=assignee)
        return ToolResult(success=True, data={"blocked": blocked})
```

**(c)** Register the 3 new classes in `create_hub_tools` factory (find the existing tool list inside the factory and append).

If `_finalize_hub_tools` (or similar) needs them, add them too — match the existing convention in the file.

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_priority_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 886 OK (882 + 4 new).

If `test_no_duplicate_tool_names` (Cutover 18) flags a collision with existing tool NAMEs, rename to `workhub_*` (which they already are — no collision expected).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/hub_tools.py agent/tests/test_workhub_priority_tools.py
git commit -m "workhub tools: priority kwarg on create_task + workhub_set_priority / list_ready / list_blocked"
```

---

## Task 5: Orchestrator prompt — PRIORITY + DEPENDENCY DISCIPLINE

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_priority_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_priority_prompt.py`:

```python
"""Tests that orchestrator prompt teaches task priority + dependency discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorPriorityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_mentions_priority_levels(self) -> None:
        upper = self.system.upper()
        for p in ("P0", "P1", "P2", "P3"):
            self.assertIn(p, upper)

    def test_mentions_depends_on_enforcement(self) -> None:
        upper = self.system.upper()
        self.assertIn("DEPENDS_ON", upper)

    def test_mentions_list_ready_and_blocked(self) -> None:
        upper = self.system.upper()
        self.assertIn("WORKHUB_LIST_READY", upper)
        self.assertIn("WORKHUB_LIST_BLOCKED", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Add prompt block**

In `lead_specifics()` of `orchestrator_agent.j2`, after the existing SEED SUFFICIENCY block (Cutover 21), append:

```jinja
### PRIORITY + DEPENDENCY DISCIPLINE (Cutover 23)
Tasks have two scheduling signals — use them when you `workhub_create_task`:

**Priority** (P0-P3, default P2):
- P0 = release-blocker / fix-now (auth broken, deploy stuck)
- P1 = important / current-feature (the main path you're shipping)
- P2 = normal (default; routine work)
- P3 = nice-to-have / polish (skip if time-bound)

Pass `priority="P0"` etc. in `workhub_create_task`. Use `workhub_set_priority(task_id, priority)` to escalate/de-escalate mid-flight.

**Dependencies** (`depends_on=[task_id1, task_id2]`):
- If task B logically requires task A's output (e.g., backend route depends on database schema), set `depends_on=[A_id]` when creating B.
- `claim_task` REFUSES to claim B until every task in `depends_on` is status="completed".
- Use `workhub_list_blocked(assignee=<agent>)` to see what's waiting; `workhub_list_ready(assignee=<agent>)` to see what an agent can pick up next.

**hub_pulse** automatically surfaces `## YOUR TASK QUEUE` (ready tasks sorted P0-first) and `## BLOCKED ON OTHERS` (blocked tasks + which dep they wait on) to every assignee. You don't need to re-narrate.

**Scheduling rule**: when assigning multi-step work, set priorities and deps DURING `workhub_create_task` — don't bolt them on later. The pulse + claim-gate only enforce what's already declared.
```

- [ ] **Step 4: Verify 3 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_priority_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 889 OK (886 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_orchestrator_priority_prompt.py
git commit -m "Orchestrator prompt: PRIORITY + DEPENDENCY DISCIPLINE block (P0-P3 + depends_on + list_ready/blocked)"
```

---

## Task 6: E2E test

**Files:**
- Create: `agent/tests/test_task_priority_e2e.py`

- [ ] **Step 1: Write the E2E test**

Create `agent/tests/test_task_priority_e2e.py`:

```python
"""E2E: create P0 task with deps; backend's claim refused until dep complete; pulse reflects it."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse, build_hub_pulse_prompt  # noqa: E402


class TaskPriorityE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_e2e_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_dep_chain_flow(self) -> None:
        # Orchestrator creates dep + dependent + assigns both
        dep = self.reg.workhub.create_task(
            title="design schema", agent="orch",
            assignee="database", priority="P1")
        dependent = self.reg.workhub.create_task(
            title="implement feed endpoint", agent="orch",
            assignee="backend", priority="P0",
            depends_on=[dep["id"]])

        # Backend's pulse should show dependent BLOCKED (waiting on dep)
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("BLOCKED ON OTHERS", rendered.upper())
        self.assertIn("implement feed endpoint", rendered)

        # Backend tries to claim -> refused
        claim_result = self.reg.workhub.claim_task(dependent["id"], agent="backend")
        self.assertIn("error", claim_result)

        # Database claims + completes its dep
        self.reg.workhub.claim_task(dep["id"], agent="database")
        self.reg.workhub.complete_task(dep["id"], agent="database",
                                        result={"schema": "users"})

        # Now backend's pulse should show dependent READY
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("YOUR TASK QUEUE", rendered.upper())
        self.assertIn("implement feed endpoint", rendered)
        # And critically: [P0] prefix since it's priority P0
        self.assertIn("[P0]", rendered)

        # Backend can now claim
        claim_result = self.reg.workhub.claim_task(dependent["id"], agent="backend")
        self.assertEqual(claim_result.get("status"), "in_progress")

    def test_pulse_priority_sort_p0_before_p3(self) -> None:
        # Create one P3 first, then P0; both assigned to backend, no deps
        self.reg.workhub.create_task(
            title="cleanup logs", agent="orch",
            assignee="backend", priority="P3")
        self.reg.workhub.create_task(
            title="fix prod outage", agent="orch",
            assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        # P0 should appear before P3 regardless of creation order
        self.assertLess(rendered.find("fix prod outage"),
                          rendered.find("cleanup logs"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify 2 tests + final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_task_priority_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 2 OK; 7 OK / 891 OK (889 + 2 new).

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_task_priority_e2e.py
git commit -m "Add task priority + dep E2E: full chain blocked->complete dep->ready->claim succeeds"
```

---

## Task 7: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/24-task-priority-deps.md`

- [ ] **Step 1: Final baselines + Claude trailer check**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: 7 OK / 891 OK; trailer count 0.

- [ ] **Step 2: Write migration log**

Create `docs/superpowers/migration-logs/24-task-priority-deps.md`:

```markdown
# Cutover 23: Task Priority + Dependency Graph

**Branch:** `haibotong-cutover-23-priority-deps`
**Date:** 2026-05-25

## What

WorkHub tasks gain scheduling signals:
- **priority** metadata field (P0-P3, default P2)
- **depends_on** enforced at claim time (was metadata-only)
- hub_pulse surfaces `## YOUR TASK QUEUE` (ready, P0-first) + `## BLOCKED ON OTHERS` per agent
- 3 new LLM tools: workhub_set_priority / workhub_list_ready / workhub_list_blocked
- create_task tool extended with `priority` kwarg

## Why

After 22 cutovers we had rich routing + structural gates but no scheduling
signal. Agents picked tasks in arrival order; deps were declared but never
enforced; orchestrator couldn't say "do P0 first". Both real-engineering
basics — now mechanical.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 862 OK -> 891 OK (+29 new)

## Schema additions (no new entity stores)
- `metadata.priority`: "P0" | "P1" | "P2" | "P3" (default "P2")
- `depends_on`: List[str] (existed; now enforced at claim_task)

## API additions
- WorkHub: list_ready_tasks(assignee=None), list_blocked_tasks(assignee=None), get_blockers_for(task_id), get_blocked_by(task_id)
- WorkHub: create_task(priority=) validated
- WorkHub: claim_task refuses if any dep != "completed"
- LLM tools: workhub_create_task(priority=); workhub_set_priority; workhub_list_ready; workhub_list_blocked

## Render additions
- hub_pulse: ## YOUR TASK QUEUE (P0-first sorted) + ## BLOCKED ON OTHERS (with blocker IDs)

## Known limits (future cutovers)
- No SLA / staleness escalation (a P0 sitting unclaimed for 50 steps doesn't auto-escalate)
- No cross-priority preemption (P0 doesn't pause an in-progress P2)
- No load rebalancing (one agent hit with 20 tasks doesn't rebalance)
- Priority change doesn't re-emit notification to assignee
```

- [ ] **Step 3: Commit + push**

```bash
git add docs/superpowers/migration-logs/24-task-priority-deps.md
git commit -m "Add Cutover 23 migration log"
git push red-env-gen haibotong-cutover-23-priority-deps 2>&1 | tail -5
```

- [ ] **Step 4: Report** — final test counts, push URL, deferred items.

---

## Self-Review

**1. Spec coverage:** WorkHub priority + dep enforcement + helpers (T2) ✓; hub_pulse render (T3) ✓; LLM tools (T4) ✓; orchestrator prompt (T5) ✓; E2E (T6) ✓; log + push (T7) ✓.

**2. Placeholder scan:** No TBD / "implement later". All code shown.

**3. Type consistency:**
- `priority ∈ {"P0", "P1", "P2", "P3"}` consistent in WorkHub + tool + prompt + tests
- `_PRIORITY_RANK = {P0: 0, ..., P3: 3}` for sort ordering — same across pulse + workhub
- `list_ready_tasks(assignee=None)` / `list_blocked_tasks(assignee=None)` / `get_blockers_for(task_id)` / `get_blocked_by(task_id)` — signatures consistent
- `claim_task` error keyword `"blocked"` — same in assertions + impl
- Tool NAMEs: `workhub_create_task`, `workhub_set_priority`, `workhub_list_ready`, `workhub_list_blocked` — consistent + no collisions
- Render strings: `## YOUR TASK QUEUE`, `## BLOCKED ON OTHERS`, `[Pn]` priority prefix — consistent

**4. Cross-cutting:**
- No Claude trailer (T1 + T7) ✓
- Baselines green per task ✓
- TDD throughout ✓
- No new entity stores — rides on existing tasks store ✓
- No new agent — pure schema + behavior + render extension ✓
