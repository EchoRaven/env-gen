# Cutover 12: Runtime Feedback Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the chain `RunHub publishes run_failed` → `BugTriageOrchestrator receives` → `BugTriageOrch creates remediation task on WorkHub` → `owning agent sees the bug in its hub_pulse`. Today (post-Cutover-11) the events are PUBLISHED but no agent is SUBSCRIBED — so they land in the events store but nobody's inbox. This cutover adds **default subscriptions per agent profile** + an **end-to-end integration test** proving the loop closes without LLM involvement.

**Architecture:** Subscriptions are declarative. A new `runtime/agent_subscriptions.py` module defines `DEFAULT_SUBSCRIPTIONS: dict[agent_profile, list[(source_hub, event_type, priority_floor)]]`. A helper `ensure_default_subscriptions(hubs, agent_id)` registers them via `EventHub.subscribe` (naturally idempotent — sub_id is `f"{agent}:{source_hub}:{event_type}"`). The helper runs at the top of `collect_hub_pulse` so every step refreshes subscriptions (no-op after the first one). For Cutover 12 the only profile getting new defaults is `bug_triage_orchestrator` (subscribes to `verifier/bug_found` + `runhub/run_failed` + `runhub/run_completed`), but the structure is general so future profiles (Cutover 13+) can declare theirs the same way. Plus a hard-evidence integration test: build a HubRegistry → register an APIHub endpoint → call `runhub.start_run` with a fake probe returning 500 → assert the bug_triage_orchestrator's inbox now contains the run_failed event → call BugTriage tool → assert backend's `hub_pulse` shows the new assigned bug.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Existing surfaces: `EventHub.subscribe / get_subscriptions / get_inbox` (Cutover 5), `RunHub.start_run` (Cutover 11), `BugTriageOrch` + `bug_triage` resolver + `bug_tools` (Cutover 10).

---

## Context for Worker

### Why this cutover exists

Cutover 11 wired `RunHub` to publish `runhub/run_failed` events on probe failures. The events ARE persisted to `eventhub_events.json`, but the only delivery mechanism is **inbox fan-out via subscriptions**. No agent is currently subscribed to `runhub/run_failed`, so `BugTriageOrchestrator`'s inbox never sees them. Verifier publishes `verifier/bug_found` (Cutover 10 Task 8) — same problem.

**Without this cutover, the new Bug Triage workflow only works for bugs Verifier MANUALLY routes — defeating the whole single-responsibility separation the advisor recommended.**

Cutover 12 fixes this by declaratively registering the default subscriptions and proving end-to-end with an integration test that doesn't need an LLM.

### The subscription model

`EventHub.subscribe(agent, source_hub="*", event_type="*", priority_floor="low", delivery="live")` upserts a subscription keyed by `f"{agent}:{source_hub}:{event_type}"`. Calling it again with the same triple overwrites the same row — naturally idempotent. The `publish_event` fan-out reads all subscriptions and adds matching agents as event recipients (which puts the event in their inbox).

### Subscription registry shape

```python
# runtime/agent_subscriptions.py
DEFAULT_SUBSCRIPTIONS: dict[str, list[tuple[str, str, str]]] = {
    "bug_triage_orchestrator": [
        ("verifier", "bug_found", "low"),
        ("runhub",   "run_failed", "low"),
        ("runhub",   "run_completed", "normal"),  # only high-priority completions reach
    ],
    # Future cutovers can add more profiles here.
}
```

Each tuple: `(source_hub, event_type, priority_floor)`. `priority_floor` defaults to `"low"` (everything reaches) but can be `"normal"` or `"high"` to filter noisy event streams.

### `ensure_default_subscriptions` placement

Inside `collect_hub_pulse` at line 1 (before any hub collection). Reasons:
- Every agent calls it every step → subscription always present
- Idempotent → no cost after first call
- Centralized → no new lifecycle hook needed (no agent-spawn handler exists today)
- Side-effect-tolerant → wrap in try/except so a subscription failure can't break the pulse

### End-to-end integration test (Task 4)

This is the cutover's load-bearing test. It exercises the FULL chain without spinning up an LLM:

```python
# 1. Setup
reg = HubRegistry(tmp)
reg.apihub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")

# 2. Trigger hub_pulse for bug_triage_orchestrator (registers subscriptions)
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse
collect_hub_pulse(reg, "bug_triage_orchestrator")

# 3. RunHub probes the endpoint and gets 500 -> publishes run_failed
fake_probe = lambda plan: {"status_code": 500, "body_excerpt": "boom",
                             "transport_error": None, "latency_ms": 10}
fake_compose = _FakeCompose()
fake_hc = _FakeHealthyHC()
run = reg.runhub.start_run(branch="feature/x", generated_dir="/tmp/gen",
                            base_url="http://localhost:8000", agent="orch",
                            compose=fake_compose, healthcheck=fake_hc,
                            probe_runner=fake_probe)
assert run["status"] == "failed"
assert run["fail_count"] == 1

# 4. Verify the event reached BugTriageOrch's inbox (via subscription fan-out)
inbox = reg.eventhub.get_inbox("bug_triage_orchestrator") or {"items": {}}
matching = [iid for iid, item in inbox.get("items", {}).items()
             if reg.eventhub.get_event(iid).get("event_type") == "run_failed"]
assert len(matching) == 1

# 5. Simulate BugTriageOrch triaging (resolver + tool path)
from multi_agent.runtime.bug_triage import resolve_owning_agent
event = reg.eventhub.get_event(matching[0])
# BugTriage creates the WorkHub bug task from the event payload
bug_task = reg.workhub.create_task(
    title=event["payload"]["title"], assignee="backend",
    agent="bug_triage_orchestrator",
    kind="bug", severity="P1", bug_state="assigned",
    source="runhub", bug_artifacts=event["payload"]["bug_artifacts"],
)

# 6. Assert backend's hub_pulse now shows the assigned bug
report = collect_hub_pulse(reg, "backend")
assigned = report["assigned_bugs"]
assert len(assigned) == 1
assert assigned[0]["title"] == event["payload"]["title"]
```

This test is the **canonical proof** that the architecture works without LLMs. If it ever fails after a future cutover, the loop is broken.

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (`dt` conda env)
- No Claude trailers on commits
- No emojis in code or prompts
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 7
- Both baselines green at every task boundary: `python agent/tests/run_regressions.py` (currently 7 OK) and `python -m unittest discover agent/tests -p 'test_*.py'` (currently 491 OK after Cutover 11)
- Worktree path: `worktrees/<agent_id>`; default git branch: `master`

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/agent_subscriptions.py` — `DEFAULT_SUBSCRIPTIONS` + `ensure_default_subscriptions(hubs, agent_id)`
- `agent/tests/test_agent_subscriptions.py`
- `agent/tests/test_runtime_feedback_loop_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py` — call `ensure_default_subscriptions` at top of `collect_hub_pulse`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2` — add `runhub/run_failed` as a source
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — note that BugOrch auto-picks up RunHub failures (no manual hand-off needed)

---

## Task 1: Worktree setup + baseline

**Files:**
- Create: `docs/superpowers/cutover-12-baseline.md`

- [ ] **Step 1: Verify worktree on correct branch**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-12-feedback-loop
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-12-feedback-loop`, branched from `haibotong-0521-pipeline-web-tools` at the post-Cutover-11 SHA. (If missing: `git worktree add -b haibotong-cutover-12-feedback-loop .worktrees/haibotong-cutover-12-feedback-loop haibotong-0521-pipeline-web-tools` from repo root.)

- [ ] **Step 2: Run baseline regression suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

Expected: `7 tests, OK`.

- [ ] **Step 3: Run baseline discover suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 491 tests` + `OK`.

- [ ] **Step 4: Confirm no agent is currently subscribed to run_failed**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys; sys.path.insert(0, 'agent/env_generator/llm_generator')
import tempfile; from pathlib import Path
from multi_agent.runtime.hub_registry import HubRegistry
reg = HubRegistry(Path(tempfile.mkdtemp()))
subs = reg.eventhub.get_subscriptions()
print('subs at fresh registry:', subs)
"
```

Expected: empty list. This confirms the gap that Cutover 12 closes.

- [ ] **Step 5: Write baseline note**

Create `docs/superpowers/cutover-12-baseline.md`:

```markdown
# Cutover 12 Baseline (Runtime Feedback Loop)

## Test counts
- regressions: 7 OK
- discover: 491 OK

## Gap this cutover closes
At a fresh HubRegistry, `eventhub.get_subscriptions()` returns []. Verifier and RunHub
publish bug events into the events store, but with no subscriber the events never
reach the BugTriageOrchestrator's inbox. This cutover registers default subscriptions
per agent profile and proves end-to-end with an integration test.

## Approach
- new module runtime/agent_subscriptions.py with DEFAULT_SUBSCRIPTIONS table
- hub_pulse calls ensure_default_subscriptions(hubs, agent_id) at top — idempotent
- end-to-end integration test exercises full chain without LLM
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/cutover-12-baseline.md
git commit -m "Cutover 12: record pre-flight baseline (regressions 7 OK, discover 491 OK)"
```

Verify no Claude trailer.

---

## Task 2: `agent_subscriptions` module

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/agent_subscriptions.py`
- Create: `agent/tests/test_agent_subscriptions.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_agent_subscriptions.py`:

```python
"""Tests for runtime/agent_subscriptions.py (Cutover 12)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS,
    ensure_default_subscriptions,
)


class DefaultSubscriptionsTableTests(unittest.TestCase):
    def test_bug_triage_orchestrator_subscribes_to_verifier_bug_found(self) -> None:
        subs = DEFAULT_SUBSCRIPTIONS.get("bug_triage_orchestrator", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("verifier", "bug_found"), triples)

    def test_bug_triage_orchestrator_subscribes_to_runhub_run_failed(self) -> None:
        subs = DEFAULT_SUBSCRIPTIONS.get("bug_triage_orchestrator", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("runhub", "run_failed"), triples)

    def test_bug_triage_orchestrator_subscribes_to_runhub_run_completed(self) -> None:
        subs = DEFAULT_SUBSCRIPTIONS.get("bug_triage_orchestrator", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("runhub", "run_completed"), triples)


class EnsureDefaultSubscriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="subs_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_agent_is_noop(self) -> None:
        ensure_default_subscriptions(self.reg, "no_such_agent_profile")
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])

    def test_bug_triage_orchestrator_registers_three_subscriptions(self) -> None:
        ensure_default_subscriptions(self.reg, "bug_triage_orchestrator")
        subs = self.reg.eventhub.get_subscriptions("bug_triage_orchestrator")
        triples = {(s["source_hub"], s["event_type"]) for s in subs}
        self.assertEqual(triples, {
            ("verifier", "bug_found"),
            ("runhub", "run_failed"),
            ("runhub", "run_completed"),
        })

    def test_idempotent_repeated_calls_dont_duplicate(self) -> None:
        for _ in range(5):
            ensure_default_subscriptions(self.reg, "bug_triage_orchestrator")
        subs = self.reg.eventhub.get_subscriptions("bug_triage_orchestrator")
        self.assertEqual(len(subs), 3)

    def test_swallowed_exception_does_not_propagate(self) -> None:
        # Pass a hubs surrogate without eventhub; should not raise.
        class _Fake:
            pass
        ensure_default_subscriptions(_Fake(), "bug_triage_orchestrator")  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_agent_subscriptions -v 2>&1 | tail -10
```

Expected: ImportError on `multi_agent.runtime.agent_subscriptions`.

- [ ] **Step 3: Implement the module**

Create `agent/env_generator/llm_generator/multi_agent/runtime/agent_subscriptions.py`:

```python
"""Default EventHub subscriptions per agent profile (Cutover 12).

`ensure_default_subscriptions(hubs, agent_id)` is called at the top of
`collect_hub_pulse` to install (idempotently) the subscriptions an agent
needs to receive cross-hub events. EventHub.subscribe is keyed by
`(agent, source_hub, event_type)` so calling this every step is cheap.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# (source_hub, event_type, priority_floor)
DEFAULT_SUBSCRIPTIONS: Dict[str, List[Tuple[str, str, str]]] = {
    "bug_triage_orchestrator": [
        ("verifier", "bug_found", "low"),
        ("runhub", "run_failed", "low"),
        ("runhub", "run_completed", "normal"),
    ],
}


def ensure_default_subscriptions(hubs, agent_id: str) -> None:
    """Idempotently register the agent's default subscriptions.

    Wrapped in try/except so a subscription failure can never break the
    pulse. EventHub.subscribe is idempotent by (agent, source, type).
    """
    subs = DEFAULT_SUBSCRIPTIONS.get(agent_id)
    if not subs:
        return
    eventhub = getattr(hubs, "eventhub", None)
    if eventhub is None or not hasattr(eventhub, "subscribe"):
        return
    for source_hub, event_type, priority_floor in subs:
        try:
            eventhub.subscribe(
                agent=agent_id,
                source_hub=source_hub,
                event_type=event_type,
                priority_floor=priority_floor,
                delivery="live",
            )
        except Exception:
            # never let a subscription failure break the caller
            pass


__all__ = ["DEFAULT_SUBSCRIPTIONS", "ensure_default_subscriptions"]
```

- [ ] **Step 4: Verify the 7 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_agent_subscriptions -v 2>&1 | tail -15
```

Expected: 7 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 498 OK (491 + 7 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/agent_subscriptions.py agent/tests/test_agent_subscriptions.py
git commit -m "Add agent_subscriptions: DEFAULT_SUBSCRIPTIONS + ensure_default_subscriptions (idempotent)"
```

---

## Task 3: Wire `ensure_default_subscriptions` into `hub_pulse`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`
- Create: `agent/tests/test_hub_pulse_installs_subscriptions.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_hub_pulse_installs_subscriptions.py`:

```python
"""Tests that collect_hub_pulse installs default subscriptions on every call."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402


class HubPulseInstallsSubscriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_subs_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pulse_for_bug_triage_orch_installs_subscriptions(self) -> None:
        # Before pulse: no subs
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])
        collect_hub_pulse(self.reg, "bug_triage_orchestrator")
        subs = self.reg.eventhub.get_subscriptions("bug_triage_orchestrator")
        self.assertEqual(len(subs), 3)

    def test_pulse_for_unknown_profile_does_not_install(self) -> None:
        collect_hub_pulse(self.reg, "backend")  # no defaults for backend
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])

    def test_pulse_called_repeatedly_does_not_duplicate(self) -> None:
        for _ in range(3):
            collect_hub_pulse(self.reg, "bug_triage_orchestrator")
        subs = self.reg.eventhub.get_subscriptions("bug_triage_orchestrator")
        self.assertEqual(len(subs), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_installs_subscriptions -v 2>&1 | tail -10
```

Expected: 3 failures — `get_subscriptions` returns empty after pulse because no install happens yet.

- [ ] **Step 3: Edit `hub_pulse.py`**

In `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`, at the top of `collect_hub_pulse(hubs, agent_id, step_num)`, add (BEFORE the `report = {...}` line):

```python
    # Cutover 12: install default subscriptions for this agent (idempotent).
    try:
        from ...runtime.agent_subscriptions import ensure_default_subscriptions
        ensure_default_subscriptions(hubs, agent_id)
    except Exception:
        pass  # never let subscription install break the pulse
```

If the existing import block at the top of the file uses absolute imports (`from multi_agent.runtime...`), match that style instead.

- [ ] **Step 4: Verify the 3 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_installs_subscriptions -v 2>&1 | tail -10
```

Expected: 3 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 501 OK (498 + 3 new). If any existing `hub_pulse` test breaks because subscriptions are now created where they weren't before, that's likely a fixture using bug_triage_orchestrator as the agent_id — update only what's strictly required.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py agent/tests/test_hub_pulse_installs_subscriptions.py
git commit -m "hub_pulse: install default subscriptions for agent on every pulse (idempotent)"
```

---

## Task 4: End-to-end integration test (THE load-bearing test)

This test exercises the FULL chain: RunHub probe failure → EventHub fan-out → BugTriageOrch inbox → triage tool → WorkHub bug task → owning agent's hub_pulse. No LLM needed.

**Files:**
- Create: `agent/tests/test_runtime_feedback_loop_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_runtime_feedback_loop_e2e.py`:

```python
"""End-to-end integration test for the runtime feedback loop (Cutover 12).

Proves: RunHub probe failure -> EventHub fan-out (via Cutover-12 subscriptions)
        -> BugTriageOrch inbox -> triage creates WorkHub bug task
        -> owning agent's hub_pulse shows the assigned bug.

No LLM involved. All IO mocked. This test is the canonical proof that the
post-Cutover-11 architecture closes the loop without manual intervention.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.bug_triage import resolve_owning_agent  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402


class _FakeCompose:
    def __init__(self):
        self.up_called = False
        self.down_called = False
    def up(self, timeout=180.0):
        self.up_called = True
        return ComposeResult(returncode=0, stdout="up ok")
    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _FakeHealthyHC:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.05)


def _probe_runner_returning(status_code):
    def _runner(plan):
        return {"status_code": status_code, "body_excerpt": "boom",
                "transport_error": None, "latency_ms": 10}
    return _runner


class RuntimeFeedbackLoopE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="loop_e2e_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runhub_failure_reaches_bug_triage_orchestrator_inbox(self) -> None:
        # 1. Register endpoint with backend as owner
        self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")

        # 2. Pulse for bug_triage_orchestrator -> installs subscriptions
        collect_hub_pulse(self.reg, "bug_triage_orchestrator")
        subs = self.reg.eventhub.get_subscriptions("bug_triage_orchestrator")
        self.assertEqual(len(subs), 3)

        # 3. Trigger a failing RunHub run
        run = self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(500))
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["fail_count"], 1)

        # 4. The run_failed event must be in bug_triage_orchestrator's inbox
        inbox = self.reg.eventhub.get_inbox("bug_triage_orchestrator")
        self.assertIsNotNone(inbox)
        items = inbox.get("items") or {}
        run_failed_items = []
        for event_id in items.keys():
            ev = self.reg.eventhub.get_event(event_id)
            if ev and ev.get("event_type") == "run_failed":
                run_failed_items.append(ev)
        self.assertEqual(len(run_failed_items), 1,
                          "BugTriageOrch inbox should contain exactly one run_failed event")

    def test_triage_creates_bug_task_and_backend_pulse_sees_it(self) -> None:
        # 1. Wire endpoint owned by backend
        self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")

        # 2. Install subs and trigger failure
        collect_hub_pulse(self.reg, "bug_triage_orchestrator")
        self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(500))

        # 3. BugTriageOrch reads the inbox and triages (simulating what the LLM would do)
        inbox = self.reg.eventhub.get_inbox("bug_triage_orchestrator")
        events = [self.reg.eventhub.get_event(eid)
                   for eid in (inbox.get("items") or {}).keys()]
        failure_event = next(e for e in events if e and e.get("event_type") == "run_failed")
        payload = failure_event["payload"]
        artifacts = payload["bug_artifacts"]
        owner = resolve_owning_agent(self.reg, artifacts)
        self.assertEqual(owner, "backend")

        bug = self.reg.workhub.create_task(
            title=payload["title"],
            description=f"From RunHub failure: {payload['title']}",
            assignee=owner, agent="bug_triage_orchestrator",
            kind="bug", severity=payload["severity"], bug_state="assigned",
            source="runhub", bug_artifacts=artifacts)

        # 4. Backend's pulse must now show the assigned bug
        backend_report = collect_hub_pulse(self.reg, "backend")
        assigned = backend_report.get("assigned_bugs") or []
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]["id"], bug["id"])
        self.assertEqual(assigned[0]["title"], payload["title"])

    def test_passing_run_does_not_create_inbox_noise_for_bug_orch(self) -> None:
        # When a run passes, only run_completed fires (priority=normal); run_failed must not.
        self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend", status="defined")
        collect_hub_pulse(self.reg, "bug_triage_orchestrator")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(), healthcheck=_FakeHealthyHC(),
            probe_runner=_probe_runner_returning(200))
        self.assertEqual(run["status"], "completed")
        inbox = self.reg.eventhub.get_inbox("bug_triage_orchestrator") or {"items": {}}
        types = []
        for eid in (inbox.get("items") or {}).keys():
            ev = self.reg.eventhub.get_event(eid)
            if ev:
                types.append(ev.get("event_type"))
        self.assertNotIn("run_failed", types)
        # run_completed should reach (its priority is "normal" >= the "normal" floor)
        self.assertIn("run_completed", types)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify all 3 tests pass on the existing implementation**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runtime_feedback_loop_e2e -v 2>&1 | tail -15
```

Expected: 3 OK — Tasks 2/3 already wired everything; this test EXERCISES the result rather than introducing new code.

If a test fails:
- `test_runhub_failure_reaches_bug_triage_orchestrator_inbox` failing → subscriptions aren't being installed by hub_pulse (revisit Task 3)
- `test_triage_creates_bug_task_and_backend_pulse_sees_it` failing in `resolve_owning_agent` → APIHub `provider` field isn't reaching the bug_artifacts (verify RunHub `_publish_run_failed` includes `owner_hint=ep.get("provider")` AND the resolver also reads `affected_endpoint` which is set)
- `test_passing_run_does_not_create_inbox_noise_for_bug_orch` failing → priority floor isn't being respected; check EventHub's `_PRIORITY_RANK` map

Diagnose and fix; do not weaken the test.

- [ ] **Step 3: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 504 OK (501 + 3 new).

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_runtime_feedback_loop_e2e.py
git commit -m "Add end-to-end test: RunHub failure -> BugTriageOrch inbox -> WorkHub bug -> owner pulse"
```

---

## Task 5: BugTriageOrch prompt update — mention runhub source

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2`
- Create: `agent/tests/test_bug_triage_runhub_source.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_bug_triage_runhub_source.py`:

```python
"""Tests that bug_triage_orchestrator prompt mentions runhub as a source (Cutover 12)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class BugTriageRunHubSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("bug_triage_orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.bug_triage_system_prompt()

    def test_prompt_mentions_runhub_run_failed(self) -> None:
        self.assertIn("RUN_FAILED", self.system.upper())

    def test_prompt_mentions_runhub_as_source(self) -> None:
        self.assertIn("RUNHUB", self.system.upper())

    def test_prompt_describes_runhub_artifact_shape(self) -> None:
        upper = self.system.upper()
        self.assertIn("AFFECTED_ENDPOINT", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_runhub_source -v 2>&1 | tail -10
```

Expected: 3 failures (mentions of runhub/run_failed missing).

- [ ] **Step 3: Edit the prompt**

In `agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2`, inside the `bug_triage_system_prompt()` macro, find the existing "## ROLE SPLIT" or "## HARD RULES" block. Replace the line about Verifier as the sole source with text that lists BOTH event sources:

Find the existing wording about `verifier/bug_found` events (it was added in Cutover 10 Task 7). Extend the relevant section to read:

```jinja
## EVENT SOURCES YOU SUBSCRIBE TO
- `verifier/bug_found`  - Verifier detected a contract test failure
- `runhub/run_failed`   - RunHub probed a deployed app and got 4xx/5xx/timeout (Cutover 11)
- `runhub/run_completed` - run summary (informational; only high-priority reaches you)

Both `bug_found` and `run_failed` events carry the same `bug_artifacts` shape:
  - `affected_endpoint`: "METHOD /path"  (drives owning-agent resolution)
  - `affected_files`:   list of file paths (fallback resolver hint)
  - `affected_table`:   table name (for database bugs)
  - `expected` / `actual`: contract vs observed
  - `owner_hint`:       APIHub provider for the affected endpoint
  - `run_id`, `branch`: present for runhub-sourced bugs

Resolve the owning agent via the priority order in your HARD RULES; do not assume
the source dictates the owner. A `runhub/run_failed` for a frontend-served HTML
endpoint goes to frontend, not backend.
```

(Adapt indentation / wrapping to the existing macro style.)

- [ ] **Step 4: Verify the 3 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_runhub_source -v 2>&1 | tail -10
```

Expected: 3 OK. The existing 7 Cutover-10 prompt tests should still pass — re-run the full prompt suite:

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_bug_triage_orchestrator_prompt agent.tests.test_bug_triage_runhub_source -v 2>&1 | tail -15
```

Expected: 10 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 507 OK (504 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/bug_triage_orchestrator_agent.j2 agent/tests/test_bug_triage_runhub_source.py
git commit -m "BugTriageOrch prompt: list runhub/run_failed alongside verifier/bug_found as sources"
```

---

## Task 6: Orchestrator prompt update — auto-handoff to BugOrch

The orchestrator should NOT manually triage failures after a `run_start()`. The Bug Triage Orchestrator subscribes automatically and handles them. The prompt should make that explicit.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_runhub_handoff.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_runhub_handoff.py`:

```python
"""Tests that orchestrator prompt notes BugOrch auto-picks up RunHub failures (Cutover 12)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorRunHubHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_mentions_bug_triage_orchestrator_auto_handoff(self) -> None:
        upper = self.system.upper()
        self.assertIn("BUG TRIAGE", upper)
        # Some phrasing of "auto-picks-up" / "automatically" / "subscribed"
        self.assertTrue(
            any(phrase in upper for phrase in (
                "AUTOMATICALLY", "AUTO-PICK", "AUTO PICK", "SUBSCRIBED",
                "AUTO-ROUTE", "AUTO ROUTE",
            )),
            "prompt must indicate BugOrch auto-handles RunHub failures",
        )

    def test_prompt_warns_not_to_manually_triage_run_failures(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "DO NOT" in upper or "NEVER" in upper or "MUST NOT" in upper,
            "prompt must include a 'do not' rule about manual run-failure triage",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_runhub_handoff -v 2>&1 | tail -10
```

Expected: 2 failures.

- [ ] **Step 3: Edit the orchestrator prompt**

In `lead_specifics()`, find the existing "### RUN VERIFICATION DISCIPLINE (Cutover 11 - RunHub)" block (added in Cutover 11 Task 8). Append to it (don't replace it):

```jinja
After `run_start` returns, DO NOT manually create remediation tasks for the
failures it reports. The **Bug Triage Orchestrator** (Cutover 10) is automatically
subscribed to `runhub/run_failed` events and will analyze + assign each failure
to the owning agent. Your job is to monitor (via `run_list()` / `run_get()`) and
escalate only if BugOrch is overwhelmed or repeatedly fails to resolve an owner.

Auto-handoff chain (engine-enforced):
  RunHub probe fails -> `runhub/run_failed` event -> BugOrch inbox (via subscription)
  -> BugOrch creates WorkHub bug task assigned to owner -> owner sees bug in hub_pulse.
```

- [ ] **Step 4: Verify the 2 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_runhub_handoff -v 2>&1 | tail -10
```

Expected: 2 OK. Re-run the prior orchestrator prompt suites to confirm no regressions:

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_orchestrator_prompt agent.tests.test_orchestrator_runhub_handoff -v 2>&1 | tail -15
```

Expected: 5 OK (3 from Cutover 11 + 2 new).

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 509 OK (507 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_orchestrator_runhub_handoff.py
git commit -m "Orchestrator prompt: BugTriageOrch auto-handles RunHub failures (no manual triage)"
```

---

## Task 7: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/13-runtime-feedback-loop.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 509 OK. STOP if anything fails.

- [ ] **Step 2: Verify zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Write migration log**

Create `docs/superpowers/migration-logs/13-runtime-feedback-loop.md`:

```markdown
# Cutover 12: Runtime Feedback Loop

**Branch:** `haibotong-cutover-12-feedback-loop`
**Date:** 2026-05-24

## What

Closed the chain `RunHub publishes run_failed` -> `BugTriageOrchestrator receives via
subscription` -> `BugTriageOrch creates WorkHub bug task` -> `owning agent's hub_pulse
shows the assigned bug`. Before this cutover, RunHub and Verifier published bug events
but no agent was subscribed, so they never reached anyone's inbox.

## Commits

(fill from `git log --oneline haibotong-0521-pipeline-web-tools..HEAD`)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 491 OK -> 509 OK (+18 new)

## New surfaces
- `runtime/agent_subscriptions.py` (~50 LoC) - `DEFAULT_SUBSCRIPTIONS` table + `ensure_default_subscriptions(hubs, agent_id)` helper (idempotent)
- `agent/tests/test_runtime_feedback_loop_e2e.py` - canonical end-to-end test proving the loop closes without LLM involvement

## Modified
- `hub_pulse.py` - calls `ensure_default_subscriptions` at top of every `collect_hub_pulse`
- `prompts/v2/bug_triage_orchestrator_agent.j2` - lists `runhub/run_failed` alongside `verifier/bug_found` as sources
- `prompts/v2/orchestrator_agent.j2` - orchestrator must NOT manually triage RunHub failures; BugOrch auto-handles via subscription

## Subscriptions table
`bug_triage_orchestrator` subscribes to:
- `verifier/bug_found` (priority_floor=low)
- `runhub/run_failed` (priority_floor=low)
- `runhub/run_completed` (priority_floor=normal)

Future cutovers can extend `DEFAULT_SUBSCRIPTIONS` to add per-profile defaults.

## Why subscriptions live in code (not yaml)
Subscriptions are part of agent BEHAVIOR (not config). They're declared in a single
Python dict alongside `ensure_default_subscriptions`, so the wiring is co-located
with the helper that uses it. Future profiles add an entry in two lines.
```

- [ ] **Step 4: Commit log**

```bash
git add docs/superpowers/migration-logs/13-runtime-feedback-loop.md
git commit -m "Add Cutover 12 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-12-feedback-loop 2>&1 | tail -5
```

- [ ] **Step 6: Report**

Print: final test counts, commit count, push URL, compare URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:**
- Subscription registry — Task 2 ✓
- Install in pulse — Task 3 ✓
- End-to-end test — Task 4 ✓
- BugOrch prompt mentions both sources — Task 5 ✓
- Orchestrator prompt: no manual triage of RunHub failures — Task 6 ✓
- Migration log + push — Task 7 ✓

**2. Placeholder scan:** No "TBD" / "implement later". Every code-change task has actual code shown.

**3. Type consistency:**
- `DEFAULT_SUBSCRIPTIONS: dict[str, list[tuple[str, str, str]]]` (agent_id → list of `(source_hub, event_type, priority_floor)`) — used in registry + ensure helper + tests ✓
- `ensure_default_subscriptions(hubs, agent_id)` — same signature in module + caller + tests ✓
- `EventHub.subscribe(agent=, source_hub=, event_type=, priority_floor=, delivery="live")` — kwargs match real API ✓
- bug_artifacts payload keys (`affected_endpoint`, `affected_files`, `affected_table`, `expected`, `actual`, `owner_hint`, `run_id`, `branch`) — consistent with Cutover 10/11 resolver inputs ✓

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 7 ✓
- Baselines green at every task boundary — explicit step in each task ✓
- TDD — every code-change task starts with failing test ✓
- End-to-end test is the load-bearing proof; documented as such ✓
- Idempotency: `EventHub.subscribe` key is `f"{agent}:{source_hub}:{event_type}"` (overwrites same row) — pulse can call every step without growing storage ✓
