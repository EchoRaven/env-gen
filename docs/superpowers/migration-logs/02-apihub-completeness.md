# 02 — APIHub Completeness Cutover

**Branch:** haibotong-cutover-1.5-apihub-completeness
**Predecessor:** Cutover 1 (APIHub core, tip e31e66a8)
**Audit reference:** docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md §2.2

## Summary

Closes the audit-flagged gaps in APIHub: 5 public accessors that previously existed only in the LLM tool layer (reaching into private CRDT stores), plus the missing `submit_api_review` to transition review status. Adds `apihub_submit_review` LLM tool. Refactors `apihub_get_dependencies_for_file` and `apihub_get_breaking_changes` tools to use the new public accessors.

## Methods added to APIHub

- `get_consumers(endpoint_id) -> List[dict]`
- `get_dependencies_for_file(file_path) -> List[dict]`
- `get_breaking_changes(since_ts=None) -> List[dict]`
- `get_contract_test_results(endpoint_id) -> List[dict]`
- `submit_api_review(review_id, reviewer, decision, comments)` — completes the review lifecycle started by `request_api_review`

## Tools added

- `apihub_submit_review`

## Tools refactored to use public accessors

- `apihub_get_dependencies_for_file`
- `apihub_get_breaking_changes`

## Tests

- New: `agent/tests/test_apihub_accessors.py` — 11 tests across the 5 new methods
- Updated: `agent/tests/test_apihub_tools.py` — added `apihub_submit_review` to REQUIRED_TOOLS
- Combined apihub suite total: 29 tests (was 18 post-Cutover 1; up by 11)

## Commits

2abbdf61 Refactor apihub tools to use public accessors + add apihub_submit_review tool
6004568f Add APIHub.submit_api_review to close review lifecycle
65cfe3da Add APIHub.get_contract_test_results public accessor
58d83490 Add APIHub.get_breaking_changes public accessor with since_ts filter
a4f061ec Add APIHub.get_dependencies_for_file public accessor
caa3cd0e Add APIHub.get_consumers public accessor

## Regression evidence

----------------------------------------------------------------------
Ran 7 tests in 0.927s

OK

Combined apihub-related suite: 29 tests, all passing.

## Code quality verification

- `grep -rn "_consumers.value\|_breaking_changes.value" agent/env_generator/llm_generator/tools/` returns zero matches.
- `git log --pretty=%B e31e66a8..HEAD | grep -c "Co-Authored-By:"` returns 0.

## Next

Cutover 2 — EventHub MessageBus bridge. The current EventHub is a write-only store; bridge wiring is required before WorkHub or CodeHub additions can rely on push-based event delivery.
