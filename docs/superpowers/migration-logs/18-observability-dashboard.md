# Cutover 17: Observability Dashboard (FINAL CUTOVER)

**Branch:** `haibotong-cutover-17-observability`
**Date:** 2026-05-24

## What

Pure aggregator over `.agent_logs/<Agent>/*.jsonl` -> self-contained HTML
dashboard. No JS, no CDN, no live server, no new dependencies (stdlib only).
Surfaces: Python module, CLI (`python -m multi_agent.runtime.observability`),
and LLM tool (`observability_dashboard`, orchestrator profile).

## This is the FINAL cutover (17 / 17)

Roadmap end-to-end: 4 hubs (Cutovers 1-5) -> tool surface fill (6-7) ->
step-pipeline integration + schema gates (7-9) -> CRDT scaffolding purge
(10) -> bug triage orchestrator + runtime feedback loop (10-12) -> review
quality (13) -> design review (14) -> structured knowledge (15) -> retro
(16) -> observability (17). The system now has structural gates at every
checkpoint plus visibility into its own execution.

## Commits on this branch

```
b3117b5a Cutover 17: record pre-flight baseline (regressions 7 OK, discover 636 OK)
8a4958a8 Add observability log_parser + aggregator (LogStats/AgentStats, top tools, event types)
9c627643 Add observability dashboard.py: render_dashboard(LogStats) -> self-contained HTML
7ef7819c Add observability CLI (python -m) + LLM tool (observability_dashboard); wire to orchestrator
9ffbe51d Add e2e: aggregate real .agent_logs/ and render dashboard
```
(+ this migration-log commit, which also adds the rendered dashboard artifact.)

## Test deltas (this cutover)
- Regressions: 7 OK -> 7 OK
- Discover: 636 OK -> 666 OK (+30 new across parser, dashboard, tool, e2e)

## Real-data sanity (this branch)
The dashboard was rendered from this project's actual `agent/.agent_logs/`:
- 8 agents (Backend / Database / Design / Frontend / QA / Task / Task Runner / User)
- 37,197 events aggregated
- Output: `docs/superpowers/observability/dashboard.html` (committed as artifact)

## Roadmap totals (Cutovers 1 - 17)
- **Started:** ~312 discover tests, CRDT scaffolding, no structural gates
  beyond "code compiles", no observability surface.
- **Ended:** 666 discover tests (+354), 5 hubs (APIHub / EventHub / WorkHub /
  CodeHub / RunHub), 12 agent profiles, 10 hard structural gates,
  0 Claude trailers across the entire roadmap.

## Gates added across the 17 cutovers (in order)
1. **Schema gates, 3-layer defense** (Cutover 7) — validator at producer,
   consumer, and persistence boundaries.
2. **Registration discipline / APIHub provider tracking** (Cutover 7) —
   every tool registered through a single provider with audit trail.
3. **>=2 reviewer including orchestrator** (Cutover 7) — no single-reviewer
   merges; orchestrator counts as one of the two.
4. **force_merge orchestrator-only audit** (Cutover 7) — emergency override
   restricted and logged.
5. **hub_pulse engine-forced step-start** (Cutover 8) — every step opens
   with a pulse event the engine emits, not the agent.
6. **hub_commit_gate engine-forced step-end** (Cutover 8) — every step
   closes through a commit-gate the engine enforces.
7. **Bug Triage Orchestrator + runtime feedback loop** (Cutovers 10 - 12) —
   failures flow back as triage tickets, not silent retries.
8. **Substantive PR review** (Cutover 13) — review stage must produce a
   substantive verdict; rubber-stamps blocked.
9. **Architect design review with >=3 challenges** (Cutover 14) —
   architect must articulate at least three concrete design challenges
   before approval.
10. **Mandatory retro before deliver_project** (Cutover 16) — no project
    delivery without a recorded retro entry.

## Observability surface (Cutover 17)
- `LogStats` / `AgentStats` dataclasses (`log_parser.py`)
- `aggregate_logs(logs_dir: Path) -> LogStats` (pure, ~100 LoC)
- `render_dashboard(stats, output_path=None) -> str` (pure, ~100 LoC,
  self-contained HTML with inline CSS, no JS, no CDN)
- CLI: `python -m multi_agent.runtime.observability --logs-dir X --output Y`
- LLM tool: `observability_dashboard` (orchestrator profile, knowledge bundle)
- Committed artifact: `docs/superpowers/observability/dashboard.html`

## Closing note

This is the final cutover of the 17-cutover roadmap. The pipeline now has
defense-in-depth at every stage and can also look at itself.
