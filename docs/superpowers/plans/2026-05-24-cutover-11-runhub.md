# Cutover 11: RunHub (Auto-Run Generated Code + HTTP Probes)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5th hub — **RunHub** — that actually executes the generated application after CodeHub merge: spins up the docker compose stack, waits for healthcheck, hits each APIHub-registered endpoint with happy-path probes, captures 4xx/5xx responses as runtime bugs, publishes `runhub/run_failed` events that the BugTriageOrchestrator (Cutover 10) picks up. Browser-based UI e2e (Playwright) is **deliberately deferred** to a future cutover — this MVP focuses on backend-side runtime smoke.

**Architecture:** RunHub mirrors the other hubs (service class + JsonStore-backed stores + EventHub publisher). Its lifecycle stores a `Run` entity per execution: id, branch, started_at, finished_at, status (running|healthy|failed|aborted), healthcheck_results, probe_results (per endpoint pass/fail with status code + latency), error_count. RunHub is invoked explicitly (`runhub.start_run(branch, generated_dir)` — usually by the main Orchestrator after a CodeHub PR merges), runs synchronously to completion (no async background tasks — the Orchestrator decides when to call), and emits a structured `run_completed` (or `run_failed`) EventHub event. Failures spawn one `runhub/run_failed` event PER failing probe, each carrying enough `bug_artifacts` for the BugTriageOrchestrator's resolver to find the owning agent.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), `subprocess` for `docker compose`, `httpx` for HTTP probes (already in env — verify with `python -c "import httpx"`; fallback to `urllib.request` if not), unittest. Existing surfaces: `JsonStore` (Cutover 9), `EventHub.publish_event` (Cutover 5), APIHub `get_endpoints()` (Cutover 4), Docker tools (`tools/docker_tools.py`).

---

## Context for Worker

### Why this cutover exists

After Cutover 10 we have a complete bug WORKFLOW (Verifier detects → BugOrch triages → owner fixes) but **no production of real runtime bugs**. Verifier only runs contract tests at design time; nothing actually starts the generated app and probes it. Real engineering has CI smoke + staging deployment that surfaces "the API contract matches, but POST /api/feed crashes with NullPointerException on real request." That whole class of bugs is invisible today.

RunHub fills this gap: it deploys the generated app to a local docker stack, runs lightweight HTTP probes, and feeds failures into the bug pipeline.

### Scope discipline

**In scope (Cutover 11):**
- New `RunHub` service class wired into `HubRegistry`
- `start_run(branch, generated_dir, timeout_s=300)` orchestrator entry point
- Docker compose lifecycle: `up -d` → poll healthcheck → `down` (always, even on failure)
- HTTP probes against every APIHub-registered endpoint with `status == "defined"` (skip undeclared endpoints — they're not part of the contract surface)
- Probe verdict: HTTP 2xx/3xx = pass; 4xx (except documented 4xx response codes in the endpoint's schema) = fail; 5xx = fail; timeout = fail; connection refused = fail
- One `runhub/run_failed` event per failing probe, with full `bug_artifacts` for BugOrch
- Run history: persisted to `JsonStore` so prior runs are inspectable
- LLM tools: `run_start`, `run_status`, `run_list`, `run_get`
- Orchestrator prompt update: must `run_start()` after merging a PR with backend changes

**Explicitly out of scope (future cutovers):**
- Playwright / browser-based UI e2e — needs separate sub-project; current MVP is backend-side only
- Performance / load testing — runs are single-shot smoke
- Production deploys — local docker only
- Auto-rollback on failure — RunHub reports; doesn't decide
- Multi-environment (staging/prod) — only "local docker" exists in this cutover
- Cross-run flake detection — single run, single verdict

### Probe semantics

For each APIHub-registered endpoint:

- **GET** without auth: probe with no body, expect 200/304/404. 4xx-without-405 is a fail; 5xx is a fail. 401/403 acceptable if endpoint has `auth_required=true` (don't try to authenticate — we're smoke-probing).
- **POST/PUT/PATCH** with auth required: skip (we don't have credentials in the probe runner); record as `skipped: auth_required`. **Not a fail.** This is a known MVP gap — annotated in the run summary.
- **POST/PUT/PATCH** without auth: probe with body = endpoint's example request body if registered on APIHub (`examples` store), otherwise empty JSON `{}`. Expect 2xx/3xx; otherwise fail. Body is best-effort — if the endpoint requires specific JSON shape we don't have, the 4xx is signal in itself.
- **DELETE**: skip in MVP (would mutate state without ability to recover). Record as `skipped: destructive`.

A failing probe produces a bug-shaped event payload:

```python
{
    "task_id": None,  # BugOrch will create the WorkHub task
    "source": "runhub",
    "severity": "P1" if 5xx else "P2",
    "title": f"{method} {path} returned {status_code}",
    "bug_artifacts": {
        "affected_endpoint": f"{method} {path}",
        "expected": "2xx",
        "actual": str(status_code),
        "response_body_excerpt": first_500_chars,
        "request_body": probe_body_json,
        "run_id": run_id,
        "branch": branch,
        "latency_ms": ms,
    },
}
```

### Run lifecycle

```
start_run() called
   │
   ▼
status="starting" -> persist Run
   │
   ▼
docker compose up -d (cwd = generated_dir)
   │
   ▼
poll healthcheck (HTTP GET to declared /health or root path)
  every 2s, timeout=60s
   │
   │ healthy?
   ▼
status="healthy" -> persist
   │
   ▼
iterate APIHub endpoints, probe each
  collect probe_results: pass/fail/skipped
   │
   ▼
For each failing probe:
   publish_event(source_hub="runhub", event_type="run_failed",
                 payload=<bug-shape>, priority="high")
   │
   ▼
status= "failed" if any fail else "healthy" -> persist
   │
   ▼
docker compose down (always, in finally)
   │
   ▼
publish_event(source_hub="runhub", event_type="run_completed",
              payload={run_id, status, summary}, priority="normal")
   │
   ▼
return Run snapshot
```

### Conventions (inherited from prior cutovers)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (`dt` conda env)
- No `Co-Authored-By: Claude` trailers
- No emojis in code or prompts
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 10
- Default git branch: `master`; worktree under `worktrees/<agent_id>`; CodeHub `merge_pull_request` is real git
- Both baselines green at every task boundary: `python agent/tests/run_regressions.py` (currently 7 OK) and `python -m unittest discover agent/tests -p 'test_*.py'` (currently 443 OK after Cutover 10)
- All hubs use `JsonStore` (Cutover 9); on-disk dir is `shared/hubs/`
- EventHub `publish_event(source_hub, event_type, payload, recipients, priority, thread_id)` and `subscribe(agent, source_hub, event_type, ...)` exist
- APIHub `get_endpoints()` returns `{key: endpoint_dict}` where endpoint has `method`, `path`, `status`, `provider`, `auth_required`, `examples_ref` etc.
- HubTool framework: `class XTool(HubTool)`, `NAME`/`DESCRIPTION`/`PARAMETERS` (JSON schema), `async _run(self, **kwargs) -> ToolResult`. Constructor: `__init__(self, agent_id="", hub_workspace=None)`. Hub registry via `self._hubs`. `_finalize_hub_tools(...)` call at module bottom.
- Tool bundles: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — `TOOL_BUNDLE_REGISTRY` (callable per bundle) + `TOOL_BUNDLE_REQUIREMENTS` (categories per bundle)

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/__init__.py` — re-export `RunHub`
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py` — `RunHub` class
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/stores.py` — `RunHubStores` dataclass
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/probes.py` — pure probe planner + result types
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/compose.py` — `docker compose` subprocess wrapper with healthcheck poller
- `agent/env_generator/llm_generator/tools/run_tools.py` — 4 LLM tools (`run_start`, `run_status`, `run_list`, `run_get`)
- `agent/tests/test_runhub_probes.py`
- `agent/tests/test_runhub_compose.py`
- `agent/tests/test_runhub_service.py`
- `agent/tests/test_run_tools.py`
- `agent/tests/test_runhub_orchestrator_prompt.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — instantiate `RunHub`, attach as `self.runhub`, include in `get_versions()` / `snapshot()`
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/__init__.py` — add `runhub` to package re-exports if any
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `run_tools` bundle to orchestrator profile
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `run_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — add "RUN VERIFICATION DISCIPLINE" block instructing the lead to `run_start()` after any backend-touching PR merge

---

## Task 1: Worktree setup + baseline capture

**Files:**
- Create: `docs/superpowers/cutover-11-baseline.md`

- [ ] **Step 1: Verify worktree on correct branch**

Worktree should be created by parent session. Confirm:

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-11-runhub
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-11-runhub`, branched from `haibotong-0521-pipeline-web-tools` at the post-Cutover-10 SHA. (If missing, create from repo root: `git worktree add -b haibotong-cutover-11-runhub .worktrees/haibotong-cutover-11-runhub haibotong-0521-pipeline-web-tools`)

- [ ] **Step 2: Verify httpx availability**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "import httpx; print(httpx.__version__)"
```

Expected: a version string. If `ImportError`, record in baseline note — Tasks 4/5 will need to fall back to `urllib.request` for probes.

- [ ] **Step 3: Verify docker compose availability**

```bash
docker compose version 2>&1 | head -1
```

Expected: a version string. If docker isn't available, tests will use mocked subprocess — note in baseline.

- [ ] **Step 4: Run baseline regression suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

Expected: `7 tests, OK`.

- [ ] **Step 5: Run baseline discover suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 443 tests` + `OK`.

- [ ] **Step 6: Confirm existing hub registration pattern**

```bash
grep -nE "self\.(eventhub|codehub|workhub|apihub) = " agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py | head -10
```

Note the ordering and arg shape — `RunHub` will follow the same pattern.

- [ ] **Step 7: Write baseline note**

Create `docs/superpowers/cutover-11-baseline.md`:

```markdown
# Cutover 11 Baseline (RunHub)

## Test counts
- regressions: 7 OK
- discover: 443 OK

## Environment
- httpx version: <fill from Step 2>
- docker compose version: <fill from Step 3>

## Existing surfaces this cutover extends
- HubRegistry init pattern: matches eventhub/codehub/workhub/apihub
- EventHub.publish_event(source_hub, event_type, payload, recipients=, priority=, thread_id=)
- APIHub.get_endpoints() -> {key: endpoint_dict}
- JsonStore: file-locked atomic JSON KV (post-Cutover-9)

## New hub being added
RunHub — 5th sibling of the existing 4 hubs
```

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/cutover-11-baseline.md
git commit -m "Cutover 11: record pre-flight baseline (regressions 7 OK, discover 443 OK)"
```

Verify no Claude trailer.

---

## Task 2: Probe planner (pure functions, no IO)

A pure module that, given an APIHub endpoint dict + an optional example body, returns either a `ProbePlan` (method, url, headers, body) or a `SkipReason`. No HTTP IO — separating planning from execution makes the planner fully unit-testable without docker / httpx.

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/probes.py`
- Create: `agent/tests/test_runhub_probes.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_runhub_probes.py`:

```python
"""Tests for RunHub probe planner (pure, no IO)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    plan_probe, ProbePlan, ProbeSkip, classify_probe_result, ProbeOutcome,
)


class ProbePlanTests(unittest.TestCase):
    def test_get_endpoint_returns_plan_with_empty_body(self) -> None:
        ep = {"method": "GET", "path": "/api/feed", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.method, "GET")
        self.assertEqual(result.url, "http://localhost:8000/api/feed")
        self.assertIsNone(result.body)

    def test_get_endpoint_with_auth_required_still_probes(self) -> None:
        # GET with auth: we probe, 401/403 will be tolerated at result-classification time
        ep = {"method": "GET", "path": "/api/me", "auth_required": True}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)

    def test_post_with_auth_required_skipped(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": True}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "auth_required")

    def test_post_without_auth_uses_example_body_when_available(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": False}
        example = {"text": "hello"}
        result = plan_probe(ep, base_url="http://localhost:8000", example_body=example)
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.body, example)

    def test_post_without_auth_falls_back_to_empty_json(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.body, {})

    def test_delete_always_skipped_destructive(self) -> None:
        ep = {"method": "DELETE", "path": "/api/feed/1", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "destructive")

    def test_undefined_endpoint_skipped(self) -> None:
        ep = {"method": "GET", "path": "/api/wip", "status": "draft"}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "not_defined")


class ProbeOutcomeClassificationTests(unittest.TestCase):
    def test_2xx_is_pass(self) -> None:
        outcome = classify_probe_result(200, "OK", auth_required=False)
        self.assertEqual(outcome.verdict, "pass")

    def test_3xx_is_pass(self) -> None:
        outcome = classify_probe_result(301, "", auth_required=False)
        self.assertEqual(outcome.verdict, "pass")

    def test_5xx_is_fail_high_severity(self) -> None:
        outcome = classify_probe_result(500, "Internal error", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_4xx_other_than_401_403_404_is_fail(self) -> None:
        outcome = classify_probe_result(400, "bad request", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P2")

    def test_401_or_403_pass_when_auth_required(self) -> None:
        for code in (401, 403):
            outcome = classify_probe_result(code, "auth", auth_required=True)
            self.assertEqual(outcome.verdict, "pass")

    def test_401_or_403_fail_when_auth_not_required(self) -> None:
        for code in (401, 403):
            outcome = classify_probe_result(code, "auth", auth_required=False)
            self.assertEqual(outcome.verdict, "fail")

    def test_404_is_fail(self) -> None:
        # 404 on a declared endpoint means the route isn't wired up — that's a bug.
        outcome = classify_probe_result(404, "", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_timeout_string_is_fail(self) -> None:
        outcome = classify_probe_result(None, "TIMEOUT", auth_required=False,
                                         transport_error="timeout")
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_connection_refused_is_fail(self) -> None:
        outcome = classify_probe_result(None, "", auth_required=False,
                                         transport_error="connection_refused")
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_probes -v 2>&1 | tail -10
```

Expected: ImportError on `multi_agent.runtime.hubs.runhub.probes`.

- [ ] **Step 3: Create the package skeleton**

```bash
mkdir -p agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub
touch agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/__init__.py
```

- [ ] **Step 4: Implement the probe planner**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/probes.py`:

```python
"""RunHub probe planner — pure functions, no IO.

`plan_probe(endpoint_dict, base_url, example_body=None)` returns either:
  - `ProbePlan(method, url, headers, body)` — ready to execute
  - `ProbeSkip(reason)` — endpoint should not be probed (auth, destructive, draft)

`classify_probe_result(status_code, body_excerpt, auth_required, transport_error)`
returns a `ProbeOutcome(verdict, severity, note)`.

Verdict matrix:
  2xx, 3xx                            -> pass
  401, 403 when auth_required=True    -> pass
  401, 403 when auth_required=False   -> fail (P2)
  404                                 -> fail (P1)  (route not wired)
  4xx (other)                         -> fail (P2)
  5xx                                 -> fail (P1)
  transport_error="timeout"           -> fail (P1)
  transport_error="connection_refused"-> fail (P0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union


@dataclass
class ProbePlan:
    method: str
    url: str
    body: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=lambda: {"accept": "application/json"})


@dataclass
class ProbeSkip:
    reason: str  # "auth_required" | "destructive" | "not_defined"


@dataclass
class ProbeOutcome:
    verdict: str          # "pass" | "fail"
    severity: str = "P3"  # P0 | P1 | P2 | P3
    note: str = ""


_DESTRUCTIVE = {"DELETE"}


def plan_probe(
    endpoint: Dict[str, Any],
    base_url: str,
    example_body: Optional[Dict[str, Any]] = None,
) -> Union[ProbePlan, ProbeSkip]:
    status = (endpoint.get("status") or "defined")
    if status != "defined":
        return ProbeSkip(reason="not_defined")

    method = (endpoint.get("method") or "GET").upper()
    path = endpoint.get("path") or "/"
    auth_required = bool(endpoint.get("auth_required"))

    if method in _DESTRUCTIVE:
        return ProbeSkip(reason="destructive")

    # POST/PUT/PATCH require auth -> skip; GET still probes (401 will be tolerated at classify).
    if method in ("POST", "PUT", "PATCH") and auth_required:
        return ProbeSkip(reason="auth_required")

    body: Optional[Dict[str, Any]] = None
    if method in ("POST", "PUT", "PATCH"):
        body = example_body if example_body is not None else {}

    url = base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)
    return ProbePlan(method=method, url=url, body=body)


def classify_probe_result(
    status_code: Optional[int],
    body_excerpt: str,
    auth_required: bool,
    transport_error: Optional[str] = None,
) -> ProbeOutcome:
    if transport_error == "connection_refused":
        return ProbeOutcome(verdict="fail", severity="P0",
                            note="connection refused — service not running")
    if transport_error == "timeout":
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="probe timed out")
    if transport_error:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"transport error: {transport_error}")

    if status_code is None:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="no status code received")
    if 200 <= status_code < 400:
        return ProbeOutcome(verdict="pass")
    if status_code in (401, 403) and auth_required:
        return ProbeOutcome(verdict="pass", note="auth-protected as expected")
    if status_code == 404:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note="route not wired (404 on declared endpoint)")
    if 500 <= status_code < 600:
        return ProbeOutcome(verdict="fail", severity="P1",
                            note=f"server error {status_code}")
    return ProbeOutcome(verdict="fail", severity="P2",
                        note=f"unexpected status {status_code}")


__all__ = [
    "ProbePlan", "ProbeSkip", "ProbeOutcome",
    "plan_probe", "classify_probe_result",
]
```

- [ ] **Step 5: Verify the 16 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_probes -v 2>&1 | tail -25
```

Expected: 16 tests OK.

- [ ] **Step 6: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 459 OK (was 443 + 16 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/__init__.py agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/probes.py agent/tests/test_runhub_probes.py
git commit -m "RunHub: add pure probe planner (plan_probe + classify_probe_result)"
```

---

## Task 3: Docker compose wrapper + healthcheck poller

A thin subprocess wrapper. All actual `docker compose` invocations are gated behind a callable that tests can stub with a fake `runner`. The healthcheck poller hits a URL with a backoff loop.

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/compose.py`
- Create: `agent/tests/test_runhub_compose.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_runhub_compose.py`:

```python
"""Tests for RunHub docker compose wrapper (mocked subprocess)."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.runhub.compose import (  # noqa: E402
    ComposeLifecycle, ComposeResult, HealthcheckProbe, HealthcheckResult,
)


def _make_completed(returncode=0, stdout="", stderr=""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class ComposeLifecycleTests(unittest.TestCase):
    def test_up_calls_docker_compose_up_with_d_flag(self) -> None:
        runner = MagicMock(return_value=_make_completed())
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.up()
        self.assertIsInstance(result, ComposeResult)
        self.assertEqual(result.returncode, 0)
        runner.assert_called_once()
        args, kwargs = runner.call_args
        self.assertEqual(list(args[0])[:3], ["docker", "compose", "up"])
        self.assertIn("-d", args[0])
        self.assertEqual(kwargs.get("cwd"), "/tmp/gen")

    def test_up_failure_returncode_propagates(self) -> None:
        runner = MagicMock(return_value=_make_completed(returncode=1, stderr="boom"))
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.up()
        self.assertEqual(result.returncode, 1)
        self.assertIn("boom", result.stderr)

    def test_down_calls_docker_compose_down(self) -> None:
        runner = MagicMock(return_value=_make_completed())
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        lc.down()
        args, _ = runner.call_args
        self.assertEqual(list(args[0])[:3], ["docker", "compose", "down"])

    def test_down_swallows_nonzero_returncode(self) -> None:
        # down() must not raise on failure — caller always calls it in finally
        runner = MagicMock(return_value=_make_completed(returncode=2, stderr="already down"))
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.down()
        self.assertEqual(result.returncode, 2)  # we return it but don't raise


class HealthcheckProbeTests(unittest.TestCase):
    def test_healthy_when_first_attempt_returns_2xx(self) -> None:
        def fake_get(url, timeout):
            return MagicMock(status_code=200)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=1, getter=fake_get)
        result = hc.wait()
        self.assertIsInstance(result, HealthcheckResult)
        self.assertTrue(result.healthy)
        self.assertEqual(result.status_code, 200)
        self.assertGreaterEqual(result.attempts, 1)

    def test_unhealthy_when_timeout_reached(self) -> None:
        def fake_get(url, timeout):
            return MagicMock(status_code=503)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=0.1, getter=fake_get)
        result = hc.wait()
        self.assertFalse(result.healthy)
        self.assertEqual(result.status_code, 503)

    def test_unhealthy_when_connection_refused_throughout(self) -> None:
        class _Refused(Exception):
            pass
        def fake_get(url, timeout):
            raise _Refused("connection refused")
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=0.05, getter=fake_get)
        result = hc.wait()
        self.assertFalse(result.healthy)
        self.assertIn("connection", result.last_error.lower())

    def test_healthy_after_initial_failures(self) -> None:
        attempts = {"n": 0}
        def fake_get(url, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("not yet")
            return MagicMock(status_code=200)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=5, getter=fake_get)
        result = hc.wait()
        self.assertTrue(result.healthy)
        self.assertGreaterEqual(result.attempts, 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_compose -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the wrapper**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/compose.py`:

```python
"""RunHub docker compose lifecycle wrapper + HTTP healthcheck poller.

All subprocess/HTTP calls are gated behind injectable callables so unit tests
can stub them. Production callers pass `runner=subprocess.run` and
`getter=httpx.get` (or `urllib.request.urlopen`).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional


@dataclass
class ComposeResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class HealthcheckResult:
    healthy: bool
    status_code: Optional[int] = None
    attempts: int = 0
    elapsed_s: float = 0.0
    last_error: str = ""


def _default_runner(args: List[str], cwd: str = None, timeout: float = 120.0) -> ComposeResult:
    cp = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return ComposeResult(returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)


class ComposeLifecycle:
    def __init__(self, cwd: str, runner: Callable = None,
                 compose_file: Optional[str] = None) -> None:
        self.cwd = cwd
        self._runner = runner or _default_runner
        self.compose_file = compose_file

    def _base_args(self) -> List[str]:
        args = ["docker", "compose"]
        if self.compose_file:
            args += ["-f", self.compose_file]
        return args

    def up(self, timeout: float = 180.0) -> ComposeResult:
        result = self._runner(self._base_args() + ["up", "-d", "--remove-orphans"],
                              cwd=self.cwd, timeout=timeout)
        return _coerce(result)

    def down(self, timeout: float = 60.0) -> ComposeResult:
        try:
            result = self._runner(self._base_args() + ["down", "--remove-orphans"],
                                  cwd=self.cwd, timeout=timeout)
            return _coerce(result)
        except Exception as e:  # never raise from down() — finally must always succeed
            return ComposeResult(returncode=-1, stderr=f"down failed: {e}")


def _coerce(r: Any) -> ComposeResult:
    if isinstance(r, ComposeResult):
        return r
    # subprocess.CompletedProcess shape
    return ComposeResult(returncode=int(getattr(r, "returncode", -1)),
                         stdout=str(getattr(r, "stdout", "")),
                         stderr=str(getattr(r, "stderr", "")))


class HealthcheckProbe:
    def __init__(self, url: str, poll_interval_s: float = 2.0,
                 timeout_s: float = 60.0, getter: Callable = None,
                 request_timeout_s: float = 5.0,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.url = url
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._getter = getter
        self._request_timeout_s = request_timeout_s
        self._clock = clock
        self._sleep = sleep

    def _http_get(self, url: str, timeout: float):
        if self._getter is not None:
            return self._getter(url, timeout)
        try:
            import httpx
        except ImportError:
            from urllib.request import urlopen
            return _UrllibResponse(urlopen(url, timeout=timeout))
        return httpx.get(url, timeout=timeout)

    def wait(self) -> HealthcheckResult:
        start = self._clock()
        attempts = 0
        last_status: Optional[int] = None
        last_error = ""
        while True:
            attempts += 1
            try:
                resp = self._http_get(self.url, self._request_timeout_s)
                code = getattr(resp, "status_code", None)
                last_status = code
                if isinstance(code, int) and 200 <= code < 400:
                    return HealthcheckResult(
                        healthy=True, status_code=code, attempts=attempts,
                        elapsed_s=self._clock() - start)
            except Exception as e:
                last_error = str(e)
            elapsed = self._clock() - start
            if elapsed >= self.timeout_s:
                return HealthcheckResult(
                    healthy=False, status_code=last_status, attempts=attempts,
                    elapsed_s=elapsed, last_error=last_error)
            self._sleep(self.poll_interval_s)


class _UrllibResponse:
    def __init__(self, raw):
        self.status_code = getattr(raw, "status", getattr(raw, "code", 0))


__all__ = ["ComposeLifecycle", "ComposeResult", "HealthcheckProbe", "HealthcheckResult"]
```

- [ ] **Step 4: Verify the 8 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_compose -v 2>&1 | tail -15
```

Expected: 8 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 467 OK (was 459 + 8 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/compose.py agent/tests/test_runhub_compose.py
git commit -m "RunHub: add ComposeLifecycle (up/down) + HealthcheckProbe (HTTP poll with backoff)"
```

---

## Task 4: `RunHubStores` + `RunHub` service skeleton

The service ties probe planner + compose lifecycle + JsonStore + EventHub publisher together. We build the skeleton first (constructor, store wiring, `record_run` / `get_run` / `list_runs`) then layer in `start_run` orchestration in Task 5.

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/stores.py`
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/__init__.py`
- Create: `agent/tests/test_runhub_service.py` (skeleton tests only — full `start_run` tests in Task 5)

- [ ] **Step 1: Write failing skeleton tests**

Create `agent/tests/test_runhub_service.py`:

```python
"""Skeleton tests for RunHub service (Task 4); start_run tests added in Task 5."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.service import RunHub  # noqa: E402
from multi_agent.runtime.hubs.runhub.stores import RunHubStores  # noqa: E402


class RunHubSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runhub_stores_have_runs_json(self) -> None:
        stores = RunHubStores.create(self.tmp / "shared" / "hubs")
        self.assertTrue(hasattr(stores, "runs"))
        # JsonStore exposes value() returning dict
        self.assertEqual(stores.runs.value(), {})

    def test_runhub_service_init_creates_store_dir(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        self.assertEqual(rh.list_runs(), [])

    def test_record_run_persists_and_get_run_reads_back(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        run = rh.record_run(branch="feature/x", generated_dir="/tmp/gen", agent="orch")
        self.assertIn("id", run)
        self.assertEqual(run["branch"], "feature/x")
        self.assertEqual(run["status"], "starting")
        self.assertEqual(rh.get_run(run["id"])["id"], run["id"])
        self.assertEqual(len(rh.list_runs()), 1)

    def test_update_run_status_transitions_state(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        run = rh.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        updated = rh.update_run_status(run["id"], status="healthy", agent="runhub")
        self.assertEqual(updated["status"], "healthy")
        self.assertIn("updated_at", updated)

    def test_list_runs_sorted_most_recent_first(self) -> None:
        rh = RunHub(self.tmp / "shared" / "hubs")
        a = rh.record_run(branch="a", generated_dir="/tmp/g", agent="orch")
        b = rh.record_run(branch="b", generated_dir="/tmp/g", agent="orch")
        c = rh.record_run(branch="c", generated_dir="/tmp/g", agent="orch")
        ids = [r["id"] for r in rh.list_runs()]
        self.assertEqual(ids, [c["id"], b["id"], a["id"]])

    def test_hub_registry_exposes_runhub(self) -> None:
        reg = HubRegistry(self.tmp)
        self.assertIsNotNone(reg.runhub)
        self.assertEqual(reg.runhub.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_service -v 2>&1 | tail -10
```

Expected: ImportError on stores / service.

- [ ] **Step 3: Implement `RunHubStores`**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/stores.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class RunHubStores:
    runs: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "RunHubStores":
        hub_dir = Path(hub_dir)
        return cls(runs=JsonStore(hub_dir / "runhub_runs.json"))

    def ensure_documents(self) -> None:
        self.runs.update(lambda m: m, change_info={"system": "ensure_runhub_document"})

    def versions(self) -> dict:
        return {"runhub_runs": self.runs.get_version()}

    def snapshot(self) -> dict:
        return {"runs": self.runs.value()}
```

- [ ] **Step 4: Implement `RunHub` service skeleton (no `start_run` yet)**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`:

```python
"""RunHub service — 5th hub. Tracks app run sessions and emits run events.

This file holds the persistence + lifecycle bookkeeping; `start_run` (the
docker-compose + probe orchestration) is added in Task 5.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .stores import RunHubStores


_VALID_STATUSES = (
    "starting", "starting_compose", "healthy", "probing",
    "failed", "aborted", "completed",
)


class RunHub:
    def __init__(self, hub_dir: Path, eventhub: Any = None):
        self.hub_dir = Path(hub_dir)
        self.hub_dir.mkdir(parents=True, exist_ok=True)
        self.stores = RunHubStores.create(self.hub_dir)
        self.eventhub = eventhub
        self.apihub: Any = None  # attached by HubRegistry

    def attach_apihub(self, apihub: Any) -> None:
        self.apihub = apihub

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def record_run(self, branch: str, generated_dir: str, agent: str = "") -> dict:
        now = time.time()
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        run = {
            "id": run_id,
            "branch": branch,
            "generated_dir": str(generated_dir),
            "status": "starting",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "healthcheck": None,
            "probes": [],
            "fail_count": 0,
            "started_by": agent,
        }
        self.stores.runs.update(lambda m: m.set(run_id, run, agent),
                                 change_info={"agent": agent})
        return run

    def update_run_status(self, run_id: str, status: str, agent: str = "",
                           **field_updates) -> dict:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        run = self.stores.runs.get(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        updated = dict(run)
        updated["status"] = status
        updated["updated_at"] = time.time()
        if status in ("failed", "aborted", "completed"):
            updated["finished_at"] = updated["updated_at"]
        for k, v in field_updates.items():
            updated[k] = v
        self.stores.runs.update(lambda m: m.set(run_id, updated, agent),
                                 change_info={"agent": agent})
        return updated

    def get_run(self, run_id: str) -> Optional[dict]:
        return self.stores.runs.get(run_id)

    def list_runs(self, limit: int = 50) -> List[dict]:
        runs = list((self.stores.runs.value() or {}).values())
        runs.sort(key=lambda r: r.get("started_at", 0.0), reverse=True)
        return runs[:limit]

    # ------------------------------------------------------------------ #
    # Versions / snapshot (HubRegistry interface)
    # ------------------------------------------------------------------ #

    def get_versions(self) -> Dict[str, int]:
        return self.stores.versions()

    def snapshot(self) -> Dict[str, Any]:
        return self.stores.snapshot()
```

- [ ] **Step 5: Update `runhub/__init__.py`**

```python
# agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/__init__.py
from .service import RunHub  # noqa: F401

__all__ = ["RunHub"]
```

- [ ] **Step 6: Wire `RunHub` into `HubRegistry`**

In `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`:

Inside `__init__`, after `self.apihub = APIHub(...)` and the existing attach calls, add:

```python
from .hubs.runhub import RunHub
self.runhub = RunHub(self._store_dir, eventhub=self.eventhub)
self.runhub.attach_apihub(self.apihub)
```

In `get_versions()`:
```python
versions.update(self.runhub.get_versions())
```

In `snapshot()`:
```python
return {
    "codehub": self.codehub.snapshot(),
    "workhub": self.workhub.snapshot(),
    "apihub": self.apihub.snapshot(),
    "eventhub": self.eventhub.snapshot(),
    "runhub": self.runhub.snapshot(),
}
```

- [ ] **Step 7: Verify the 6 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_service -v 2>&1 | tail -15
```

Expected: 6 tests OK.

- [ ] **Step 8: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 473 OK (was 467 + 6 new). If any existing test that snapshots `HubRegistry` breaks because of the new `runhub` key, update the test to tolerate the new key — minimum change.

- [ ] **Step 9: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/ agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py agent/tests/test_runhub_service.py
# include any HubRegistry test fixture update if required
git commit -m "RunHub: add service skeleton + RunHubStores; wire as 5th hub in HubRegistry"
```

---

## Task 5: `start_run` orchestration (compose up → healthcheck → probe → events → down)

The end-to-end orchestration. Heavily injectable — the test passes fake compose, fake healthcheck, fake probe-runner so we exercise the full flow without docker or HTTP.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`
- Modify: `agent/tests/test_runhub_service.py`

- [ ] **Step 1: Append failing tests**

Append to `agent/tests/test_runhub_service.py`:

```python
class RunHubStartRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_start_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wire_endpoint(self, method, path, status="defined", auth_required=False, provider="backend"):
        self.reg.apihub.register_endpoint(method, path, schema={},
                                          provider=provider, agent=provider,
                                          status=status, auth_required=auth_required)

    def _fake_compose(self, up_rc=0, down_rc=0):
        class _Compose:
            def __init__(s):
                s.up_called = False
                s.down_called = False
            def up(s, timeout=180.0):
                s.up_called = True
                from multi_agent.runtime.hubs.runhub.compose import ComposeResult
                return ComposeResult(returncode=up_rc, stdout="up ok" if up_rc == 0 else "", stderr="")
            def down(s, timeout=60.0):
                s.down_called = True
                from multi_agent.runtime.hubs.runhub.compose import ComposeResult
                return ComposeResult(returncode=down_rc)
        return _Compose()

    def _fake_healthcheck(self, healthy=True):
        from multi_agent.runtime.hubs.runhub.compose import HealthcheckResult
        class _HC:
            def wait(s):
                return HealthcheckResult(
                    healthy=healthy, status_code=200 if healthy else 503,
                    attempts=1, elapsed_s=0.1)
        return _HC()

    def _fake_probe_runner(self, responses_by_url):
        """responses_by_url: {url: (status_code, body)} or {url: ("error", "timeout")}"""
        from unittest.mock import MagicMock
        def runner(plan):
            resp = responses_by_url.get(plan.url, (200, ""))
            if isinstance(resp, tuple) and resp[0] == "error":
                return {"status_code": None, "body_excerpt": "",
                        "transport_error": resp[1], "latency_ms": 0.0}
            sc, body = resp
            return {"status_code": sc, "body_excerpt": body,
                    "transport_error": None, "latency_ms": 10.5}
        return runner

    def test_start_run_happy_path_all_endpoints_pass(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        self._wire_endpoint("GET", "/api/health")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="feature/x", generated_dir="/tmp/gen",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(healthy=True),
            probe_runner=self._fake_probe_runner({}),  # all 200
        )
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["fail_count"], 0)
        self.assertEqual(len(run["probes"]), 2)
        self.assertTrue(all(p["verdict"] == "pass" for p in run["probes"]))
        self.assertTrue(compose.up_called and compose.down_called)

    def test_start_run_compose_up_failure_aborts(self) -> None:
        compose = self._fake_compose(up_rc=1)
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "aborted")
        self.assertTrue(compose.down_called, "down() must run even after up() failure")

    def test_start_run_healthcheck_failure_aborts_before_probes(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(healthy=False),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "aborted")
        self.assertEqual(run["probes"], [])  # never probed
        self.assertTrue(compose.down_called)

    def test_start_run_5xx_probe_publishes_run_failed_event(self) -> None:
        self._wire_endpoint("GET", "/api/feed", provider="backend")
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({
                "http://localhost:8000/api/feed": (500, "server error"),
            }),
        )
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["fail_count"], 1)
        events = list(self.reg.eventhub.list_events_by_type("run_failed"))
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["severity"], "P1")
        self.assertEqual(payload["bug_artifacts"]["affected_endpoint"], "GET /api/feed")
        self.assertEqual(payload["bug_artifacts"]["actual"], "500")
        self.assertEqual(payload["bug_artifacts"]["run_id"], run["id"])

    def test_start_run_publishes_run_completed_event_at_end(self) -> None:
        self._wire_endpoint("GET", "/api/feed")
        compose = self._fake_compose()
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        events = list(self.reg.eventhub.list_events_by_type("run_completed"))
        self.assertEqual(len(events), 1)

    def test_start_run_skipped_endpoints_dont_count_as_failures(self) -> None:
        self._wire_endpoint("DELETE", "/api/feed/1")  # destructive -> skip
        self._wire_endpoint("POST", "/api/login", auth_required=True)  # auth -> skip
        self._wire_endpoint("GET", "/api/health")  # probed
        compose = self._fake_compose()
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=compose,
            healthcheck=self._fake_healthcheck(),
            probe_runner=self._fake_probe_runner({}),
        )
        self.assertEqual(run["status"], "completed")
        verdicts = [p["verdict"] for p in run["probes"]]
        self.assertIn("skipped", verdicts)
        self.assertIn("pass", verdicts)
        self.assertNotIn("fail", verdicts)
```

You will also need a helper on `EventHub` to query by event type. Check if it exists:

```bash
grep -nE "def (list_events_by_type|get_events_of_type)" agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py
```

If it doesn't exist, add it (small helper):

```python
    def list_events_by_type(self, event_type: str) -> List[dict]:
        return [
            e for e in (self._events.value() or {}).values()
            if e.get("event_type") == event_type
        ]
```

This is a 3-line addition; include it in this task's commit.

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_service.RunHubStartRunTests -v 2>&1 | tail -15
```

Expected: AttributeError on `start_run` (and possibly on `list_events_by_type`).

- [ ] **Step 3: Implement `start_run`**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`, add (at the end of `RunHub` class):

```python
    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    def start_run(self, *,
                   branch: str,
                   generated_dir: str,
                   base_url: str,
                   agent: str = "",
                   compose: Any = None,
                   healthcheck: Any = None,
                   probe_runner: Any = None,
                   timeout_s: int = 300) -> dict:
        from .probes import plan_probe, classify_probe_result, ProbePlan, ProbeSkip
        from .compose import ComposeLifecycle, HealthcheckProbe

        run = self.record_run(branch=branch, generated_dir=generated_dir, agent=agent)
        run_id = run["id"]

        compose = compose or ComposeLifecycle(cwd=str(generated_dir))
        healthcheck = healthcheck or HealthcheckProbe(
            url=base_url.rstrip("/") + "/health", poll_interval_s=2.0, timeout_s=60.0)
        probe_runner = probe_runner or self._default_probe_runner()

        probes: list = []
        fail_count = 0

        try:
            # Stage 1: compose up
            self.update_run_status(run_id, "starting_compose", agent="runhub")
            up_result = compose.up()
            if up_result.returncode != 0:
                self.update_run_status(run_id, "aborted", agent="runhub",
                                        compose_stderr=up_result.stderr[:500])
                self._emit("run_completed", run_id, {"reason": "compose_up_failed"},
                            priority="high")
                return self.get_run(run_id)

            # Stage 2: healthcheck
            hc_result = healthcheck.wait()
            self.update_run_status(run_id, "healthy" if hc_result.healthy else "aborted",
                                    agent="runhub",
                                    healthcheck={
                                        "healthy": hc_result.healthy,
                                        "status_code": hc_result.status_code,
                                        "attempts": hc_result.attempts,
                                        "elapsed_s": hc_result.elapsed_s,
                                        "last_error": hc_result.last_error,
                                    })
            if not hc_result.healthy:
                self._emit("run_completed", run_id, {"reason": "healthcheck_failed"},
                            priority="high")
                return self.get_run(run_id)

            # Stage 3: probe
            self.update_run_status(run_id, "probing", agent="runhub")
            endpoints = self._list_apihub_endpoints()
            for ep in endpoints:
                plan_or_skip = plan_probe(ep, base_url=base_url)
                if isinstance(plan_or_skip, ProbeSkip):
                    probes.append({
                        "method": ep.get("method"), "path": ep.get("path"),
                        "verdict": "skipped", "reason": plan_or_skip.reason,
                    })
                    continue
                plan = plan_or_skip
                raw = probe_runner(plan)
                outcome = classify_probe_result(
                    status_code=raw.get("status_code"),
                    body_excerpt=raw.get("body_excerpt", ""),
                    auth_required=bool(ep.get("auth_required")),
                    transport_error=raw.get("transport_error"),
                )
                probes.append({
                    "method": plan.method, "path": ep.get("path"), "url": plan.url,
                    "verdict": outcome.verdict, "severity": outcome.severity,
                    "note": outcome.note,
                    "status_code": raw.get("status_code"),
                    "transport_error": raw.get("transport_error"),
                    "latency_ms": raw.get("latency_ms"),
                })
                if outcome.verdict == "fail":
                    fail_count += 1
                    self._publish_run_failed(run_id, branch, plan, ep, raw, outcome)

            final_status = "failed" if fail_count > 0 else "completed"
            self.update_run_status(run_id, final_status, agent="runhub",
                                    probes=probes, fail_count=fail_count)
            self._emit("run_completed", run_id,
                        {"status": final_status, "fail_count": fail_count,
                         "probe_count": len(probes)},
                        priority="high" if fail_count else "normal")
            return self.get_run(run_id)
        finally:
            try:
                compose.down()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _list_apihub_endpoints(self) -> list:
        if self.apihub is None:
            return []
        eps = self.apihub.get_endpoints() if hasattr(self.apihub, "get_endpoints") else {}
        return list((eps or {}).values())

    def _publish_run_failed(self, run_id: str, branch: str, plan, ep: dict,
                             raw: dict, outcome) -> None:
        if self.eventhub is None:
            return
        payload = {
            "source": "runhub",
            "severity": outcome.severity,
            "title": f"{plan.method} {ep.get('path')} returned {raw.get('status_code')}",
            "bug_artifacts": {
                "affected_endpoint": f"{plan.method} {ep.get('path')}",
                "expected": "2xx",
                "actual": str(raw.get("status_code")),
                "response_body_excerpt": (raw.get("body_excerpt") or "")[:500],
                "request_body": plan.body,
                "run_id": run_id,
                "branch": branch,
                "latency_ms": raw.get("latency_ms"),
                "transport_error": raw.get("transport_error"),
                "owner_hint": ep.get("provider"),
            },
        }
        self.eventhub.publish_event(
            source_hub="runhub", event_type="run_failed",
            payload=payload, priority="high")

    def _emit(self, event_type: str, run_id: str, extra: dict, priority: str = "normal") -> None:
        if self.eventhub is None:
            return
        self.eventhub.publish_event(
            source_hub="runhub", event_type=event_type,
            payload={"run_id": run_id, **extra},
            priority=priority)

    def _default_probe_runner(self):
        # Lazy import — httpx is preferred, urllib is fallback
        def _runner(plan):
            import time as _time
            try:
                import httpx
                t0 = _time.time()
                if plan.method == "GET":
                    resp = httpx.get(plan.url, headers=plan.headers, timeout=10.0)
                else:
                    resp = httpx.request(plan.method, plan.url, json=plan.body,
                                          headers=plan.headers, timeout=10.0)
                latency = (_time.time() - t0) * 1000.0
                body = ""
                try:
                    body = (resp.text or "")[:500]
                except Exception:
                    pass
                return {"status_code": resp.status_code, "body_excerpt": body,
                        "transport_error": None, "latency_ms": latency}
            except Exception as e:
                kind = type(e).__name__.lower()
                terr = "timeout" if "timeout" in kind else (
                    "connection_refused" if "connect" in kind else kind)
                return {"status_code": None, "body_excerpt": "",
                        "transport_error": terr, "latency_ms": 0.0}
        return _runner
```

- [ ] **Step 4: Verify the 6 `start_run` tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_service.RunHubStartRunTests -v 2>&1 | tail -15
```

Expected: 6 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 479 OK (was 473 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py agent/tests/test_runhub_service.py
git commit -m "RunHub: implement start_run orchestration (compose up + healthcheck + probe + events)"
```

---

## Task 6: Run LLM tools

4 tools: `run_start`, `run_status`, `run_list`, `run_get`. Mirrors the bug_tools convention from Cutover 10.

**Files:**
- Create: `agent/env_generator/llm_generator/tools/run_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Create: `agent/tests/test_run_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_run_tools.py`:

```python
"""Tests for RunHub LLM tools (Cutover 11)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.run_tools import (  # noqa: E402
    RunStartTool, RunStatusTool, RunListTool, RunGetTool,
)


def _run_async(coro):
    """Ephemeral event loop per call (matches Cutover-10 bug_tools test pattern)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RunToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="run_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_list_empty(self) -> None:
        tool = RunListTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run())
        self.assertTrue(result.success)
        self.assertEqual(result.data["runs"], [])

    def test_run_status_for_recorded_run(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        tool = RunStatusTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id=run["id"]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["run"]["status"], "starting")

    def test_run_get_returns_full_run(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        tool = RunGetTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id=run["id"]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["run"]["id"], run["id"])

    def test_run_get_unknown_returns_error(self) -> None:
        tool = RunGetTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id="run_missing"))
        self.assertFalse(result.success)

    def test_run_start_invokes_runhub_start_run(self) -> None:
        # Wire up a minimal endpoint so the run has something to probe
        self.reg.apihub.register_endpoint("GET", "/api/health", schema={},
                                          provider="backend", agent="backend",
                                          status="defined")
        # Use the inject-friendly start_run by replacing it on the runhub instance.
        # The tool calls runhub.start_run(...) — we monkey-patch to verify args.
        called = {}
        def _fake_start_run(*, branch, generated_dir, base_url, agent, **kwargs):
            called["kwargs"] = {"branch": branch, "generated_dir": generated_dir,
                                 "base_url": base_url, "agent": agent}
            return {"id": "run_fake", "status": "completed", "fail_count": 0}
        self.reg.runhub.start_run = _fake_start_run
        tool = RunStartTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(branch="feature/x",
                                       generated_dir="/tmp/gen",
                                       base_url="http://localhost:8000"))
        self.assertTrue(result.success)
        self.assertEqual(called["kwargs"]["branch"], "feature/x")
        self.assertEqual(called["kwargs"]["agent"], "orch")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_run_tools -v 2>&1 | tail -10
```

Expected: ImportError on `tools.run_tools`.

- [ ] **Step 3: Implement the tools**

Create `agent/env_generator/llm_generator/tools/run_tools.py`. Match the `HubTool` / `_run` / `_finalize_hub_tools` convention discovered in Cutover 10 Task 5:

```python
"""RunHub LLM tools (Cutover 11). Mirrors the bug_tools convention."""

from __future__ import annotations

from typing import Any

from .hub_tools import HubTool, _finalize_hub_tools  # adjust if convention differs
from ._base import ToolResult  # adjust to real base import path


class RunStartTool(HubTool):
    NAME = "run_start"
    DESCRIPTION = ("Spin up the generated app via docker compose, run healthcheck + "
                    "HTTP probes against APIHub-registered endpoints, publish run_failed "
                    "events for any failures. Returns the run summary.")
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "git branch being verified"},
            "generated_dir": {"type": "string",
                              "description": "directory containing docker-compose.yml"},
            "base_url": {"type": "string", "description": "base URL the app exposes",
                          "default": "http://localhost:8000"},
        },
        "required": ["branch", "generated_dir"],
    }

    async def _run(self, *, branch: str, generated_dir: str,
                    base_url: str = "http://localhost:8000") -> ToolResult:
        try:
            run = self._hubs.runhub.start_run(
                branch=branch, generated_dir=generated_dir,
                base_url=base_url, agent=self._agent_id)
            return ToolResult(success=True, data={"run": run})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class RunStatusTool(HubTool):
    NAME = "run_status"
    DESCRIPTION = "Get the current status of a run by run_id."
    PARAMETERS = {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    }

    async def _run(self, *, run_id: str) -> ToolResult:
        run = self._hubs.runhub.get_run(run_id)
        if not run:
            return ToolResult(success=False, error=f"run not found: {run_id}")
        return ToolResult(success=True, data={"run": {
            "id": run["id"], "status": run["status"], "branch": run.get("branch"),
            "fail_count": run.get("fail_count", 0),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
        }})


class RunListTool(HubTool):
    NAME = "run_list"
    DESCRIPTION = "List most recent runs (default limit 20)."
    PARAMETERS = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    }

    async def _run(self, *, limit: int = 20) -> ToolResult:
        runs = self._hubs.runhub.list_runs(limit=limit)
        # Return summaries, not full probe arrays — keep payload small
        summaries = [{
            "id": r["id"], "branch": r.get("branch"), "status": r.get("status"),
            "fail_count": r.get("fail_count", 0),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        } for r in runs]
        return ToolResult(success=True, data={"runs": summaries})


class RunGetTool(HubTool):
    NAME = "run_get"
    DESCRIPTION = "Get the full run record (including all probe results) by run_id."
    PARAMETERS = {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    }

    async def _run(self, *, run_id: str) -> ToolResult:
        run = self._hubs.runhub.get_run(run_id)
        if not run:
            return ToolResult(success=False, error=f"run not found: {run_id}")
        return ToolResult(success=True, data={"run": run})


_RUN_TOOLS = [RunStartTool, RunStatusTool, RunListTool, RunGetTool]
_finalize_hub_tools(_RUN_TOOLS)


def create_run_tools(agent_id: str = "", hub_workspace: Any = None) -> list:
    return [cls(agent_id=agent_id, hub_workspace=hub_workspace) for cls in _RUN_TOOLS]


__all__ = ["RunStartTool", "RunStatusTool", "RunListTool", "RunGetTool",
            "create_run_tools"]
```

If `_finalize_hub_tools` or `ToolResult` import paths differ, match Cutover 10's bug_tools.py — it solved exactly this discovery in Task 5.

- [ ] **Step 4: Register `run_tools` bundle**

In `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`, mirror the pattern used by `_bundle_bug_tools` (added in Cutover 10):

```python
from tools.run_tools import create_run_tools

def _bundle_run_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(
        create_run_tools(agent_id=context.agent_id or context.agent_type,
                         hub_workspace=context.hub_workspace),
        ("run", "hub"),
    )

# Add to TOOL_BUNDLE_REGISTRY (after bug_tools):
"run_tools": _bundle_run_tools,

# Add to TOOL_BUNDLE_REQUIREMENTS:
"run_tools": {"run"},
```

- [ ] **Step 5: Verify the 5 tool tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_run_tools -v 2>&1 | tail -10
```

Expected: 5 tests OK.

- [ ] **Step 6: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 484 OK (was 479 + 5 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/tools/run_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/tests/test_run_tools.py
git commit -m "Add run_tools LLM surface (run_start / run_status / run_list / run_get)"
```

---

## Task 7: Wire `run_tools` bundle to orchestrator profile

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_orchestrator_run_tools_config.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_run_tools_config.py`:

```python
"""Tests that orchestrator profile includes run_tools bundle (Cutover 11)."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class OrchestratorRunToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_orchestrator_has_run_tools_bundle(self) -> None:
        bundles = self.cfg["profiles"]["orchestrator"]["tool_bundles"]
        self.assertIn("run_tools", bundles)

    def test_orchestrator_tool_categories_include_run(self) -> None:
        cats = self.cfg["profiles"]["orchestrator"]["tool_categories"]
        self.assertIn("run", cats)
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_run_tools_config -v 2>&1 | tail -10
```

Expected: 2 failures.

- [ ] **Step 3: Edit `agents_config.yaml`**

In the `orchestrator:` profile, add `run_tools` to `tool_bundles` (after `eventhub_tools`) and `"run"` to `tool_categories`. Keep formatting consistent with surrounding entries.

- [ ] **Step 4: Verify the 2 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_run_tools_config -v 2>&1 | tail -10
```

Expected: 2 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 486 OK (was 484 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_orchestrator_run_tools_config.py
git commit -m "Orchestrator: wire run_tools bundle (orchestrator can now invoke run_start)"
```

---

## Task 8: Orchestrator prompt — RUN VERIFICATION DISCIPLINE

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_runhub_orchestrator_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_runhub_orchestrator_prompt.py`:

```python
"""Tests that orchestrator prompt now includes RunHub discipline (Cutover 11)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorRunDisciplineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        # Macro name was `lead_specifics` per Cutover 8.
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_mentions_run_start(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUN_START", upper)

    def test_prompt_requires_run_after_backend_merge(self) -> None:
        upper = self.system.upper()
        # Some phrasing of "after PR merge, call run_start"
        self.assertIn("AFTER", upper)
        self.assertTrue("MERGE" in upper or "PR" in upper)

    def test_prompt_references_runhub(self) -> None:
        upper = self.system.upper()
        self.assertIn("RUNHUB", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_orchestrator_prompt -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `orchestrator_agent.j2`**

In the `lead_specifics()` macro, add (just after the existing Cutover-8 STEP PIPELINE block):

```jinja
### RUN VERIFICATION DISCIPLINE (Cutover 11 - RunHub)
After merging any PR that touches backend or database code, you MUST call `run_start(branch=<merged_branch>, generated_dir=<repo_root>)` to spin up the generated app, run a healthcheck, and probe every registered APIHub endpoint. RunHub will publish `runhub/run_failed` events for any 4xx/5xx/timeout — the Bug Triage Orchestrator (Cutover 10) auto-routes those to the owning agent.

DO NOT skip `run_start` because "the contract tests passed" — contract tests verify the SHAPE, RunHub verifies the app actually RUNS. Most real bugs surface here, not in contract tests.

Use `run_list()` to see recent runs and `run_get(run_id)` to inspect probe-by-probe results when triaging.
```

- [ ] **Step 4: Verify the 3 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_orchestrator_prompt -v 2>&1 | tail -10
```

Expected: 3 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 489 OK (was 486 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_runhub_orchestrator_prompt.py
git commit -m "Orchestrator prompt: RUN VERIFICATION DISCIPLINE - call run_start after backend PR merge"
```

---

## Task 9: hub_pulse surfaces recent failed runs

Lightweight render: for the orchestrator and the bug_triage_orchestrator, show the most recent run's status (and failing endpoint count if any) in their pulse.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`
- Create: `agent/tests/test_hub_pulse_run_rendering.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_hub_pulse_run_rendering.py`:

```python
"""Tests for hub_pulse RunHub rendering (Cutover 11)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse, build_hub_pulse_prompt  # noqa: E402


class HubPulseRunRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_run_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_runs_no_section(self) -> None:
        report = collect_hub_pulse(self.reg, "orchestrator")
        rendered = build_hub_pulse_prompt(report)
        self.assertNotIn("RECENT RUN", rendered.upper())

    def test_orchestrator_sees_latest_run_status(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(run["id"], "failed", agent="runhub", fail_count=3)
        report = collect_hub_pulse(self.reg, "orchestrator")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("RECENT RUN", rendered.upper())
        self.assertIn("failed", rendered.lower())
        self.assertIn("3", rendered)  # fail_count


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_run_rendering -v 2>&1 | tail -10
```

- [ ] **Step 3: Extend `hub_pulse.py`**

Add to `collect_hub_pulse(hubs, agent_id, step_num=0)` (or equivalent collector): populate `report["latest_run"]` for orchestrator and bug_triage_orchestrator agents:

```python
if agent_id in ("orchestrator", "bug_triage_orchestrator") and hasattr(hubs, "runhub"):
    recent = hubs.runhub.list_runs(limit=1)
    report["latest_run"] = recent[0] if recent else None
```

And add to `build_hub_pulse_prompt(report)`:

```python
lr = report.get("latest_run") if isinstance(report, dict) else None
if lr:
    sections.append(
        f"## RECENT RUN\n"
        f"- {lr.get('id')}: status={lr.get('status')}, "
        f"branch={lr.get('branch')}, fail_count={lr.get('fail_count', 0)}"
    )
```

(Adapt placement to match the existing `sections.append(...)` / string-concat pattern in `build_hub_pulse_prompt` — look at how Cutover 10's `ASSIGNED BUGS` / `OPEN BUG QUEUE` blocks were inserted.)

- [ ] **Step 4: Verify the 2 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse_run_rendering -v 2>&1 | tail -10
```

Expected: 2 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 491 OK (was 489 + 2 new). Adjust existing hub_pulse fixture tests if they break — minimum required change.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py agent/tests/test_hub_pulse_run_rendering.py
# include hub_pulse fixture test updates if any
git commit -m "hub_pulse: surface RECENT RUN section to orchestrator / bug_triage_orchestrator"
```

---

## Task 10: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/12-runhub.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 491 OK. STOP if anything fails.

- [ ] **Step 2: Verify zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Write migration log**

Create `docs/superpowers/migration-logs/12-runhub.md` summarizing:
- Goal + scope (MVP: backend probes; Playwright deferred)
- Commit list (fill from `git log --oneline`)
- Test delta: 443 → 491 (+48)
- New surfaces: RunHub service, ComposeLifecycle, HealthcheckProbe, probe planner, run_tools, orchestrator prompt update, hub_pulse RECENT RUN section
- How it integrates with Cutover 10's BugTriageOrchestrator (runhub/run_failed → BugOrch resolver picks owner_hint or affected_endpoint → assigns to backend/etc.)
- Known MVP gaps: auth-protected POST/PUT/PATCH skipped (need credential flow); DELETE skipped (destructive); no UI/browser tests (Playwright sub-cutover later)

- [ ] **Step 4: Commit log**

```bash
git add docs/superpowers/migration-logs/12-runhub.md
git commit -m "Add Cutover 11 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-11-runhub 2>&1 | tail -5
```

- [ ] **Step 6: Report**

Print: final test counts, commit count, push URL, compare URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:**
- New RunHub as 5th hub — Tasks 4 + wired in HubRegistry ✓
- docker compose lifecycle — Task 3 ✓
- Healthcheck poller — Task 3 ✓
- Probe planner (pure) — Task 2 ✓
- start_run orchestration — Task 5 ✓
- run_failed events shaped for BugOrch — Task 5 + bug_artifacts schema matches Cutover 10's resolver ✓
- LLM tools — Task 6 ✓
- Orchestrator prompt discipline — Task 8 ✓
- Pulse render — Task 9 ✓
- Migration log + push — Task 10 ✓
- Explicit out-of-scope list (no Playwright / no auth flow / no DELETE) — section "Scope discipline" ✓

**2. Placeholder scan:** No "TBD" / "fill in later" / unfilled code blocks. Tool import fallback in Task 6 mirrors Cutover 10's solved pattern.

**3. Type consistency:**
- `RunHub.__init__(hub_dir, eventhub=None)` — matches other hub ctors after Cutover 9 ✓
- `RunHub.start_run(*, branch, generated_dir, base_url, agent, compose=None, healthcheck=None, probe_runner=None, timeout_s=300)` — same kwargs in tests + impl + tool + prompt ✓
- `ProbePlan(method, url, body, headers)`, `ProbeSkip(reason)`, `ProbeOutcome(verdict, severity, note)` — same in planner + service + tests ✓
- `ComposeResult(returncode, stdout, stderr)`, `HealthcheckResult(healthy, status_code, attempts, elapsed_s, last_error)` — same in compose + service ✓
- Event types: `run_failed` (per-failure) + `run_completed` (per-run) — same in tests + impl + prompt ✓
- bug_artifacts payload keys (`affected_endpoint`, `expected`, `actual`, `response_body_excerpt`, `request_body`, `run_id`, `branch`, `latency_ms`, `transport_error`, `owner_hint`) — match Cutover 10's BugOrch `resolve_owning_agent` artifact schema (`affected_endpoint` is the key the resolver reads first) ✓

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 10 ✓
- Baselines green at every task boundary ✓
- TDD throughout ✓
- All subprocess + HTTP IO behind injectable callables — fully unit-testable without docker or httpx ✓
- `down()` always runs in `finally` — no orphaned containers if probe phase crashes ✓
