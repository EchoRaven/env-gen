# Cutover 5 — system_tools + Final CRDT Purge

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Close the book. Build `tools/system_tools.py` for the cross-hub metrics (token/performance/retry/dashboard/health), delete `CRDTWorkspace` and all `crdt_*` source files, replace the `crdt_workspace` reference in `Orchestrator` with a top-level `HubRegistry`. End-state: **`git grep -iE "crdt|CRDT" -- ":!docs/" ":!agent/tests/"` returns zero matches in runtime/agent source.**

**Why now:** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §3.3 + §6 + §3.5. After Cutover 4, ~25 methods + several files remain. This cutover ends the work.

**Source spec:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` §9.1, §12.

**Audit acceptance criteria (must all pass at the end):**
- A. `git grep -lE "from .*crdt|crdt_workspace|CRDTWorkspace" -- ":!docs/" ":!agent/tests/"` returns zero in source.
- B. Files deleted: `crdt.py`, `crdt_observer.py`, `hub_workspace.py`, `crdt_tools.py`, `crdt_metrics_tools.py`, `crdt_tool_base.py`.
- C. `Orchestrator.__init__` holds a `HubRegistry` directly (`self.hubs = HubRegistry(self.output_dir, self.message_bus)`), no `self.crdt_workspace`.
- D. `agents_config.yaml` profiles do not list `crdt` in `tool_categories` and do not include `crdt`-named tool bundles.
- E. Full regression + e2e smoke pass.

---

## Phase Map

| Phase | Scope | Tasks |
|---|---|---|
| A | Build `tools/system_tools.py` for cross-hub metrics | 3 |
| B | Migrate `record_token_usage` / `get_token_usage` / `get_token_budget_status` to EventHub system topic + system_tools | 2 |
| C | Migrate `check_agent_health` / `get_stuck_agents` / `get_progress_dashboard` / `get_summary` / `increment_progress` to EventHub / system_tools | 3 |
| D | Audit + delete dead methods (`publish_task`, `claim_task`, `get_pending_tasks`, `create_observer`, `get_api_usage_records`, `get_build_records`, `get_contracts`, `update_artifact`, `get_artifacts`, `update_table` (kept as fallback in C4 — delete now), `get_tables`, `get_table`, `update_table`) | 2 |
| E | Build `runtime/hubs.py:HubRegistry`, switch `Orchestrator` to use it, delete `CRDTWorkspace`, `crdt.py`, `crdt_observer.py`, `hub_workspace.py` | 3 |
| F | Delete `tools/crdt_tools.py`, `tools/crdt_metrics_tools.py`, `tools/crdt_tool_base.py`; update `agents_config.yaml`; final residue scan; migration log + push | 4 |

Total: ~17 tasks. Effort: 3-5 days per audit estimate.

---

## File Map

**Create:**
- `agent/env_generator/llm_generator/tools/system_tools.py` — cross-hub metrics
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs.py` — `HubRegistry` (top-level aggregator replacing `HubWorkspace`)
- `agent/tests/test_system_tools.py`
- `agent/tests/test_hub_registry.py`
- `docs/superpowers/migration-logs/06-final-purge.md`

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py` — switch to `HubRegistry` (delete `self.crdt_workspace`)
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py` — drop `crdt` tool category branch
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — drop `crdt`-prefixed bundle helpers
- `agent/env_generator/llm_generator/multi_agent/tool_runtime.py` — drop `crdt_workspace` from `ToolAssemblyContext`
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — drop `crdt` from `tool_categories`, drop crdt bundle refs
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py` — drop CRDT snapshot helpers (`_collect_crdt_change_summary` if still present and replaced)
- Anywhere `getattr(agent, '_crdt_workspace')` is read — point at `hubs` instead

**Delete (final acceptance):**
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py`
- `agent/env_generator/llm_generator/tools/crdt_tools.py`
- `agent/env_generator/llm_generator/tools/crdt_metrics_tools.py`
- `agent/env_generator/llm_generator/tools/crdt_tool_base.py`

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-5-final-purge -b haibotong-cutover-5-final-purge red-env-gen/haibotong-cutover-4-codehub-real-git
cd .worktrees/haibotong-cutover-5-final-purge
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: 7 OK.

---

## Phase A — `tools/system_tools.py`

### Task 2: Create system_tools.py with token/performance/retry recorders

Create `agent/env_generator/llm_generator/tools/system_tools.py`. This file owns cross-hub observability (NOT collaboration). It exposes:

- `SystemMetrics` class (singleton-style per orchestrator) wrapping CRDT JSON stores in `shared/crdt/system_*.json`:
  - `record_token_usage(agent_id, input_tokens, output_tokens, cached_tokens=0, model="", cost_usd=0.0)`
  - `get_token_usage(agent_id=None)` → dict
  - `get_token_budget_status(budget_usd=10.0)` → dict
  - `record_operation_time(operation, duration_ms, agent_id="")`
  - `get_performance_stats(operation=None)` → dict
  - `record_retry(operation, attempts, success, agent_id="")`
  - `get_retry_stats(operation=None)` → dict

Each method mirrors the old `CRDTWorkspace` signature exactly so caller migration is mechanical.

Stores live under `shared/crdt/`:
- `system_token_usage.json`
- `system_performance.json`
- `system_retries.json`

Use `CRDTStore` + `LWWMap` (same primitives as before).

Add LLM tool classes (subclassing `BaseTool`):
- `RecordTokenUsageTool` (NAME=`system_record_token_usage`)
- `GetTokenUsageTool` (NAME=`system_get_token_usage`)
- `GetTokenBudgetStatusTool` (NAME=`system_get_token_budget`)
- `GetPerformanceStatsTool` (NAME=`system_get_performance`)
- `GetRetryStatsTool` (NAME=`system_get_retry_stats`)

Create `agent/tests/test_system_tools.py` with 6-8 tests covering each method.

Commit: `Add tools/system_tools.py with cross-hub metrics`.

### Task 3: Build `system_tools` bundle in `tool_bundles.py`

Add `_bundle_system_tools(builder, context)` that exposes the system tool classes. Add `"system_tools"` to `TOOL_BUNDLE_REGISTRY` and `TOOL_BUNDLE_REQUIREMENTS`.

Update `agents_config.yaml` profiles that previously had `crdt_metrics_tools` in `tool_bundles:` — replace with `system_tools`.

Commit: `Wire system_tools bundle into tool registry + agents_config`.

### Task 4: Verify orchestrator + agent_spawn use system_tools

Orchestrator's pipeline (around `_validate_delivery_gate` and report rendering) likely reads token usage. Switch any `self.crdt_workspace.record_token_usage(...)` / `get_token_usage(...)` calls to a direct `SystemMetrics` instance held by Orchestrator (e.g., `self.metrics = SystemMetrics(self.output_dir)`).

Commit: `Switch orchestrator + agents to use SystemMetrics directly`.

---

## Phase B — Migrate token usage from CRDT

### Task 5: Switch all `record_token_usage` callers

```bash
grep -rn "record_token_usage\|get_token_usage\|get_token_budget_status" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Rewrite each: `workspace.record_token_usage(...)` → `metrics.record_token_usage(...)` (Orchestrator holds `metrics`; agents access via their orchestrator handle).

Delete `record_token_usage / get_token_usage / get_token_budget_status` + `_token_usage` store from `crdt.py`.

Commit: `Switch token usage to SystemMetrics, delete from CRDT`.

### Task 6: Migrate performance + retry metrics

`record_operation_time` / `get_performance_stats` / `record_retry` / `get_retry_stats` callers:

```bash
grep -rn "record_operation_time\|get_performance_stats\|record_retry\|get_retry_stats" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Same pattern as Task 5 — switch to SystemMetrics, delete from CRDT.

Commit: `Switch performance + retry stats to SystemMetrics, delete from CRDT`.

---

## Phase C — Migrate health / progress / dashboard

### Task 7: `check_agent_health` + `get_stuck_agents` → EventHub.get_all_agent_statuses

Both methods read agent statuses. EventHub's `get_all_agent_statuses` was added in Cutover 3 Phase E.

Add to `system_tools.py`:

```python
def check_agent_health(eventhub, timeout_seconds=300):
    statuses = eventhub.get_all_agent_statuses() or {}
    now = time.time()
    stuck = []
    healthy = []
    for agent_id, status in statuses.items():
        last = status.get("_event_created_at", 0) or 0
        if now - last > timeout_seconds:
            stuck.append({"agent_id": agent_id, "last_seen": last, "stale_seconds": int(now - last)})
        else:
            healthy.append({"agent_id": agent_id, "last_seen": last})
    return {"healthy": healthy, "stuck": stuck, "total": len(statuses)}

def get_stuck_agents(eventhub, timeout_seconds=300):
    return check_agent_health(eventhub, timeout_seconds)["stuck"]
```

Switch callers (orchestrator delivery gate, dashboard render). Delete from `crdt.py`.

Commit: `Migrate check_agent_health / get_stuck_agents to EventHub + system_tools`.

### Task 8: `get_progress_dashboard` + `get_summary` + `increment_progress` / `get_progress`

These aggregate everything (endpoints, tables, tasks, plans, agents, build status). Now everything lives in hubs. Rewrite in `system_tools.py`:

```python
def get_progress_dashboard(hubs):
    return {
        "endpoints": len(hubs.apihub.get_endpoints() or {}),
        "tables": len(hubs.apihub.list_tables() or {}),
        "tasks": {
            "total": len(hubs.workhub.list_tasks() or []),
            "pending": len(hubs.workhub.list_tasks(status="pending") or []),
            "in_progress": len(hubs.workhub.list_tasks(status="in_progress") or []),
            "completed": len(hubs.workhub.list_tasks(status="completed") or []),
        },
        "pages": len(hubs.workhub.list_pages() or []),
        "plans": len(hubs.workhub.list_plans() or []),
        "agents": hubs.eventhub.get_all_agent_statuses() or {},
        "checks": {"summary": hubs.codehub.get_check_summary("main")},
    }

def get_summary(hubs):
    return {"hubs": hubs.snapshot(), "metrics": _metric_snapshot()}
```

`increment_progress` / `get_progress` were simple counters — replace with EventHub `progress` topic OR drop entirely (if no callers).

Switch callers + delete from `crdt.py`. Add 2 tests.

Commit: `Migrate get_progress_dashboard / get_summary / progress counters to system_tools`.

### Task 9: System tools final integration

Update `tool_bundles.py:_bundle_system_tools` to include all the new system tool classes. Update agents that previously had broad CRDT access (orchestrator, verifier) to use `system_tools` bundle.

Commit: `Finalize system_tools bundle scope + agent assignments`.

---

## Phase D — Dead-code purge

### Task 10: Delete dead methods + dual-write residues from crdt.py

Methods to delete (no callers):
- `publish_task`, `claim_task` (old task layer pre-dev_task), `get_pending_tasks`
- `create_observer`
- `get_api_usage_records`, `get_build_records`, `get_contracts` (read-only accessors with no callers now that data is in hubs)
- `update_artifact`, `get_artifacts` (Cutover 4 dual-write fallback)
- `update_table`, `get_table`, `get_tables` (Cutover 4 dual-write fallback)
- `get_build_status`, `get_verification_checklist`, `get_build_history` (Cutover 4 dual-write fallback)
- `_validation_results`, `_builds`, `_retries`, `_performance`, `_artifacts`, `_tables`, `_contracts`, `_implementations` stores (if still present after Cutover 4)

Verify zero callers via grep before delete:
```bash
grep -rn "workspace\.\(publish_task\|claim_task\|get_pending_tasks\|create_observer\|update_artifact\|get_artifacts\|update_table\|get_table\|get_tables\|get_build_status\|get_verification_checklist\|get_build_history\|get_api_usage_records\|get_build_records\|get_contracts\)" --include='*.py' agent/ | grep -v __pycache__ | grep -v test_
```

Expected: zero (any remaining → fix in this commit). Then delete methods + stores.

Commit: `Delete dead CRDT methods (publish_task/create_observer/dual-write fallbacks)`.

### Task 11: Final crdt.py audit

What remains in crdt.py? Inspect:
```bash
grep -nE "^    def [a-z]|^class " agent/env_generator/llm_generator/multi_agent/runtime/crdt.py
```

Anything not absorbed by hubs or system_tools? Each remaining method:
- `__init__`, `ensure_core_documents` — boot logic. Will be gone with the file.
- `get_versions`, `snapshot` — already aggregate from hubs. Will be replicated in `HubRegistry`.

If anything material remains, decide: migrate or delete. Document the decision.

Commit (if needed): `Final crdt.py dead-method audit`.

---

## Phase E — Build HubRegistry + replace CRDTWorkspace

### Task 12: Create `runtime/hubs.py:HubRegistry`

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs.py`:

```python
"""Top-level hub aggregator that replaces CRDTWorkspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .apihub import APIHub
from .codehub import CodeHub
from .eventhub import EventHub
from .workhub import WorkHub
from .hubs.eventhub import MessageBusBridge


class HubRegistry:
    """Aggregator passed to agents and tools. Replaces CRDTWorkspace as the runtime DI surface."""

    def __init__(self, output_dir: Path, message_bus: Any = None):
        self.output_dir = Path(output_dir)
        self.crdt_dir = self.output_dir / "shared" / "crdt"
        self.crdt_dir.mkdir(parents=True, exist_ok=True)
        # Order matters: EventHub first (others depend on it)
        self.eventhub = EventHub(self.crdt_dir)
        if message_bus is not None:
            self.bridge = MessageBusBridge(self.eventhub, message_bus)
            self.eventhub.attach_bridge(self.bridge)
        else:
            self.bridge = None
        self.codehub = CodeHub(self.output_dir, self.crdt_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub = APIHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub.attach_workhub(self.workhub)
        if hasattr(self.codehub, "attach_workhub"):
            self.codehub.attach_workhub(self.workhub)

    def snapshot(self) -> dict:
        return {
            "apihub": self.apihub.snapshot(),
            "workhub": self.workhub.snapshot(),
            "codehub": self.codehub.snapshot(),
            "eventhub": self.eventhub.snapshot(),
        }

    def get_versions(self) -> Dict[str, int]:
        v = {}
        v.update(self.apihub.get_versions())
        v.update(self.workhub.get_versions())
        v.update(self.codehub.get_versions())
        v.update(self.eventhub.get_versions())
        return v
```

Add `agent/tests/test_hub_registry.py` with tests:
1. Construct, no message_bus → bridge=None, all 4 hubs accessible.
2. Construct with message_bus → bridge non-None, attached to EventHub.
3. `snapshot()` returns 4-key dict.
4. `get_versions()` returns merged version map.

Commit: `Add HubRegistry as runtime DI surface`.

### Task 13: Switch Orchestrator from CRDTWorkspace to HubRegistry

Find: `self.crdt_workspace = CRDTWorkspace(self.output_dir, message_bus=self.message_bus)` in `orchestrator.py`.

Replace with:
```python
self.hubs = HubRegistry(self.output_dir, message_bus=self.message_bus)
# Transitional alias for any caller that still expects crdt_workspace
self.crdt_workspace = self.hubs
```

(The alias keeps backward compat for one more pass; the next task removes it.)

Find all `self.crdt_workspace.X` in orchestrator.py and switch to `self.hubs.X` if X is a hub-level attribute (e.g., `self.crdt_workspace.hubs.apihub.get_endpoints()` → `self.hubs.apihub.get_endpoints()`).

Search for any agent code that does `getattr(agent, "_crdt_workspace", None)` — switch to `_hubs`. Or extend `set_crdt_workspace` in agent/runtime/tooling.py to accept a HubRegistry instance and rename to `set_hubs`.

Verify regressions + commit: `Switch Orchestrator from CRDTWorkspace to HubRegistry`.

### Task 14: Delete CRDTWorkspace, crdt.py, crdt_observer.py, hub_workspace.py

Once Task 13 settles (and the transitional alias is no longer needed):

1. Delete `self.crdt_workspace = self.hubs` alias from orchestrator.
2. `git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt.py`
3. `git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer.py`
4. `git rm agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py`
5. Update `runtime/__init__.py` to drop the imports.

Verify `git grep "CRDTWorkspace\|crdt_workspace"` is empty in source dir:
```bash
git grep -lE "CRDTWorkspace|crdt_workspace" -- ":!docs/" ":!agent/tests/"
```

Expected: empty.

Commit: `Delete CRDTWorkspace, crdt.py, crdt_observer.py, hub_workspace.py`.

---

## Phase F — Tool cleanup + final ship

### Task 15: Delete crdt_tools.py / crdt_metrics_tools.py / crdt_tool_base.py

```bash
git rm agent/env_generator/llm_generator/tools/crdt_tools.py
git rm agent/env_generator/llm_generator/tools/crdt_metrics_tools.py
git rm agent/env_generator/llm_generator/tools/crdt_tool_base.py
```

Update `tools/__init__.py` to drop imports.

Update `tool_bundles.py` to drop any remaining `crdt`-prefixed bundle helpers.

Update `tool_runtime.py` to drop `crdt_workspace` from `ToolAssemblyContext`.

Update `agents/runtime/tooling.py` to drop the `if "crdt" in self.allowed_tool_categories:` block.

Update `agents_config.yaml`:
- Remove `"crdt"` from every `tool_categories:` list
- Remove any remaining `crdt_*_tools` from `tool_bundles:` lists

Verify imports + tests + commit: `Delete crdt_tools.py / crdt_metrics_tools.py / crdt_tool_base.py + cleanup wiring`.

### Task 16: Final residue audit

```bash
git grep -lE "CRDTWorkspace|crdt_workspace|from .*\\bcrdt\\b" -- ":!docs/" ":!agent/tests/"
```

Expected: empty.

```bash
git grep -lE "\\bcrdt\\b" -- ":!docs/" ":!agent/tests/" ":!**/*.json" ":!.gitignore"
```

May still match `shared/crdt/` directory references (we keep the directory for backwards-compat with disk JSON; or rename it to `shared/hubs/` — decide and document). Anything else → fix.

Commit: `Final CRDT residue audit` (or no-op if already clean).

### Task 17: Full regression + e2e smoke + migration log + push

Run discover all tests:
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
```

Expected: all green.

E2E smoke (same as previous cutovers but now via HubRegistry):
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from utils.communication import MessageBus
from multi_agent.runtime.hubs import HubRegistry

class FakeAgent:
    def __init__(self, aid): self.agent_id = aid; self.received = []
    async def receive_message(self, m): self.received.append(m)

async def main():
    with tempfile.TemporaryDirectory() as td:
        bus = MessageBus(); await bus.start()
        backend = FakeAgent('backend'); bus.register_agent(backend)
        hubs = HubRegistry(Path(td), message_bus=bus)
        hubs.codehub.ensure_repo()
        wt = hubs.codehub.register_agent_worktree('backend')
        print('worktree at:', wt['worktree_path'])
        hubs.apihub.register_endpoint('GET', '/api/feed', schema={'response': {'posts': []}}, provider='backend', agent='design')
        hubs.apihub.register_consumer('GET /api/feed', 'f.jsx', 'backend')
        hubs.apihub.update_schema('GET /api/feed', response={'items': []}, agent='backend')
        await asyncio.sleep(0.1)
        print('backend received', len(backend.received), 'live event(s)')
        await bus.stop()

asyncio.get_event_loop().run_until_complete(main())
"
```

Expected: `worktree at:` line + `backend received >=1`.

Write `docs/superpowers/migration-logs/06-final-purge.md`:
- Audit references (§6, §12)
- Final acceptance criteria all PASS
- Files deleted (final tally)
- `HubRegistry` design
- Commit list
- Total lines removed across all cutovers (Cutover 1 → 5)
- Closing notes

Push branch + PR compare URL.

Commit: `Add Cutover 5 migration log — CRDT fully stripped`.

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer** on any commit.
- Use `dt` conda env Python.
- Branch from `red-env-gen/haibotong-cutover-4-codehub-real-git`.
- ~17 commits.

## Acceptance summary (recheck before merge)

All boxes must be ticked:

- [ ] `git grep -lE "CRDTWorkspace|crdt_workspace|from .*\\bcrdt\\b" -- ":!docs/" ":!agent/tests/"` returns empty
- [ ] `multi_agent/runtime/crdt.py`, `crdt_observer.py`, `hub_workspace.py` deleted
- [ ] `tools/crdt_tools.py`, `crdt_metrics_tools.py`, `crdt_tool_base.py` deleted
- [ ] `Orchestrator.__init__` holds `self.hubs = HubRegistry(...)`, no `self.crdt_workspace`
- [ ] `agents_config.yaml` profiles do not list `crdt` in `tool_categories` and do not include `crdt_*_tools` bundles
- [ ] Full regression + e2e smoke pass
- [ ] EventHub → MessageBus delivery confirmed in live run
- [ ] CodeHub `merge_pull_request` performs a real `git merge`
- [ ] Zero Claude trailers across all Cutover 5 commits

## Recovery Notes

This is the final cutover. Each Phase is independently revertable. Phase E (HubRegistry switch) is the most risky — if Orchestrator breaks unexpectedly, revert Phases E-F and ship Phases A-D as a smaller PR, then write a follow-up plan for the final replacement.
