# Agent Tools Reference

This document provides a comprehensive guide to all available tools for agents.
Use the `search_tools` tool to find specific tools by keyword.

---

## 🤖 AGENT TEAM OVERVIEW

| Agent | Role | Responsibilities |
|-------|------|------------------|
| **orchestrator** | Project Lead | Requirements refinement, planning, coordination, delivery |
| **design** | Architect | Database/API/UI specifications |
| **database** | DBA | PostgreSQL schema and seed data |
| **backend** | Backend Dev | Express.js API implementation, fix own bugs |
| **frontend** | Frontend Dev | React UI implementation, fix own bugs |
| **verifier** | Validation Engineer | API testing, UI testing, runtime validation, report bugs to code agents |
| **task** | Task Designer | Define state-machine test tasks |
| **task_runner** | Task Executor | Deterministically execute task suites via browser/API |
| **knowledge** | Knowledge Curator | Collect patterns, answer queries |

### Key Delegation Rules

- **Orchestrator does NOT**: Run Docker, test APIs/UI, execute validation itself
- **Verifier handles**: Docker management, API testing, UI testing, bug reporting, release validation execution
- **Code Agents (backend/frontend/database)**: Fix their own bugs, use `run_parallel_reasoning()` for complex issues
- **Backend may handle**: MCP-compatible integration surfaces when a project needs them

### Runtime Validation Notes (Current)

- Verifier primary entrypoint for deterministic runtime validation is `execute_task_suite`, not manual step-by-step tool orchestration.
- Recommended call sequence:
  1) `execute_task_suite(validate_only=true)` for preflight
  2) `execute_task_suite(...)` for real execution
  3) `get_validation_summary()` for aggregate gate signal
- `execute_task_suite` supports:
  - `only_task_ids`, `stop_on_failure`, `max_concurrent`, `parallel_by_domain`
  - `action_timeout_seconds`, `task_timeout_seconds`
  - `action_retry_count`, `action_retry_backoff_ms`
  - `validate_only` / `dry_run`
- Per-task outputs are written to `tasks/execution_results/*.json`.
- Failure outputs include machine-readable `error_code` and remediation suggestions.
- Dynamic team governance knobs (spawn budget/circuit/adaptive concurrency) are loaded from `multi_agent/docs/dynamic_team_rules.yaml`.

### MCP vs Task Runner (Boundary)

- Backend responsibility may include **generating/building MCP service code** and related wrappers when the project needs MCP surfaces.
- `task_runner` responsibility: **execute runtime validation tasks** via `execute_task_suite` using browser/API execution modes.
- Task Runner should **not** default to MCP execution paths during validation.
- MCP should only be used in validation when:
  1) task suite explicitly defines a validated MCP execution mode/toolchain, and
  2) runtime guarantees MCP client/tool availability for Task Runner.

---

## 📁 FILE OPERATIONS

Tools for reading, writing, and managing files.

**Canonical surface**:
- Prefer `read`, `write`, `edit`, and `apply_patch` for normal file work.
- Treat these four as the primary file-editing contract for prompts and runtime behavior.
- Use `delete_file` only for explicit cleanup/removal.
- Use `glob` / `grep` as the canonical discovery/search companions to that file-editing surface, not as substitutes for file edits.

### read
**Purpose**: Read file contents with line numbers
**When to use**: Before editing a file, understanding code structure
**Parameters**:
- `file_path` (required): Path to file
- `offset` (optional): 1-based start line; negative values count from the end
- `limit` (optional): Max lines to return
**Example**:
```
read(file_path="src/app.py", offset=1, limit=50)
```
**Tips**:
- Always read before editing
- Use offset/limit for large files

### write
**Purpose**: Create or overwrite a file
**When to use**: Creating new files, replacing entire file content
**Parameters**:
- `file_path` (required): Path to file
- `content` (required): File content
**Example**:
```
write(file_path="src/new_component.jsx", content="import React...")
```
**Tips**:
- Use for NEW files or complete rewrites
- For targeted changes, prefer `edit` or `apply_patch`

### edit
**Purpose**: Make precise edits by replacing exact text
**When to use**: Modifying existing files, fixing bugs, adding code
**Parameters**:
- `file_path` (required): Path to file
- `old_string` (required): Exact string to replace
- `new_string` (required): Replacement string
- `replace_all` (optional): Replace all matches instead of requiring uniqueness
**Example**:
```
edit(
    file_path="src/app.py",
    old_string="def old_function():\n    pass",
    new_string="def new_function():\n    return 'updated'"
)
```
**Tips**:
- `old_string` MUST match exactly (including whitespace)
- Include enough context for a unique match, or use `replace_all=true`
- Prefer `apply_patch` when a structured multi-hunk diff is clearer

### apply_patch
**Purpose**: Apply a structured patch to one or more files
**When to use**: Multi-line or multi-hunk edits where exact patch context is clearer than a single replacement
**Parameters**:
- `patch` (required): Patch text in `*** Begin Patch` format
**Example**:
```
apply_patch(patch=\"\"\"*** Begin Patch
*** Update File: src/app.py
@@
-old_line
+new_line
*** End Patch\"\"\")
```
**Tips**:
- Prefer for grouped edits across a file
- Patch context must match current file contents exactly

### delete_file
**Purpose**: Delete a file
**When to use**: Removing unused files, cleanup
**Parameters**:
- `file_path` (required): Path to file (relative to workspace)
- `purge` (optional): When true, permanently delete instead of moving to trash
**Example**:
```
delete_file(file_path="src/deprecated.py")
```

### glob
**Purpose**: Find files matching a pattern
**When to use**: Discovering project structure, finding files by extension
**Parameters**:
- `pattern` (required): Glob pattern (e.g., "**/*.jsx")
- `path` (optional): Search scope directory (default: workspace root)
**Example**:
```
glob(pattern="**/*.py", path="src/")
```

### grep
**Purpose**: Search for text patterns in files
**When to use**: Finding code usage, locating definitions
**Parameters**:
- `pattern` (required): Regex pattern
- `path` (optional): Search scope file or directory (default: workspace root)
- `include` (optional): File pattern to include
**Example**:
```
grep(pattern="def create_user", path="src/")
```

---

## 💬 COMMUNICATION

Tools for inter-agent communication.

### send_message
**Purpose**: Send a message to another agent
**When to use**: Sharing information, asking questions, coordination
**Parameters**:
- `to` (required): Recipient agent ID (e.g., "frontend", "backend")
- `content` (required): Message content
- `priority` (optional): "low", "normal", "high", "urgent"
- `requires_response` (optional): Whether response is expected
**Example**:
```
send_message(
    to="frontend",
    content="API endpoint /api/users is ready with pagination support",
    priority="high"
)
```

### ask_agent
**Purpose**: Ask a question and wait for response
**When to use**: Need specific information from another agent
**Parameters**:
- `to` (required): Agent to ask
- `question` (required): The question
- `timeout` (optional): Wait timeout in seconds
**Example**:
```
ask_agent(to="database", question="What is the primary key for users table?")
```

### broadcast
**Purpose**: Send message to all agents
**When to use**: Important announcements, status updates
**Parameters**:
- `content` (required): Message content
- `priority` (optional): Priority level
**Example**:
```
broadcast(content="Database schema has been updated", priority="high")
```

### check_inbox
**Purpose**: Check for incoming messages
**When to use**: Periodically to stay synchronized, before starting new work
**Parameters**: None
**Example**:
```
check_inbox()
```
**Tips**: Call regularly to respond to questions

### list_agents
**Purpose**: List all available agents and their status
**When to use**: Understanding team composition
**Example**:
```
list_agents()
```

---

## 🤝 TEAM COLLABORATION

Advanced multi-agent coordination tools.

### team_health_summary
**Purpose**: Get dynamic team operational health snapshot
**When to use**: Before/after parallel runs, during instability triage, before spawning large batches
**Parameters**: None
**Example**:
```
team_health_summary()
```
**Key fields**:
- `recent_failure_rate`, `recent_success_count`, `recent_failure_count`
- `spawn_budget` and `circuit_breaker` status
- `dedup` and `contract_validation` observed rates
- `parallel_runtime.avg_duration_seconds`
- `recommended_actions.last_summary` and `recommended_actions.totals`

### create_agent_team / define_team_agent / launch_agent_team
**Purpose**: Define and run a managed multi-agent team with explicit lifecycle
**When to use**: Long-running or monitorable teamwork where the parent needs `launch`, `monitor`, `pause`, `resume`, or `terminate`
**Positioning**: Use this for managed teams; use `parallel_execute` for one-shot fan-out

**Managed member fields**:
- `agent_type`: Runtime worker label
- `config_profile`: Explicit backing execution profile
- `skills`: Final skill allowlist for that member
- `inherit_parent_skills`: Whether to merge parent skills
- `capabilities`: Role/capability hints for prompt shaping
- `model`: Optional runtime model override
- `write_scopes`: Optional explicit writable paths for that member
- `include_vision`: Optional vision override
- `context`: Additional context and file contracts
- `depends_on`: Hard launch dependency edges
- `disabled_tools`: Tool denylist enforced before execution

**Contract tips**:
- Use `context.owned_files` / `context.forbidden_files` (or `context.file_contract.*`) to declare single-writer file ownership before launch.
- Use `config_profile` when the runtime label should differ from the backing execution profile.
- Use `capabilities` and `description` together so the spawned member prompt reflects both responsibility and expected tool/use patterns.
- Use `wait_for_completion=true` when the parent should block until the full managed team finishes; otherwise launch in background and rely on the automatic completion/failure message plus `monitor_agent_team`.

### spawn_worker
**Purpose**: Create a new task-scoped worker at runtime
**When to use**: Need additional help, parallel work
**Positioning**: Low-level primitive; prefer managed team lifecycle tools for multi-member, monitorable workflows.
**Parameters**:
- `worker_type` (required): Free-form runtime worker label
- `task` (required): Task for the new agent
- `role` (optional): Specialized persona/label
- `config_profile` (optional): Backing execution profile
- `wait_for_completion` (optional): Block until the worker finishes
- `timeout_seconds` (optional): Wait timeout when `wait_for_completion=true`
**Completion modes**:
- Blocking mode: `wait_for_completion=true` returns worker completion data inline.
- Background mode: default behavior; the spawned worker runs independently and sends its result back to the parent via message bus.
**Example**:
```
spawn_worker(
    worker_type="security_auditor",
    task="Review authentication code for security issues",
    role="risk_analyst",
    config_profile="review_worker",
    wait_for_completion=true
)
```

**Failure Contract (error-code first)**:
- Prefer `error_code` + `error_message` for control flow decisions.
- `error` remains for backward compatibility and should not be primary parsing source.
- Common codes:
  - `E_SPAWN_BUDGET_EXCEEDED`: spawn budget/circuit constraints hit
  - `E_AGENT_EXECUTION` / `E_AGENT_ERROR`: child runtime failure
  - `E_AGENT_TIMEOUT`: execution timeout
  - `E_AGENT_NO_COMPLETION_EVENT`: missing completion signal

### parallel_execute
**Purpose**: Execute multiple tasks in parallel with profile-resolved agent team
**When to use**: Creating multiple pages/endpoints, parallel analysis
**Positioning**: One-shot convenience fan-out; prefer managed team lifecycle tools for long-running orchestration.
**Prompt model**: Uses execution profiles plus free-form worker labels, not ad-hoc custom system prompt text.
**Parameters**:
- `team_name` (required): Name for the team
- `agents` (required): List of agent definitions
  - each agent supports optional `agent_type` as runtime worker label
  - each agent supports optional `config_profile` to select execution profile explicitly
- `coordination` (optional): How agents should work together
- `max_concurrent` (optional): Max parallel agents
**Example**:
```
parallel_execute(
    team_name="PageBuilders",
    agents=[
        {"name": "HomePage Builder", "role": "Landing specialist", "task": "Create HomePage"},
        {"name": "Cart Builder", "role": "E-commerce expert", "task": "Create CartPage"},
    ],
    coordination="Share common components"
)
```

**Result Fields (important)**:
- `effective_max_concurrent`: resolved concurrency after risk + failure-rate feedback
- `failure_rate_recent`: recent failure ratio used by adaptive throttling
- `spawn_budget_remaining`: current budget headroom
- `deduped_count`: skipped duplicates (batch or recent-history idempotency)
- `contract_rejected_count`: subtasks rejected by child-task contract validation
- `recommended_actions_summary`: aggregated next-step hints keyed by action id

**Failure Contract (error-code first)**:
- Top-level and per-subtask failures include `error_code` + `error_message` (+ compatibility `error`).
- Failures also include `recommended_action` to enable deterministic remediation routing.
- Subtask validation supports `contract_version` (default/current: `v1`) with field-path error messages.
- Common per-subtask codes:
  - `E_CHILD_TASK_CONTRACT`: invalid subtask schema
  - `E_AGENT_TIMEOUT`: timed out
  - `E_AGENT_NO_COMPLETION_EVENT`: no completion signal
  - `E_AGENT_EXECUTION`: runtime exception
  - `E_NOT_EXECUTED`: skipped due to prior gate failure

**Operational Guidance**:
- Retry transient failures (`E_AGENT_TIMEOUT`, `E_AGENT_NO_COMPLETION_EVENT`) with lower concurrency/smaller tasks.
- For `E_CHILD_TASK_CONTRACT`, repair payload shape first; do not immediate blind retry.
- For `E_SPAWN_BUDGET_EXCEEDED`, wait cooldown or split into smaller batches.

### run_parallel_reasoning
**Purpose**: Run multi-candidate analysis with challenge rounds
**When to use**: Complex debugging, root-cause analysis, architecture tradeoff exploration
**Parameters**:
- `problem` (required): Problem description
- `candidates` (required): List of candidate explanations to analyze
**Example**:
```
run_parallel_reasoning(
    problem="API returning 500 error intermittently",
    candidates=[
        "Database connection pool exhaustion",
        "Race condition in order processing",
        "Memory leak in caching layer"
    ]
)
```

### submit_plan
**Purpose**: Submit a plan for decision before execution
**When to use**: Complex changes requiring oversight
**Parameters**:
- `title` (required): Plan title
- `steps` (required): List of planned steps
- `estimated_time` (optional): Time estimate
**Example**:
```
submit_plan(
    title="Refactor authentication system",
    steps=["Backup current code", "Implement new JWT flow", "Update tests"]
)
```

### accept_plan / request_plan_changes / list_pending_plan_decisions
**Purpose**: Resolve queued plans after lead review
**When to use**: Lead agent needs to accept, reject, or request revisions
**Example**:
```
pending = list_pending_plan_decisions()
accept_plan(plan_id=pending[0]["id"], feedback="Looks good")
```

### list_personas / create_persona
**Purpose**: Inspect or define reusable specialist personas
**When to use**: Need a named analysis perspective beyond defaults
**Example**:
```
create_persona(
    persona_id="api_contract_guardian",
    name="API Contract Guardian",
    description="Check contract completeness and consistency",
    focus=["schemas", "errors", "auth"],
    personality="Strict but practical",
    prompt="Prioritize missing constraints and ambiguous contracts."
)
```

### suggest_team
**Purpose**: Get team composition suggestions based on past successes
**When to use**: Before spawning agents, learning from history
**Parameters**:
- `problem_category` (required): Category (debugging, api_issue, performance)
**Example**:
```
suggest_team(problem_category="api_bug")
```

### record_practice
**Purpose**: Record a successful team collaboration for future reference
**When to use**: After successful team effort
**Parameters**:
- `practice_type` (required): parallel_reasoning, quality_analysis, parallel_execution
- `problem_category` (required): Category
- `agents_used` (required): List of agents
- `outcome` (required): Result
- `success` (required): True/False

---

## 📊 SHARED WORKSPACE

Tools for shared state and coordination.

### update_endpoint
**Purpose**: Create or update endpoint spec/state in CRDT workspace
**When to use**: Design defines contract, Backend updates implementation/test status
**Parameters**:
- `key` (required): Endpoint key (e.g., `"GET /api/users"`)
- `data` (required): Endpoint payload (`path`, `method`, `status`, schema fields)
**Example**:
```
update_endpoint(
    key="GET /api/users",
    data={
        "path": "/api/users",
        "method": "GET",
        "status": "defined",
        "response_key": "users"
    }
)
```

### get_endpoints
**Purpose**: Read endpoint set from CRDT
**When to use**: Check available APIs, filter by status in agent logic
**Example**:
```
get_endpoints()
```

### update_table
**Purpose**: Create or update table schema/status in CRDT
**When to use**: Database agent evolves schema lifecycle (`defined`/`implemented`/`tested`)
**Parameters**:
- `name` (required): Table name
- `data` (required): Table definition payload
**Example**:
```
update_table(
    name="users",
    data={
        "status": "implemented",
        "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": true},
            {"name": "email", "type": "VARCHAR(255)"}
        ]
    }
)
```

### get_tables
**Purpose**: Read table set from CRDT
**When to use**: Validate schema readiness and dependencies
**Example**:
```
get_tables()
```

### update_page / get_pages
**Purpose**: Track UI page lifecycle/status in CRDT
**When to use**: Frontend progress sync and verifier readiness checks
**Example**:
```
update_page(name="HomePage", data={"status": "implemented"})
get_pages()
```

### get_project_summary
**Purpose**: Get overview of project progress
**When to use**: Understanding overall status
**Example**:
```
get_project_summary()
```

### Runtime Validation CRDT Tools
Use these after Task Runner executes task suite items.

#### record_validation_result
Persist one task runtime result (`passed`/`failed`/`skipped`/`error`) with artifacts/evidence.

#### get_validation_summary
Get aggregate runtime status, including retry counters and recent failures.

#### handle_validation_failure
Retry-first (for smoke checks) then remediation `dev_task` fallback.

#### create_dev_task_from_validation_failure
Directly create remediation task from a failed validation result (dedupe built-in).

---

## 🐳 DOCKER

Tools for container management.

### docker_build
**Purpose**: Build Docker images
**When to use**: After code changes, initial setup
**Parameters**:
- `service` (optional): Specific service to build
**Example**:
```
docker_build(service="backend")
```

### docker_up
**Purpose**: Start Docker containers
**When to use**: Starting the application
**Parameters**:
- `service` (optional): Specific service
- `detach` (optional): Run in background
**Example**:
```
docker_up(detach=true)
```

### docker_down
**Purpose**: Stop Docker containers
**When to use**: Stopping application, cleanup
**Example**:
```
docker_down()
```

### docker_logs
**Purpose**: Get container logs
**When to use**: Debugging, checking errors
**Parameters**:
- `service` (required): Service name
- `tail` (optional): Number of lines
**Example**:
```
docker_logs(service="backend", tail=100)
```

### docker_status
**Purpose**: Check container status
**When to use**: Verifying containers are running
**Example**:
```
docker_status()
```

---

## 🌐 BROWSER

Tools for web testing and verification.

### browser_navigate
**Purpose**: Navigate to a URL
**When to use**: Starting browser testing
**Parameters**:
- `url` (required): URL to navigate to
**Example**:
```
browser_navigate(url="http://localhost:3000")
```

### browser_screenshot
**Purpose**: Take a screenshot
**When to use**: Visual verification, debugging
**Parameters**:
- `name` (optional): Screenshot name
**Example**:
```
browser_screenshot(name="homepage_test")
```

### browser_click
**Purpose**: Click an element
**When to use**: UI testing, interaction
**Parameters**:
- `selector` (required): CSS selector or text
**Example**:
```
browser_click(selector="button.submit")
```

### browser_fill
**Purpose**: Fill in a form field
**When to use**: Form testing
**Parameters**:
- `selector` (required): Field selector
- `value` (required): Value to enter
**Example**:
```
browser_fill(selector="input[name='email']", value="test@example.com")
```

### browser_get_elements
**Purpose**: Get elements matching selector
**When to use**: Inspecting page structure
**Parameters**:
- `selector` (required): CSS selector
**Example**:
```
browser_get_elements(selector=".product-card")
```

---

## 🔧 RUNTIME

Tools for running commands and processes.

### execute_bash
**Purpose**: Execute a bash command
**When to use**: Running scripts, system operations
**Parameters**:
- `command` (required): Command to run
- `timeout` (optional): Max execution time
**Example**:
```
execute_bash(command="npm install")
```

### run_background
**Purpose**: Start a background process
**When to use**: Starting servers, long-running tasks
**Parameters**:
- `command` (required): Command to run
- `name` (optional): Process name
**Example**:
```
run_background(command="npm run dev", name="frontend_server")
```

### stop_process
**Purpose**: Stop a background process
**When to use**: Cleanup, restarting
**Parameters**:
- `name` (required): Process name
**Example**:
```
stop_process(name="frontend_server")
```

### list_processes
**Purpose**: List running background processes
**When to use**: Checking what's running
**Example**:
```
list_processes()
```

### find_free_port
**Purpose**: Find an available port
**When to use**: Starting services
**Example**:
```
find_free_port()
```

### test_api
**Purpose**: Test an API endpoint
**When to use**: API verification
**Parameters**:
- `url` (required): Endpoint URL
- `method` (optional): HTTP method
- `body` (optional): Request body
**Example**:
```
test_api(url="http://localhost:8000/api/users", method="GET")
```

---

## 🧠 REASONING

Tools for planning and thinking.

### think
**Purpose**: Record thoughts and reasoning
**When to use**: Complex decisions, documenting approach
**Parameters**:
- `thought` (required): Your reasoning
**Example**:
```
think(thought="The user registration needs email validation. I should add...")
```

### plan
**Purpose**: Create and manage a staged workboard with task assignment, acceptance criteria, and participant sync
**When to use**: Complex multi-stage tasks requiring team coordination

**Actions**:
- Plan Management: `create`, `status`, `clear`
- Stage Management: `add_stage`, `start_stage`, `complete_stage`
- Task Management: `add_task`, `assign_task`, `start_task`, `complete_task`, `block_task`, `list_tasks`
- Acceptance: `set_acceptance`, `show_acceptance`, `update_acceptance_item`, `sync_acceptance_from_validation`
- Party Sync: `start_party`, `add_party_note`, `propose_change`, `end_party`

**Key Parameters**:
- `action` (required): Action to perform
- `plan_name`, `plan_description`: For creating plans
- `stages`: Initial stage definitions [{id, name, description}]
- `stage_id`: Stage identifier
- `task_id`, `task_description`: Task details
- `assignee`: Agent to assign task to
- `scope`: Acceptance target scope (`plan`, `stage`, `task`)
- `functional_acceptance`: Feature/behavior acceptance items
- `artifact_acceptance`: File/artifact acceptance items
- `criterion_id`, `criterion_status`, `criterion_notes`, `criterion_evidence`: For updating one acceptance item
- `validation_task_id`, `validation_kind`, `verification_ref`, `task_suite_ref`: For explicitly binding one acceptance item to runtime validation signals
- `note`, `note_type`: Sync updates (`progress`, `feedback`, `question`, `blocker`, `suggestion`)
- `change_type`, `change_details`: For proposing plan modifications during sync

**Runtime behavior**:
- `show_acceptance` returns both raw `acceptance` and runtime-derived `effective_acceptance`.
- Functional acceptance can auto-resolve from CRDT validation results when items reference `task_suite_ref`, `verification_ref`, or `metadata.validation_kind`.
- Artifact acceptance can auto-resolve when required files/directories/specs already exist in the workspace.
- `plan(action="status")` now includes a compact summary of validation-linked acceptance at plan, stage, and current-task level.
- `start_party` now returns `acceptance_focus`, including unresolved stage acceptance, validation-linked acceptance, and task-level acceptance gaps for the sync kickoff.

**Examples**:

Creating a staged plan:
```
plan(
    action="create",
    plan_name="Build Dashboard",
    plan_description="Implement user dashboard",
    stages=[
        {"id": "design", "name": "Design Phase", "description": "Create specs"},
        {"id": "implement", "name": "Implementation", "description": "Build code"},
        {"id": "test", "name": "Testing", "description": "Verify functionality"}
    ]
)
```

Adding tasks with assignment:
```
plan(
    action="add_task",
    stage_id="implement",
    task_id="api_endpoints",
    task_description="Create REST API endpoints",
    assignee="backend"
)
```

Setting stage acceptance:
```
plan(
    action="set_acceptance",
    scope="stage",
    stage_id="implement",
    functional_acceptance=[
        "Backend API responds with dashboard data",
        {"id": "dashboard_loading", "title": "Loading state handled"}
    ],
    artifact_acceptance={
        "required_files": ["app/backend/routes/dashboard.py"],
        "required_specs": ["design/spec.api.json"]
    }
)
```

Marking an acceptance item complete:
```
plan(
    action="update_acceptance_item",
    scope="stage",
    stage_id="implement",
    criterion_id="dashboard_loading",
    criterion_status="passed",
    criterion_evidence=["tests/dashboard_loading.txt"]
)
```

Binding acceptance to validation explicitly:
```
plan(
    action="sync_acceptance_from_validation",
    scope="stage",
    stage_id="implement",
    criterion_id="dashboard_loading",
    validation_task_id="dashboard_loading_smoke",
    validation_kind="ui_smoke"
)
```

Starting a sync discussion:
```
plan(action="start_party", stage_id="design")
```

Adding sync updates:
```
plan(
    action="add_party_note",
    stage_id="design",
    note="Design approved, but add error states",
    note_type="feedback"
)
```

Proposing changes during sync:
```
plan(
    action="propose_change",
    stage_id="design",
    change_type="add_task",
    change_details={"stage_id": "implement", "task_id": "error_ui", "description": "Add error state UI"}
)
```

Ending sync (applies proposed changes and returns sync summary):
```
plan(action="end_party", stage_id="design")
```

Checking status:
```
plan(action="status")
```

### verify_plan
**Purpose**: Track a verification checklist for validation coverage
**When to use**: During verifier/final validation work, separate from the local implementation `plan`
**Parameters**:
- `action` (required): `create`, `status`, or `complete`
- `items`: Checklist items for `create`
- `item_index` or `item_text`: Which checklist item to complete
- `result`: `pass`, `fail`, or `skip`
**Example**:
```
verify_plan(action="create", items=["[P0] API health smoke", "[P0] Dashboard load path"])
```

---

## 📚 MEMORY & KNOWLEDGE

Memory tools are agent-local operational memory. Knowledge tools are project/global structured knowledge.

### remember
**Purpose**: Store important memory entries for later recall
**When to use**: Decisions, constraints, bug fixes, progress notes
**Parameters**:
- `content` (required): Memory content
- `category` (required): `requirement|decision|bug_fix|pattern|tech_context|warning|progress`
- `importance` (optional): `0.0-1.0`, default `0.5`
- `share_with` (optional): List of agent IDs
**Example**:
```
remember(
    content="Auth must use JWT bearer tokens and 24h expiry",
    category="requirement",
    importance=0.9
)
```

### recall
**Purpose**: Search stored memory with relevance ranking
**When to use**: Retrieve related prior decisions/fixes/context
**Parameters**:
- `query` (optional): Text query
- `category` (optional): Filter category
- `limit` (optional): `1-10`, default `5`
**Behavior Notes**:
- `query` mode uses phrase + token relevance with importance/recency tie-breaks
- no `query` uses importance-first ordering
**Example**:
```
recall(query="jwt token expiration", category="requirement", limit=5)
```

### share_knowledge
**Purpose**: Share knowledge to other agents through message bus
**When to use**: Cross-agent contracts, API/schema constraints, warnings
**Parameters**:
- `to_agents` (required): Target agent IDs
- `content` (required): Content to share
- `category` (required): `tech_context|pattern|warning|requirement|decision`
- `importance` (optional): `low|normal|high`, default `normal`
**Behavior Notes**:
- `to_agents` enum is runtime-discovered (registered core + dynamic agents)
- invalid targets are returned in `invalid_targets` and skipped
**Example**:
```
share_knowledge(
    to_agents=["backend", "frontend"],
    content="API returns snake_case fields; keep DTO mapping explicit",
    category="tech_context",
    importance="high"
)
```

### get_history
**Purpose**: Inspect recent operation history and quick stats
**When to use**: Debug loops, check file/tool/error/knowledge activity
**Parameters**:
- `include` (optional): subset of `tools|files|errors|knowledge`
**Example**:
```
get_history(include=["tools", "errors"])
```

### get_memory_context
**Purpose**: Get formatted current memory context for prompt grounding
**When to use**: Refresh state before planning or large edits
**Parameters**: none
**Example**:
```
get_memory_context()
```

### memory_health_summary
**Purpose**: Get observability snapshot for memory lifecycle
**When to use**: Monitor memory quality/persistence behavior and drift
**Parameters**: none
**Returns (high-signal fields)**:
- `knowledge_count`, `knowledge_ttl_seconds`, `knowledge_expired_removed_total`
- `persistence_mode`, `persistence_path`, `persistence_exists`, `persistence_size_bytes`
- `auto_knowledge` counters: `attempted_total`, `stored_total`, `dedup_skipped_total`, `quality_skipped_total`
**Example**:
```
memory_health_summary()
```

### query_knowledge
**Purpose**: Search global knowledge store (issue/solution/pattern/team practices)
**When to use**: Finding project-wide prior solutions and reusable practices
**Parameters**:
- `query` (required): Search query
**Example**:
```
query_knowledge(query="React form validation patterns")
```

---

## 📋 TASK SUITE EXECUTION (Task Runner)

Task Runner should execute suite artifacts deterministically with `execute_task_suite`.

### execute_task_suite
**Purpose**: Deterministically execute `tasks/tasks.yaml` and persist structured runtime results

**Recommended Call Order**:
1. `execute_task_suite(suite_path="tasks/tasks.yaml", validate_only=true)`
2. `execute_task_suite(suite_path="tasks/tasks.yaml", ...)`
3. `get_validation_summary()`

**Core Parameters**:
- `suite_path`: Suite file path (default `tasks/tasks.yaml`)
- `validate_only` / `dry_run`: Preflight schema/action validation only
- `only_task_ids`: Execute subset
- `stop_on_failure`: Stop at first failed/error task
- `max_concurrent`, `parallel_by_domain`: Concurrency tuning
- `action_timeout_seconds`, `task_timeout_seconds`: Timeout guards
- `action_retry_count`, `action_retry_backoff_ms`: Retry strategy
- `max_auto_retries`: Passed into `handle_validation_failure`

**Outputs**:
- Writes `tasks/execution_results/<task_id>.json`
- CRDT `record_validation_result(...)`
- On failure: `handle_validation_failure(...)`
- Includes machine-readable `error_code` per task/action

**Example**:
```
execute_task_suite(
    suite_path="tasks/tasks.yaml",
    max_concurrent=2,
    parallel_by_domain=true,
    action_retry_count=2,
    action_timeout_seconds=20
)
```

---

## 📋 DEV TASK LIST (Agent Coordination)

Development task coordination between agents. **Different from verifier-owned runtime validation artifacts under `tasks/`.**

### Task Types
- `project`: High-level tasks (only Orchestrator can publish)
- `domain`: Domain-specific tasks (agents publish for their domain)
- `subtask`: Sub-tasks for spawned teams (any agent)

### Task Lifecycle
`pending` → `in_progress` → `completed` / `failed` / `cancelled`

### Domains
`database` | `backend` | `frontend` | `design` | `verifier` | `knowledge` | `any`

### publish_dev_task
**Purpose**: Publish a development task for agents to work on
**When to use**: Breaking down work into trackable tasks
**Permissions**: 
- PROJECT: Only Orchestrator
- DOMAIN: Only for your own domain
- SUBTASK: Any agent (for spawned teams)
**Parameters**:
- `task_id` (required): Unique identifier
- `title` (required): Short title
- `domain` (required): Task domain
- `task_type` (optional): "project", "domain", "subtask" (default: domain)
- `depends_on` (optional): List of task IDs that must complete first
- `assigned_to` (optional): Assign to specific agent
- `priority` (optional): "low", "normal", "high", "urgent"
**Example**:
```
publish_dev_task(
    task_id="impl_get_users",
    title="Implement GET /api/users endpoint",
    domain="backend",
    depends_on=["create_users_table"],
    priority="high"
)
```

### claim_dev_task
**Purpose**: Claim a task to start working on it
**When to use**: Before starting work on a task
**Checks**: Domain permission, dependencies completed, not claimed by others
**Parameters**:
- `task_id` (required): Task to claim
**Example**:
```
claim_dev_task(task_id="impl_get_users")
```

### complete_dev_task
**Purpose**: Mark a claimed task as completed
**When to use**: After finishing the task
**Parameters**:
- `task_id` (required): Task to complete
- `success` (optional): True/False (default: True)
- `result` (optional): Result data for dependent tasks
**Example**:
```
complete_dev_task(
    task_id="impl_get_users",
    success=True,
    result={"endpoint": "/api/users", "response_key": "users"}
)
```

### get_available_dev_tasks
**Purpose**: Get tasks you can claim
**When to use**: Looking for work to do
**Returns**: Pending tasks where you have permission and dependencies are met
**Example**:
```
get_available_dev_tasks()
```

### get_my_dev_tasks
**Purpose**: Get tasks you are currently working on
**When to use**: Checking your active tasks
**Example**:
```
get_my_dev_tasks()
```

### get_dev_task_summary
**Purpose**: Get overview of all development tasks
**When to use**: Understanding project progress
**Returns**: Total, by status, by domain, blocked tasks
**Example**:
```
get_dev_task_summary()
```

### escalate_to_lead
**Purpose**: Escalate a request to Orchestrator
**When to use**: 
- Need cross-domain coordination
- Can't publish task due to permissions
- Need approval for significant changes
**Parameters**:
- `request_type` (required): Type of escalation
- `description` (required): What you need
- `details` (optional): Additional details
**Example**:
```
escalate_to_lead(
    request_type="cross_domain_coordination",
    description="Need frontend to add loading states",
    details={"api": "/api/users"}
)
```

---

## 🎯 AGENT LIFECYCLE

Tools for agent workflow control.

### finish
**Purpose**: Signal task completion, notify downstream agents
**When to use**: When your task is complete
**Parameters**:
- `summary` (optional): Summary of work done
- `notify` (optional): Whether to notify other agents
**Example**:
```
finish(summary="Created users and products tables", notify=true)
```

### deliver_project
**Purpose**: Mark entire project as complete (Orchestrator only)
**When to use**: All work done, ready for delivery
**Parameters**:
- `verification_summary` (optional): Final verification notes
**Example**:
```
deliver_project(verification_summary="All endpoints tested, UI verified")
```

### read_memory_bank
**Purpose**: Read project documentation
**When to use**: Understanding project context
**Parameters**:
- `file` (optional): Specific file (project_brief, tech_context, etc.)
**Example**:
```
read_memory_bank(file="tech_context")
```

---

## 🌍 WEB RESEARCH

Use these tools when you need current external information, documentation, examples,
release notes, or reference webpages. Prefer these over shell `curl`/ad-hoc scripts so
results are bounded and structured.

### web_search
**Purpose**: Search the public web for current text information and return ranked URLs/snippets
**When to use**: Finding external docs, package release notes, API examples, reference pages, or current facts
**Parameters**:
- `query` (required): Search query
- `limit` (optional): Max results, 1-10
**Example**:
```
web_search(query="FastAPI release notes current version", limit=5)
```
**Tips**:
- Use this before `web_fetch` when you do not already know the URL.
- Store durable findings with knowledge tools only if they are reusable.

### web_fetch
**Purpose**: Fetch a URL and return readable page text with scripts/styles stripped
**When to use**: Reading details from a specific documentation page or reference webpage
**Parameters**:
- `url` (required): HTTP or HTTPS URL
- `max_chars` (optional): Max returned text chars, 500-20000
**Example**:
```
web_fetch(url="https://fastapi.tiangolo.com/release-notes/", max_chars=8000)
```
**Tips**:
- Use `web_search` first if you need to discover the page.
- Use browser tools or `capture_webpage` when you need screenshots/visual layout, not just text.

---

## 🔍 SEARCH TOOLS

### search_tools
**Purpose**: Search this documentation for tools
**When to use**: Finding the right tool for a task
**Parameters**:
- `query` (required): Search keywords
**Example**:
```
search_tools(query="send message to agent")
```

---

## Quick Reference by Task

| Task | Tools to Use |
|------|-------------|
| Edit existing file | `read` → `edit` / `apply_patch` |
| Create new file | `write` |
| Delete file | `delete_file` |
| Find files | `glob`, `grep` |
| Talk to agents | `send_message`, `ask_agent` |
| Parallel work | `parallel_execute` |
| Debug complex bug | `run_parallel_reasoning` |
| Check project status | `get_project_summary` |
| Run tests | `execute_bash`, `test_api` |
| Start services | `docker_up`, `run_background` |
| Test UI | `browser_navigate`, `browser_screenshot` |
| Research current docs | `web_search`, `web_fetch` |
| Gather visual references | `search_photos`, `capture_webpage`, `save_image` |
| Mark done | `finish`, `deliver_project` |

