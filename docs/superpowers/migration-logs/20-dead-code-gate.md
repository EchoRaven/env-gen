# Cutover 19: Dead-Code Detection + Reverse-Consumer Gate

**Branch:** `haibotong-cutover-19-dead-code`
**Date:** 2026-05-25

## What

Reverse-direction coverage gate: `deliver_project()` now refuses if any:
- APIHub endpoint with zero consumers exists
- APIHub table with zero exposing endpoints exists
- frontend/backend source file imported by nothing exists

…unless explicitly whitelisted via `mark_intentionally_dead(path, reason)`
or bypassed via orchestrator-only `force_deliver=True` (audited).

## Why

Schema gates (Cutover 7) ensure declared APIs/tables are *implemented*.
They don't check the reverse — that every *implemented* artifact is *used*.
The system could ship endpoints nobody calls, components nobody imports,
tables nobody exposes. All passed previous gates.

## Commits

- `05c94365` Cutover 19: record pre-flight baseline (regressions 7 OK, discover 698 OK)
- `de5785f2` Add coverage_audit: scan dead APIHub endpoints/tables + dead source files (+17 tests; Python resolver hardened to handle `__init__.py` auto-load)
- `dd73e527` WorkHub: add coverage_allowlist page kind + list/mark_path_intentionally_dead helpers (+6 tests)
- `222980d3` Add coverage_tools: coverage_audit_check / mark_intentionally_dead / list_dead_allowlist + orch wiring (+4 tests)
- `78eb92a7` DeliverProjectTool: coverage pre-flight gate + orchestrator-only force_deliver audit bypass (+5 tests)
- `971c111f` Orchestrator prompt: COVERAGE DISCIPLINE + workflow + force_deliver bypass (+4 tests)
- `4779ea2d` Add coverage E2E: dead endpoint/file blocks deliver; consumer/allowlist unblocks; force audit event (+3 tests)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 698 OK -> 737 OK (+39 new)

## New surfaces
- runtime/coverage_audit.py (~180 LoC pure scanner)
- tools/coverage_tools.py (3 tools)
- WorkHub: list_coverage_allowlist + mark_path_intentionally_dead
- DeliverProjectTool: coverage pre-flight + force_deliver kwarg
- Orchestrator prompt: COVERAGE DISCIPLINE block

## Known limits / future work
- Static regex import scan misses dynamic imports (React.lazy with computed paths)
- Python import resolver is MVP — false positives on cross-package imports
- mark_intentionally_dead is per-generation; no rolling allowlist across generations
- AST-aware scanning is a future cutover
