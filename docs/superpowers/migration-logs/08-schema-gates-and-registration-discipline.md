# 08 — Schema 3-Layer + Registration Discipline + Reviewer Gate

**Branch:** haibotong-cutover-7-schema-gates
**Predecessor:** haibotong-cutover-6-tool-surface-fill (merged into parent)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §6-8
**Plan:** docs/superpowers/plans/2026-05-23-cutover-7-schema-gates-and-registration-discipline.md

## Summary

Locks down PR/merge/registration so frontend ↔ backend ↔ database stay aligned
at code level. Five enforcement layers active simultaneously.

## Enforcement layers

L1: **APIHub write-time gate** — `register_consumer` / `register_table_consumer`
    reject unknown endpoint, deprecated endpoint, schema mismatch via the new
    `_schema_subset_check` helper.

L2: **CodeHub merge-time verifier gate** — `merge_pull_request` runs
    `_run_premerge_verifier_gate` before any git merge: every `linked_api`
    must have a recent passing contract test; every `linked_task` must be
    completed. Failure → PR status=premerge_failed + auto WorkHub fix task
    assigned to PR author with urgent priority.

**open_pr 7-gate** — `linked_tasks_required` / `insufficient_reviewers` /
    `linked_apis_unknown` / `linked_tasks_unknown` / `linked_pages_unknown` /
    `linked_consumers_unknown`. Orchestrator auto-injected unless author IS
    orchestrator.

**Strict approval** — `_is_pr_approved` requires ALL reviewers in `required`
    set to be in `approved` set (`required.issubset(approved)`).

**force_merge bypass** — `force_merge_pull_request(pr_id, reason, agent)`
    is orchestrator-only, requires reason ≥ 20 chars, emits urgent EventHub
    audit event before delegating to merge_pull_request.

## Files modified

- `runtime/apihub.py` — `_schema_subset_check` helper + L1 gates on register_consumer/register_table_consumer
- `runtime/hubs/codehub/service.py` — attach_apihub setter, rewritten open_pull_request (7 gates), suggest_reviewers, _run_premerge_verifier_gate, force_merge_pull_request, strict _is_pr_approved
- `runtime/hub_registry.py` — codehub.attach_apihub(apihub) wiring
- `tools/hub_tools.py` — extended CodeHubOpenPRTool params, added CodeHubSuggestReviewersTool + CodeHubForceMergeTool
- `multi_agent/tool_bundles.py` — widened _bundle_codehub_tools include_names
- `agents/agents_config.yaml` — deny codehub_force_merge for 9 non-orchestrator profiles

## Tools added (2)

- codehub_suggest_reviewers (weighted picker)
- codehub_force_merge (orchestrator-only, audit-logged)

## Test additions (6 new files)

- test_apihub_l1_write_time_gate.py (14 tests)
- test_codehub_open_pr_gates.py (7 tests)
- test_codehub_strict_approval.py (3 tests)
- test_codehub_suggest_reviewers.py (4 tests)
- test_codehub_premerge_gate.py (6 tests)
- test_codehub_force_merge.py (4 tests)

## Commits

10c99e97 Add CodeHub suggest_reviewers + force_merge LLM tools (orchestrator-only deny)
d6960a4d CodeHub.force_merge_pull_request: orchestrator-only bypass with audit
df9668b0 CodeHub L2 merge-time verifier gate (contract tests + task completion)
8d49cea2 Add CodeHub.suggest_reviewers (weighted picker, orchestrator mandatory)
b97a9c65 CodeHub: _is_pr_approved requires ALL reviewers approve, not just one
bbe2b696 CodeHub.open_pull_request: 7 gates (tasks/reviewers/apis/pages/consumers)
e5eec940 APIHub L1 write-time gate for register_table_consumer (expected_columns check)
09fa6155 APIHub L1 write-time gate: reject unknown/deprecated endpoint + schema mismatch
5c73a1c7 Add _schema_subset_check helper for APIHub L1 write-time gate

## Regression evidence

----------------------------------------------------------------------
Ran 7 tests in 0.714s

OK

Total hub tools: 61 (was 59).

## Next

Cutover 8 — step-pipeline integration (`hub_pulse` start-of-step + `hub_commit_gate` end-of-step + agent prompt updates).
