# Cutover 8 — Pre-flight Baseline

Recorded for plan `docs/superpowers/plans/2026-05-23-cutover-8-step-pipeline-integration.md` Task 1.

## Worktree

- Branch: `haibotong-cutover-8-step-pipeline`
- Branched from: `red-env-gen/haibotong-0521-pipeline-web-tools`
- Parent tip commit: `f1389264` ("Add Cutover 8 plan: step pipeline integration (hub_pulse + hub_commit_gate)")
- Working tree: clean

## Baseline test results

Run from worktree root with `dt` conda env (`/home/haibotong/miniconda3/envs/dt/bin/python`).

### Regression suite

```
$ python agent/tests/run_regressions.py
Ran 7 tests in 0.437s
OK
```

- Tests run: 7
- Pass: 7
- Fail: 0
- Skip: 0

Matches plan expectation ("regressions 7 OK").

### Full unittest discover

```
$ python -m unittest discover agent/tests -p 'test_*.py'
Ran 312 tests in 35.988s
OK
```

- Tests run: 312
- Pass: 312
- Fail: 0
- Skip: 0

Matches plan expectation ("discover ~312 OK").

Non-fatal noise observed (informational only, not test failures):

- `CodeHub.merge_pull_request: no .git dir at /tmp/...; falling back to metadata-only merge` — expected fallback in tests using temp dirs without a real repo
- `ResourceWarning: unclosed event loop` from `asyncio/base_events.py` — pre-existing teardown warning, unrelated to Cutover 8

## Dead-stage references slated for removal (Task 5 / Task 6)

`grep -nE "inbox_status|crdt_changes|crdt_sync" agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py`:

- Line 81: `"inbox_status",` in `default_stage_order`
- Line 82: `"crdt_changes",` in `default_stage_order`
- Line 87: `"crdt_sync",` in `default_stage_order`
- Line 99: `"crdt_sync": 4,` (stage-index map)
- Lines 130-131: `inbox_status_prompt = None` / `crdt_changes_prompt = None`
- Lines 193-234: `inbox_status` stage block (gated by `_stage_enabled("inbox_status")`)
- Lines 236-259: `crdt_changes` stage block (gated by `_stage_enabled("crdt_changes")`)
- Lines 309-310: `inbox_status_prompt=` / `crdt_changes_prompt=` kwargs passed downstream
- Lines 368-369: `_run_crdt_sync_stage(enabled=_stage_enabled("crdt_sync"), ...)`

Per the plan, Task 5 replaces `inbox_status` + `crdt_changes` with `hub_pulse`, and Task 6 replaces `crdt_sync` with `hub_commit_gate`. Both new stages are engine-forced regardless of yaml.

## Ready for Task 2

Baseline matches plan expectations exactly. No unexpected failures. Proceeding to Phase A (TDD for the four new CodeHub helpers) is unblocked.
