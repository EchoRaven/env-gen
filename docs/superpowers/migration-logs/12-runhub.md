# Cutover 11: RunHub

**Branch:** `haibotong-cutover-11-runhub`
**Date:** 2026-05-24

## What

Add a fifth hub - **RunHub** - that actually stands a generated backend service up
(`docker compose up`), waits for it to come healthy, and exercises one safe probe
per endpoint to confirm the service responds. The orchestrator can now call
`run_start(env_id)` after a backend PR merges to convert "code compiles" into
"code runs", and runtime failures publish events that flow into Cutover 10's
BugTriageOrchestrator for owner assignment.

MVP scope is intentionally backend-only:
- Safe probes only (GET, plus 200/401/403/404/405 classification).
- No auth-protected POST/PUT/PATCH (requires a credential flow not yet designed).
- No DELETE (destructive).
- No UI / browser tests (Playwright is a future sub-cutover).

## Why

The previous pipeline could merge PRs whose code passed unit tests but whose
service would never boot (missing env var, port collision, broken healthcheck,
bad route mount). Verifier had no runtime signal; bugs surfaced only when a
human ran the stack. RunHub closes that gap with a deterministic, scriptable
"does it actually run" gate, and shapes failures so the BugTriageOrchestrator
can route them to backend / database / etc. without human triage.

## Commit history

```
28b14f9d Cutover 11: record pre-flight baseline (regressions 7 OK, discover 443 OK)
edb1222d RunHub: add pure probe planner (plan_probe + classify_probe_result)
cdc67c57 RunHub: add ComposeLifecycle (up/down) + HealthcheckProbe (HTTP poll with backoff)
86aea992 RunHub: add service skeleton + RunHubStores; wire as 5th hub in HubRegistry
20e75a0d RunHub: implement start_run orchestration (compose up + healthcheck + probe + events)
d7b5cb9e Add run_tools LLM surface (run_start / run_status / run_list / run_get)
6151957e Orchestrator: wire run_tools bundle (orchestrator can now invoke run_start)
8bddf271 Orchestrator prompt: RUN VERIFICATION DISCIPLINE - call run_start after backend PR merge
e15ddc48 hub_pulse: surface RECENT RUN section to orchestrator / bug_triage_orchestrator
```

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 443 OK -> 491 OK (+48 new tests across probe planner, compose
  lifecycle, healthcheck poller, RunHub service, run_tools, orchestrator wiring,
  prompt rendering, and hub_pulse RECENT RUN section)

## New surfaces

- `multi_agent/hubs/runhub/probe_planner.py` - pure `plan_probe` /
  `classify_probe_result` (no I/O, fully unit-tested)
- `multi_agent/hubs/runhub/compose_lifecycle.py` - `ComposeLifecycle.up/down`
  wrapping `docker compose` with timeout + stdout/stderr capture
- `multi_agent/hubs/runhub/healthcheck_probe.py` - `HealthcheckProbe.wait_ready`
  HTTP poller with exponential backoff
- `multi_agent/hubs/runhub/service.py` - `RunHub.start_run` orchestration:
  compose up -> healthcheck -> per-endpoint probe -> publish `run_started` /
  `run_succeeded` / `run_failed` events
- `multi_agent/hubs/runhub/stores.py` - `RunHubStores` (in-memory run records)
- `multi_agent/hubs/registry.py` - RunHub registered as 5th hub alongside
  APIHub/CodeHub/EventHub/WorkHub
- `tools/run_tools.py` - 4 LLM tools (`run_start`, `run_status`, `run_list`,
  `run_get`)
- `multi_agent/runtime/agent_runtime.py` - orchestrator profile loads
  run_tools bundle
- `prompts/v2/orchestrator_agent.j2` - "RUN VERIFICATION DISCIPLINE" section
  requires `run_start` after every backend PR merge
- `multi_agent/runtime/hub_pulse.py` - new `RECENT RUN` section visible to
  orchestrator + bug_triage_orchestrator

## Run lifecycle

```
run_start(env_id)
   |
   v
ComposeLifecycle.up  --(fail)-->  publish run_failed{stage=compose_up}
   |                                       |
   |                                       +--> BugTriageOrch picks up,
   v                                            resolves owner (devops / backend),
HealthcheckProbe.wait_ready                     opens bug task
   |
   +--(timeout)--> publish run_failed{stage=healthcheck}
   |
   v
for endpoint in APIHub.list_endpoints:
   plan_probe(endpoint) -> HTTP call -> classify_probe_result
   |
   +--(unexpected status)--> bug_artifacts={endpoint, status, body}
   |                          publish run_failed{stage=probe, ...}
   v
all probes OK -> publish run_succeeded
ComposeLifecycle.down
```

## Integration with Cutover 10 (BugTriageOrchestrator)

`run_failed` events carry `bug_artifacts` shaped to match the resolver in
`multi_agent/runtime/bug_triage.py`:

- `affected_endpoint` (e.g. `POST /users`) -> resolver heuristic routes to the
  APIHub provider that owns it -> usually `backend`.
- `owner_hint` (e.g. `database` when the failure is an SQL error in the response
  body) overrides the heuristic.
- `stage=compose_up` failures default to `backend` (compose/Dockerfile is in
  the backend repo today; a `devops` owner will be added in a later cutover
  if/when that surface separates).

BugTriageOrch consumes these via the same hub_pulse `OPEN BUG QUEUE` it already
watches, so no new wiring was needed on the consumer side.

## Known MVP gaps (deferred)

- **Auth-protected mutations (POST/PUT/PATCH on protected routes)**: probe
  planner skips them rather than sending unauthenticated requests that would
  always 401. Needs a credential-provisioning flow (seed user / token mint) -
  scoped for a follow-up cutover.
- **DELETE**: skipped wholesale (destructive on a real DB).
- **UI / browser tests**: no Playwright driver. RunHub today verifies backend
  reachability + per-endpoint response shape only; full user-flow verification
  is a separate sub-cutover.
- **Concurrent runs**: `start_run` is sequential per env_id. If two orchestrators
  race on the same env, second call will fail at compose-up (port conflict).
  Acceptable for current single-orchestrator workflow.
- **Long-running services**: compose stack is torn down after probes complete.
  No "keep running for manual inspection" mode yet.

## Verification

- Zero Claude trailers across all 9 commits
- Both baselines green (7 OK / 491 OK)
- New hub registered + service wired + tools loadable + prompt renders +
  hub_pulse section emits + BugTriageOrch artifact shape matches resolver
