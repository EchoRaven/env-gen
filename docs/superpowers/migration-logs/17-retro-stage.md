# Cutover 16: Retro Stage (End-of-Generation Review)

**Branch:** `haibotong-cutover-16-retro`
**Date:** 2026-05-24

## What

Forced the orchestrator to produce a structured **retro** before
`deliver_project()` can succeed. End-of-generation reflection is now a
hard gate, not an optional habit: the orchestrator must compare the
plan against reality, name systematic failures, capture lessons, and
propose at least one concrete prompt change for a downstream agent —
otherwise the delivery tool refuses to ship.

- New WorkHub page `kind="retro"` (no new entity store — reuses the
  existing pages surface added in Cutover 14). Two helpers on
  `WorkHub`: `list_retros()` and
  `get_latest_retro_for_generation(generation_id)`.
- Pure read-side aggregator `runtime/retro_aggregator.py` exposes
  `RetroStats { bug_stats, run_stats, review_stats }` and
  `compute_retro_stats(hub_registry)`. No mutation. Used both by
  `submit_retro` to auto-populate the stats and by `get_retro_stats`
  so the orchestrator can inspect aggregates before writing the retro.
- 3 new LLM tools in `tools/retro_tools.py`:
  - `submit_retro(title, plan_vs_reality, systematic_failures, lessons,
    proposed_prompt_changes)` — validates required fields, auto-attaches
    `bug_stats` / `run_stats` / `review_stats`, stamps `generation_id`
    from the tool's session context.
  - `list_retros()` — lists `kind="retro"` pages with their
    `generation_id` for quick lookup.
  - `get_retro_stats()` — returns the live aggregate without persisting.
- `DeliverProjectTool.execute()` gains a pre-flight: if
  `agent.hub_registry.workhub.get_latest_retro_for_generation(
   agent._session_start_ts)` returns `None`, delivery is refused with
  "you must submit_retro before deliver_project". The gate is wrapped in
  try/except so malformed agent contexts (no registry, no session
  timestamp) bypass it safely rather than break delivery.
- `retro_tools` bundle registered in `tool_bundles.py` and wired to the
  `orchestrator` profile in `agents_config.yaml`.
- Orchestrator prompt (`prompts/v2/orchestrator_agent.j2`) gains a
  **RETRO DISCIPLINE** block teaching the
  `get_retro_stats → submit_retro → deliver_project` workflow and
  flagging that empty `proposed_prompt_changes` is rejected.

## Validation rules in `submit_retro`

- `plan_vs_reality` — list of ≥2 entries; each entry a dict with
  non-empty `plan_item` / `actual_outcome` / `drift_reason` strings.
- `systematic_failures` — may be `[]` (genuine "no recurring failures"
  is a valid answer), but the list must be supplied.
- `lessons` — list of ≥2 non-empty strings.
- `proposed_prompt_changes` — list of ≥1 entry; each entry a dict with
  non-empty `agent_profile` / `change_description` strings.
- `bug_stats` / `run_stats` / `review_stats` — caller does **not**
  supply them; the tool computes them via `compute_retro_stats(...)`.

## Reconciliations during implementation

Two small surfaces drifted from the plan template and were reconciled
during the cutover:

1. **`DeliverProjectTool.execute` signature.** The plan sketch assumed
   the existing `execute()` method had a single straight-through body
   where the retro pre-flight could be prepended. The actual method
   already does input parsing + checklist validation + workspace
   resolution before producing a `ToolResult`. The retro pre-flight was
   placed immediately after the `confirmation` / agent-context checks
   so the agent gets the same `ToolResult(success=False, ...)` shape
   used by every other early-exit branch, instead of grafting a new
   return path.
2. **`checklist` keys in tests.** Existing
   `DeliverProjectTool` checklist validation expects specific keys
   (`tests`, `docker`, `requirements`, `ux`). The plan's example
   payload happened to match, but new gate tests had to mirror that
   exact key set — otherwise the checklist gate fires before the retro
   gate and you'd see a misleading "missing checklist key" failure
   in the retro-gate tests. Both the dedicated gate tests
   (`test_deliver_retro_gate.py`) and the E2E
   (`test_retro_e2e.py`) use the full 4-key checklist.

## Commits

- `a0074ae2` Cutover 16: record pre-flight baseline (regressions 7 OK, discover 611 OK)
- `c1227f63` WorkHub: add list_retros + get_latest_retro_for_generation helpers
- `20432bd2` Add retro_aggregator: pure RetroStats from WorkHub bugs + RunHub runs + CodeHub PRs
- `462d1025` Add retro_tools: submit_retro / list_retros / get_retro_stats (validated, auto-stats)
- `3d3dc744` DeliverProjectTool: retro pre-flight - refuse if no retro for this generation_id
- `a544f605` Orchestrator: RETRO DISCIPLINE + wire retro_tools bundle
- `5524ea88` Add e2e: retro must precede deliver_project; gate blocks then unblocks

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 611 OK -> 636 OK (+25 new)

New test files:

- `agent/tests/test_workhub_retro.py` (5) — `list_retros` filter,
  generation lookup, latest-wins tie-break.
- `agent/tests/test_retro_aggregator.py` (4) — empty registry, bug
  severity/state breakdown, run pass/fail breakdown, PR force-merge
  counting.
- `agent/tests/test_retro_tools.py` (8) — happy path, each validation
  rule, stats auto-population, list, get-stats.
- `agent/tests/test_deliver_retro_gate.py` (3) — refused without retro,
  succeeds with matching-generation retro, refused with
  different-generation retro.
- `agent/tests/test_orchestrator_retro_prompt.py` (3) — prompt mentions
  `SUBMIT_RETRO`, calls out the prerequisite for `deliver_project`,
  lists the required retro fields.
- `agent/tests/test_retro_e2e.py` (2) — submit then deliver succeeds;
  deliver-without-retro refused, then submit unblocks delivery.

## New surfaces

- `multi_agent/runtime/hubs/workhub/service.py` — `list_retros()`,
  `get_latest_retro_for_generation(generation_id)`.
- `multi_agent/runtime/retro_aggregator.py` — `RetroStats` dataclass
  (`bug_stats` / `run_stats` / `review_stats` dicts, `to_dict()`),
  `compute_retro_stats(hub_registry)` plus private `_bug_stats` /
  `_run_stats` / `_review_stats` readers (all defensive when a hub or
  its store is missing).
- `tools/retro_tools.py` — `SubmitRetroTool`, `ListRetrosTool`,
  `GetRetroStatsTool`, shared `_RetroToolBase` (takes `hub_registry`
  and `generation_id` in `__init__`), `create_retro_tools` factory.
- `tools/agent_interaction_tools.py` — retro pre-flight added to
  `DeliverProjectTool.execute()` (early-return
  `ToolResult(success=False, ...)` when no retro exists for the
  current `_session_start_ts`).

## Updated prompts

- `multi_agent/prompts/v2/orchestrator_agent.j2` — new **RETRO
  DISCIPLINE** block in `lead_specifics()` teaching the
  `get_retro_stats → submit_retro → deliver_project` order, the
  required fields, and the explicit warning that empty
  `proposed_prompt_changes` is rejected.

## Updated config

- `multi_agent/tool_bundles.py` — `retro_tools` entry in
  `TOOL_BUNDLE_REGISTRY` + `TOOL_BUNDLE_REQUIREMENTS` (requires
  `memory`).
- `multi_agent/agents/agents_config.yaml` — `orchestrator` profile
  picks up the `retro_tools` bundle.

## Known gaps (future cutovers)

- `generation_id` is the orchestrator's session-start timestamp,
  carried on `agent._session_start_ts`. It works, but it leaks
  session-lifecycle state onto the agent object; a small
  `GenerationContext` value-type would be cleaner and would survive
  agent rebuilds within the same generation.
- `compute_retro_stats` reads each hub's `stores.*.value()` directly;
  this is fine at current volume but locks the aggregator to the
  current in-memory layout. A future cutover should route reads
  through `list_*` helpers (analogous to `runhub.list_runs`) once
  `CodeHub` and `WorkHub` grow them.
- The delivery gate uses `try/except: pass` defense-in-depth so that
  agents constructed without a real hub registry (older tests, smoke
  paths) don't break. A future cutover can tighten this once all
  construction paths are guaranteed to provide a registry and a
  session timestamp.
- The retro currently has no link back to the design pages or runs it
  references. Cross-linking
  (`retro.metadata.referenced_designs`, `referenced_runs`) would let
  future generations pivot from a lesson to the concrete artifact it
  came from.
- Retros do not yet feed back into the next generation's planning
  prompt. The proposed_prompt_changes list is stored but not applied;
  a future cutover could surface the most recent retro's
  `proposed_prompt_changes` into the relevant agents' system prompts
  on session start.
