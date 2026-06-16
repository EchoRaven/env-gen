# Cutover 16: Retro Stage (End-of-Generation Review)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force the orchestrator to produce a structured **retro** (compare plan vs reality + identify systematic failures + propose prompt diffs) BEFORE `deliver_project()` can succeed. Make end-of-generation reflection a hard gate, not an optional habit.

**Architecture:** New WorkHub page type `kind="retro"` with structured fields. New `submit_retro` LLM tool that validates required fields. New `runtime/retro_aggregator.py` pure module that scans WorkHub/RunHub/CodeHub/EventHub and returns aggregate stats (the LLM uses these as input). `DeliverProjectTool` extended to query WorkHub for a retro tagged with the current generation_id; refuses if not present. The "generation_id" is a session-start timestamp stamped onto retro metadata.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Existing surfaces: WorkHub `create_page` (now supports `kind=` after Cutover 14), RunHub `list_runs` (Cutover 11), BugTriageOrch + WorkHub bug helpers (Cutover 10), `DeliverProjectTool` (existing).

---

## Context for Worker

### Why this cutover exists

Real engineering orgs run retros after every meaningful release. Without one, the same class of failure recurs across runs because nothing accumulates lessons. Today the orchestrator can call `deliver_project()` the moment the smoke tests pass — no requirement to look back and ask "what went wrong, what almost went wrong, what should we change next time."

Cutover 15 added structured postmortems for **incidents**, but a retro is broader: it compares the generation's *plan* against the generation's *reality* across all hubs and produces actionable changes to prompts/processes for future generations.

This cutover makes that reflection mandatory before `deliver_project()` succeeds.

### Retro page schema

`kind="retro"` page on WorkHub with structured fields:

```python
{
    "kind": "retro",
    "status": "active",
    "metadata": {
        "generation_id": "<session_start_epoch>",  # stamped at submit time
        "plan_vs_reality": [                       # >=2 entries
            {"plan_item": "...", "actual_outcome": "...", "drift_reason": "..."},
            ...
        ],
        "systematic_failures": [...],              # >=1 entry (or [] if truly none)
        "lessons": [...],                          # >=2 entries
        "proposed_prompt_changes": [               # >=1 entry
            {"agent_profile": "backend", "change_description": "..."},
            ...
        ],
        "bug_stats": {                             # auto-populated by aggregator
            "total_bugs": <int>, "by_severity": {"P0": ..., "P1": ...},
            "closed": <int>, "escalated": <int>,
            "avg_lifecycle_steps": <float>,
        },
        "run_stats": {                             # auto-populated by aggregator
            "total_runs": <int>, "passed": <int>, "failed": <int>,
            "failure_rate": <float>,
        },
        "review_stats": {                          # PR review aggregates
            "total_prs": <int>, "force_merged": <int>,
            "median_review_count_per_pr": <int>,
        },
    },
}
```

Validation in `submit_retro` enforces:
- `plan_vs_reality` ≥2 entries, each with non-empty `plan_item`/`actual_outcome`/`drift_reason`
- `systematic_failures` can be `[]` (genuine "no recurring failures") but must be supplied
- `lessons` ≥2 non-empty entries
- `proposed_prompt_changes` ≥1 entry with non-empty `agent_profile` + `change_description`
- `bug_stats` / `run_stats` / `review_stats` are auto-computed by `retro_aggregator` — caller doesn't supply them

### Aggregator (pure, no LLM)

`runtime/retro_aggregator.py` exposes `compute_retro_stats(hub_registry) -> RetroStats`:

```python
@dataclass
class RetroStats:
    bug_stats: dict
    run_stats: dict
    review_stats: dict
```

Pure read-side function. No mutation. Used by `submit_retro` automatically. Also exposed as a tool `retro_get_stats` so the orchestrator can inspect stats before writing the retro.

### Delivery gate

`DeliverProjectTool` (existing) gets a new pre-flight check:

```python
last_retro = workhub.get_latest_retro_for_generation(generation_id)
if last_retro is None:
    return failure("must submit_retro before deliver_project")
```

`generation_id` is the orchestrator agent's session start timestamp. We add a `_session_start_ts: float` attribute on the orchestrator agent (or, simpler, on the `DeliverProjectTool` instance — it's instantiated per-session). `submit_retro` reads the same timestamp from its tool context.

For tests: an isolated `HubRegistry` plus a `DeliverProjectTool(agent=mock_agent_with_session_start)` exercises the gate fully without LLMs.

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python`
- No Claude trailer on commits; no emojis
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Both baselines green at every task: regressions 7 OK; discover 611 OK after Cutover 15
- HubTool framework: only relevant for new hub-style tools; the retro tools sit in the `BaseTool` family (matching `DeliverProjectTool` / knowledge tools)

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/retro_aggregator.py` — `RetroStats` + `compute_retro_stats`
- `agent/env_generator/llm_generator/tools/retro_tools.py` — `SubmitRetroTool`, `ListRetrosTool`, `GetRetroStatsTool`
- `agent/tests/test_workhub_retro.py`
- `agent/tests/test_retro_aggregator.py`
- `agent/tests/test_retro_tools.py`
- `agent/tests/test_deliver_retro_gate.py`
- `agent/tests/test_orchestrator_retro_prompt.py`
- `agent/tests/test_retro_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — add `list_retros`, `get_latest_retro_for_generation`
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` — `DeliverProjectTool` retro pre-flight check
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `retro_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `retro_tools` bundle to `orchestrator` profile
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — RETRO DISCIPLINE block

---

## Task 1: Worktree + baseline

**Files:**
- Create: `docs/superpowers/cutover-16-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-16-retro
git status
git log --oneline -3
```

If missing: `git worktree add -b haibotong-cutover-16-retro .worktrees/haibotong-cutover-16-retro haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 611 OK.

- [ ] **Step 3: Inventory DeliverProjectTool surface**

```bash
sed -n '425,500p' agent/env_generator/llm_generator/tools/agent_interaction_tools.py
```

Note: how `DeliverProjectTool.__init__(agent=...)` and `.execute()` are shaped. Task 5 will extend `execute()` with a retro pre-flight.

- [ ] **Step 4: Inventory WorkHub list_pages signature**

```bash
grep -nE "def list_pages|def create_page" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py | head -3
```

Confirm `list_pages(kind=, status=)` exists (added in Cutover 14 / pre-existing).

- [ ] **Step 5: Write baseline note**

Create `docs/superpowers/cutover-16-baseline.md`:

```markdown
# Cutover 16 Baseline (Retro Stage)

## Test counts
- regressions: 7 OK
- discover: 611 OK

## Gap this cutover closes
Orchestrator can call deliver_project() the moment smoke passes — no
mandatory reflection on the generation. Cutover 15 added structured
postmortems for incidents; this cutover adds the broader "retro" doc
type tied to deliver_project as a hard gate.

## Approach
- retros are WorkHub pages with kind="retro" (parallel to design pages)
- submit_retro requires plan_vs_reality, lessons, proposed_prompt_changes
- runtime/retro_aggregator.py pure function computes bug/run/review stats
- DeliverProjectTool refuses if no retro for this session's generation_id
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/cutover-16-baseline.md
git commit -m "Cutover 16: record pre-flight baseline (regressions 7 OK, discover 611 OK)"
```

---

## Task 2: WorkHub retro helpers

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_retro.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_workhub_retro.py`:

```python
"""Tests for WorkHub retro helpers (Cutover 16)."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class WorkHubRetroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_retro_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_retros_empty(self) -> None:
        self.assertEqual(self.reg.workhub.list_retros(), [])

    def test_list_retros_filters_only_retro_kind(self) -> None:
        self.reg.workhub.create_page(title="design", agent="d", kind="design")
        self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        retros = self.reg.workhub.list_retros()
        self.assertEqual(len(retros), 1)
        self.assertEqual(retros[0]["title"], "r1")

    def test_get_latest_retro_for_generation_returns_match(self) -> None:
        self.reg.workhub.create_page(title="r-old", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        self.reg.workhub.create_page(title="r-new", agent="orch", kind="retro",
                                       metadata={"generation_id": 2000.0})
        r = self.reg.workhub.get_latest_retro_for_generation(2000.0)
        self.assertIsNotNone(r)
        self.assertEqual(r["title"], "r-new")

    def test_get_latest_retro_for_generation_returns_none_when_no_match(self) -> None:
        self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        self.assertIsNone(self.reg.workhub.get_latest_retro_for_generation(9999.0))

    def test_get_latest_retro_returns_most_recent_when_multiple_for_same_gen(self) -> None:
        # Same generation_id used by two retros (e.g., revised retro)
        p1 = self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                            metadata={"generation_id": 1000.0})
        time.sleep(0.01)
        p2 = self.reg.workhub.create_page(title="r2", agent="orch", kind="retro",
                                            metadata={"generation_id": 1000.0})
        latest = self.reg.workhub.get_latest_retro_for_generation(1000.0)
        self.assertEqual(latest["id"], p2["id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_retro -v 2>&1 | tail -10
```

Expected: AttributeError on `list_retros` / `get_latest_retro_for_generation`.

- [ ] **Step 3: Add the 2 methods on `WorkHub`**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, add (near `list_pending_design_reviews` from Cutover 14):

```python
    def list_retros(self) -> list:
        return [p for p in (self.stores.pages.value() or {}).values()
                if p.get("kind") == "retro"]

    def get_latest_retro_for_generation(self, generation_id) -> Optional[dict]:
        matches = [p for p in self.list_retros()
                   if (p.get("metadata") or {}).get("generation_id") == generation_id]
        if not matches:
            return None
        return max(matches, key=lambda p: p.get("created_at", 0.0))
```

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_retro -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 616 OK (611 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_retro.py
git commit -m "WorkHub: add list_retros + get_latest_retro_for_generation helpers"
```

---

## Task 3: `retro_aggregator` (pure stats)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/retro_aggregator.py`
- Create: `agent/tests/test_retro_aggregator.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_retro_aggregator.py`:

```python
"""Tests for runtime/retro_aggregator.py (Cutover 16)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.retro_aggregator import (  # noqa: E402
    RetroStats, compute_retro_stats,
)


class RetroAggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_agg_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_registry_returns_zero_stats(self) -> None:
        stats = compute_retro_stats(self.reg)
        self.assertIsInstance(stats, RetroStats)
        self.assertEqual(stats.bug_stats["total_bugs"], 0)
        self.assertEqual(stats.run_stats["total_runs"], 0)
        self.assertEqual(stats.review_stats["total_prs"], 0)

    def test_bug_stats_counts_by_severity_and_state(self) -> None:
        self.reg.workhub.create_task(title="b1", agent="orch", kind="bug",
                                       severity="P0", bug_state="closed")
        self.reg.workhub.create_task(title="b2", agent="orch", kind="bug",
                                       severity="P1", bug_state="open")
        self.reg.workhub.create_task(title="b3", agent="orch", kind="bug",
                                       severity="P1", bug_state="escalated")
        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.bug_stats["total_bugs"], 3)
        self.assertEqual(stats.bug_stats["by_severity"]["P0"], 1)
        self.assertEqual(stats.bug_stats["by_severity"]["P1"], 2)
        self.assertEqual(stats.bug_stats["closed"], 1)
        self.assertEqual(stats.bug_stats["escalated"], 1)

    def test_run_stats_counts_passes_and_failures(self) -> None:
        r1 = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r1["id"], "completed", agent="r", fail_count=0)
        r2 = self.reg.runhub.record_run(branch="y", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r2["id"], "failed", agent="r", fail_count=3)
        r3 = self.reg.runhub.record_run(branch="z", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r3["id"], "completed", agent="r", fail_count=0)
        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.run_stats["total_runs"], 3)
        self.assertEqual(stats.run_stats["passed"], 2)
        self.assertEqual(stats.run_stats["failed"], 1)
        self.assertAlmostEqual(stats.run_stats["failure_rate"], 1 / 3, places=3)

    def test_review_stats_counts_prs_and_force_merges(self) -> None:
        # Wire 2 PRs; one normal merge, one force_merge audit entry
        task = self.reg.workhub.create_task(title="t", agent="backend", kind="feature")
        pr1 = self.reg.codehub.open_pull_request(
            branch="agent/backend", target="main", title="t1", author="backend",
            reviewers=["frontend", "orchestrator"], linked_tasks=[task["id"]])
        pr2 = self.reg.codehub.open_pull_request(
            branch="agent/backend2", target="main", title="t2", author="backend",
            reviewers=["frontend", "orchestrator"], linked_tasks=[task["id"]])
        # Tag pr2 as force-merged by stamping metadata directly (force_merge would do this in real flow)
        p2_full = self.reg.codehub.stores.pull_requests.get(pr2["id"])
        p2_full["force_merged"] = True
        self.reg.codehub.stores.pull_requests.update(
            lambda m: m.set(pr2["id"], p2_full, "orchestrator"),
            change_info={"agent": "orchestrator"})

        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.review_stats["total_prs"], 2)
        self.assertEqual(stats.review_stats["force_merged"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_retro_aggregator -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the aggregator**

Create `agent/env_generator/llm_generator/multi_agent/runtime/retro_aggregator.py`:

```python
"""Retro stats aggregator (Cutover 16). Pure read-side over HubRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RetroStats:
    bug_stats: Dict[str, Any] = field(default_factory=dict)
    run_stats: Dict[str, Any] = field(default_factory=dict)
    review_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bug_stats": dict(self.bug_stats),
            "run_stats": dict(self.run_stats),
            "review_stats": dict(self.review_stats),
        }


def _bug_stats(workhub) -> Dict[str, Any]:
    if workhub is None or not hasattr(workhub, "stores"):
        return {"total_bugs": 0, "by_severity": {}, "closed": 0, "escalated": 0}
    bugs = [t for t in (workhub.stores.tasks.value() or {}).values()
            if (t.get("metadata") or {}).get("kind") == "bug"]
    by_sev: Dict[str, int] = {}
    closed = 0
    escalated = 0
    for b in bugs:
        meta = b.get("metadata") or {}
        sev = meta.get("severity", "P3")
        by_sev[sev] = by_sev.get(sev, 0) + 1
        state = meta.get("bug_state", "")
        if state == "closed":
            closed += 1
        elif state == "escalated":
            escalated += 1
    return {
        "total_bugs": len(bugs),
        "by_severity": by_sev,
        "closed": closed,
        "escalated": escalated,
    }


def _run_stats(runhub) -> Dict[str, Any]:
    if runhub is None or not hasattr(runhub, "list_runs"):
        return {"total_runs": 0, "passed": 0, "failed": 0, "failure_rate": 0.0}
    runs = runhub.list_runs(limit=1000)
    total = len(runs)
    passed = sum(1 for r in runs if r.get("status") == "completed"
                  and r.get("fail_count", 0) == 0)
    failed = sum(1 for r in runs if r.get("status") == "failed"
                  or r.get("fail_count", 0) > 0)
    return {
        "total_runs": total, "passed": passed, "failed": failed,
        "failure_rate": (failed / total) if total else 0.0,
    }


def _review_stats(codehub) -> Dict[str, Any]:
    if codehub is None or not hasattr(codehub, "stores"):
        return {"total_prs": 0, "force_merged": 0}
    prs = list((codehub.stores.pull_requests.value() or {}).values())
    force_merged = sum(1 for p in prs if p.get("force_merged"))
    return {"total_prs": len(prs), "force_merged": force_merged}


def compute_retro_stats(hub_registry) -> RetroStats:
    return RetroStats(
        bug_stats=_bug_stats(getattr(hub_registry, "workhub", None)),
        run_stats=_run_stats(getattr(hub_registry, "runhub", None)),
        review_stats=_review_stats(getattr(hub_registry, "codehub", None)),
    )


__all__ = ["RetroStats", "compute_retro_stats"]
```

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_retro_aggregator -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 620 OK (616 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/retro_aggregator.py agent/tests/test_retro_aggregator.py
git commit -m "Add retro_aggregator: pure RetroStats from WorkHub bugs + RunHub runs + CodeHub PRs"
```

---

## Task 4: Retro LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/retro_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Create: `agent/tests/test_retro_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_retro_tools.py`:

```python
"""Tests for retro LLM tools (Cutover 16)."""

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


_PVR = [
    {"plan_item": "ship feed by EOD", "actual_outcome": "shipped morning of next day",
     "drift_reason": "schema gate fired late"},
    {"plan_item": "0 force-merges", "actual_outcome": "1 force-merge on auth PR",
     "drift_reason": "blocker on review queue"},
]
_LESSONS = ["catch schema drift earlier", "preview reviewer queue saturation"]
_PROMPT_CHANGES = [{"agent_profile": "design",
                     "change_description": "publish schema spec immediately when design moves to under_review"}]


class RetroToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_tool(self, cls, **kwargs):
        from tools import retro_tools as rt
        instance = cls(hub_registry=self.reg, generation_id=1000.0, **kwargs)
        return instance

    def test_submit_retro_with_required_fields_succeeds(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="generation 2026-05-24 retro",
            plan_vs_reality=_PVR, systematic_failures=["queue saturation"],
            lessons=_LESSONS, proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(result.success, f"failed: {result.error_message}")
        self.assertIn("id", result.data)
        retro = self.reg.workhub.get_latest_retro_for_generation(1000.0)
        self.assertIsNotNone(retro)
        self.assertEqual(retro["kind"], "retro")

    def test_submit_retro_rejects_under_2_plan_vs_reality(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR[:1],
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertFalse(result.success)

    def test_submit_retro_rejects_under_2_lessons(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=["only one"],
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertFalse(result.success)

    def test_submit_retro_rejects_empty_proposed_prompt_changes(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=[]))
        self.assertFalse(result.success)

    def test_submit_retro_accepts_empty_systematic_failures(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        tool = self._make_tool(SubmitRetroTool)
        result = _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_retro_auto_populates_aggregated_stats(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        self.reg.workhub.create_task(title="b1", agent="orch", kind="bug",
                                       severity="P1", bug_state="closed")
        tool = self._make_tool(SubmitRetroTool)
        _run_async(tool.execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        retro = self.reg.workhub.get_latest_retro_for_generation(1000.0)
        meta = retro["metadata"]
        self.assertIn("bug_stats", meta)
        self.assertEqual(meta["bug_stats"]["total_bugs"], 1)
        self.assertIn("run_stats", meta)
        self.assertIn("review_stats", meta)

    def test_list_retros_returns_retros(self) -> None:
        from tools.retro_tools import SubmitRetroTool, ListRetrosTool
        _run_async(self._make_tool(SubmitRetroTool).execute(
            title="r", plan_vs_reality=_PVR,
            systematic_failures=[], lessons=_LESSONS,
            proposed_prompt_changes=_PROMPT_CHANGES))
        list_tool = self._make_tool(ListRetrosTool)
        result = _run_async(list_tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["retros"]), 1)

    def test_get_retro_stats_returns_aggregated_stats(self) -> None:
        from tools.retro_tools import GetRetroStatsTool
        self.reg.workhub.create_task(title="b", agent="orch", kind="bug",
                                       severity="P0", bug_state="open")
        tool = self._make_tool(GetRetroStatsTool)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["bug_stats"]["total_bugs"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_retro_tools -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the tools**

Create `agent/env_generator/llm_generator/tools/retro_tools.py`. Match `BaseTool` convention (the same as knowledge tools / structured_knowledge tools from Cutover 15 — `BaseTool` from `utils.tool`, `async def execute`, `create_tool_param`):

```python
"""Retro LLM tools (Cutover 16).

Three tools used by orchestrator at end of generation:
- submit_retro: validates structured fields, auto-populates aggregated stats,
                stamps generation_id from session
- list_retros: list retros (optionally filtered by generation_id)
- get_retro_stats: aggregated bug/run/review stats (no LLM input needed)

Note: these tools take an explicit `hub_registry` + `generation_id` in their
constructor for tests; in production the orchestrator's tool wiring supplies
both. SubmitRetroTool and ListRetrosTool reuse the existing WorkHub page surface
for persistence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.retro_aggregator import compute_retro_stats


def _validate_list_min(value: Any, name: str, min_len: int) -> Optional[str]:
    if not isinstance(value, list) or len(value) < min_len:
        return f"{name} must be a list of length >= {min_len}"
    return None


def _validate_pvr(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "plan_vs_reality", 2)
    if err:
        return err
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"plan_vs_reality[{i}] must be a dict"
        for k in ("plan_item", "actual_outcome", "drift_reason"):
            v = item.get(k)
            if not isinstance(v, str) or not v.strip():
                return f"plan_vs_reality[{i}].{k} must be a non-empty string"
    return None


def _validate_lessons(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "lessons", 2)
    if err:
        return err
    for i, v in enumerate(items):
        if not isinstance(v, str) or not v.strip():
            return f"lessons[{i}] must be a non-empty string"
    return None


def _validate_prompt_changes(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "proposed_prompt_changes", 1)
    if err:
        return err
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"proposed_prompt_changes[{i}] must be a dict"
        for k in ("agent_profile", "change_description"):
            v = item.get(k)
            if not isinstance(v, str) or not v.strip():
                return f"proposed_prompt_changes[{i}].{k} must be a non-empty string"
    return None


class _RetroToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, generation_id=None):
        super().__init__(name=self.NAME, category=ToolCategory.MEMORY)
        self.hub_registry = hub_registry
        self.generation_id = generation_id


class SubmitRetroTool(_RetroToolBase):
    NAME = "submit_retro"
    DESCRIPTION = ("Submit a generation retro. Required: plan_vs_reality (>=2 entries "
                    "with plan_item/actual_outcome/drift_reason), systematic_failures "
                    "(may be empty list if truly none), lessons (>=2), "
                    "proposed_prompt_changes (>=1 with agent_profile/change_description). "
                    "bug_stats / run_stats / review_stats are auto-populated.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            properties={
                "title": {"type": "string"},
                "plan_vs_reality": {"type": "array", "items": {"type": "object"}},
                "systematic_failures": {"type": "array", "items": {"type": "string"},
                                         "default": []},
                "lessons": {"type": "array", "items": {"type": "string"}},
                "proposed_prompt_changes": {"type": "array",
                                              "items": {"type": "object"}},
            },
            required=["title", "plan_vs_reality", "systematic_failures",
                       "lessons", "proposed_prompt_changes"],
        )

    async def execute(self, *, title: str, plan_vs_reality: list,
                       systematic_failures: list, lessons: list,
                       proposed_prompt_changes: list) -> ToolResult:
        if not isinstance(title, str) or not title.strip():
            return ToolResult(success=False, error_message="title must be non-empty")
        err = _validate_pvr(plan_vs_reality) \
            or _validate_lessons(lessons) \
            or _validate_prompt_changes(proposed_prompt_changes)
        if err:
            return ToolResult(success=False, error_message=err)
        if not isinstance(systematic_failures, list):
            return ToolResult(success=False,
                              error_message="systematic_failures must be a list")

        stats = compute_retro_stats(self.hub_registry)
        metadata = {
            "generation_id": self.generation_id,
            "plan_vs_reality": plan_vs_reality,
            "systematic_failures": systematic_failures,
            "lessons": lessons,
            "proposed_prompt_changes": proposed_prompt_changes,
            **stats.to_dict(),
        }
        page = self.hub_registry.workhub.create_page(
            title=title, agent="orchestrator", kind="retro", metadata=metadata)
        return ToolResult(success=True, data={"id": page["id"], "title": page["title"]})


class ListRetrosTool(_RetroToolBase):
    NAME = "list_retros"
    DESCRIPTION = "List all retros on WorkHub (kind='retro')."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            properties={}, required=[])

    async def execute(self) -> ToolResult:
        retros = self.hub_registry.workhub.list_retros()
        return ToolResult(success=True, data={"retros": [
            {"id": r["id"], "title": r["title"],
             "generation_id": (r.get("metadata") or {}).get("generation_id")}
            for r in retros
        ]})


class GetRetroStatsTool(_RetroToolBase):
    NAME = "get_retro_stats"
    DESCRIPTION = ("Compute aggregated bug/run/review stats across hubs. "
                    "Use this before writing your retro to inform the analysis.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            properties={}, required=[])

    async def execute(self) -> ToolResult:
        stats = compute_retro_stats(self.hub_registry)
        return ToolResult(success=True, data=stats.to_dict())


_RETRO_TOOLS = [SubmitRetroTool, ListRetrosTool, GetRetroStatsTool]


def create_retro_tools(hub_registry=None, generation_id=None) -> list:
    return [cls(hub_registry=hub_registry, generation_id=generation_id)
            for cls in _RETRO_TOOLS]


__all__ = ["SubmitRetroTool", "ListRetrosTool", "GetRetroStatsTool",
            "create_retro_tools"]
```

- [ ] **Step 4: Register the bundle**

In `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`, mirror existing patterns:

```python
from tools.retro_tools import create_retro_tools
import time as _time

def _bundle_retro_tools(builder, context) -> None:
    # generation_id defaults to context start time; production orchestrator
    # supplies its own session start.
    gen_id = getattr(context, "generation_id", None) or _time.time()
    builder.add(
        create_retro_tools(hub_registry=context.hub_workspace, generation_id=gen_id),
        "memory",
    )

# TOOL_BUNDLE_REGISTRY:
"retro_tools": _bundle_retro_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"retro_tools": {"memory"},
```

- [ ] **Step 5: Verify 8 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_retro_tools -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 8 OK; 7 OK / 628 OK (620 + 8 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/tools/retro_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/tests/test_retro_tools.py
git commit -m "Add retro_tools: submit_retro / list_retros / get_retro_stats (validated, auto-stats)"
```

---

## Task 5: `deliver_project` retro gate

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`
- Create: `agent/tests/test_deliver_retro_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliver_retro_gate.py`:

```python
"""Tests that DeliverProjectTool refuses without retro for this generation (Cutover 16)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


def _make_agent(reg, gen_id=1000.0):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.workspace_path = "/tmp/fake"
    return a


class DeliverProjectRetroGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliver_gate_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deliver_refuses_without_retro(self) -> None:
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_make_agent(self.reg))
        result = _run_async(tool.execute(
            confirmation="CONFIRMED",
            delivery_summary="all done",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertFalse(result.success)
        self.assertIn("retro", result.error_message.lower())

    def test_deliver_succeeds_with_retro_for_this_generation(self) -> None:
        from tools.agent_interaction_tools import DeliverProjectTool
        # Insert a retro for generation_id=1000.0
        self.reg.workhub.create_page(
            title="retro", agent="orchestrator", kind="retro",
            metadata={"generation_id": 1000.0,
                       "plan_vs_reality": [], "lessons": [],
                       "proposed_prompt_changes": []})
        tool = DeliverProjectTool(agent=_make_agent(self.reg, gen_id=1000.0))
        result = _run_async(tool.execute(
            confirmation="CONFIRMED",
            delivery_summary="all done",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_refuses_with_retro_for_different_generation(self) -> None:
        from tools.agent_interaction_tools import DeliverProjectTool
        # Retro exists, but for a different generation_id
        self.reg.workhub.create_page(
            title="old retro", agent="orchestrator", kind="retro",
            metadata={"generation_id": 999.0})
        tool = DeliverProjectTool(agent=_make_agent(self.reg, gen_id=1000.0))
        result = _run_async(tool.execute(
            confirmation="CONFIRMED",
            delivery_summary="all done",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_retro_gate -v 2>&1 | tail -10
```

Expected: failures — gate not implemented.

- [ ] **Step 3: Add the gate to `DeliverProjectTool.execute`**

In `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`, locate `DeliverProjectTool.execute` (or whichever method handles delivery). At the very top of the method body, BEFORE other checks, add:

```python
        # Cutover 16: retro must exist for this generation
        try:
            registry = getattr(self.agent, "hub_registry", None)
            gen_id = getattr(self.agent, "_session_start_ts", None)
            if registry is not None and gen_id is not None and hasattr(registry, "workhub"):
                retro = registry.workhub.get_latest_retro_for_generation(gen_id)
                if retro is None:
                    return ToolResult(success=False,
                                       error_message=("retro for this generation not found — "
                                                       "you must submit_retro before deliver_project"))
        except Exception:
            # Gate is non-fatal in malformed contexts (defense in depth)
            pass
```

If the existing `execute` returns a different shape (string, dict), wrap accordingly to match the surrounding code's return convention. Inspect the surrounding method first.

- [ ] **Step 4: Verify 3 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_retro_gate -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 631 OK (628 + 3 new). If pre-existing deliver_project tests break, update them to set `_session_start_ts` AND insert a retro (or set the agent.hub_registry to None to bypass the gate path, depending on the existing tests' shape).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/agent_interaction_tools.py agent/tests/test_deliver_retro_gate.py
# include any deliver_project fixture updates
git commit -m "DeliverProjectTool: retro pre-flight — refuse if no retro for this generation_id"
```

---

## Task 6: Orchestrator prompt update

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_retro_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_retro_prompt.py`:

```python
"""Tests that orchestrator prompt teaches retro discipline (Cutover 16)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorRetroPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break

    def test_prompt_mentions_submit_retro(self) -> None:
        self.assertIn("SUBMIT_RETRO", self.system.upper())

    def test_prompt_warns_deliver_blocked_without_retro(self) -> None:
        upper = self.system.upper()
        self.assertIn("RETRO", upper)
        self.assertTrue(
            any(p in upper for p in ("BEFORE DELIVER", "BEFORE CALLING DELIVER",
                                       "PREREQUISITE", "GATE")),
            "prompt must indicate retro is a prerequisite for deliver_project",
        )

    def test_prompt_mentions_required_retro_fields(self) -> None:
        upper = self.system.upper()
        self.assertIn("PLAN_VS_REALITY", upper)
        self.assertIn("LESSONS", upper)
        self.assertIn("PROPOSED_PROMPT_CHANGES", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_retro_prompt -v 2>&1 | tail -10
```

- [ ] **Step 3: Add the block to `lead_specifics`**

In `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`, append to `lead_specifics()`:

```jinja
### RETRO DISCIPLINE (Cutover 16)
Before you call `deliver_project()`, you MUST call `submit_retro(...)`. CodeHub gates delivery: without a retro tagged with this session's generation_id, `deliver_project()` returns an error.

The retro is not paperwork. It's the only mechanism that captures lessons from this generation that future generations can act on.

Workflow:
1. Call `get_retro_stats()` to see aggregated bug/run/review counts across hubs
2. Compare against the original plan — where did reality drift?
3. Submit:
   `submit_retro(title="<descriptive title>",
                  plan_vs_reality=[{plan_item, actual_outcome, drift_reason}, ...] >=2,
                  systematic_failures=[...] (may be empty list),
                  lessons=[...] >=2,
                  proposed_prompt_changes=[{agent_profile, change_description}, ...] >=1)`
4. Then call `deliver_project(...)`.

A retro with empty `proposed_prompt_changes` is REJECTED — there is always at least one improvement to suggest. If the generation went perfectly, suggest a hardening / scale-up change instead of leaving the field blank.
```

- [ ] **Step 4: Verify 3 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_retro_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 634 OK (631 + 3 new).

- [ ] **Step 5: Wire `retro_tools` to orchestrator profile**

In `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`, find `orchestrator:` profile and add `retro_tools` to its `tool_bundles` list (after `eventhub_tools` or similar).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_orchestrator_retro_prompt.py
git commit -m "Orchestrator: RETRO DISCIPLINE + wire retro_tools bundle"
```

---

## Task 7: End-to-end test

**Files:**
- Create: `agent/tests/test_retro_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_retro_e2e.py`:

```python
"""End-to-end retro flow (Cutover 16)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


_PVR = [
    {"plan_item": "p1", "actual_outcome": "a1", "drift_reason": "d1"},
    {"plan_item": "p2", "actual_outcome": "a2", "drift_reason": "d2"},
]
_LESSONS = ["l1", "l2"]
_PROMPT_CHANGES = [{"agent_profile": "design", "change_description": "x"}]


class RetroE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_e2e_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _agent(self, gen_id=2000.0):
        a = MagicMock()
        a.hub_registry = self.reg
        a._session_start_ts = gen_id
        a.workspace_path = "/tmp/x"
        return a

    def test_full_flow_submit_then_deliver(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        from tools.agent_interaction_tools import DeliverProjectTool

        # Step 1: agent submits retro for gen 2000.0
        rt = SubmitRetroTool(hub_registry=self.reg, generation_id=2000.0)
        r1 = _run_async(rt.execute(
            title="retro-gen-2000",
            plan_vs_reality=_PVR, systematic_failures=[],
            lessons=_LESSONS, proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(r1.success)

        # Step 2: deliver_project succeeds
        dt = DeliverProjectTool(agent=self._agent(2000.0))
        r2 = _run_async(dt.execute(
            confirmation="CONFIRMED",
            delivery_summary="done",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_attempting_deliver_without_retro_then_submit_then_succeed(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        from tools.agent_interaction_tools import DeliverProjectTool

        agent = self._agent(3000.0)
        dt = DeliverProjectTool(agent=agent)

        # No retro yet -> refused
        r1 = _run_async(dt.execute(
            confirmation="CONFIRMED",
            delivery_summary="d",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertFalse(r1.success)

        # Submit retro -> now deliver succeeds
        rt = SubmitRetroTool(hub_registry=self.reg, generation_id=3000.0)
        _run_async(rt.execute(
            title="r", plan_vs_reality=_PVR, systematic_failures=[],
            lessons=_LESSONS, proposed_prompt_changes=_PROMPT_CHANGES))
        r2 = _run_async(DeliverProjectTool(agent=agent).execute(
            confirmation="CONFIRMED",
            delivery_summary="d",
            checklist={"tests": "pass", "docker": "ok",
                        "requirements": "met", "ux": "ready"}))
        self.assertTrue(r2.success)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_retro_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 2 OK; 7 OK / 636 OK (634 + 2 new).

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_retro_e2e.py
git commit -m "Add e2e: retro must precede deliver_project; gate blocks then unblocks"
```

---

## Task 8: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/17-retro-stage.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 636 OK.

- [ ] **Step 2: Zero Claude trailers** + write migration log per template

- [ ] **Step 3: Commit + push**

```bash
git add docs/superpowers/migration-logs/17-retro-stage.md
git commit -m "Add Cutover 16 migration log"
git push red-env-gen haibotong-cutover-16-retro 2>&1 | tail -5
```

- [ ] **Step 4: Report** baselines / SHA / trailer count / compare URL

---

## Self-Review

**1. Spec coverage:** WorkHub retro helpers (T2) ✓; pure aggregator (T3) ✓; retro LLM tools (T4) ✓; deliver_project gate (T5) ✓; orchestrator prompt (T6) ✓; E2E (T7) ✓; log + push (T8) ✓.

**2. Placeholder scan:** No "TBD" / unfilled code blocks.

**3. Type consistency:** `RetroStats`/`compute_retro_stats` signatures consistent across module + tools + tests. `generation_id` always a float (epoch). Validation messages contain the field name asserted in tests. Retro page schema (`metadata.generation_id`, `metadata.plan_vs_reality`, etc.) consistent across tool + workhub helpers + delivery gate + prompt.

**4. Cross-cutting:** No Claude trailer (T1/T8) ✓; baselines green per task ✓; TDD throughout ✓; reuses existing WorkHub pages (no new entity store) ✓; deliver_project gate wrapped in try/except so malformed agent contexts don't break delivery ✓.
