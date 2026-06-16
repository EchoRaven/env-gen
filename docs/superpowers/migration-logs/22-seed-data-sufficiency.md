# Cutover 21: Seed Data Sufficiency Gate

**Branch:** `haibotong-cutover-21-seed-data`
**Date:** 2026-05-25

## What

Block `deliver_project()` if any APIHub-registered table:
- Has no `register_seed_data` entry (`missing_seed`)
- Has fewer rows than required (`low_row_count`, default 5)
- Contains placeholder content (`user1`/`lorem ipsum`/etc., score >= 0.5)

Database agent self-reports via `register_seed_data(table, row_count, sample_excerpt)`. Audit reads registrations; no file scanning needed.

## Commits

- `ba9e0530` Cutover 21: record pre-flight baseline (regressions 7 OK, discover 788 OK)
- `898b7ab1` APIHub: add register_seed_data + get_seed_data + list_seed_registrations
- `e0eea317` Add seed_audit: detect placeholder content + audit row counts per table
- `f9a2955e` Add seed_tools: register_seed_data / seed_audit_check / list_seed_issues + database/orch/verifier wiring
- `c77f06bb` DeliverProjectTool: seed audit gate (refuse if any table missing seed / low rows / placeholder content)
- `b9275afb` Database + orchestrator prompts: SEED DATA DISCIPLINE + SEED SUFFICIENCY workflow
- (this commit) Add Cutover 21 e2e + migration log

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 788 OK -> 829 OK (+41 new)

## New surfaces
- APIHub: register_seed_data / get_seed_data / list_seed_registrations + _seed_registrations JsonStore
- runtime/seed_audit.py: detect_placeholder_score + audit_seed_data
- tools/seed_tools.py: 3 LLM tools
- DeliverProjectTool seed gate
- Database + orchestrator prompts: SEED DATA DISCIPLINE + SEED SUFFICIENCY workflow

## Placeholder detection rubric
- Generic words (test/foo/bar/lorem/etc.): each match +0.15 (capped at 5)
- Sequential names (user1, item_2): each match +0.30 (capped at 3)
- All-same-boolean column (3+ rows): +0.20
- Threshold for fail: score >= 0.5

## Bypass mechanisms (Cutover 19/20 patterns reused)
- `min_seed_rows=0` in table metadata -> opt out per-table at design time
- `mark_intentionally_dead('seed:<table>', reason)` -> orchestrator allowlist
- `deliver_project(force_deliver=True)` -> orchestrator-only audited bypass (publishes `seed_audit_bypass` EventHub event)

## Known limits (future cutovers)
- Audit reads agent-reported registrations, not real DB state. If database agent
  reports false row_count, audit can't catch it. Future cutover: tie to RunHub
  DB query that verifies actual COUNT(*).
- Placeholder detection is heuristic (regex + word list). False positives
  possible (e.g., real customer named "Test" who exists). Override via
  mark_intentionally_dead allowlist.
- No referential integrity / FK coverage / time-series diversity yet.
