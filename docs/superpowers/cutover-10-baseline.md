# Cutover 10 Baseline (Bug Triage Orchestrator)

Captured before any code changes on branch `haibotong-cutover-10-bug-triage`.

## Test counts
- regressions: 7 OK
- discover: 393 OK

## Existing surfaces this cutover will extend
- WorkHub: `create_task(..., **metadata)` already accepts arbitrary metadata
- EventHub: `subscribe(agent, source_hub, event_type, ...)` and `publish_event(source_hub, event_type, payload, ...)` already exist
- APIHub: `register_endpoint(..., provider=)` and `register_table(..., provider=)` track owning agent

## Existing agent profiles (10)
orchestrator, design, database, backend, frontend, verifier, knowledge, analysis_worker, review_worker, worker

## New profile this cutover adds (1)
bug_triage_orchestrator
