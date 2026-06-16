# Cutover 24: Deliverable Verification Stage

**Branch:** `haibotong-cutover-24-deliverability`
**Date:** 2026-05-26

## What

Replace LLM-judged `checklist` with evidence-based deliverability verification.
DeliverProjectTool adds NEW gate: refuses if no successful RunHub run started
≥ agent._session_start_ts. Unified `deliverability_check` LLM tool returns
aggregated report (latest run + endpoint probes + MCP probes + coverage +
seed + visual reviews). Orchestrator prompt teaches the new workflow:
`run_start → deliverability_check → deliver_project`.

## Why

Cutovers 16/19/20/21 added evidence-based gates (retro / coverage / visual /
seed) but none enforced that RunHub actually ran. Orchestrator could deliver
having never spun up the app. The user-judged checklist was pure
self-assertion (`{no_bugs: True, requirements_met: True, ...}`).

## Commits

- `58cf994b` Cutover 24: record pre-flight baseline (regressions 7 OK, discover 891 OK)
- `e95eeda4` RunHub: add last_successful_run_since(ts) -> most recent fully-passing run after timestamp
- `df53cb92` Add deliverability aggregator: unified report over RunHub + Coverage + Seed + Visual
- `2893bc69` Add deliverability_tools (check + summary) + wire to orchestrator
- `12da8761` DeliverProjectTool: RunHub-since-session gate + deliverability_bypass force-bypass
- `3785968c` Orchestrator prompt: DELIVERABILITY DISCIPLINE block (run_start->check->deliver)
- (this commit) Add Cutover 24 e2e + migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Discover: 891 OK → 920 OK (+29 new)

## New surfaces

- `runtime/deliverability.py` — `DeliverabilityReport` dataclass + `compute_deliverability(hub_registry, app_root, session_start_ts)` pure aggregator
- `tools/deliverability_tools.py` — 2 tools: `deliverability_check` (full report) + `deliverability_summary` (one-line verdict)
- `RunHub.last_successful_run_since(ts) -> Optional[dict]` — filters status="completed" + fail_count==0 + started_at >= ts
- `DeliverProjectTool` adds RunHub-since-session gate + `deliverability_bypass` force_deliver bypass
- Orchestrator prompt: DELIVERABILITY DISCIPLINE block

## Migrations: 17 fixture updates across 9 prior deliver tests

Cutover 5 (the gate addition) broke 17 pre-existing tests because they didn't
insert a successful RunHub run before calling `deliver_project()`. Subagent
migrated each fixture by adding an `_insert_passing_run(reg, started_at=gen_id+1.0)`
helper:

**Gate-specific tests** (4 files, 9 tests):
- `test_deliver_retro_gate.py` — 1 test (gen_id=1000.0)
- `test_deliver_coverage_gate.py` — 2 tests (gen_id=1000.0)
- `test_deliver_seed_gate.py` — 3 tests (gen_id=5000.0)
- `test_deliver_visual_gate.py` — 3 tests (gen_id=3000.0)

**E2E tests** (5 files, 8 tests):
- `test_coverage_e2e.py` — 2 tests (gen_id=2000.0)
- `test_mcp_e2e.py` — 1 test (gen_id=7000.0)
- `test_retro_e2e.py` — 2 tests (gen_ids 2000.0 + 3000.0)
- `test_seed_e2e.py` — 2 tests (gen_id=6000.0)
- `test_visual_review_e2e.py` — 1 test (gen_id=4000.0)

All 17 satisfied the new gate cleanly with the helper while still exercising
their specific cutover-gate. Tests that were supposed to keep failing (e.g.
coverage/seed/visual/MCP gate-specific block assertions) continued to block
at their earlier-ordered gate.

## Deprecation

Old `checklist` kwarg on `DeliverProjectTool.execute()` still accepted (backward
compat). Orchestrator prompt teaches replacing it with `deliverability_check()`.
A future cutover may strip the kwarg entirely.

## Bypass mechanisms (consistent with Cutovers 19-23)

- `force_deliver=True` — orchestrator-only audited bypass; publishes
  `deliverability_bypass` EventHub event
- `mark_intentionally_dead(...)` allowlist — for individual blockers from
  coverage/seed/visual sub-gates (those still enforce separately)

## Known limits (future cutovers)

- "Successful run" = status="completed" + fail_count=0; could add stricter
  checks (all critical pages had screenshots captured)
- Aggregator's `blockers` list is informational at delivery time — per-gate
  enforcement is the source of truth. Could consolidate enforcement in a
  follow-up.
- No per-blocker severity in the report (e.g., "informational only"); future
  enhancement.
- LLM checklist still accepted (deprecation event but not refused).
