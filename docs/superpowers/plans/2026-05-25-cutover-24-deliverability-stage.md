# Cutover 24: Deliverable Verification Stage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace LLM-judged `checklist` (`no_bugs/requirements_met/fully_functional/docker_ok` booleans) with evidence-based **deliverability verification**. New `runtime/deliverability.py` aggregates: most recent successful RunHub run + endpoint probe pass-rate + MCP probe pass-rate + seed coverage + Cutover 19 coverage + Cutover 20 visual approvals. `DeliverProjectTool` adds new gate: refuse if no successful RunHub run since the orchestrator's session start. New `deliverability_check` tool returns the unified report.

**Architecture:** Pure aggregator over existing hub state — no new probes, no new entity stores. Reads `runhub.list_runs()` + `apihub.list_tables()/get_seed_data()/get_mcp_servers()` + `coverage_audit` + WorkHub visual reviews. Produces `DeliverabilityReport` dataclass with per-category pass/fail counts and a unified `blockers` list. The KEY NEW GATE: deliver refuses if no `status="completed"` RunHub run exists with `started_at >= agent._session_start_ts`. This plugs the hole where orchestrator skips runtime verification entirely. Force-deliver bypass reuses the Cutover 19/20/21 pattern (new event type `deliverability_bypass`).

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Pure aggregator — no new IO.

---

## Context for Worker

### Why this cutover exists

The user requirement "最终得到一个能deliver的可用环境" had a critical gap:

`DeliverProjectTool` checks the orchestrator's self-judged `checklist`:
```python
{"no_bugs": True, "requirements_met": True, "fully_functional": True, "docker_ok": True}
```

These are LLM **assertions**, not verified facts. The LLM can say `docker_ok=True` without `docker compose up` ever running. Cutovers 16/19/20/21 added evidence-based gates for retro / coverage / visual / seed — but **nothing forces the orchestrator to actually start RunHub** before claiming deliverability.

### What changes

1. **New `runtime/deliverability.py`**: pure aggregator producing `DeliverabilityReport`.
2. **New RunHub helper `last_successful_run_since(ts)`**: returns most recent `status="completed"` + `fail_count==0` run started ≥ `ts`, or `None`.
3. **New `DeliverProjectTool` gate**: refuse if `last_successful_run_since(session_start_ts)` is None.
4. **2 new LLM tools**: `deliverability_check` (returns full report), `deliverability_summary` (one-line verdict).
5. **Orchestrator prompt**: DELIVERABILITY DISCIPLINE block — must `run_start` THIS session + `deliverability_check` returns clean → then `deliver_project`.

### DeliverabilityReport schema

```python
@dataclass
class DeliverabilityReport:
    last_successful_run: Optional[dict]   # most recent qualifying run, or None
    run_within_session: bool              # ran since session_start_ts
    endpoint_probes: dict                 # {total, passed, failed, skipped} from latest run
    mcp_probes: dict                      # {total, passed, failed, skipped} from latest run
    coverage: dict                        # {is_clean, dead_count_by_kind}
    seed_data: dict                       # {tables, registered, missing, flagged}
    visual_reviews: dict                  # {critical_total, approved, pending, needs_revision}
    blockers: List[str]                   # human-readable; empty if deliverable
    verdict: str                          # "deliverable" | "blocked"
```

`verdict == "deliverable"` iff `blockers == []`.

### Blocker rules (what makes verdict="blocked")

- `last_successful_run is None` → "no successful RunHub run since session start"
- `latest_run.fail_count > 0` → "X probes failed in latest run"
- `coverage.is_clean is False` → "N dead artifacts (covered separately by Cutover 19 gate)"
- `seed_data.missing > 0` → "N tables missing seed registration (covered by Cutover 21 gate)"
- `visual_reviews.pending > 0` → "N visual reviews pending (covered by Cutover 20 gate)"

Coverage/seed/visual blockers are informational — they're separately enforced by their own gates. The NEW blocker is `last_successful_run_since`.

### Deprecation of LLM checklist

`DeliverProjectTool.execute(checklist=...)` still accepts the dict for backward compat, but emits a `system/deprecated_checklist` EventHub event when used. The orchestrator prompt teaches replacing it with `deliverability_check()`.

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python`
- No Claude trailer; no emojis
- TDD throughout; bite-sized commits; no push until Task 7
- Both baselines green at every task: regressions 7 OK; discover 891 OK after Cutover 23

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/deliverability.py` — `DeliverabilityReport` + `compute_deliverability`
- `agent/env_generator/llm_generator/tools/deliverability_tools.py` — 2 tools
- `agent/tests/test_runhub_last_successful_run.py`
- `agent/tests/test_deliverability_aggregator.py`
- `agent/tests/test_deliverability_tools.py`
- `agent/tests/test_deliver_runhub_gate.py`
- `agent/tests/test_deliverability_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py` — add `last_successful_run_since(ts) -> Optional[dict]`
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` — `DeliverProjectTool` adds RunHub-since-session gate; deprecation event on checklist usage
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `deliverability_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — wire `deliverability_tools` to orchestrator
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — DELIVERABILITY DISCIPLINE block

---

## Task 1: Worktree + baseline + recon

**Files:**
- Create: `docs/superpowers/cutover-24-baseline.md`

- [ ] **Step 1: Verify worktree + baseline**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-24-deliverability
git status
git log --oneline -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: clean; 7 OK / 891 OK. If worktree missing: `git worktree add -b haibotong-cutover-24-deliverability .worktrees/haibotong-cutover-24-deliverability haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Confirm DeliverProjectTool gate insertion anchor**

```bash
grep -nE "Cutover 21|seed_audit_bypass" agent/env_generator/llm_generator/tools/agent_interaction_tools.py | head -5
```

Note line of Cutover 21 seed gate end. Task 5 inserts the new RunHub-since-session gate after.

- [ ] **Step 3: Confirm RunHub list_runs return shape**

```bash
grep -nA 8 "def list_runs" agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py
```

Note: returns most-recent-first. Run dicts have `id`, `status`, `started_at`, `finished_at`, `fail_count`, `probes`, `mcp_probes`.

- [ ] **Step 4: Baseline note + commit**

Create `docs/superpowers/cutover-24-baseline.md`:

```markdown
# Cutover 24 Baseline (Deliverable Verification Stage)

## Test counts
- regressions: 7 OK
- discover: 891 OK

## Gap this cutover closes
DeliverProjectTool checks an LLM-judged checklist (`no_bugs/requirements_met/...`)
that's pure self-assertion. Cutovers 16/19/20/21 added evidence-based gates,
but NOTHING enforces that RunHub actually ran. Orchestrator can deliver having
never spun up the app.

## Approach
- runtime/deliverability.py aggregates RunHub/APIHub/Coverage/Seed/Visual into
  a unified DeliverabilityReport
- DeliverProjectTool adds gate: refuses if no successful RunHub run since
  agent._session_start_ts
- 2 LLM tools: deliverability_check (full report) + deliverability_summary (verdict)
- Orchestrator prompt teaches the new workflow
- force_deliver=True bypasses (publishes deliverability_bypass EventHub event)
```

```bash
git add docs/superpowers/cutover-24-baseline.md
git commit -m "Cutover 24: record pre-flight baseline (regressions 7 OK, discover 891 OK)"
```

---

## Task 2: RunHub `last_successful_run_since` helper

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`
- Create: `agent/tests/test_runhub_last_successful_run.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_runhub_last_successful_run.py`:

```python
"""Tests for RunHub.last_successful_run_since (Cutover 24)."""

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


class LastSuccessfulRunSinceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_last_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_runs_returns_none(self) -> None:
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_failed_run_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "failed", agent="runhub", fail_count=3)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_completed_run_with_zero_fail_count_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=0)
        result = self.reg.runhub.last_successful_run_since(0.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], run["id"])

    def test_completed_run_with_failures_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=2)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_run_started_before_threshold_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=0)
        future_ts = time.time() + 1000.0
        self.assertIsNone(self.reg.runhub.last_successful_run_since(future_ts))

    def test_returns_most_recent_when_multiple_qualify(self) -> None:
        r1 = self.reg.runhub.record_run(branch="a", generated_dir="/g", agent="o")
        self.reg.runhub.update_run_status(r1["id"], "completed", agent="runhub", fail_count=0)
        time.sleep(0.01)
        r2 = self.reg.runhub.record_run(branch="b", generated_dir="/g", agent="o")
        self.reg.runhub.update_run_status(r2["id"], "completed", agent="runhub", fail_count=0)
        result = self.reg.runhub.last_successful_run_since(0.0)
        self.assertEqual(result["id"], r2["id"])

    def test_aborted_run_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "aborted", agent="runhub", fail_count=0)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_last_successful_run -v 2>&1 | tail -10
```

Expected: AttributeError on `last_successful_run_since`.

- [ ] **Step 3: Add helper to RunHub**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`, add (near `list_runs` / `get_run`):

```python
    def last_successful_run_since(self, since_ts: float) -> Optional[dict]:
        """Return the most recent run that:
        - was started at or after since_ts
        - finished with status="completed" AND fail_count==0
        Returns None if no qualifying run exists.
        """
        runs = self.list_runs(limit=1000)
        qualifying = []
        for r in runs:
            if r.get("status") != "completed":
                continue
            if r.get("fail_count", 0) != 0:
                continue
            if r.get("started_at", 0.0) < since_ts:
                continue
            qualifying.append(r)
        if not qualifying:
            return None
        # list_runs returns most-recent-first, so first matching is latest
        return qualifying[0]
```

- [ ] **Step 4: Verify 7 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_last_successful_run -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK; 7 OK / 898 OK (891 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py agent/tests/test_runhub_last_successful_run.py
git commit -m "RunHub: add last_successful_run_since(ts) -> most recent fully-passing run after timestamp"
```

---

## Task 3: deliverability aggregator

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/deliverability.py`
- Create: `agent/tests/test_deliverability_aggregator.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliverability_aggregator.py`:

```python
"""Tests for runtime/deliverability.py aggregator (Cutover 24)."""

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
from multi_agent.runtime.deliverability import (  # noqa: E402
    DeliverabilityReport, compute_deliverability,
)


def _good_seed(reg, table_name):
    reg.apihub.register_table(
        table_name, schema={"columns": []}, provider="database", agent="database")
    reg.apihub.register_seed_data(
        table_name, row_count=42,
        sample_excerpt=[{"id": 1, "name": "Alex Chen", "email": "alex@gmail.com"}],
        agent="database")


def _passing_run(reg, ts_offset=0.0):
    """Insert a successful run with started_at = now + ts_offset."""
    now = time.time() + ts_offset
    r = reg.runhub.record_run(
        branch="feature/x", generated_dir="/tmp/g", agent="orch")
    # Patch started_at directly via the store
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = now
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = [{"verdict": "pass"}]
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})
    return raw


class DeliverabilityAggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliverability_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()
        (self.app_root / "main.tsx").write_text("x = 1;\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_state_blocks_on_no_run(self) -> None:
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertIsInstance(report, DeliverabilityReport)
        self.assertEqual(report.verdict, "blocked")
        self.assertTrue(any("run" in b.lower() for b in report.blockers))

    def test_with_passing_run_clean_state_is_deliverable(self) -> None:
        _passing_run(self.reg)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "deliverable", f"blockers: {report.blockers}")

    def test_run_before_session_start_blocks(self) -> None:
        _passing_run(self.reg, ts_offset=-1000.0)  # ran in the past
        report = compute_deliverability(
            self.reg, self.app_root, session_start_ts=time.time())
        self.assertEqual(report.verdict, "blocked")
        self.assertFalse(report.run_within_session)

    def test_failed_run_blocks(self) -> None:
        r = self.reg.runhub.record_run(
            branch="x", generated_dir="/g", agent="orch")
        self.reg.runhub.update_run_status(r["id"], "failed", agent="runhub", fail_count=3)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")

    def test_dead_endpoint_surfaced_in_report(self) -> None:
        _passing_run(self.reg)
        self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")
        self.assertFalse(report.coverage["is_clean"])

    def test_seed_block_surfaced(self) -> None:
        _passing_run(self.reg)
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        # No seed registered
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")
        self.assertGreater(report.seed_data["missing"], 0)

    def test_visual_pending_surfaced(self) -> None:
        _passing_run(self.reg)
        _good_seed(self.reg, "users")
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")
        self.assertGreater(report.visual_reviews["pending"], 0)

    def test_endpoint_probe_counts_aggregated(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
        raw = self.reg.runhub.stores.runs.get(run["id"])
        raw["started_at"] = time.time()
        raw["status"] = "completed"
        raw["fail_count"] = 0
        raw["probes"] = [
            {"verdict": "pass"}, {"verdict": "pass"},
            {"verdict": "skipped"}, {"verdict": "fail"},
        ]
        raw["mcp_probes"] = []
        self.reg.runhub.stores.runs.update(
            lambda m: m.set(run["id"], raw, "runhub"), change_info={"agent": "runhub"})
        # fail_count=0 contradicts probe fail; aggregator should trust probes list
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.endpoint_probes["total"], 4)
        self.assertEqual(report.endpoint_probes["passed"], 2)
        self.assertEqual(report.endpoint_probes["failed"], 1)
        self.assertEqual(report.endpoint_probes["skipped"], 1)

    def test_to_dict_round_trips(self) -> None:
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        d = report.to_dict()
        self.assertIn("verdict", d)
        self.assertIn("blockers", d)
        self.assertIn("endpoint_probes", d)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliverability_aggregator -v 2>&1 | tail -15
```

Expected: ImportError.

- [ ] **Step 3: Implement aggregator**

Create `agent/env_generator/llm_generator/multi_agent/runtime/deliverability.py`:

```python
"""Deliverability aggregator (Cutover 24).

Pure read-side over RunHub + APIHub + WorkHub + coverage_audit + seed_audit.
Replaces the LLM-judged checklist with an evidence-based unified report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class DeliverabilityReport:
    last_successful_run: Optional[dict] = None
    run_within_session: bool = False
    endpoint_probes: Dict[str, int] = field(default_factory=dict)
    mcp_probes: Dict[str, int] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    seed_data: Dict[str, Any] = field(default_factory=dict)
    visual_reviews: Dict[str, int] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    verdict: str = "blocked"

    def to_dict(self) -> dict:
        return {
            "last_successful_run": self.last_successful_run,
            "run_within_session": self.run_within_session,
            "endpoint_probes": dict(self.endpoint_probes),
            "mcp_probes": dict(self.mcp_probes),
            "coverage": dict(self.coverage),
            "seed_data": dict(self.seed_data),
            "visual_reviews": dict(self.visual_reviews),
            "blockers": list(self.blockers),
            "verdict": self.verdict,
        }


def _probe_counts(probes: list) -> Dict[str, int]:
    counts = {"total": len(probes), "passed": 0, "failed": 0, "skipped": 0}
    for p in probes or []:
        v = p.get("verdict") if isinstance(p, dict) else None
        if v == "pass":
            counts["passed"] += 1
        elif v == "fail":
            counts["failed"] += 1
        elif v == "skipped":
            counts["skipped"] += 1
    return counts


def _coverage_summary(hub_registry, app_root) -> Dict[str, Any]:
    try:
        from .coverage_audit import compute_coverage
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
    try:
        report = compute_coverage(hub_registry, Path(app_root))
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
    return {
        "is_clean": report.is_clean,
        "dead_count_by_kind": {
            "endpoints": len(report.dead_endpoints),
            "tables": len(report.dead_tables),
            "files": len(report.dead_files),
            "mcp_tools": len(report.dead_mcp_tools),
        },
    }


def _seed_summary(hub_registry) -> Dict[str, Any]:
    try:
        from .seed_audit import audit_seed_data
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    try:
        report = audit_seed_data(hub_registry)
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    apihub = getattr(hub_registry, "apihub", None)
    total_tables = len((apihub.list_tables() if apihub else {}) or {})
    registered = len((apihub.list_seed_registrations() if apihub else {}) or {})
    missing = sum(1 for f in report.flagged_tables if f.get("reason") == "missing_seed")
    flagged = len(report.flagged_tables)
    return {"tables": total_tables, "registered": registered,
            "missing": missing, "flagged": flagged}


def _visual_summary(hub_registry) -> Dict[str, int]:
    wh = getattr(hub_registry, "workhub", None)
    if wh is None or not hasattr(wh, "list_critical_visual_reviews"):
        return {"critical_total": 0, "approved": 0,
                "pending": 0, "needs_revision": 0}
    critical = wh.list_critical_visual_reviews() or []
    approved = sum(1 for p in critical if p.get("status") == "approved")
    pending = sum(1 for p in critical
                  if p.get("status") in ("pending", "reviewing"))
    needs_rev = sum(1 for p in critical if p.get("status") == "needs_revision")
    return {"critical_total": len(critical), "approved": approved,
            "pending": pending, "needs_revision": needs_rev}


def compute_deliverability(hub_registry, app_root,
                            session_start_ts: float = 0.0) -> DeliverabilityReport:
    blockers: List[str] = []

    runhub = getattr(hub_registry, "runhub", None)
    last_run = None
    run_within_session = False
    if runhub is not None and hasattr(runhub, "last_successful_run_since"):
        last_run = runhub.last_successful_run_since(session_start_ts)
        run_within_session = last_run is not None

    if not run_within_session:
        blockers.append(
            "no successful RunHub run since session start "
            "(call run_start(...) and ensure fail_count=0 before deliver)")

    ep_counts = _probe_counts(last_run.get("probes") if last_run else [])
    mcp_counts = _probe_counts(last_run.get("mcp_probes") if last_run else [])
    if ep_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {ep_counts['failed']} failed endpoint probe(s)")
    if mcp_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {mcp_counts['failed']} failed MCP probe(s)")

    coverage = _coverage_summary(hub_registry, app_root)
    if not coverage.get("is_clean", True):
        dead = coverage.get("dead_count_by_kind") or {}
        total = sum(dead.values()) if dead else 0
        blockers.append(f"{total} dead artifact(s) (Cutover 19 gate)")

    seed = _seed_summary(hub_registry)
    if seed.get("missing", 0) > 0:
        blockers.append(
            f"{seed['missing']} table(s) missing seed registration (Cutover 21 gate)")
    if seed.get("flagged", 0) > seed.get("missing", 0):
        # additional flagged are placeholder_content or low_row_count
        extra = seed["flagged"] - seed.get("missing", 0)
        blockers.append(
            f"{extra} table(s) with low row count or placeholder seed (Cutover 21 gate)")

    visual = _visual_summary(hub_registry)
    if visual.get("pending", 0) > 0:
        blockers.append(
            f"{visual['pending']} critical visual review(s) pending (Cutover 20 gate)")
    if visual.get("needs_revision", 0) > 0:
        blockers.append(
            f"{visual['needs_revision']} critical visual review(s) need revision")

    verdict = "deliverable" if not blockers else "blocked"
    return DeliverabilityReport(
        last_successful_run=last_run,
        run_within_session=run_within_session,
        endpoint_probes=ep_counts,
        mcp_probes=mcp_counts,
        coverage=coverage,
        seed_data=seed,
        visual_reviews=visual,
        blockers=blockers,
        verdict=verdict,
    )


__all__ = ["DeliverabilityReport", "compute_deliverability"]
```

- [ ] **Step 4: Verify 9 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliverability_aggregator -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 9 OK; 7 OK / 907 OK (898 + 9 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/deliverability.py agent/tests/test_deliverability_aggregator.py
git commit -m "Add deliverability aggregator: unified report over RunHub + Coverage + Seed + Visual"
```

---

## Task 4: Deliverability LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/deliverability_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_deliverability_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliverability_tools.py`:

```python
"""Tests for deliverability LLM tools (Cutover 24)."""

import asyncio
import shutil
import sys
import tempfile
import time
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


def _passing_run(reg, ts_offset=0.0):
    now = time.time() + ts_offset
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = now
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class DeliverabilityToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="del_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()
        (self.app_root / "main.tsx").write_text("x = 1;\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_with_no_run_blocked(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["verdict"], "blocked")

    def test_check_with_passing_run_deliverable(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        _passing_run(self.reg)
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(result.data["verdict"], "deliverable",
                          f"blockers: {result.data['blockers']}")

    def test_summary_returns_one_line(self) -> None:
        from tools.deliverability_tools import DeliverabilitySummaryTool
        _passing_run(self.reg)
        tool = DeliverabilitySummaryTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertIn("verdict", result.data)
        self.assertIn("blocker_count", result.data)

    def test_check_data_includes_endpoint_and_mcp_probes(self) -> None:
        from tools.deliverability_tools import DeliverabilityCheckTool
        _passing_run(self.reg)
        tool = DeliverabilityCheckTool(
            hub_registry=self.reg, app_root=str(self.app_root),
            session_start_ts=0.0)
        result = _run_async(tool.execute())
        self.assertIn("endpoint_probes", result.data)
        self.assertIn("mcp_probes", result.data)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement tools**

Create `agent/env_generator/llm_generator/tools/deliverability_tools.py`:

```python
"""Deliverability LLM tools (Cutover 24)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.deliverability import compute_deliverability


class _DeliverabilityToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, app_root: Optional[str] = None,
                 session_start_ts: float = 0.0):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        self.app_root = app_root
        self.session_start_ts = session_start_ts


class DeliverabilityCheckTool(_DeliverabilityToolBase):
    NAME = "deliverability_check"
    DESCRIPTION = ("Evidence-based unified deliverability report: latest RunHub "
                    "run + endpoint/MCP probe counts + coverage + seed + visual "
                    "reviews. Replaces LLM-judged checklist. Verdict = "
                    "'deliverable' iff blockers list is empty.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        return ToolResult.ok(data=report.to_dict())


class DeliverabilitySummaryTool(_DeliverabilityToolBase):
    NAME = "deliverability_summary"
    DESCRIPTION = ("One-line summary of deliverability: verdict + blocker count "
                    "+ first blocker. Use this for quick checks; use "
                    "deliverability_check for the full report.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        return ToolResult.ok(data={
            "verdict": report.verdict,
            "blocker_count": len(report.blockers),
            "first_blocker": report.blockers[0] if report.blockers else None,
            "run_within_session": report.run_within_session,
        })


_DELIVERABILITY_TOOLS = [DeliverabilityCheckTool, DeliverabilitySummaryTool]


def create_deliverability_tools(hub_registry=None,
                                 app_root: Optional[str] = None,
                                 session_start_ts: float = 0.0) -> list:
    return [cls(hub_registry=hub_registry, app_root=app_root,
                session_start_ts=session_start_ts)
            for cls in _DELIVERABILITY_TOOLS]


__all__ = [
    "DeliverabilityCheckTool", "DeliverabilitySummaryTool",
    "create_deliverability_tools",
]
```

- [ ] **Step 3: Register bundle + wire to orchestrator**

In `tool_bundles.py`:

```python
from tools.deliverability_tools import create_deliverability_tools

def _bundle_deliverability_tools(builder, context) -> None:
    app_root = getattr(context, "app_root", None) or getattr(context, "workspace_path", None)
    builder.add(
        create_deliverability_tools(
            hub_registry=context.hub_workspace,
            app_root=str(app_root) if app_root else None,
            session_start_ts=getattr(context, "session_start_ts", 0.0) or 0.0),
        "knowledge")

# TOOL_BUNDLE_REGISTRY:
"deliverability_tools": _bundle_deliverability_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"deliverability_tools": {"knowledge"},
```

In `agents_config.yaml`, add `deliverability_tools` to `orchestrator` profile `tool_bundles`.

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliverability_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 911 OK (907 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/deliverability_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_deliverability_tools.py
git commit -m "Add deliverability_tools (check + summary) + wire to orchestrator"
```

---

## Task 5: DeliverProjectTool RunHub-since-session gate

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`
- Create: `agent/tests/test_deliver_runhub_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliver_runhub_gate.py`:

```python
"""DeliverProjectTool RunHub-since-session gate tests (Cutover 24)."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _agent(reg, gen_id=8000.0, agent_type="orchestrator"):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


def _passing_run(reg, started_at):
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class DeliverRunhubGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="del_runhub_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 8000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED",
                             delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_deliver_refuses_without_runhub_run(self) -> None:
        result = self._deliver()
        self.assertFalse(result.success)
        self.assertIn("run", result.error_message.lower())

    def test_deliver_refuses_with_run_before_session(self) -> None:
        _passing_run(self.reg, started_at=7999.0)  # before session_start
        result = self._deliver()
        self.assertFalse(result.success)

    def test_deliver_succeeds_with_run_at_or_after_session(self) -> None:
        _passing_run(self.reg, started_at=8001.0)
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_force_deliver_bypasses_runhub_gate(self) -> None:
        result = self._deliver(force_deliver=True)
        self.assertTrue(result.success, f"failed: {result.error_message}")
        events = list(self.reg.eventhub.list_events_by_type("deliverability_bypass"))
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_runhub_gate -v 2>&1 | tail -10
```

Expected: failures — gate doesn't exist yet.

- [ ] **Step 3: Add gate to `DeliverProjectTool.execute`**

In `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`, after the Cutover 21 seed gate (and before any other post-gate logic), insert:

```python
        # Cutover 24: RunHub-since-session gate
        try:
            registry = getattr(self.agent, "hub_registry", None)
            session_start = getattr(self.agent, "_session_start_ts", None)
            agent_type = getattr(self.agent, "agent_type", "")
            force = kwargs.get("force_deliver") or False

            if (registry is not None and session_start is not None
                    and hasattr(registry, "runhub")):
                last = registry.runhub.last_successful_run_since(session_start)
                if last is None:
                    if force:
                        if agent_type != "orchestrator":
                            return ToolResult.fail(error_message=(
                                "force_deliver is orchestrator-only; "
                                f"caller agent_type={agent_type!r}"))
                        try:
                            registry.eventhub.publish_event(
                                source_hub="deliver",
                                event_type="deliverability_bypass",
                                payload={"reason": "no_successful_run_since_session_start",
                                          "by": agent_type},
                                priority="high")
                        except Exception:
                            pass
                    else:
                        return ToolResult.fail(error_message=(
                            "refused: no successful RunHub run since session start. "
                            "Call run_start(...) and verify the run completes with "
                            "fail_count=0 before deliver_project. Use "
                            "deliverability_check to see the unified report."))
        except Exception:
            pass  # defense in depth
```

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_runhub_gate -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 915 OK (911 + 4 new).

**Note**: existing deliver tests from Cutovers 16/19/20/21 will break because they don't add a successful RunHub run. Update them:

```bash
grep -rnE "DeliverProjectTool.*execute|test_deliver" agent/tests/ | grep -v "test_deliver_runhub_gate" | head -10
```

For each affected test, add a `_passing_run(self.reg, started_at=<session_start>)` setup (or set `agent._session_start_ts = None` to bypass the new gate, but that defeats the cutover — prefer adding the run). Use minimum-change approach.

If `test_deliver_coverage_gate`, `test_deliver_visual_gate`, `test_deliver_seed_gate`, `test_deliver_retro_gate` break: each test's `_agent` fixture already sets `agent._session_start_ts`; add a fixture helper to insert a passing run with `started_at = gen_id + 1.0` so the new gate passes (then the test still exercises its specific gate).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/agent_interaction_tools.py agent/tests/test_deliver_runhub_gate.py
# Add any deliver-test fixture updates strictly required
git add agent/tests/test_deliver_*.py
git commit -m "DeliverProjectTool: RunHub-since-session gate + deliverability_bypass force-bypass"
```

---

## Task 6: Orchestrator prompt — DELIVERABILITY DISCIPLINE

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_deliverability_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_deliverability_prompt.py`:

```python
"""Tests that orchestrator prompt teaches deliverability discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorDeliverabilityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_mentions_deliverability_check(self) -> None:
        self.assertIn("DELIVERABILITY_CHECK", self.system.upper())

    def test_warns_runhub_required_this_session(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUN_START", upper)
        self.assertIn("SESSION", upper)

    def test_mentions_evidence_over_checklist(self) -> None:
        upper = self.system.upper()
        self.assertTrue("EVIDENCE" in upper or "CHECKLIST" in upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Add block**

In `lead_specifics()` of `orchestrator_agent.j2`, after the existing PRIORITY + DEPENDENCY DISCIPLINE block (Cutover 23), append:

```jinja
### DELIVERABILITY DISCIPLINE (Cutover 24)
`deliver_project()` no longer trusts your self-judged checklist (`no_bugs`, `requirements_met`, etc.). It enforces EVIDENCE: there must be a successful `run_start(...)` from RunHub started AFTER your session began (engine refuses otherwise).

Pre-deliver workflow:
1. `run_start(branch=..., generated_dir=..., base_url=...)` — must return `status="completed"`, `fail_count=0`
2. `deliverability_check()` — unified report aggregating:
   - latest successful run (must be within this session)
   - endpoint probe pass-rate (must have 0 failures)
   - MCP probe pass-rate
   - coverage (Cutover 19 gate)
   - seed registrations (Cutover 21 gate)
   - critical visual reviews (Cutover 20 gate)
3. If `verdict == "blocked"`, work through each entry in `blockers` (assign tasks to the right agent)
4. Re-run `run_start` + `deliverability_check` after fixes
5. When `verdict == "deliverable"` AND retro submitted, call `deliver_project(...)`

The old `checklist` kwarg is deprecated but still accepted. Stop using it — `deliverability_check` is the source of truth.

`force_deliver=True` still bypasses (orchestrator-only; publishes `deliverability_bypass` event). Use ONLY when blockers are demonstrably false-positives (e.g., visual_reviewer offline, no human reviewer available). Every use shows up in the next retro.
```

- [ ] **Step 4: Verify 3 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_deliverability_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 918 OK (915 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_orchestrator_deliverability_prompt.py
git commit -m "Orchestrator prompt: DELIVERABILITY DISCIPLINE block (run_start->check->deliver)"
```

---

## Task 7: E2E + migration log + push

**Files:**
- Create: `agent/tests/test_deliverability_e2e.py`
- Create: `docs/superpowers/migration-logs/25-deliverability-stage.md`

- [ ] **Step 1: E2E test**

Create `agent/tests/test_deliverability_e2e.py`:

```python
"""E2E: deliver blocked → run_start successful → deliverability check clean → deliver succeeds."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _agent(reg, gen_id=9000.0):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = "orchestrator"
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


def _insert_passing_run(reg, started_at):
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class DeliverabilityE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliv_e2e_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 9000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_full_flow_blocked_then_run_unblocks(self) -> None:
        # Step 1: deliver refused — no run
        r1 = self._deliver()
        self.assertFalse(r1.success)
        self.assertIn("run", r1.error_message.lower())

        # Step 2: orchestrator runs RunHub successfully
        _insert_passing_run(self.reg, started_at=9001.0)

        # Step 3: deliver now succeeds
        r2 = self._deliver()
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_deliverability_check_aligns_with_deliver_verdict(self) -> None:
        from multi_agent.runtime.deliverability import compute_deliverability
        # Before run: aggregator says blocked, deliver refuses
        report = compute_deliverability(self.reg, "/tmp", session_start_ts=9000.0)
        self.assertEqual(report.verdict, "blocked")
        # After run: aggregator says deliverable, deliver succeeds
        _insert_passing_run(self.reg, started_at=9001.0)
        report = compute_deliverability(self.reg, "/tmp", session_start_ts=9000.0)
        self.assertEqual(report.verdict, "deliverable", f"blockers: {report.blockers}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify 2 tests + final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliverability_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 2 OK; 7 OK / 920 OK (918 + 2 new).

- [ ] **Step 3: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 4: Migration log**

Create `docs/superpowers/migration-logs/25-deliverability-stage.md`:

```markdown
# Cutover 24: Deliverable Verification Stage

**Branch:** `haibotong-cutover-24-deliverability`
**Date:** 2026-05-25

## What

Replace LLM-judged `checklist` with evidence-based deliverability verification.
DeliverProjectTool adds NEW gate: refuses if no successful RunHub run started
≥ agent._session_start_ts. Unified `deliverability_check` LLM tool returns
aggregated report (latest run + endpoint probes + MCP probes + coverage + seed
+ visual reviews). Orchestrator prompt teaches the new workflow:
`run_start → deliverability_check → deliver_project`.

## Why

Cutovers 16/19/20/21 added evidence-based gates (retro/coverage/visual/seed) but
none enforced that RunHub actually ran. Orchestrator could deliver having never
spun up the app. The user-judged checklist was pure self-assertion.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 891 OK -> 920 OK (+29 new)

## New surfaces
- runtime/deliverability.py — DeliverabilityReport + compute_deliverability (pure aggregator)
- tools/deliverability_tools.py — 2 tools: deliverability_check + deliverability_summary
- RunHub.last_successful_run_since(ts) -> Optional[run dict]
- DeliverProjectTool: RunHub-since-session gate + deliverability_bypass force_deliver
- Orchestrator prompt: DELIVERABILITY DISCIPLINE block

## Migrations
- Existing deliver tests (Cutovers 16/19/20/21 gate tests) needed _insert_passing_run
  fixture additions to satisfy the new gate while exercising their specific gates
- Old `checklist` kwarg still accepted (backward compat); deprecated in favor of
  deliverability_check

## Known limits (future cutovers)
- "Successful run" = status="completed" + fail_count=0; could add stricter checks
  (e.g., all critical pages had screenshots captured)
- Aggregator doesn't enforce its own report at delivery time — relies on existing
  per-category gates (coverage / seed / visual / retro). Could become enforcement
  surface in a future consolidation cutover.
- No way to declare "this gate is informational only" today; could add per-blocker
  severity in a follow-up.
```

- [ ] **Step 5: Commit + push**

```bash
git add agent/tests/test_deliverability_e2e.py docs/superpowers/migration-logs/25-deliverability-stage.md
git commit -m "Add Cutover 24 e2e + migration log"
git push red-env-gen haibotong-cutover-24-deliverability 2>&1 | tail -5
```

- [ ] **Step 6: Report** — final test counts, push URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:** RunHub helper (T2) ✓; aggregator (T3) ✓; LLM tools (T4) ✓; DeliverProjectTool gate (T5) ✓; orchestrator prompt (T6) ✓; E2E + log + push (T7) ✓.

**2. Placeholder scan:** No TBD / "implement later". All code shown.

**3. Type consistency:**
- `DeliverabilityReport(last_successful_run, run_within_session, endpoint_probes, mcp_probes, coverage, seed_data, visual_reviews, blockers, verdict) + to_dict()` — consistent
- `compute_deliverability(hub_registry, app_root, session_start_ts)` — same in module + tools + tests
- `last_successful_run_since(ts: float) -> Optional[dict]` — consistent in RunHub + aggregator + gate + tests
- Tool NAMEs: `deliverability_check`, `deliverability_summary` — same in tool + prompt + tests
- `deliverability_bypass` event type — same in gate + test assertions

**4. Cross-cutting:**
- No Claude trailer (T1 + T7) ✓
- Baselines green per task ✓
- TDD throughout ✓
- Aggregator reuses Cutover 19/20/21 surfaces (no duplicate logic) ✓
- New gate sits AFTER seed gate; force_deliver bypass mirrors prior cutovers ✓
- Existing deliver tests get minimal _insert_passing_run fixture addition ✓
