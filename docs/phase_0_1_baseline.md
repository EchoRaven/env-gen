# Phase 0.1 Baseline — FROZEN

> Frozen 2026-05-30 after reviewer's APPROVED sign-off on
> Phase 0.1 (with the method-level-delete correction applied in
> commit `0a785334` and sibling rescopes in commit `f55003e3`).
> This file is referenced by every later phase's pre-existing
> failures line per `docs/progressive_elaboration_refactor.md` §6
> submission template.

## Frozen state

| Field | Value |
|---|---|
| Baseline date | 2026-05-30 |
| Branch | `haibotong-0527-hub-focus-and-tooling-cleanup` |
| Commit SHA | `f55003e3` (sibling rescopes; the final Phase 0.1 commit before this baseline freeze) |
| `pytest --collect-only` total | **1581 tests** |
| `pytest tests/` passing | **1581** |
| `pytest tests/` failing | **0** |
| `pytest tests/` errors | **0** |

## Phase 0.1 commits (full chain)

| Commit | Title | Effect on suite |
|---|---|---|
| `dc2a7362` | docs: SDLC refactor plan + Phase 0.1 red-test triage | (no test changes) |
| `7826712f` | fix(tests): ENV_RED fixture hygiene | 13 RED → GREEN |
| `b740657f` | fix(tests): pass agent='orchestrator' to create_release | 1 RED → GREEN |
| `1057a7e1` | fix(llm): flatten Anthropic content for single-text turns | 1 RED → GREEN |
| `1cac7349` | fix(security): restore env-driven auth_required() | 4 RED → GREEN (+ closes reviewer 3.1 critical #2) |
| `563746b3` | fix(runtime): hub_registry migration old_dir was equal to new_dir | 1 RED → GREEN (+ closes reviewer 3.7 high #2) |
| `b648b04b` | chore(tests): repair run_regressions.py — delegate to pytest | (infra) |
| `1c8d9be8` | docs(plan): fill in Phase 0.1 implementation log | (docs) |
| `0a785334` | cleanup(tests): delete 11 OBSOLETE tests per reviewer sign-off | 11 RED → REMOVED (with method-level correction) |
| `f55003e3` | refactor(tests): rescope DeliverProject *_gate siblings to happy-path smoke | (rename only; preserves 2 passing tests, no count change) |

Net delta: **1528 passing / 31 failing  →  1581 passing / 0 failing**.

## What this baseline means for later phases

Per `docs/progressive_elaboration_refactor.md` §5 Phase 0.1
"Baseline snapshot frozen" rule and §6 submission template:

- Every later phase's submission report must list pre-existing
  failures **VERBATIM** against this baseline. Since the baseline
  is 0 failing, there are no pre-existing failures any phase can
  claim — any red surfaced in a later phase IS that phase's red,
  not background noise.
- Every later phase's acceptance gate requires
  `passing_count_after ≥ 1581`.

## Reproducing the baseline

```bash
cd agent
# (Setup once)
pip install -r utils/requirements.txt
pip install pytest pyyaml

# Verify baseline
python -m pytest tests/ --no-header -q --tb=no
# Expected: "1581 passed, ... in <X>s"
```

If the count diverges:
- **Higher**: someone added passing tests since the baseline. OK,
  but update this doc and re-baseline.
- **Lower**: regression. **STOP** and triage before progressing
  to the next phase.

## Closed reviewer audit items (from Phase 0.1)

| Reviewer audit item | Severity | Closed by |
|---|---|---|
| 3.1 critical #2 (unauthenticated RCE-enabler: `auth_required` hardcoded False) | 🔴 | commit `1cac7349` |
| 3.7 critical (test suite RED + no CI) | 🔴 | commit `b648b04b` + this baseline |
| 3.7 high #2 ("red tests encode shipping bugs": migration was no-op) | 🟠 | commit `563746b3` |

The Phase 0.2 deliverables (RCE-enabler in 3.1 critical #2) landed
early as a happy byproduct of Phase 0.1's red-test triage. Remaining
Phase 0.2 items (monitor force_merge/start_run/delete_project role
checks, PathRoutedWorkspace containment, docker-compose privileged-block)
stay in Phase 0.2 scope.

## Closed Phase 0.1 acceptance refinements

| Refinement | Source | Folded into |
|---|---|---|
| Whole-file delete requires full test inventory + all-OBSOLETE confirmation | Reviewer round-2 sign-off follow-up #2 | §5 Phase 0.1 acceptance gate (commit landed alongside this baseline) |
| Sibling tests post-gate-removal renamed to happy-path smoke | Reviewer round-2 sign-off follow-up #1 | commit `f55003e3` |
