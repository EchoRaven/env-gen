# Prompt Contract (Agent Prompts vs Runtime Tools)

This document is the source-of-truth checklist for keeping prompt instructions aligned with actual runtime capabilities.

Use it whenever editing files under `prompts/v2/*.j2`.

## Core Rules

- Prompts must only reference tools that exist in current runtime registration.
- Construction coordination uses `dev_task` tools; runtime validation is owned by `verifier` using release validation flows and optional `tasks/` artifacts.
- Do not reintroduce deprecated/removed aliases (for example: `check_dependencies`, `claim_task`, `report_task_result`, `get_task_summary`).
- If a flow changes in code, update this contract and affected prompts in the same change.
- Validation remediation domain inference rules are configurable in `multi_agent/docs/validation_domain_rules.yaml` (check mapping, keyword patterns, mode prior).
- Dynamic team governance rules are configurable in `multi_agent/docs/dynamic_team_rules.yaml` (spawn budget, circuit breaker, adaptive concurrency, dedup TTL).

## Skill Contract

- Configurable agents may receive OpenClaw-style skill allowlists from `agents_config.yaml`.
- Skills are discovered from workspace `skills/` plus project-agent `/.agents/skills/`.
- Bundled framework skills are synced into `/.agents/skills/` so agents can open them with normal `read(...)`.
- Skill usage contract is lazy: the system prompt advertises `<available_skills>`, and the agent should read the relevant `SKILL.md` on demand before following it.
- Profile `skills` are fail-fast: if a configured skill is missing, agent construction should error rather than silently ignore it.
- Dynamic workers may inherit parent skills by default and can explicitly override or extend them via `skills` plus `inherit_parent_skills`.
- Knowledge observer may auto-promote repeated workflow/checklist/playbook-style messages into project-agent skills; this path should stay conservative and append to existing skills when evidence repeats.

## Config Contract

- Prefer wiring per-profile behavior in `agents/agents_config.yaml` before adding new role-specific runtime branches.
- `tool_bundles: [...]` selects named capability bundles from `multi_agent/tool_bundles.py`.
- `workflow_policies: [...]` controls `task_ready` gates and finish semantics from `multi_agent/workflow_policies.py`.
- `flags.observer_handler` selects observer-side extraction logic from `multi_agent/observer_handlers.py`.
- `allow_tools` / `deny_tools` can prune high-surface profiles without adding more bespoke runtime branches.
- `execution_pipeline.max_action_rounds_per_step` controls how many action moves an agent may take inside one step before the runtime ends that step. The default is `15`.
- `execution_pipeline.step_reminders` lets a profile pin structured reminders that are injected at the start of every step. Each entry may be plain text or `{title, content}` where `content` can be text, a list, or a dict.
- `execution_pipeline.stages` now supports `runtime_team_status`, which injects a summary of spawned runtimes and managed teams owned by the current agent before planning.
- Prefer narrow capability categories (`memory`, `project`, `analysis`, `knowledge_read`, `knowledge_write`, `team_*`, `verification`, etc.) over broad catch-all buckets.

## Phase Boundary Contract

- **Construction phase** (`init/design/implement`):
  - allowed coordination queue: `publish_dev_task`, `claim_dev_task`, `complete_dev_task`, `get_available_dev_tasks`, `get_dev_task_summary`
- **Validation phase** (`test`):
  - Verifier may write `tasks/action_space.yaml` and `tasks/tasks.yaml` when deterministic release validation is needed
  - Verifier executes validation with `execute_task_suite` (preflight with `validate_only=true`) and reports results via `send_message`
- **Delivery phase** (`done`):
  - no new construction `dev_task` items should be published

## Tool Exposure Contract

- Registered tools are not the same as visible tools. The runtime may register a broader pool, then narrow each step to a small stage-specific subset.
- Default staged execution now prefers:
  - `inbox_status`
  - `crdt_changes`
  - `runtime_team_status`
  - `planning`
  - `retrieve_context`
  - `action`
  - `crdt_sync`
  - `knowledge_sync`
- `action` may internally dispatch to narrower modes such as `communicate`, `edit_code`, `run_checks`, `delegate_team`, and `deliver`, but prompts should reason about a single top-level action phase.
- Within one step, the runtime may allow multiple action rounds. Each action round is preceded by a required next-move planning pass (`think()` when available). Prompts may stop the current step by writing `ACTION_STATUS: stop`, continue to another move with `ACTION_STATUS: continue`, or finish the task with `finish()`.
- Prompts should assume the runtime may retrieve and expose only a top-k subset of relevant tools for a stage, rather than every tool in the profile pool.
- If a prompt needs a tool family consistently, make sure the profile declares the right category + bundle rather than telling the model to “search available tools”.

## File Tool Contract

- Treat `read`, `write`, `edit`, and `apply_patch` as the canonical file operation surface, with `glob` / `grep` as the matching discovery/search companions.
- Use `read(file_path=...)` before mutating an existing file so stale-write guards have current content.
- Prefer `edit` for exact localized replacements, `apply_patch` for structured multi-line edits, and `write` only for new files or full rewrites.
- Use `delete_file(file_path=...)` only for explicit cleanup/removal; do not treat it as part of the normal edit loop.
- Do not rely on legacy path aliases for canonical file tools; use `file_path` explicitly.
- For `glob` / `grep`, `path` means search scope, not a target file mutation path.

## Runtime Team Status Contract

- Before planning, the runtime may inject a `runtime_team_status` section summarizing task-scoped workers and managed teams spawned by the current agent.
- Treat this as the source of truth for whether you already have active workers or teams to reuse, monitor, pause, resume, or terminate.
- The same section may also surface unread background completion notifications already sitting in the parent inbox, so the agent can consume finished worker/team outcomes before spawning more helpers.
- If the section is absent, assume the current step has no owned spawned runtimes or managed teams worth summarizing.

## Agent-Level Contract

Below are key tools that prompts should rely on. This is not an exhaustive dump of every base tool.

### Orchestrator (`orchestrator_agent.j2`)

- Coordination: `send_message`, `broadcast`, `ask_agent`, `check_inbox`, `get_project_summary`
- Work planning: `plan`
- Verification planning: `verify_plan`
- Approval routing: `submit_plan`, `accept_plan`, `request_plan_changes`, `list_pending_plan_decisions`
- Team protocols: `spawn_worker`, `parallel_execute`, `create_agent_team`, `define_team_agent`, `launch_agent_team`, `monitor_agent_team`, `pause_agent_team`, `resume_agent_team`, `terminate_agent_team`, `run_parallel_reasoning`, `list_personas`, `create_persona`
- Delivery: `deliver_project`
- Validation orchestration: trigger `verifier` once implementation is ready, then drive remediation from verification results

Avoid:
- Directly instructing orchestrator to execute release validation itself.

### Verifier (`verifier_agent.j2`)

- Readiness checks: `get_tables`, `get_endpoints(status_filter='implemented')`, `get_pages`
- Runtime checks: `docker_*`, `test_api`, browser tools, verification tools
- Validation execution: `define_action_space`, `define_task`, `save_task_suite`, `execute_task_suite`
- Reporting: `send_message` to domain agents and orchestrator
- Ownership boundary: verifier owns validation design and validation execution; backend may expose MCP-compatible surfaces, but MCP is not a standalone resident prompt anymore

Avoid:
- `check_dependencies` (not available)

### Design / Database / Backend / Frontend / Knowledge

- Keep using CRDT state tools (`update_endpoint`, `update_table`, `update_page`, status queries) for cross-agent observability.
- Keep implementation details in domain prompts, but never use removed aliases (`add_endpoint`, `add_table`, etc.).
- Knowledge may manage project-visible skills with `list_skills`, `get_skill`, and `upsert_skill`; use skills for reusable procedures and `store_knowledge` for searchable facts/solutions.

### Plan Contract (`plan`)

- `think` remains the step-local planner; use `plan` for longer-horizon workboards with stages, tasks, assignees, acceptance, and stage sync.
- Use `plan(action='set_acceptance', scope=...)` to attach feature acceptance or artifact/file acceptance at the `plan`, `stage`, or `task` level.
- Use `functional_acceptance` for expected behavior or verifier/task-suite style checks.
- Use `artifact_acceptance` for files, directories, specs, or owned outputs such as `required_files`, `required_dirs`, and `required_specs`.
- `functional_acceptance` entries may include `task_suite_ref`, `verification_ref`, or `metadata.validation_kind`; `plan` will reflect matching CRDT validation results when available.
- `artifact_acceptance` entries may auto-resolve when referenced files/directories already exist in the workspace.
- Use `plan(action='sync_acceptance_from_validation', ...)` when you want to explicitly bind a criterion to `validation_task_id`, `validation_kind`, `verification_ref`, or `task_suite_ref` instead of relying on implicit metadata conventions.
- Use `plan(action='update_acceptance_item', ...)` to mark acceptance criteria `passed`, `failed`, `waived`, or back to `pending`.
- `complete_task` and `complete_stage` may reject completion when required acceptance remains unresolved.

### Party Sync Contract (`plan` party actions)

- `start_party` now means “start a stage sync session”, not just open a note thread.
- Party participants should be interpreted as the current stage assignees plus the initiator.
- `start_party` returns an `acceptance_focus` snapshot so sync can center on unresolved acceptance gaps and validation-linked acceptance, not only raw task status.
- `add_party_note` is the structured reporting channel during sync. Use `note_type='progress'|'blocker'|'feedback'|'question'|'suggestion'` to report status, blockers, decisions, or next actions.
- `propose_change` queues plan deltas during the sync; `end_party` applies them and returns a sync summary with participants, blockers, and next action items.

### Approval Contract (`submit_plan` / `accept_plan` / `request_plan_changes`)

- Treat these as approval-routing tools for major change proposals, not as the same object as the local `plan` workboard.
- Use `submit_plan` only when a lead decision is needed before risky execution.

### Managed Team Contract (`create_agent_team` / `define_team_agent` / `launch_agent_team`)

- Prefer managed team lifecycle tools over `parallel_execute` when the parent needs explicit `launch` / `monitor` / `pause` / `resume` / `terminate` control.
- Managed team members may now specify richer runtime fields including `config_profile`, `skills`, `inherit_parent_skills`, `capabilities`, `model`, `write_scopes`, and `include_vision`.
- Use `agent_type` as the runtime label and `config_profile` when you need to pin a specific execution profile.
- Treat `capabilities` as guidance for role shaping and prompt construction, not as a hard security boundary by itself.
- Use `context.owned_files` / `context.forbidden_files` (or `context.file_contract.*`) when the team needs single-writer file ownership guarantees before launch.
- Use `launch_agent_team(wait_for_completion=true)` when the parent must block until the team run completes.
- When `launch_agent_team(wait_for_completion=false)` or `resume_agent_team(wait_for_completion=false)` is used, the runtime will send a `team_update` message to the parent inbox when that background run completes or fails.

### Memory Tool Contract (`remember` / `recall` / `share_knowledge`)

- `remember` must use `content` + `category`; do not use legacy `key` parameter.
- `recall` should prefer semantic query phrases (not opaque keys). Use `category` and `limit` when narrowing.
- `share_knowledge` should treat `to_agents` as runtime-discovered; if result includes `invalid_targets`, retry with valid targets only.
- `submit_learning` is the structured path for normal agents to hand reusable lessons to `knowledge`; prefer it over raw `share_knowledge` when the knowledge agent should choose `knowledge` vs `skill` storage.
- For troubleshooting memory quality/drift, call `memory_health_summary` and branch on counters (`dedup_skipped_total`, `quality_skipped_total`, persistence fields).
- Keep automatic memory extraction concise and high-signal; avoid prompting for noisy one-line self-notes.

### Step Reminder Contract (`set_step_reminder` / `list_step_reminders` / `clear_step_reminders`)

- Use `set_step_reminder(title=..., content=...)` to pin short-lived self-guidance across future steps.
- Add `ttl_steps=N` when the reminder should expire automatically after the next `N` step openings.
- Add `auto_clear_on_finish=true` for task-local reminders that should disappear once `finish()` or `deliver_project()` succeeds.
- `content` may be text, a list, or a small object; prefer concise operational reminders over long notes.
- Use `list_step_reminders()` before adding more if you are unsure what is already pinned; prefer its normalized `summary` view when checking remaining TTL or finish-auto-clear behavior.
- Clear reminders once they are stale with `clear_step_reminders(title=...)` or wipe all of them with `clear_step_reminders()`.
- Prefer this reminder channel for temporary step-to-step guidance; use `remember` / `store_knowledge` for longer-lived memory.

### Dynamic Agents / Team Lifecycle

- Runtime currently allows full capability through dynamic branch registration.
- Prompts should still scope behavior by task, persona, or execution profile to avoid unnecessary side effects.
- For `spawn_worker` / `parallel_execute` failures, branch on `error_code` first; treat `error` text as compatibility-only.
- Prefer managed lifecycle tools for multi-member orchestration and long-running tasks; use spawn/parallel as lower-level primitives.
- Prefer `recommended_action` when present to choose retry/cooldown/remediation path deterministically.
- Use `team_health_summary` for lightweight collaboration observability before aggressive fan-out or when failures spike.
- `spawn_worker(wait_for_completion=true)` now supports blocking until the child runtime finishes and returns completion data inline.
- Default `spawn_worker` remains background-oriented: the spawned worker sends its result back to the parent through the message bus, so the parent can pick it up in `inbox_status` / `check_inbox`.

### Dynamic Team Failure Contract

When prompts consume outputs from `spawn_worker` or `parallel_execute`, use machine-readable codes for deterministic branching:

- `E_CHILD_TASK_CONTRACT`: subtask schema invalid -> fix task payload shape before retry.
  - Contract is versioned via `contract_version` (current: `v1`).
- `E_SPAWN_BUDGET_EXCEEDED`: spawn window budget exhausted -> wait/cooldown or reduce batch size.
- `E_AGENT_TIMEOUT`: child execution timeout -> retry with smaller scope and tighter task definition.
- `E_AGENT_NO_COMPLETION_EVENT`: spawned task completion signal missing -> treat as infra/runtime issue, retry once conservatively.
- `E_AGENT_EXECUTION` / `E_AGENT_ERROR`: child raised runtime error -> route to relevant owner (backend/frontend/database) with diagnostics.
- `E_NOT_EXECUTED`: task skipped due to earlier gate failure -> do not treat as success.

Execution routing recommendations:

- Retry only for transient classes (`E_AGENT_TIMEOUT`, `E_AGENT_NO_COMPLETION_EVENT`, budget/circuit conditions after cooldown).
- Do not blindly retry contract/config errors (`E_CHILD_TASK_CONTRACT`); repair payload first.
- Prefer `error_code` + `error_message` fields in summaries sent to `orchestrator`/`verifier`.

## Prompt Review Checklist (Quick)

Before merging prompt edits:

1. Search edited prompts for removed tool names.
2. Confirm phase wording:
   - construction => `dev_task`
   - validation => verifier-owned release validation, optionally backed by task suite (`tasks/*.yaml`)
3. Confirm examples only use currently available tool names.
4. Confirm owner responsibilities are consistent (`verifier` owns validation design/execution, `orchestrator` coordinates).

## Common Drift Patterns

- Old queue API names copied from legacy docs.
- Mixing construction queue semantics into validation execution instructions.
- Examples showing MCP mode while runtime execution prompt/tooling expects browser/API modes.
- Prompt role text contradicting current team responsibilities.
