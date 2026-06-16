# Cutover 12: Runtime Feedback Loop

**Branch:** `haibotong-cutover-12-feedback-loop`
**Date:** 2026-05-24

## What

Closed the chain `RunHub publishes run_failed` -> `BugTriageOrchestrator receives via
subscription` -> `BugTriageOrch creates WorkHub bug task` -> `owning agent's hub_pulse
shows the assigned bug`. Before this cutover, RunHub and Verifier published bug events
but no agent was subscribed, so they never reached anyone's inbox.

## Commits

- `9c7eff8e` Cutover 12: record pre-flight baseline (regressions 7 OK, discover 491 OK)
- `2513aa82` Add agent_subscriptions: DEFAULT_SUBSCRIPTIONS + ensure_default_subscriptions (idempotent)
- `8c1947a0` hub_pulse: install default subscriptions for agent on every pulse (idempotent)
- `23a44884` Add end-to-end test: RunHub failure -> BugTriageOrch inbox -> WorkHub bug -> owner pulse
- `9ac6ddd3` BugTriageOrch prompt: list runhub/run_failed alongside verifier/bug_found as sources
- `d83f6fed` Orchestrator prompt: BugTriageOrch auto-handles RunHub failures (no manual triage)

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
