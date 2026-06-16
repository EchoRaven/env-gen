# Cutover 23: Task Priority + Dependency Graph

**Branch:** `haibotong-cutover-23-priority-deps`
**Date:** 2026-05-25

## What

WorkHub tasks gain scheduling signals:
- **priority** metadata field (P0-P3, default P2), validated on `create_task`
- **depends_on** enforced at `claim_task` time (was metadata-only before)
- hub_pulse surfaces `## YOUR TASK QUEUE` (ready, P0-first) + `## BLOCKED ON OTHERS` per agent
- 3 new LLM tools: `workhub_set_priority` / `workhub_list_ready` / `workhub_list_blocked`
- `workhub_create_task` tool extended with `priority` kwarg
- Orchestrator prompt teaches PRIORITY + DEPENDENCY DISCIPLINE

## Why

After 22 cutovers we had rich routing (bugs -> triage -> owner) and structural
gates (coverage / visual / seed / mcp) but no scheduling signal. Agents picked
tasks in arrival order; `depends_on` was declared but never enforced;
orchestrator could not say "do P0 first." Both real-engineering basics --
priority + dep graph -- are now mechanical, not just convention.

## Commits

- `ed96eec4` Cutover 23: record pre-flight baseline (regressions 7 OK, discover 862 OK)
- `d0042207` WorkHub: validate task priority (P0-P3) + enforce depends_on at claim + add list_ready/blocked + get_blockers/blocked_by
- `ec2c7d33` hub_pulse: surface YOUR TASK QUEUE + BLOCKED ON OTHERS (priority-sorted, dep-aware)
- `7c4231b6` workhub tools: priority kwarg on create_task + workhub_set_priority / list_ready / list_blocked
- `9ea6e63a` Orchestrator prompt: PRIORITY + DEPENDENCY DISCIPLINE block (P0-P3 + depends_on + list_ready/blocked)
- `61d4c5b0` Add task priority + dep E2E: full chain blocked->complete dep->ready->claim succeeds

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 862 OK -> 891 OK (+29 new)

Breakdown of new tests:
- `test_workhub_task_priority` (4) + `test_workhub_task_deps` (12) -- Task 2
- `test_hub_pulse_task_queue` (4) -- Task 3
- `test_workhub_priority_tools` (4) -- Task 4
- `test_orchestrator_priority_prompt` (3) -- Task 5
- `test_task_priority_e2e` (2) -- Task 6

## Schema additions (no new entity stores)

- `metadata.priority`: `"P0" | "P1" | "P2" | "P3"` (default `"P2"`)
- `depends_on`: `List[str]` (existed since Cutover 10; now enforced at `claim_task`)

## API additions

- WorkHub: `list_ready_tasks(assignee=None)`, `list_blocked_tasks(assignee=None)`,
  `get_blockers_for(task_id)`, `get_blocked_by(task_id)`
- WorkHub: `create_task(priority=...)` validated against `{P0,P1,P2,P3}`
- WorkHub: `claim_task` refuses when any dep is missing or `status != "completed"`,
  with error message naming the blocker(s)
- LLM tools: `workhub_create_task(priority=...)`; new `workhub_set_priority`,
  `workhub_list_ready`, `workhub_list_blocked`

## Render additions

- hub_pulse: `## YOUR TASK QUEUE` (P0-first sorted, `[Pn]` prefix on each row) +
  `## BLOCKED ON OTHERS` (with blocker IDs)

## Notable migrations + adaptations

### Task 2: production-code fixture migration (4 callers)

The new priority validator rejects anything outside `{P0,P1,P2,P3}`. Four
existing production callers were creating tasks with the legacy
`priority="urgent"` / `priority="high"` strings inherited from earlier
prototypes and had to be migrated to satisfy the new contract:

- `multi_agent/runtime/apihub.py` -- breaking-change remediation task (urgent -> P0)
- `multi_agent/runtime/hub_registry.py` -- validation-failure remediation task (urgent -> P0; touched twice)
- `multi_agent/runtime/hubs/codehub/service.py` -- premerge-gate failure task + merge-conflict task (high -> P1; touched twice)

These were caught by the regression suite (which exercises those paths) and
fixed inline so the `d0042207` commit lands with both new tests and existing
baselines green.

### Task 4: dispatcher-pattern adaptation for new tool surface

The plan sketched the new LLM tools (`workhub_set_priority`,
`workhub_list_ready`, `workhub_list_blocked`) as separate `HubTool` classes
with their own `NAME` / `PARAMETERS` / `_run`. The actual `tools/hub_tools.py`
file uses a single dispatcher class -- `WorkHubTaskTool` with an `action`
parameter (`create`, `claim`, `complete`, ...) -- rather than one class per
operation. The implementation was adapted to that pattern: the new actions
were folded into the existing `WorkHubTaskTool` dispatcher (`action="create"`
gained `priority`; new actions `set_priority`, `list_ready`, `list_blocked`
added alongside) so the tool surface stays uniform and the
`test_no_duplicate_tool_names` invariant (Cutover 18) stays clean.

## Known limits (future cutovers)

- No SLA / staleness escalation -- a P0 sitting unclaimed for 50 steps does not auto-escalate
- No cross-priority preemption -- a P0 does not pause an in-progress P2
- No load rebalancing -- one agent hit with 20 tasks does not auto-redistribute
- `workhub_set_priority` does not re-emit a notification to the assignee
- No deadline / due-date field
