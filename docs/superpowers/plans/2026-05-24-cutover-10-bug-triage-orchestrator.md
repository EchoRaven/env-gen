# Cutover 10: Bug Triage Orchestrator

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the bug-handling workflow into three single-responsibility roles — Verifier *finds* bugs, **Bug Triage Orchestrator** *analyzes & routes* bugs, owning agent *fixes* bugs — instead of Verifier doing all three at once.

**Architecture:** Bug Triage Orchestrator is a new top-level agent (sibling of the main Orchestrator) that subscribes to bug-emitting EventHub events (`verifier/bug_found`, `runhub/run_failed` (future), `codehub/check_failed`), pulls the bug payload, runs root-cause analysis using APIHub/WorkHub/CodeHub context, identifies the owning agent (via APIHub's existing `provider` field on endpoints/tables and CodeHub's last-committer on files), creates a remediation task on WorkHub with structured bug metadata (`severity`, `bug_state`, `root_cause_hypothesis`, `parent_bug_id`, `bug_artifacts`), and publishes a `bug_triaged/{agent}` event so the assignee's `hub_pulse` picks it up. Bugs ride on existing WorkHub tasks via `metadata.kind = "bug"` plus bug-specific fields — no separate entity store needed.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest, Jinja2 prompts, existing WorkHub/APIHub/CodeHub/EventHub surfaces (post-Cutover 9 — `JsonStore`, `hub_dir`, `shared/hubs/`).

---

## Context for Worker

### Why this cutover exists

Today, Verifier does three jobs at once: (1) runs contract tests, (2) decides what the failure means, (3) decides who should fix it. That conflates *detection*, *triage*, and *assignment* — three distinct skills that real engineering orgs separate (monitoring/alerting ≠ root cause analysis ≠ fix). The advisor's request is to **let Verifier only find bugs**, and route all triage/assignment through a dedicated **Bug Triage Orchestrator** agent.

### What changes

- Verifier: when a bug is found, publish a `verifier/bug_found` EventHub event with a structured payload. **DO NOT create a remediation task directly.**
- BugTriageOrchestrator (new agent): subscribed to bug events. Runs an analysis loop: read payload → cross-reference APIHub/CodeHub/WorkHub → emit a `WorkHub task` with `metadata.kind="bug"` and `assignee=<owning agent>`. Publishes `bug_triaged/{agent}` for live delivery.
- Owning agents (backend/database/frontend/etc.): their existing `hub_pulse` already shows assigned WorkHub tasks; a small render tweak makes bug tasks visually distinct (severity prefix).
- New tool surface: `bug_*` LLM tools (create, list_open, list_assigned_to, triage, update_state, close, escalate).

### Bug schema (rides on existing WorkHub tasks)

We do NOT create a new store. Bugs are ordinary tasks plus structured metadata:

```python
{
    "id": "task_<hex>",
    "title": "BUG: 500 on POST /api/feed",
    "description": "<verifier-supplied detail>",
    "assignee": "backend",       # set by triage
    "status": "pending",         # task lifecycle (existing)
    "metadata": {
        "kind": "bug",                            # discriminator
        "severity": "P1",                         # P0|P1|P2|P3
        "bug_state": "triaged",                   # open|triaged|assigned|in_progress|fix_proposed|fix_verified|closed|escalated
        "root_cause_hypothesis": "Missing null check on user_id",
        "parent_bug_id": null,                    # set if this is a recurrence
        "source": "verifier",                     # verifier|runhub|codehub_check|manual
        "bug_artifacts": {                        # raw bug evidence
            "failing_test": "test_feed_post_returns_200",
            "stack_trace": "...",
            "affected_endpoint": "POST /api/feed",
            "affected_files": ["backend/routes/feed.py"],
            "expected": "201",
            "actual": "500",
        },
        "triage_history": [                       # append-only audit
            {"at": 1716552000.0, "by": "bug_triage_orchestrator", "action": "triaged", "note": "..."},
            ...
        ],
    },
}
```

Lifecycle: `open → triaged → assigned → in_progress → fix_proposed → fix_verified → closed`. Sidetrack: `escalated` (after N failed fix attempts; surfaces to main Orchestrator).

### Conventions (inherited from prior cutovers)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (the `dt` conda env)
- No `Co-Authored-By: Claude` trailers anywhere
- No emojis in code or rendered prompts
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 10
- Default git branch: `master`; worktree under `worktrees/<agent_id>`
- `GitOps._run(*args, check=, cwd=)` returns CompletedProcess (read `.stdout`)
- Both baselines green at every task boundary: `python agent/tests/run_regressions.py` (currently 7 OK) and `python -m unittest discover agent/tests -p 'test_*.py'` (currently 393 OK after Cutover 9)
- WorkHub task store: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — `create_task(title, description, assignee, plan_id, depends_on, agent, task_id, **metadata)` exists and accepts arbitrary metadata kwargs
- EventHub: `subscribe(agent, source_hub, event_type, filter, priority_floor, delivery)` exists; `publish_event(source_hub, event_type, payload, recipients, priority, thread_id)` exists
- APIHub: `register_endpoint(..., provider=...)` and `register_table(..., provider=...)` track the agent that owns each contract — use this for owning-agent lookup
- agents_config.yaml: 10 profiles today (orchestrator, design, database, backend, frontend, verifier, knowledge, analysis_worker, review_worker, worker); add an 11th (bug_triage_orchestrator)
- prompts/v2/: per-agent `.j2` templates; add `bug_triage_orchestrator_agent.j2`

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/bug_triage.py` — owning-agent resolution helpers (cross-hub lookups), pure functions over `HubRegistry`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2` — system + task prompts
- `agent/env_generator/llm_generator/tools/bug_tools.py` — `bug_create`, `bug_list_open`, `bug_list_assigned_to`, `bug_triage`, `bug_update_state`, `bug_close`, `bug_escalate` LLM tool classes
- `agent/tests/test_workhub_bug_helpers.py`
- `agent/tests/test_bug_triage_resolver.py`
- `agent/tests/test_bug_tools.py`
- `agent/tests/test_bug_triage_orchestrator_config.py`
- `agent/tests/test_bug_triage_orchestrator_prompt.py`
- `agent/tests/test_verifier_bug_publish_prompt.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — add `list_open_bugs`, `list_bugs_assigned_to`, `update_bug_state`, `close_bug`, `escalate_bug` methods
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py` — surface assigned-bugs prominently in pulse render; for bug_triage_orchestrator agent, surface open-bugs queue instead
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `bug_triage_orchestrator` profile + add `bug_tools` tool bundle to relevant agents
- `agent/env_generator/llm_generator/tools/tool_bundles.py` (or `multi_agent/llm_generator/multi_agent/tool_bundles.py` — re-grep to confirm path) — register `bug_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2` — verifier now MUST publish `verifier/bug_found` event and MUST NOT create remediation tasks; update prompt

---

## Task 1: Worktree setup + baseline capture

**Files:**
- Create: `docs/superpowers/cutover-10-baseline.md`

- [ ] **Step 1: Verify the worktree exists and is on the right branch**

The worktree should be created by the parent session before dispatch. Confirm:

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-10-bug-triage
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-10-bug-triage`, branched from `haibotong-0521-pipeline-web-tools` at the post-Cutover-9 SHA (the merge of `1b67095f` into parent — verify with `git log --oneline haibotong-0521-pipeline-web-tools -1`).

(If the worktree does not exist, create from repo root: `git worktree add -b haibotong-cutover-10-bug-triage .worktrees/haibotong-cutover-10-bug-triage haibotong-0521-pipeline-web-tools`)

- [ ] **Step 2: Run baseline regression suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

Expected: `7 tests, OK`.

- [ ] **Step 3: Run baseline discover suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 393 tests` + `OK`. If anything fails, STOP and report.

- [ ] **Step 4: Inventory current tool bundle path**

```bash
find agent/env_generator/llm_generator -name "tool_bundles.py" 2>/dev/null
```

Record the path you find. The plan will reference it as `<TOOL_BUNDLES_PATH>` in Task 5.

- [ ] **Step 5: Inventory current profiles**

```bash
grep -nE "^  [a-z_]+:$" agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml | head -15
```

Expected: 10 profile names under the `profiles:` key (orchestrator, design, database, backend, frontend, verifier, knowledge, analysis_worker, review_worker, worker). The 11th — `bug_triage_orchestrator` — will be added in Task 6.

- [ ] **Step 6: Write the baseline note**

Create `docs/superpowers/cutover-10-baseline.md`:

```markdown
# Cutover 10 Baseline (Bug Triage Orchestrator)

Captured before any code changes on branch `haibotong-cutover-10-bug-triage`.

## Test counts
- regressions: 7 OK
- discover: 393 OK

## Existing surfaces this cutover will extend
- WorkHub: `create_task(..., **metadata)` already accepts arbitrary metadata
- EventHub: `subscribe(agent, source_hub, event_type, ...)` and `publish_event(source_hub, event_type, payload, ...)` already exist
- APIHub: `register_endpoint(..., provider=)` and `register_table(..., provider=)` track owning agent

## Existing agent profiles (10)
orchestrator, design, database, backend, frontend, verifier, knowledge, analysis_worker, review_worker, worker

## New profile this cutover adds (1)
bug_triage_orchestrator
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/cutover-10-baseline.md
git commit -m "Cutover 10: record pre-flight baseline (regressions 7 OK, discover 393 OK)"
```

Verify no Claude trailer: `git log -1 --format=%B | grep -c Claude` → `0`.

---

## Task 2: WorkHub bug list helpers

Add two read-side helpers that filter the existing tasks store by `metadata.kind == "bug"` and by bug state / assignee.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_bug_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_workhub_bug_helpers.py`:

```python
"""Tests for WorkHub bug helpers (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class WorkHubBugListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_bug_"))
        self.reg = HubRegistry(self.tmp)
        self.wh = self.reg.workhub

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_open_bugs_empty_when_no_tasks(self) -> None:
        self.assertEqual(self.wh.list_open_bugs(), [])

    def test_list_open_bugs_excludes_non_bug_tasks(self) -> None:
        self.wh.create_task(title="Feature work", agent="orch", kind="feature")
        self.assertEqual(self.wh.list_open_bugs(), [])

    def test_list_open_bugs_includes_open_and_triaged_and_in_progress(self) -> None:
        a = self.wh.create_task(title="BUG a", agent="orch", kind="bug",
                                bug_state="open", severity="P1")
        b = self.wh.create_task(title="BUG b", agent="orch", kind="bug",
                                bug_state="triaged", severity="P2")
        c = self.wh.create_task(title="BUG c", agent="orch", kind="bug",
                                bug_state="in_progress", severity="P0")
        self.wh.create_task(title="BUG d closed", agent="orch", kind="bug",
                            bug_state="closed", severity="P3")
        open_ids = {t["id"] for t in self.wh.list_open_bugs()}
        self.assertEqual(open_ids, {a["id"], b["id"], c["id"]})

    def test_list_open_bugs_sorted_by_severity_then_created_at(self) -> None:
        # Create in mixed order; expect P0 first, then P1, then P2.
        p2 = self.wh.create_task(title="BUG P2", agent="orch", kind="bug",
                                 bug_state="open", severity="P2")
        p0 = self.wh.create_task(title="BUG P0", agent="orch", kind="bug",
                                 bug_state="open", severity="P0")
        p1 = self.wh.create_task(title="BUG P1", agent="orch", kind="bug",
                                 bug_state="open", severity="P1")
        ids = [t["id"] for t in self.wh.list_open_bugs()]
        self.assertEqual(ids, [p0["id"], p1["id"], p2["id"]])

    def test_list_bugs_assigned_to_filters_by_assignee_and_open_states(self) -> None:
        self.wh.create_task(title="BUG x", assignee="backend", agent="orch",
                            kind="bug", bug_state="assigned", severity="P1")
        self.wh.create_task(title="BUG y", assignee="frontend", agent="orch",
                            kind="bug", bug_state="assigned", severity="P1")
        self.wh.create_task(title="BUG z closed", assignee="backend", agent="orch",
                            kind="bug", bug_state="closed", severity="P3")
        backend_bugs = self.wh.list_bugs_assigned_to("backend")
        backend_ids = {t["id"] for t in backend_bugs}
        self.assertEqual(len(backend_ids), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_bug_helpers -v 2>&1 | tail -10
```

Expected: AttributeError on `list_open_bugs` / `list_bugs_assigned_to`.

- [ ] **Step 3: Implement the helpers**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, add these methods to the `WorkHub` class (near the existing `create_task` / `claim_task` cluster):

```python
    _OPEN_BUG_STATES = ("open", "triaged", "assigned", "in_progress", "fix_proposed")
    _SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

    def _iter_bug_tasks(self):
        for task in (self.stores.tasks.value() or {}).values():
            meta = task.get("metadata") or {}
            if meta.get("kind") == "bug":
                yield task

    def list_open_bugs(self) -> list:
        """Return bugs whose lifecycle state is not closed/escalated, sorted P0-first then oldest-first."""
        bugs = [
            t for t in self._iter_bug_tasks()
            if (t.get("metadata") or {}).get("bug_state", "open") in self._OPEN_BUG_STATES
        ]
        bugs.sort(key=lambda t: (
            self._SEVERITY_RANK.get((t.get("metadata") or {}).get("severity", "P3"), 99),
            t.get("created_at", 0.0),
        ))
        return bugs

    def list_bugs_assigned_to(self, agent: str) -> list:
        return [t for t in self.list_open_bugs() if t.get("assignee") == agent]
```

- [ ] **Step 4: Verify the 5 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_bug_helpers -v 2>&1 | tail -10
```

Expected: `Ran 5 tests` + `OK`.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 398 OK (was 393 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_bug_helpers.py
git commit -m "WorkHub: add list_open_bugs / list_bugs_assigned_to (filter by metadata.kind=bug)"
```

---

## Task 3: WorkHub bug lifecycle helpers

`update_bug_state`, `close_bug`, `escalate_bug` — all append to `metadata.triage_history` for audit.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Modify: `agent/tests/test_workhub_bug_helpers.py`

- [ ] **Step 1: Append failing tests**

Append to `agent/tests/test_workhub_bug_helpers.py` (after the existing `WorkHubBugListTests` class):

```python
class WorkHubBugLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_buglife_"))
        self.reg = HubRegistry(self.tmp)
        self.wh = self.reg.workhub
        self.bug = self.wh.create_task(
            title="BUG: feed 500", agent="verifier",
            kind="bug", bug_state="open", severity="P1",
            source="verifier",
            bug_artifacts={"failing_test": "test_x", "affected_endpoint": "POST /api/feed"},
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_bug_state_transitions_state(self) -> None:
        updated = self.wh.update_bug_state(self.bug["id"], "triaged",
                                           agent="bug_triage_orchestrator",
                                           note="owner=backend")
        self.assertEqual(updated["metadata"]["bug_state"], "triaged")

    def test_update_bug_state_appends_triage_history(self) -> None:
        self.wh.update_bug_state(self.bug["id"], "triaged",
                                 agent="bug_triage_orchestrator", note="step1")
        self.wh.update_bug_state(self.bug["id"], "assigned",
                                 agent="bug_triage_orchestrator", note="step2",
                                 assignee="backend")
        final = self.wh.stores.tasks.get(self.bug["id"])
        history = final["metadata"]["triage_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["action"], "triaged")
        self.assertEqual(history[1]["action"], "assigned")
        self.assertEqual(history[1]["by"], "bug_triage_orchestrator")
        self.assertEqual(final["assignee"], "backend")

    def test_close_bug_sets_state_and_fix_evidence(self) -> None:
        evidence = {"fix_pr": "PR-42", "verified_by_test": "test_x"}
        closed = self.wh.close_bug(self.bug["id"], agent="backend",
                                    fix_evidence=evidence)
        self.assertEqual(closed["metadata"]["bug_state"], "closed")
        self.assertEqual(closed["metadata"]["fix_evidence"], evidence)
        self.assertEqual(closed["status"], "completed")

    def test_escalate_bug_sets_state_and_records_reason(self) -> None:
        esc = self.wh.escalate_bug(self.bug["id"], agent="bug_triage_orchestrator",
                                    reason="3 failed fix attempts")
        self.assertEqual(esc["metadata"]["bug_state"], "escalated")
        self.assertEqual(esc["metadata"]["escalation_reason"], "3 failed fix attempts")

    def test_update_bug_state_rejects_unknown_state(self) -> None:
        with self.assertRaises(ValueError):
            self.wh.update_bug_state(self.bug["id"], "magic", agent="x")

    def test_update_bug_state_rejects_non_bug_task(self) -> None:
        feat = self.wh.create_task(title="feat", agent="orch", kind="feature")
        with self.assertRaises(ValueError):
            self.wh.update_bug_state(feat["id"], "triaged", agent="x")
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_bug_helpers.WorkHubBugLifecycleTests -v 2>&1 | tail -10
```

Expected: AttributeError on `update_bug_state` / `close_bug` / `escalate_bug`.

- [ ] **Step 3: Implement the lifecycle helpers**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, add (right after `list_bugs_assigned_to`):

```python
    _VALID_BUG_STATES = {
        "open", "triaged", "assigned", "in_progress",
        "fix_proposed", "fix_verified", "closed", "escalated",
    }

    def _load_bug_or_raise(self, task_id: str) -> dict:
        task = self.stores.tasks.get(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        meta = task.get("metadata") or {}
        if meta.get("kind") != "bug":
            raise ValueError(f"task {task_id} is not a bug (kind={meta.get('kind')!r})")
        return task

    def update_bug_state(self, task_id: str, new_state: str, agent: str,
                         note: str = "", assignee: str = None,
                         **metadata_updates) -> dict:
        if new_state not in self._VALID_BUG_STATES:
            raise ValueError(f"invalid bug state: {new_state!r}")
        task = self._load_bug_or_raise(task_id)
        updated = dict(task)
        meta = dict(updated.get("metadata") or {})
        meta["bug_state"] = new_state
        meta.setdefault("triage_history", []).append({
            "at": time.time(),
            "by": agent,
            "action": new_state,
            "note": note,
        })
        for k, v in metadata_updates.items():
            meta[k] = v
        updated["metadata"] = meta
        if assignee is not None:
            updated["assignee"] = assignee
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        self.stores.tasks.update(lambda m: m.set(task_id, updated, agent),
                                  change_info={"agent": agent})
        self._emit("bug_state_changed", updated,
                    recipients=[updated["assignee"]] if updated.get("assignee") else [],
                    priority="high")
        return updated

    def close_bug(self, task_id: str, agent: str, fix_evidence: dict = None) -> dict:
        updated = self.update_bug_state(task_id, "closed", agent=agent,
                                         note="fix verified",
                                         fix_evidence=fix_evidence or {})
        # Also flip the underlying task status to completed so downstream queries see it.
        completed = dict(updated)
        completed["status"] = "completed"
        completed["_updated_by"] = agent
        completed["_updated_at"] = time.time()
        self.stores.tasks.update(lambda m: m.set(task_id, completed, agent),
                                  change_info={"agent": agent})
        return completed

    def escalate_bug(self, task_id: str, agent: str, reason: str) -> dict:
        return self.update_bug_state(task_id, "escalated", agent=agent,
                                      note=reason, escalation_reason=reason)
```

If `time` is not already imported at the top of the file, it is (the file uses `time.time()` heavily already — verify with `grep -n "^import time" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`).

- [ ] **Step 4: Verify the 6 new tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_bug_helpers -v 2>&1 | tail -15
```

Expected: 11 tests OK (5 from Task 2 + 6 new).

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 404 OK (was 398 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_bug_helpers.py
git commit -m "WorkHub: add update_bug_state / close_bug / escalate_bug with triage_history audit"
```

---

## Task 4: Owning-agent resolution helpers

A small pure module that, given a bug payload (endpoint or file path or table name), returns the owning agent by reading APIHub/CodeHub.

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/bug_triage.py`
- Create: `agent/tests/test_bug_triage_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_bug_triage_resolver.py`:

```python
"""Tests for bug_triage owning-agent resolution helpers (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.bug_triage import (  # noqa: E402
    find_owning_agent_for_endpoint,
    find_owning_agent_for_table,
    find_owning_agent_for_file,
    resolve_owning_agent,
)


class OwningAgentResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="bt_resolver_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_endpoint_resolves_to_registered_provider(self) -> None:
        self.reg.apihub.register_endpoint("POST", "/api/feed",
                                          schema={}, provider="backend", agent="backend")
        self.assertEqual(
            find_owning_agent_for_endpoint(self.reg, "POST", "/api/feed"),
            "backend",
        )

    def test_endpoint_unknown_returns_none(self) -> None:
        self.assertIsNone(find_owning_agent_for_endpoint(self.reg, "POST", "/missing"))

    def test_table_resolves_to_registered_provider(self) -> None:
        self.reg.apihub.register_table("users", schema={"columns": []},
                                       provider="database", agent="database")
        self.assertEqual(find_owning_agent_for_table(self.reg, "users"), "database")

    def test_file_path_under_backend_dir_resolves_to_backend(self) -> None:
        self.assertEqual(find_owning_agent_for_file("backend/routes/feed.py"), "backend")

    def test_file_path_under_frontend_dir_resolves_to_frontend(self) -> None:
        self.assertEqual(find_owning_agent_for_file("frontend/components/Feed.tsx"), "frontend")

    def test_file_path_under_database_or_migrations_resolves_to_database(self) -> None:
        self.assertEqual(find_owning_agent_for_file("database/migrations/001.sql"), "database")
        self.assertEqual(find_owning_agent_for_file("migrations/002_add_users.sql"), "database")

    def test_file_path_unknown_returns_none(self) -> None:
        self.assertIsNone(find_owning_agent_for_file("README.md"))

    def test_resolve_owning_agent_prefers_endpoint_over_file(self) -> None:
        self.reg.apihub.register_endpoint("GET", "/api/x", schema={},
                                          provider="backend", agent="backend")
        artifacts = {
            "affected_endpoint": "GET /api/x",
            "affected_files": ["frontend/foo.tsx"],
        }
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "backend")

    def test_resolve_owning_agent_falls_back_to_file_when_endpoint_unknown(self) -> None:
        artifacts = {"affected_files": ["frontend/components/X.tsx"]}
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "frontend")

    def test_resolve_owning_agent_table_path(self) -> None:
        self.reg.apihub.register_table("orders", schema={"columns": []},
                                       provider="database", agent="database")
        artifacts = {"affected_table": "orders"}
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "database")

    def test_resolve_owning_agent_returns_none_when_nothing_matches(self) -> None:
        artifacts = {"affected_files": ["README.md"]}
        self.assertIsNone(resolve_owning_agent(self.reg, artifacts))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_resolver -v 2>&1 | tail -10
```

Expected: ImportError on `multi_agent.runtime.bug_triage`.

- [ ] **Step 3: Implement the resolver**

Create `agent/env_generator/llm_generator/multi_agent/runtime/bug_triage.py`:

```python
"""Owning-agent resolution helpers for the Bug Triage Orchestrator (Cutover 10).

Pure functions over HubRegistry — given a bug's evidence (endpoint, table, file
paths), return the agent that owns the affected contract. The Bug Triage
Orchestrator agent uses these to decide who gets the remediation task.

Resolution priority (when multiple artifacts are present):
  1. affected_endpoint → APIHub provider
  2. affected_table    → APIHub provider
  3. affected_files[0] → file-path heuristic (backend/frontend/database)
"""

from __future__ import annotations

from typing import Optional

# Path-prefix heuristic for files not covered by APIHub registrations.
_FILE_PREFIX_OWNERS = (
    ("backend/", "backend"),
    ("frontend/", "frontend"),
    ("database/", "database"),
    ("migrations/", "database"),
    ("db/", "database"),
)


def find_owning_agent_for_endpoint(registry, method: str, path: str) -> Optional[str]:
    method = (method or "").upper()
    for ep in (registry.apihub.list_endpoints() or {}).values():
        if (ep.get("method") or "").upper() == method and ep.get("path") == path:
            owner = ep.get("provider") or None
            return owner or None
    return None


def find_owning_agent_for_table(registry, table_name: str) -> Optional[str]:
    table = registry.apihub.get_table(table_name) if hasattr(registry.apihub, "get_table") else None
    if table:
        return table.get("provider") or None
    tables = registry.apihub.list_tables() if hasattr(registry.apihub, "list_tables") else {}
    table = (tables or {}).get(table_name)
    if table:
        return table.get("provider") or None
    return None


def find_owning_agent_for_file(file_path: str) -> Optional[str]:
    fp = (file_path or "").lstrip("/")
    for prefix, owner in _FILE_PREFIX_OWNERS:
        if fp.startswith(prefix):
            return owner
    return None


def resolve_owning_agent(registry, artifacts: dict) -> Optional[str]:
    """Given a bug's `bug_artifacts` payload, return the owning agent, or None."""
    artifacts = artifacts or {}

    endpoint = artifacts.get("affected_endpoint")
    if endpoint and " " in endpoint:
        method, _, path = endpoint.partition(" ")
        owner = find_owning_agent_for_endpoint(registry, method, path)
        if owner:
            return owner

    table = artifacts.get("affected_table")
    if table:
        owner = find_owning_agent_for_table(registry, table)
        if owner:
            return owner

    for path in (artifacts.get("affected_files") or []):
        owner = find_owning_agent_for_file(path)
        if owner:
            return owner

    return None


__all__ = [
    "find_owning_agent_for_endpoint",
    "find_owning_agent_for_table",
    "find_owning_agent_for_file",
    "resolve_owning_agent",
]
```

If APIHub's `list_endpoints` or `list_tables` method has a different name, re-grep before failing — adjust the calls accordingly:

```bash
grep -nE "def (list_endpoints|list_tables|get_table)" agent/env_generator/llm_generator/multi_agent/runtime/apihub.py | head -10
```

If `list_endpoints` doesn't exist but `endpoints()` does (or another similar name), use that. The tests will tell you.

- [ ] **Step 4: Verify the 11 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_resolver -v 2>&1 | tail -15
```

Expected: 11 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 415 OK (was 404 + 11 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/bug_triage.py agent/tests/test_bug_triage_resolver.py
git commit -m "Add bug_triage owning-agent resolver (endpoint/table/file path heuristics)"
```

---

## Task 5: Bug LLM tools

Wire the WorkHub bug helpers + resolver into LLM-callable tools. Bug Triage Orchestrator is the primary consumer; Verifier gets `bug_create` only (Verifier must publish a `verifier/bug_found` event when finding a bug); fix-side agents (backend/frontend/database) get `bug_list_assigned_to(self)`, `bug_update_state`, `bug_close`.

**Files:**
- Create: `agent/env_generator/llm_generator/tools/bug_tools.py`
- Modify: `<TOOL_BUNDLES_PATH>` (the file located in Task 1 Step 4)
- Create: `agent/tests/test_bug_tools.py`

- [ ] **Step 1: Inspect tool authoring conventions**

```bash
head -80 agent/env_generator/llm_generator/tools/hub_tools.py 2>/dev/null || find agent/env_generator/llm_generator/tools -name "*.py" | head -10
```

Pick one existing hub tool (e.g., `apihub_register_endpoint`) and read its class definition to match the convention: tool name, parameter schema, `_execute(self, ctx, **kwargs)` method.

- [ ] **Step 2: Write failing tests**

Create `agent/tests/test_bug_tools.py`:

```python
"""Tests for bug-triage LLM tools (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.bug_tools import (  # noqa: E402
    BugCreateTool, BugListOpenTool, BugListAssignedToTool,
    BugTriageTool, BugUpdateStateTool, BugCloseTool, BugEscalateTool,
)


def _make_ctx(reg):
    ctx = MagicMock()
    ctx.hub_registry = reg
    ctx.agent_id = "bug_triage_orchestrator"
    return ctx


class BugToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="bug_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.ctx = _make_ctx(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bug_create_creates_bug_task_with_metadata(self) -> None:
        tool = BugCreateTool()
        out = tool._execute(self.ctx,
                            title="500 on POST /api/feed",
                            description="reproducible from test_x",
                            source="verifier",
                            severity="P1",
                            bug_artifacts={"affected_endpoint": "POST /api/feed"})
        self.assertIn("id", out)
        task = self.reg.workhub.stores.tasks.get(out["id"])
        self.assertEqual(task["metadata"]["kind"], "bug")
        self.assertEqual(task["metadata"]["severity"], "P1")
        self.assertEqual(task["metadata"]["bug_state"], "open")
        self.assertEqual(task["metadata"]["source"], "verifier")

    def test_bug_list_open_lists_only_open(self) -> None:
        BugCreateTool()._execute(self.ctx, title="a", source="verifier",
                                  severity="P1", bug_artifacts={})
        b = BugCreateTool()._execute(self.ctx, title="b", source="verifier",
                                      severity="P0", bug_artifacts={})
        out = BugListOpenTool()._execute(self.ctx)
        self.assertEqual(len(out["bugs"]), 2)
        self.assertEqual(out["bugs"][0]["id"], b["id"])  # P0 first

    def test_bug_triage_assigns_and_records_root_cause(self) -> None:
        self.reg.apihub.register_endpoint("POST", "/api/feed", schema={},
                                          provider="backend", agent="backend")
        created = BugCreateTool()._execute(self.ctx, title="500 feed",
                                            source="verifier", severity="P1",
                                            bug_artifacts={"affected_endpoint": "POST /api/feed"})
        triaged = BugTriageTool()._execute(self.ctx, task_id=created["id"],
                                            root_cause="missing null check")
        self.assertEqual(triaged["assignee"], "backend")
        self.assertEqual(triaged["metadata"]["bug_state"], "assigned")
        self.assertEqual(triaged["metadata"]["root_cause_hypothesis"], "missing null check")

    def test_bug_triage_with_explicit_assignee_overrides_resolver(self) -> None:
        created = BugCreateTool()._execute(self.ctx, title="x", source="manual",
                                            severity="P2", bug_artifacts={})
        triaged = BugTriageTool()._execute(self.ctx, task_id=created["id"],
                                            root_cause="x", assignee="frontend")
        self.assertEqual(triaged["assignee"], "frontend")

    def test_bug_list_assigned_to_returns_assigned_bugs(self) -> None:
        self.reg.apihub.register_endpoint("GET", "/api/y", schema={},
                                          provider="backend", agent="backend")
        created = BugCreateTool()._execute(self.ctx, title="500", source="verifier",
                                            severity="P1",
                                            bug_artifacts={"affected_endpoint": "GET /api/y"})
        BugTriageTool()._execute(self.ctx, task_id=created["id"], root_cause="x")
        backend_ctx = _make_ctx(self.reg)
        backend_ctx.agent_id = "backend"
        out = BugListAssignedToTool()._execute(backend_ctx)
        self.assertEqual(len(out["bugs"]), 1)

    def test_bug_update_state_transitions(self) -> None:
        created = BugCreateTool()._execute(self.ctx, title="x", source="verifier",
                                            severity="P1", bug_artifacts={})
        BugTriageTool()._execute(self.ctx, task_id=created["id"],
                                  root_cause="x", assignee="backend")
        backend_ctx = _make_ctx(self.reg)
        backend_ctx.agent_id = "backend"
        out = BugUpdateStateTool()._execute(backend_ctx, task_id=created["id"],
                                             new_state="in_progress", note="starting")
        self.assertEqual(out["metadata"]["bug_state"], "in_progress")

    def test_bug_close_sets_state_and_evidence(self) -> None:
        created = BugCreateTool()._execute(self.ctx, title="x", source="verifier",
                                            severity="P1", bug_artifacts={})
        BugTriageTool()._execute(self.ctx, task_id=created["id"],
                                  root_cause="x", assignee="backend")
        backend_ctx = _make_ctx(self.reg)
        backend_ctx.agent_id = "backend"
        out = BugCloseTool()._execute(backend_ctx, task_id=created["id"],
                                       fix_evidence={"pr": "PR-1"})
        self.assertEqual(out["metadata"]["bug_state"], "closed")
        self.assertEqual(out["metadata"]["fix_evidence"], {"pr": "PR-1"})

    def test_bug_escalate_marks_state_escalated(self) -> None:
        created = BugCreateTool()._execute(self.ctx, title="x", source="verifier",
                                            severity="P1", bug_artifacts={})
        out = BugEscalateTool()._execute(self.ctx, task_id=created["id"],
                                          reason="3 failed fix attempts")
        self.assertEqual(out["metadata"]["bug_state"], "escalated")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_tools -v 2>&1 | tail -10
```

Expected: ImportError on `tools.bug_tools`.

- [ ] **Step 4: Implement the tools**

Create `agent/env_generator/llm_generator/tools/bug_tools.py`. The exact base-class convention should mirror what you found in Step 1 (look at e.g. `hub_tools.py` for an existing example). The structure below assumes a simple convention with a `_execute(self, ctx, **kwargs)` method; adapt to the real convention you observed:

```python
"""Bug-triage LLM tools (Cutover 10).

Tools:
  - bug_create:            Verifier / RunHub / orchestrator create a new bug task
  - bug_list_open:         Bug Triage Orchestrator lists open bugs (P0-first)
  - bug_list_assigned_to:  any agent lists bugs assigned to itself
  - bug_triage:            Bug Triage Orchestrator analyzes + assigns
  - bug_update_state:      assignee transitions bug through lifecycle
  - bug_close:             assignee closes bug with fix evidence
  - bug_escalate:          Bug Triage Orchestrator escalates after failed fixes
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Tool base class — match the existing convention in tools/hub_tools.py.
# If hub_tools.py uses `class FooTool(Tool):` with `_execute(self, ctx, **kwargs)`,
# inherit from the same base. If the base is named differently, adjust.
try:
    from .hub_tools import HubTool as _BugToolBase  # type: ignore
except ImportError:  # pragma: no cover - fallback for early development
    class _BugToolBase:  # minimal duck-typed base
        name: str = ""
        description: str = ""
        def __init__(self): pass


def _wh(ctx):
    return ctx.hub_registry.workhub


def _reg(ctx):
    return ctx.hub_registry


class BugCreateTool(_BugToolBase):
    name = "bug_create"
    description = "Create a new bug task on WorkHub with structured artifacts. Use this from Verifier / RunHub when a regression or runtime failure is observed."

    def _execute(self, ctx, *, title: str, source: str, severity: str,
                 bug_artifacts: Dict[str, Any], description: str = "",
                 parent_bug_id: Optional[str] = None) -> dict:
        if severity not in ("P0", "P1", "P2", "P3"):
            raise ValueError(f"invalid severity: {severity!r}")
        task = _wh(ctx).create_task(
            title=title, description=description,
            agent=ctx.agent_id,
            kind="bug",
            severity=severity,
            bug_state="open",
            source=source,
            parent_bug_id=parent_bug_id,
            bug_artifacts=bug_artifacts or {},
            triage_history=[],
        )
        # Publish a verifier/bug_found event so the BugTriageOrchestrator pulse picks it up.
        _reg(ctx).eventhub.publish_event(
            source_hub=source,
            event_type="bug_found",
            payload={"task_id": task["id"], "severity": severity, "title": title},
            priority="high" if severity in ("P0", "P1") else "normal",
        )
        return task


class BugListOpenTool(_BugToolBase):
    name = "bug_list_open"
    description = "List all open bugs (P0-first). Used by Bug Triage Orchestrator at the start of each step."

    def _execute(self, ctx) -> dict:
        return {"bugs": _wh(ctx).list_open_bugs()}


class BugListAssignedToTool(_BugToolBase):
    name = "bug_list_assigned_to"
    description = "List bugs assigned to the calling agent (uses ctx.agent_id)."

    def _execute(self, ctx, *, agent: Optional[str] = None) -> dict:
        target = agent or ctx.agent_id
        return {"agent": target, "bugs": _wh(ctx).list_bugs_assigned_to(target)}


class BugTriageTool(_BugToolBase):
    name = "bug_triage"
    description = "Bug Triage Orchestrator action: record root cause, identify owning agent, transition state to 'assigned'."

    def _execute(self, ctx, *, task_id: str, root_cause: str,
                 assignee: Optional[str] = None) -> dict:
        from multi_agent.runtime.bug_triage import resolve_owning_agent
        wh = _wh(ctx)
        task = wh.stores.tasks.get(task_id) or {}
        artifacts = (task.get("metadata") or {}).get("bug_artifacts") or {}
        owner = assignee or resolve_owning_agent(_reg(ctx), artifacts)
        if not owner:
            raise ValueError(
                "could not resolve owning agent and no assignee supplied")
        wh.update_bug_state(task_id, "triaged",
                            agent=ctx.agent_id, note="root cause recorded",
                            root_cause_hypothesis=root_cause)
        return wh.update_bug_state(task_id, "assigned",
                                    agent=ctx.agent_id, note=f"assigned to {owner}",
                                    assignee=owner)


class BugUpdateStateTool(_BugToolBase):
    name = "bug_update_state"
    description = "Transition a bug's lifecycle state (in_progress / fix_proposed / fix_verified)."

    def _execute(self, ctx, *, task_id: str, new_state: str,
                 note: str = "") -> dict:
        return _wh(ctx).update_bug_state(task_id, new_state,
                                          agent=ctx.agent_id, note=note)


class BugCloseTool(_BugToolBase):
    name = "bug_close"
    description = "Close a bug after fix verified. Must supply fix_evidence (e.g., {pr: 'PR-42', verified_by_test: 'test_x'})."

    def _execute(self, ctx, *, task_id: str, fix_evidence: Dict[str, Any]) -> dict:
        return _wh(ctx).close_bug(task_id, agent=ctx.agent_id,
                                   fix_evidence=fix_evidence)


class BugEscalateTool(_BugToolBase):
    name = "bug_escalate"
    description = "Escalate a bug to the main Orchestrator after N failed fix attempts. Reason required."

    def _execute(self, ctx, *, task_id: str, reason: str) -> dict:
        return _wh(ctx).escalate_bug(task_id, agent=ctx.agent_id, reason=reason)


__all__ = [
    "BugCreateTool", "BugListOpenTool", "BugListAssignedToTool",
    "BugTriageTool", "BugUpdateStateTool", "BugCloseTool", "BugEscalateTool",
]
```

- [ ] **Step 5: Register the `bug_tools` bundle**

In the tool bundle registry file (found in Task 1 Step 4 — likely `agent/env_generator/llm_generator/multi_agent/multi_agent/tool_bundles.py` or similar; re-grep), add an entry:

```python
"bug_tools": [
    BugCreateTool, BugListOpenTool, BugListAssignedToTool,
    BugTriageTool, BugUpdateStateTool, BugCloseTool, BugEscalateTool,
],
```

…with corresponding `from agent.env_generator.llm_generator.tools.bug_tools import ...` at the top of the file. Match the import style other bundles in the file use (the bundle file's existing imports tell you whether to use relative or absolute paths).

- [ ] **Step 6: Verify the 8 tool tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_tools -v 2>&1 | tail -15
```

Expected: 8 tests OK. If the tool base-class import fails, switch to the fallback in `bug_tools.py` (the `class _BugToolBase` minimal duck-type) and proceed — the tests don't care about real registration, only that `_execute` works.

- [ ] **Step 7: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 423 OK (was 415 + 8 new).

- [ ] **Step 8: Commit**

```bash
git add agent/env_generator/llm_generator/tools/bug_tools.py agent/tests/test_bug_tools.py <TOOL_BUNDLES_PATH>
git commit -m "Add bug_tools LLM tool surface (create/list/triage/update/close/escalate)"
```

---

## Task 6: New `bug_triage_orchestrator` agent profile

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_bug_triage_orchestrator_config.py`

- [ ] **Step 1: Write failing config test**

Create `agent/tests/test_bug_triage_orchestrator_config.py`:

```python
"""Tests that agents_config.yaml has the bug_triage_orchestrator profile wired correctly."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG_PATH = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "agents" / "agents_config.yaml"
)


class BugTriageOrchestratorProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.cfg = yaml.safe_load(f)

    def test_profile_exists(self) -> None:
        self.assertIn("bug_triage_orchestrator", self.cfg.get("profiles", {}))

    def test_profile_has_bug_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        self.assertIn("bug_tools", prof.get("tool_bundles", []))

    def test_profile_has_workhub_apihub_codehub_eventhub_tools(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        bundles = set(prof.get("tool_bundles", []))
        for required in ("workhub_tools", "apihub_tools",
                          "codehub_tools", "eventhub_tools"):
            self.assertIn(required, bundles)

    def test_profile_pipeline_starts_with_hub_pulse_ends_with_commit_gate(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        stages = prof.get("execution_pipeline", {}).get("stages", [])
        self.assertGreater(len(stages), 0)
        self.assertEqual(stages[0], "hub_pulse")
        self.assertIn("hub_commit_gate", stages)

    def test_profile_uses_dedicated_prompt(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        template = (prof.get("prompts") or {}).get("template", "")
        self.assertTrue(template.endswith("bug_triage_orchestrator_agent.j2"))

    def test_profile_is_coordinator_but_cannot_deliver(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        flags = prof.get("flags", {}) or {}
        self.assertTrue(flags.get("coordinator"))
        self.assertFalse(flags.get("can_deliver", False))

    def test_max_tool_calls_per_stage_caps_action(self) -> None:
        prof = self.cfg["profiles"]["bug_triage_orchestrator"]
        caps = prof.get("execution_pipeline", {}).get("max_tool_calls_per_stage", {})
        # bug triage should be allowed multiple tool calls per step (read + triage + dispatch)
        self.assertGreaterEqual(caps.get("action", 0), 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_orchestrator_config -v 2>&1 | tail -10
```

Expected: AssertionErrors on every test.

- [ ] **Step 3: Add the profile to `agents_config.yaml`**

In `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`, under the `profiles:` block, add (alphabetical or before `worker:` — match the existing ordering convention):

```yaml
  bug_triage_orchestrator:
    name: "Bug Triage Orchestrator"
    description: "Receives bug events from Verifier/RunHub, runs root-cause analysis, assigns remediation tasks to owning agents. Never modifies code directly."
    tool_categories: ["reasoning", "communication", "memory", "knowledge_read", "knowledge_write", "analysis", "workhub", "apihub", "codehub", "eventhub", "hub"]
    include_vision: false
    timeout: 3600
    prompts:
      template: "v2/bug_triage_orchestrator_agent.j2"
      system_macro: "bug_triage_system_prompt"
      task_macros:
        full: "bug_triage_task_prompt"
      context_vars: []
    flags:
      coordinator: true
      can_deliver: false
      team_lead: false
    tool_bundles:
      - memory_tools
      - analysis_tools
      - knowledge_read_tools
      - knowledge_write_tools
      - workhub_tools
      - apihub_tools
      - codehub_tools
      - eventhub_tools
      - bug_tools
    deny_tools: []
    execution_pipeline:
      stages: [hub_pulse, retrieve_context, planning, action, hub_commit_gate, knowledge_sync]
      max_tool_calls_per_stage:
        planning: 1
        retrieve_context: 3
        action: 6
        hub_commit_gate: 0
        knowledge_sync: 2
```

You will also need to extend the `tool_categories` mapping at the top of the file if there's an `tool_categories:` registry section (re-grep — `grep -n "^tool_categories:" agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`). The new categories list doesn't introduce any unfamiliar names, so unlikely to need changes; but verify.

You may also need to register the profile in the per-profile lists further down the file (e.g., `step_reminders:`, `optional_stages:`, the trailing per-profile blocks at lines 511+/544+ in the pre-Cutover-10 file — grep before assuming). For each per-profile mapping, add an entry mirroring `orchestrator`'s shape (since bug_triage_orchestrator is also a coordinator). If you find no per-profile mapping requires an entry, that's fine.

- [ ] **Step 4: Verify the 7 config tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_orchestrator_config -v 2>&1 | tail -15
```

Expected: 7 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 430 OK (was 423 + 7 new).

If the existing `test_agents_config_stages.py` test fails because it asserts the profile count or per-profile presence, update it to include `bug_triage_orchestrator`. Inspect the failure and adjust.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_bug_triage_orchestrator_config.py
# also include any test fixture update required to keep test_agents_config_stages.py green
git commit -m "Add bug_triage_orchestrator agent profile to agents_config.yaml"
```

---

## Task 7: Bug Triage Orchestrator prompt

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2`
- Create: `agent/tests/test_bug_triage_orchestrator_prompt.py`

- [ ] **Step 1: Write failing prompt test**

Create `agent/tests/test_bug_triage_orchestrator_prompt.py`:

```python
"""Tests that the bug_triage_orchestrator prompt renders and contains required discipline rules."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_DIR = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "prompts" / "v2"
)
TEMPLATE = "bug_triage_orchestrator_agent.j2"


class BugTriageOrchestratorPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
        tpl = env.get_template(TEMPLATE)
        mod = tpl.make_module()
        cls.system = mod.bug_triage_system_prompt()
        cls.task = mod.bug_triage_task_prompt()

    def test_system_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.system.strip()), 200)

    def test_system_prompt_mentions_role_split(self) -> None:
        self.assertIn("VERIFIER", self.system.upper())
        self.assertIn("OWNING AGENT", self.system.upper())
        self.assertIn("FIX", self.system.upper())

    def test_system_prompt_forbids_code_edits(self) -> None:
        self.assertIn("NEVER", self.system.upper())
        self.assertTrue(
            "CODE" in self.system.upper() or "EDIT" in self.system.upper(),
            "prompt must explicitly forbid direct code edits",
        )

    def test_system_prompt_requires_root_cause_before_assignment(self) -> None:
        self.assertIn("ROOT CAUSE", self.system.upper())

    def test_system_prompt_describes_escalation_rule(self) -> None:
        self.assertIn("ESCALAT", self.system.upper())

    def test_system_prompt_lists_step_pipeline_stages(self) -> None:
        for stage in ("HUB PULSE", "INTEGRITY CHECK"):
            self.assertIn(stage, self.system.upper())

    def test_task_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.task.strip()), 100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_orchestrator_prompt -v 2>&1 | tail -10
```

Expected: TemplateNotFound.

- [ ] **Step 3: Author the prompt**

Create `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2`:

```jinja
{# Bug Triage Orchestrator — Cutover 10 #}
{# This agent receives bug events, analyzes root cause, assigns to owning agent.
   It NEVER edits code. Verifier finds bugs; this agent triages; owning agent fixes. #}

{% macro bug_triage_system_prompt() -%}
You are the **Bug Triage Orchestrator** — the on-call SRE of this multi-agent system.

## ROLE SPLIT (read carefully)
- **VERIFIER** detects bugs by running contract tests and publishes a `verifier/bug_found` event with structured artifacts. Verifier does NOT analyze or assign.
- **YOU (Bug Triage Orchestrator)** receive bug events, run root-cause analysis using APIHub / CodeHub / WorkHub context, identify the **OWNING AGENT** for the affected contract, and create a remediation task. You do NOT fix bugs.
- **OWNING AGENT** (backend / database / frontend / etc.) picks up the assigned bug task in its next `hub_pulse`, proposes a fix, runs verification, and CLOSES the bug via `bug_close()` with fix evidence.

## HARD RULES
1. **NEVER edit code.** You have no file-write tools; do not attempt to edit, create, or delete source files. Your only outputs are: WorkHub task creation/assignment via `bug_*` tools, EventHub notifications, and Knowledge writes for postmortems.
2. **NEVER close bugs without verified fix evidence.** Closing is the assignee's job — you only escalate when an assignee fails repeatedly.
3. **Always record a `root_cause_hypothesis` before assigning.** No assignment without a stated hypothesis — even if low confidence ("likely null check missing in feed handler").
4. **Resolve the owning agent using available evidence**, in this priority order:
   - `affected_endpoint` → APIHub `provider` field on the registered endpoint
   - `affected_table` → APIHub `provider` field on the registered table
   - `affected_files[0]` → file-path heuristic (backend/* → backend, frontend/* → frontend, database/*|migrations/* → database)
   - If none resolves, ASK the main Orchestrator via EventHub for triage help — do NOT guess.
5. **ESCALATE after 3 failed fix attempts** on the same bug. Use `bug_escalate(task_id, reason)` with the failure history. Escalation surfaces the bug to the main Orchestrator for re-assignment or design rework.
6. **Recurrence**: if the bug payload matches an already-closed bug (same `affected_endpoint` or `affected_files`), set `parent_bug_id` to the closed one — recurrence signals deeper design issues.

## STEP PIPELINE
Every step you take begins with **HUB PULSE** (engine-forced snapshot of all 4 hubs) and ends with an **INTEGRITY CHECK** (hub_commit_gate verifies you actually advanced bugs through the lifecycle). Don't try to skip these — the engine adds them whether your stage list mentions them or not. If integrity check finds loose ends (e.g., you opened a `triage_history` audit entry without changing state), the prompt rolls forward to your next step.

## YOUR TOOLS
- `bug_list_open()` — review the open bug queue (P0-first)
- `bug_triage(task_id, root_cause, assignee=None)` — analyze + assign in one call; resolves owning agent automatically if `assignee` omitted
- `bug_update_state(task_id, new_state, note)` — typically only used to mark `escalated` here (assignees handle in_progress/fix_proposed/fix_verified)
- `bug_escalate(task_id, reason)` — last resort
- Read APIHub via `apihub_*` tools to verify endpoint/table ownership
- Read CodeHub via `codehub_*` tools to see recent commits / open PRs on affected files
- Publish notification via `eventhub_publish_event(source_hub="bug_triage_orchestrator", event_type="bug_triaged", payload={task_id, assignee})` after each successful triage so the assignee's next pulse sees the task

## TYPICAL STEP
1. `bug_list_open()` → pick highest-priority untriaged bug
2. Inspect `bug_artifacts` to extract affected_endpoint / table / files
3. Cross-reference with APIHub / CodeHub
4. Form a one-sentence root cause hypothesis
5. `bug_triage(task_id, root_cause=..., assignee=...)` — assignee defaults to resolver if omitted
6. Notify via EventHub
7. Move to next bug if budget allows
{%- endmacro %}

{% macro bug_triage_task_prompt() -%}
Begin your triage cycle. Your hub_pulse will list open bugs at the top.
For each open bug (P0 first):
  - Read bug_artifacts carefully
  - Form a one-sentence root cause hypothesis (low confidence is acceptable; missing hypothesis is not)
  - Call bug_triage(task_id, root_cause=..., assignee=<auto if owner resolves>)
  - Publish bug_triaged event so the assignee gets a live notification
If a bug recurs (same endpoint or file as a closed bug), set parent_bug_id and consider escalating the design.
After processing the queue (or hitting your action budget), end the step.
{%- endmacro %}
```

- [ ] **Step 4: Verify the 7 prompt tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_orchestrator_prompt -v 2>&1 | tail -15
```

Expected: 7 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 437 OK (was 430 + 7 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2 agent/tests/test_bug_triage_orchestrator_prompt.py
git commit -m "Add bug_triage_orchestrator_agent.j2 prompt with hard discipline rules"
```

---

## Task 8: Update Verifier prompt — find-only, no triage

Verifier today does detection + triage + assignment. After Cutover 10, Verifier only detects + publishes. The prompt update enforces this with discipline language.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- Create: `agent/tests/test_verifier_bug_publish_prompt.py`

- [ ] **Step 1: Write failing prompt test**

Create `agent/tests/test_verifier_bug_publish_prompt.py`:

```python
"""Tests that the verifier prompt now forbids direct bug-task creation and requires
publishing bug_found events."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_DIR = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "prompts" / "v2"
)


class VerifierBugPublishPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
        tpl = env.get_template("verifier_agent.j2")
        mod = tpl.make_module()
        # Try the standard macro name first; fall back to a probe if the name differs.
        for candidate in ("verifier_specifics", "verifier_system_prompt"):
            if hasattr(mod, candidate):
                cls.system = getattr(mod, candidate)()
                break
        else:
            raise RuntimeError("could not find a verifier specifics/system macro")

    def test_prompt_mentions_bug_create_or_bug_found(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "BUG_CREATE" in upper or "BUG_FOUND" in upper,
            "verifier prompt must reference the new bug reporting tool/event",
        )

    def test_prompt_forbids_direct_remediation_task_creation(self) -> None:
        upper = self.system.upper()
        # Either explicit "do not assign" or "do not create task" or "find only".
        self.assertTrue(
            any(phrase in upper for phrase in (
                "DO NOT ASSIGN",
                "DO NOT CREATE",
                "MUST NOT ASSIGN",
                "MUST NOT CREATE",
                "FIND ONLY",
                "DETECTION ONLY",
                "DETECT ONLY",
            )),
            "verifier prompt must explicitly forbid bug-fix assignment",
        )

    def test_prompt_references_bug_triage_orchestrator(self) -> None:
        upper = self.system.upper()
        self.assertIn("BUG TRIAGE", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_verifier_bug_publish_prompt -v 2>&1 | tail -10
```

Expected: assertion failures.

- [ ] **Step 3: Inject the role-split block into the verifier prompt**

Locate the `verifier_specifics` macro (or whichever macro is the per-agent specifics section already used after Cutover 8 — Cutover 8 patched all agents identically; same pattern applies here).

Find the existing `### STEP PIPELINE` block that Cutover 8 inserted at the top of the macro. Just AFTER that block (so the role-split rules are co-located with the pipeline reminder), insert:

```jinja
### BUG REPORTING DISCIPLINE (Cutover 10)
You DETECT bugs by running contract tests and observing failures.
You DO NOT triage, analyze, assign, or fix bugs. Those are the **Bug Triage Orchestrator**'s and the **owning agent**'s jobs.

When you find a bug:
1. Call `bug_create(title, source="verifier", severity=..., bug_artifacts={failing_test, stack_trace, affected_endpoint, affected_files, expected, actual})`.
   This will automatically publish a `verifier/bug_found` event to EventHub.
2. DO NOT use `workhub_create_task` to create a remediation task directly. That bypasses triage.
3. DO NOT set `assignee` on the bug. The Bug Triage Orchestrator does that based on owning-agent resolution.
4. Continue running tests; you can report multiple bugs per step.

Severity guide: P0 = release-blocker / data loss; P1 = major user-facing breakage; P2 = minor breakage with workaround; P3 = nit / cosmetic.
```

- [ ] **Step 4: Verify the 3 prompt tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_verifier_bug_publish_prompt -v 2>&1 | tail -10
```

Expected: 3 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 440 OK (was 437 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2 agent/tests/test_verifier_bug_publish_prompt.py
git commit -m "Verifier: detect-only — bug_create publishes event, no direct task creation or assignment"
```

---

## Task 9: hub_pulse renders assigned bugs prominently

For non-triage agents, the existing hub_pulse already shows assigned WorkHub tasks. We want bug tasks visually distinguished by severity prefix in the render. For the bug_triage_orchestrator agent specifically, hub_pulse should also surface the OPEN BUG QUEUE (not just "tasks assigned to me").

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`
- Create: `agent/tests/test_hub_pulse_bug_rendering.py`

- [ ] **Step 1: Read current hub_pulse module**

```bash
sed -n '1,60p' agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py
```

Familiarize yourself with how `collect` / `build_hub_pulse_prompt` work. Hub_pulse was built in Cutover 8 Task 3.

- [ ] **Step 2: Write failing tests**

Create `agent/tests/test_hub_pulse_bug_rendering.py`:

```python
"""Tests for hub_pulse bug rendering enhancements (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect, build_hub_pulse_prompt  # noqa: E402


class HubPulseBugRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_bug_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normal_agent_pulse_renders_assigned_bug_with_severity_prefix(self) -> None:
        self.reg.workhub.create_task(title="500 on feed", assignee="backend",
                                     agent="bug_triage_orchestrator",
                                     kind="bug", severity="P1", bug_state="assigned",
                                     bug_artifacts={})
        report = collect("backend", self.reg)
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("[P1] 500 on feed", rendered)
        self.assertIn("ASSIGNED BUGS", rendered.upper())

    def test_bug_triage_orchestrator_pulse_shows_open_bug_queue(self) -> None:
        self.reg.workhub.create_task(title="A", agent="verifier",
                                     kind="bug", severity="P0", bug_state="open",
                                     bug_artifacts={})
        self.reg.workhub.create_task(title="B", agent="verifier",
                                     kind="bug", severity="P2", bug_state="open",
                                     bug_artifacts={})
        report = collect("bug_triage_orchestrator", self.reg)
        rendered = build_hub_pulse_prompt(report)
        upper = rendered.upper()
        self.assertIn("OPEN BUG QUEUE", upper)
        self.assertIn("[P0] A", rendered)
        self.assertIn("[P2] B", rendered)

    def test_normal_agent_with_no_assigned_bugs_skips_bug_section(self) -> None:
        report = collect("backend", self.reg)
        rendered = build_hub_pulse_prompt(report)
        self.assertNotIn("ASSIGNED BUGS", rendered.upper())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_bug_rendering -v 2>&1 | tail -10
```

Expected: failures — current hub_pulse doesn't render bug section.

- [ ] **Step 4: Extend `hub_pulse.py`**

In `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`:

(a) Extend the `collect(agent_id, hub_registry, ...)` function to also populate:
- `report.assigned_bugs` — `hub_registry.workhub.list_bugs_assigned_to(agent_id)`
- `report.open_bug_queue` — only when `agent_id == "bug_triage_orchestrator"`: `hub_registry.workhub.list_open_bugs()`; otherwise `[]`

If the report is currently a dataclass / dict, add those fields. If it's a NamedTuple, refactor to a small dict so adding fields is non-breaking.

(b) Extend `build_hub_pulse_prompt(report)`:
- After existing sections, if `report.assigned_bugs` is nonempty, render:
  ```
  ## ASSIGNED BUGS
  - [P1] 500 on feed (task_xxx)
  - [P0] segfault on /api/y (task_yyy)
  ```
- If `report.open_bug_queue` is nonempty (only true for bug_triage_orchestrator), render:
  ```
  ## OPEN BUG QUEUE
  - [P0] A (task_xxx) — open
  - [P2] B (task_yyy) — open
  ```

Use plain `[Pn]` severity prefix; no emojis. Format: `- [<severity>] <title> (<task_id>)` minimum; add ` — <bug_state>` for the open queue.

(c) Update `should_render(report)` so that having non-empty bug sections counts as "render the pulse" (it should already be triggered by other report content, but if hub state is otherwise empty for a freshly spawned bug triage orchestrator, the bug queue alone should keep the pulse from being skipped).

- [ ] **Step 5: Verify the 3 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_bug_rendering -v 2>&1 | tail -10
```

Expected: 3 tests OK.

- [ ] **Step 6: Run both baselines (catch hub_pulse regressions in existing tests)**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 443 OK (was 440 + 3 new). If `test_hub_pulse.py` (the Cutover 8 test) fails because the report shape changed, update the Cutover-8 tests to tolerate the new optional fields — but DO NOT change their behavior. They should still assert what they asserted.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py agent/tests/test_hub_pulse_bug_rendering.py
# also include any existing hub_pulse test fixture update if required
git commit -m "hub_pulse: surface assigned bugs (all agents) + open bug queue (bug_triage_orch only)"
```

---

## Task 10: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/11-bug-triage-orchestrator.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 443 OK. STOP and fix if anything fails.

- [ ] **Step 2: Verify zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`. If nonzero, STOP and rewrite history with `git filter-branch --msg-filter "sed '/Co-Authored-By: Claude/d'"`.

- [ ] **Step 3: Write the migration log**

Create `docs/superpowers/migration-logs/11-bug-triage-orchestrator.md`:

```markdown
# Cutover 10: Bug Triage Orchestrator

**Branch:** `haibotong-cutover-10-bug-triage`
**Date:** 2026-05-24

## What

Split the bug-handling workflow into three single-responsibility roles per advisor's recommendation:

- **Verifier**: DETECT bugs (publish `verifier/bug_found` event via new `bug_create` tool). No more triage or assignment.
- **Bug Triage Orchestrator (NEW)**: receive bug events → root-cause hypothesis → resolve owning agent (APIHub provider / file-path heuristic) → assign remediation task. Never edits code.
- **Owning agent** (backend / database / frontend): pick up assigned bug from hub_pulse → fix → close with evidence.

Bugs ride on existing WorkHub tasks via `metadata.kind="bug"` plus structured fields (`severity`, `bug_state`, `root_cause_hypothesis`, `parent_bug_id`, `bug_artifacts`, `triage_history`).

## Why

Verifier was doing detection + analysis + assignment — three distinct skills.
Real engineering separates these (monitoring ≠ root cause ≠ fix). Concentrating
them on Verifier hurt analysis quality and made escalation impossible.

## Commit history

(fill with `git log --oneline haibotong-0521-pipeline-web-tools..HEAD`)

## Test deltas

- Regressions: 7 OK → 7 OK
- Discover: 393 OK → 443 OK (+50 new tests across WorkHub helpers, resolver, tools, config, prompts, hub_pulse rendering)

## New surfaces

- `multi_agent/runtime/bug_triage.py` — owning-agent resolver (~80 LoC)
- `tools/bug_tools.py` — 7 LLM tools (~150 LoC)
- `prompts/v2/bug_triage_orchestrator_agent.j2` — new agent prompt
- `agents_config.yaml`: 11 profiles (was 10)
- WorkHub: 5 new methods (`list_open_bugs`, `list_bugs_assigned_to`, `update_bug_state`, `close_bug`, `escalate_bug`)
- hub_pulse: 2 new render sections (`ASSIGNED BUGS`, `OPEN BUG QUEUE`)

## Bug lifecycle

```
open  ──(BugTriageOrch.triage)──>  triaged ──(.assigned)──>  assigned
   │                                                            │
   │                                                  (owner picks up)
   │                                                            ▼
   └─────(BugTriageOrch.escalate)──> escalated   ──>  in_progress
                                                            │
                                                (owner proposes fix)
                                                            ▼
                                                     fix_proposed
                                                            │
                                                 (verifier re-runs)
                                                            ▼
                                                     fix_verified
                                                            │
                                                  (owner closes)
                                                            ▼
                                                       closed
```

## Verification

- Zero Claude trailers
- Both baselines green
- New profile registered + prompt renders + tools wired + WorkHub helpers cover the lifecycle
```

- [ ] **Step 4: Commit the migration log**

```bash
git add docs/superpowers/migration-logs/11-bug-triage-orchestrator.md
git commit -m "Add Cutover 10 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-10-bug-triage 2>&1 | tail -5
```

Expected: "new branch" + compare URL.

- [ ] **Step 6: Report**

Print: branch name, commit count, final test counts, push URL, anything to flag for merge-into-parent (e.g., new test files that should appear in the parent after ff-merge).

---

## Self-Review

**1. Spec coverage:**
- Verifier becomes detect-only — Task 8 ✓
- New Bug Triage Orchestrator agent — Tasks 6 + 7 ✓
- Owning agent identification — Task 4 ✓
- Bug lifecycle (open → triaged → assigned → in_progress → fix_proposed → fix_verified → closed/escalated) — Task 3 ✓
- LLM tools for the workflow — Task 5 ✓
- Pulse surfaces assigned bugs + open queue — Task 9 ✓
- Migration log + push — Task 10 ✓

**2. Placeholder scan:** No TBD / "fill in" / "implement later". Every code-change step has actual code. Note: Task 5 (tool base class import) has a `try/except` fallback — that's intentional in case the existing tool-class convention has moved between cutovers; the test suite is the authoritative check.

**3. Type consistency:**
- WorkHub methods: `list_open_bugs() -> list`, `list_bugs_assigned_to(agent) -> list`, `update_bug_state(task_id, new_state, agent, note="", assignee=None, **metadata_updates) -> dict`, `close_bug(task_id, agent, fix_evidence=None) -> dict`, `escalate_bug(task_id, agent, reason) -> dict` — same shapes used in Tasks 2/3/5 ✓
- bug_triage helpers: `find_owning_agent_for_endpoint(registry, method, path) -> Optional[str]`, `find_owning_agent_for_table(registry, name) -> Optional[str]`, `find_owning_agent_for_file(path) -> Optional[str]`, `resolve_owning_agent(registry, artifacts) -> Optional[str]` — same shapes used in Tasks 4 + 5 ✓
- Tool `_execute` kwargs: `BugCreateTool(*, title, source, severity, bug_artifacts, description="", parent_bug_id=None)`, `BugTriageTool(*, task_id, root_cause, assignee=None)`, etc. — kwargs match what the tests pass ✓
- Bug states: `open / triaged / assigned / in_progress / fix_proposed / fix_verified / closed / escalated` — same set in `_VALID_BUG_STATES`, `_OPEN_BUG_STATES`, prompt text, lifecycle diagram ✓
- Severity values: `P0 / P1 / P2 / P3` — consistent across tool, WorkHub helper, prompt ✓

**4. Cross-cutting:**
- No Claude trailer — verified in Tasks 1 + 10 ✓
- Baselines green at every task boundary — explicit step ✓
- TDD: every code-change task starts with failing test ✓
- Bugs piggyback on existing tasks store — no schema migration burden ✓
- Verifier role-split rules in prompt are explicit (5 hard rules) ✓
