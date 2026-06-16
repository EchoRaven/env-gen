# Cutover 23 Baseline (Task Priority + Dependency Graph)

## Test counts
- regressions: 7 OK
- discover: 862 OK

## Current state
- WorkHub tasks have depends_on field (Cutover 10) but claim_task doesn't enforce it
- No priority signal — all tasks look equal in queues
- hub_pulse surfaces assigned bugs (Cutover 10) but not assigned tasks

## Recon notes (Task 1)
- `_pulse_assigned_bugs` lives in
  `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py:48`
  (also wired at line 21 into the report dict). Task 3 inserts
  `_pulse_assigned_tasks` next to it.
- There is NO dedicated `WorkhubCreateTaskTool` class. Task creation is
  exposed through `WorkHubTaskTool` (NAME = `workhub_task`) in
  `agent/env_generator/llm_generator/tools/hub_tools.py:300`, dispatched
  via the `action="create"` parameter. The literal string
  `workhub_create_task` only appears in prompt text and hint strings — it
  is the conceptual operation name, not a registered tool NAME. Task 4
  will need to extend `WorkHubTaskTool` with a `priority` kwarg on the
  `create` action (and add `workhub_set_priority` / `workhub_list_ready`
  / `workhub_list_blocked` as sibling classes in the same file).

## Approach
- Add metadata.priority {P0|P1|P2|P3, default P2}
- Enforce depends_on at claim_task: refuse if any dep incomplete
- New helpers: list_ready_tasks, list_blocked_tasks, get_blockers_for, get_blocked_by
- Extend hub_pulse with ## YOUR TASK QUEUE + ## BLOCKED ON OTHERS sections
- Extend WorkHubTaskTool create action with priority param; add list_ready/blocked + set_priority tools
- Orchestrator prompt teaches PRIORITY + DEPENDENCY DISCIPLINE

## No new entity stores; no new agent; all additive
