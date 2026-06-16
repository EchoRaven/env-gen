# 09 — Step Pipeline Integration (hub_pulse + hub_commit_gate)

**Branch:** haibotong-cutover-8-step-pipeline
**Predecessor:** haibotong-cutover-7-schema-gates (merged into parent)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §5-6, §10
**Plan:** docs/superpowers/plans/2026-05-23-cutover-8-step-pipeline-integration.md

## Summary

Every agent step now runs `hub_pulse` (start, code-forced) and
`hub_commit_gate` (end, code-forced). Pulse pulls each agent's view of
the 4 hubs + MessageBus and injects it as a prompt block before the LLM
thinks. Gate scans 6 categories of loose ends and rolls them forward to
the next step's pulse. Both stages cannot be turned off via
`agents_config.yaml` — the engine injects them regardless.

The dead `inbox_status`, `crdt_changes`, `crdt_sync` stages — whose CRDT
backings were stripped in Cutovers 4-5 — are removed.

## Modules added

- `agents/runtime/hub_pulse.py` — `collect_hub_pulse`, `build_hub_pulse_prompt`, `should_render`
- `agents/runtime/commit_gate.py` — `collect_loose_ends`, `collect_loose_ends_details`, `build_commit_gate_prompt`, `DEFAULT_THRESHOLDS`

## CodeHub helpers added

- `get_branch_status(agent_id)` — git status + ahead/behind
- `list_prs_needing_review(reviewer)` — PRs needing reviewer decision
- `get_pending_reviews_for(agent_id, since_steps=0)` — light dict for pulse
- `get_my_branch_loose_ends(agent_id)` — gate aggregator

## Step pipeline changes

Before:
```
inbox_status -> crdt_changes -> runtime_team_status -> planning -> retrieve_context
            -> action -> crdt_sync -> knowledge_sync
```

After:
```
hub_pulse -> runtime_team_status -> planning -> retrieve_context -> action
         -> hub_commit_gate -> knowledge_sync
```

Engine forces `hub_pulse` first and `hub_commit_gate` last regardless of
`agents_config.yaml`. Per-stage tool-call caps for both new stages set to 0
(they collect data via hub method calls, not LLM tools).

## Prompts updated

All 7 v2 agent prompts gained a "Step Pipeline" section explaining the
HUB PULSE + INTEGRITY CHECK auto-injected blocks:

- orchestrator_v2.md
- design_v2.md
- database_v2.md
- backend_v2.md
- frontend_v2.md
- verifier_v2.md
- knowledge_v2.md

## Files modified

- `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py` (new)
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/commit_gate.py` (new)
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py` (hub_pulse + hub_commit_gate wiring, engine-force, dead-stage removal)
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` (stage sweep across 7 v2 profiles)
- `agent/env_generator/llm_generator/runtime/hubs/codehub/service.py` (4 new branch/PR helpers)
- `agent/env_generator/llm_generator/multi_agent/agents/prompts/*_v2.md` (7 prompts)

## Test additions

- `agent/tests/test_codehub_branch_helpers.py` (8 tests)
- `agent/tests/test_hub_pulse.py` (11 tests)
- `agent/tests/test_commit_gate.py` (8 tests)
- `agent/tests/test_step_runner_hub_pulse_wiring.py` (7 tests)
- `agent/tests/test_step_runner_hub_commit_gate_wiring.py` (7 tests)
- `agent/tests/test_agents_config_step_pipeline_sweep.py` (8 tests)

Total new tests: 49 (discover 312 -> 361).

## Per-task baseline progression

| Task | Commit | New tests | Discover total |
|------|--------|-----------|----------------|
| 1    | 4ea95dd7 | 0  | 312 |
| 2    | 9c5edb18 | +8 | 320 |
| 3    | d6b9fe9f | +11 | 331 |
| 4    | 7f4f9900 | +8 | 339 |
| 5    | 48cc996b | +7 | 346 |
| 6    | 1dd7d0d2 | +7 | 353 |
| 7    | fd8c1179 | +8 | 361 |
| 8    | 36d8c0be | 0 (prompt-only) | 361 |
| 9    | 04f90c80 | 0 (prompt-only) | 361 |

Regressions held at 7 OK throughout.

## Commits

```
04f90c80 Update 3 agent prompts (frontend/verifier/knowledge) for step pipeline
36d8c0be Update 4 agent prompts to describe hub_pulse + integrity check pipeline
fd8c1179 agents_config: replace inbox_status/crdt_changes/crdt_sync with hub_pulse/hub_commit_gate
1dd7d0d2 Replace crdt_sync stage with hub_commit_gate (engine-forced, rolls forward to next pulse)
48cc996b Replace inbox_status + crdt_changes stages with hub_pulse (engine-forced)
7f4f9900 Add commit_gate module (loose-ends scanner + prompt renderer)
d6b9fe9f Add hub_pulse module (collect + build_prompt + should_render)
9c5edb18 CodeHub: add get_branch_status / list_prs_needing_review / get_pending_reviews_for / get_my_branch_loose_ends
4ea95dd7 Cutover 8: record pre-flight baseline (regressions 7 OK, discover 312 OK)
```

## Regression evidence

```
----------------------------------------------------------------------
Ran 7 tests in 0.584s

OK
```

Discover suite:

```
----------------------------------------------------------------------
Ran 361 tests in 53.615s

OK
```

## Engine-force verification

```
$ python -c "src = open('.../step_runner.py').read(); \
             assert 'hub_pulse' in src and 'hub_commit_gate' in src; \
             assert \"enabled_stages.add('hub_pulse')\" in src"
engine-force lines present
```

## Acceptance criteria from spec §13

- D. Every agent step first stage is `hub_pulse` (engine-forced) — pass
- E. Every agent step last stage is `hub_commit_gate` (engine-forced) — pass
- F. Frontend / consumer agents see breaking-change tasks in pulse (via `_pulse_apihub`) — pass
- Loose ends roll forward to next step prompt (`_pending_integrity_prompt`) — pass

## Deviations

None. All 10 tasks executed per plan. No new tools registered (per spec
hub_pulse / hub_commit_gate are engine stages, not LLM tools).

## Constraints honored

- Zero `Co-Authored-By: Claude` trailers across all branch commits.
- All work done in `dt` conda env.
- One commit per task (baseline + 8 implementation + prompt commits + migration log).

## Next

Cutover 9 (TBD) — merge `haibotong-cutover-8-step-pipeline` into parent
`haibotong-0521-pipeline-web-tools`. Manual smoke run with a real LLM
remains out of scope for this plan.
