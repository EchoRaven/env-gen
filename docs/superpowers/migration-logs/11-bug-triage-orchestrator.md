# Cutover 10: Bug Triage Orchestrator

**Branch:** `haibotong-cutover-10-bug-triage`
**Date:** 2026-05-24

## What

Split the bug-handling workflow into three single-responsibility roles per advisor's recommendation:

- **Verifier**: DETECT bugs (publish `verifier/bug_found` event via new `bug_create` tool). No more triage or assignment.
- **Bug Triage Orchestrator (NEW)**: receive bug events -> root-cause hypothesis -> resolve owning agent (APIHub provider / file-path heuristic) -> assign remediation task. Never edits code.
- **Owning agent** (backend / database / frontend): pick up assigned bug from hub_pulse -> fix -> close with evidence.

Bugs ride on existing WorkHub tasks via `metadata.kind="bug"` plus structured fields (`severity`, `bug_state`, `root_cause_hypothesis`, `parent_bug_id`, `bug_artifacts`, `triage_history`).

## Why

Verifier was doing detection + analysis + assignment - three distinct skills.
Real engineering separates these (monitoring != root cause != fix). Concentrating
them on Verifier hurt analysis quality and made escalation impossible.

## Commit history

```
4f58c03f Cutover 10: record pre-flight baseline (regressions 7 OK, discover 393 OK)
fbfe6761 WorkHub: add list_open_bugs / list_bugs_assigned_to (filter by metadata.kind=bug)
a9d26b90 WorkHub: add update_bug_state / close_bug / escalate_bug with triage_history audit
fdcd6693 Add bug_triage owning-agent resolver (endpoint/table/file path heuristics)
d5a87438 Add bug_tools LLM tool surface (create/list/triage/update/close/escalate)
b17f4eff Add bug_triage_orchestrator agent profile to agents_config.yaml
3be51006 Add bug_triage_orchestrator_agent.j2 prompt with hard discipline rules
454fec70 Verifier: detect-only - bug_create publishes event, no direct task creation or assignment
7f65a697 hub_pulse: surface assigned bugs (all agents) + open bug queue (bug_triage_orch only)
```

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 393 OK -> 443 OK (+50 new tests across WorkHub helpers, resolver, tools, config, prompts, hub_pulse rendering)

## New surfaces

- `multi_agent/runtime/bug_triage.py` - owning-agent resolver (~80 LoC)
- `tools/bug_tools.py` - 7 LLM tools (~150 LoC)
- `prompts/v2/bug_triage_orchestrator_agent.j2` - new agent prompt
- `agents_config.yaml`: 11 profiles (was 10)
- WorkHub: 5 new methods (`list_open_bugs`, `list_bugs_assigned_to`, `update_bug_state`, `close_bug`, `escalate_bug`)
- hub_pulse: 2 new render sections (`ASSIGNED BUGS`, `OPEN BUG QUEUE`)

## Bug lifecycle

```
open  --(BugTriageOrch.triage)-->  triaged --(.assigned)-->  assigned
   |                                                            |
   |                                                  (owner picks up)
   |                                                            v
   +-----(BugTriageOrch.escalate)--> escalated   -->  in_progress
                                                            |
                                                (owner proposes fix)
                                                            v
                                                     fix_proposed
                                                            |
                                                 (verifier re-runs)
                                                            v
                                                     fix_verified
                                                            |
                                                  (owner closes)
                                                            v
                                                       closed
```

## Verification

- Zero Claude trailers
- Both baselines green (7 OK / 443 OK)
- New profile registered + prompt renders + tools wired + WorkHub helpers cover the lifecycle
