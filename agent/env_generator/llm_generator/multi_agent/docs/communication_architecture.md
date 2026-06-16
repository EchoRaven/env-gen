# Communication Architecture

The multi-agent system uses a **two-layer communication architecture**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Two-Layer Communication Architecture                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌────────────────────────────┐   ┌────────────────────────────────────┐  │
│   │       Message Bus          │   │          HubRegistry               │  │
│   │      (event-driven)        │   │         (state store)              │  │
│   └────────────────────────────┘   └────────────────────────────────────┘  │
│            Push                              Observe + Update              │
│        one-shot messages              RegistryHub/WorkHub/CodeHub/EventHub      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. Message Bus: Event-Driven Communication

**Purpose**: Active, one-shot communication between agents.

```python
# Good fits for the Message Bus
message_bus.send(to="frontend", type="task_complete", content={
    "agent": "backend",
    "message": "GET /api/users implemented"
})

message_bus.send(to="backend", type="bug_report", content={
    "from": "verifier",
    "issue": "GET /api/users returns 500"
})

message_bus.broadcast(type="announcement", content={
    "message": "Project phase changed to implementation"
})
```

| Property | Notes |
|------|------|
| Mode | Push |
| Message lifecycle | Disappears after consumption |
| Best for | Notifications, bug reports, questions, urgent interrupts |
| Not suitable for | Durable state or queryable shared data |

## 2. HubRegistry: Unified Shared State

**Purpose**: All shared state, accessed through four typed hubs.

Composed of four hubs — RegistryHub (API contracts, tables), WorkHub (tasks, plans, pages), CodeHub (git worktree, checks, diffs), EventHub (status, inbox, pub/sub bridge).

```python
# State definition and updates
hubs.registryhub.register_endpoint("GET", "/api/users", schema={
    "response": {"users": [], "total": 0}
}, provider="backend", agent="design")

# Build history
hubs.codehub.record_check("build:frontend", "success", "npm run build")

# API dependency tracking
hubs.registryhub.register_consumer("GET /api/users", "src/pages/Users.jsx", "frontend")

# Status snapshot
statuses = hubs.eventhub.get_all_agent_statuses()
```

| Property | Notes |
|------|------|
| Storage | JSON + CRDT data structures |
| Concurrency | Lock-free, automatic conflict resolution (LWW) |
| Directory | `shared/crdt/` |

### CRDT Storage Layout

```
shared/crdt/
├── endpoints.json       # API definitions
├── tables.json          # Database tables
├── pages.json           # Frontend pages
├── agent_status.json    # Agent status
├── tasks.json           # Verifier runtime validation task/result index
├── dev_tasks.json       # Development tasks for agent collaboration
├── builds.json          # Build history
├── token_usage.json     # Token accounting
├── performance.json     # Performance metrics
├── retries.json         # Retry tracking
├── project.json         # Project metadata
├── implementations.json # Shared implementation knowledge
├── contracts.json       # API contracts
└── api_consumers.json   # API consumer mapping
```

## 3. Dev Task List: Development Task Coordination

**Purpose**: Task assignment and collaboration between agents. This is separate from verifier-owned runtime validation tasks.

### Task Types

| Type | Description | Allowed publisher |
|------|------|---------|
| `project` | Project-level task | Orchestrator |
| `domain` | Domain-specific task | The owning domain agent |
| `subtask` | Subtask | Any agent |

### Task Status

```
pending → in_progress → completed
                     → failed
                     → cancelled
```

### Permission Matrix

| Domain | Agents allowed to claim |
|------|---------------|
| `database` | `database`, `worker`, `analysis_worker` |
| `backend` | `backend`, `worker`, `analysis_worker` |
| `frontend` | `frontend`, `worker`, `analysis_worker` |
| `design` | `design`, `worker` |
| `verifier` | `verifier`, `review_worker`, `analysis_worker`, `worker` |
| `any` | All agents |

### Example Usage

```python
# Design publishes a domain task
publish_dev_task(
    task_id="create_users_table",
    title="Create users table",
    domain="database",
    priority="high"
)

publish_dev_task(
    task_id="impl_get_users",
    title="Implement GET /api/users",
    domain="backend",
    depends_on=["create_users_table"]  # dependency
)

# Database sees claimable tasks
tasks = get_available_dev_tasks()  # only database tasks are visible

# Database claims a task
claim_dev_task(task_id="create_users_table")

# Completing the task automatically unlocks dependent work
complete_dev_task(
    task_id="create_users_table",
    result={"columns": ["id", "email", "name"]}
)

# Backend can now claim impl_get_users

# Escalate cross-domain coordination to the lead
escalate_to_lead(
    request_type="cross_domain",
    description="Need frontend loading states for new API"
)
```

### Cross-Domain Rule

```
Do not publish cross-domain tasks directly.
Backend should not assign work to Frontend directly.

Preferred options:
1. send_message() for lightweight notification
2. escalate_to_lead() to route through Orchestrator
3. spawn_worker() + publish_dev_task() to create a temporary worker team
```

### CRDT Tool Overview

| Tool | Purpose | Primary users |
|--------|------|-----------|
| **State management** | | |
| `update_endpoint` | Create or update API definitions | Design, Backend |
| `get_endpoints` | Query API definitions | All agents |
| `update_table` | Create or update table definitions | Design, Database |
| `get_tables` | Query table definitions | All agents |
| `update_page` | Create or update page definitions | Design, Frontend |
| `get_pages` | Query page definitions | All agents |
| `update_my_status` | Update the caller's own status | All agents |
| `get_agent_statuses` | View all agent statuses | Orchestrator |
| **Dependency tracking** | | |
| `register_api_usage` | Register API usage | Frontend |
| `get_api_consumers` | View API consumers | Backend |
| `get_file_dependencies` | View file dependencies | Frontend |
| `get_api_changes` | View API change notifications | Frontend |
| `get_dependency_graph` | View dependency graph | Orchestrator, Verifier |
| **Build and verification** | | |
| `record_build` | Record build result | All agents |
| `get_build_status` | View build status | Verifier, Orchestrator |
| `get_verification_checklist` | View verification checklist | Verifier, Orchestrator |
| **Metrics and dashboards** | | |
| `get_token_usage` | View token usage | Orchestrator |
| `get_dashboard` | View project dashboard | Orchestrator |
| **Knowledge sharing** | | |
| `share_implementation` | Share a good implementation pattern | All agents |

## Selection Guide

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Which system should you use?                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Do you need to actively notify another agent?                             │
│       ├─ Yes (bug, completion, question, urgent event) → Message Bus        │
│       └─ No                                                                 │
│                                                                             │
│   For all other shared state:                                               │
│       → HubRegistry (via hub tools)                                         │
│         - state definitions (API, table, page) → RegistryHub / WorkHub           │
│         - progress tracking                    → WorkHub                    │
│         - build history                        → CodeHub                    │
│         - dependency tracking                  → RegistryHub                     │
│         - inbox / pub-sub                      → EventHub                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Typical Workflows

### API Development Flow

```
1. Design
   └─ crdt.update_endpoint("GET /api/users", status="defined")

2. Frontend (can start as soon as the API is defined)
   ├─ endpoints = crdt.get_usable_endpoints()
   ├─ build UI components
   └─ crdt.register_api_usage("GET /api/users", "Users.jsx")

3. Backend
   ├─ implement the API
   ├─ crdt.update_endpoint("GET /api/users", status="implemented")
   └─ message_bus.send(to="frontend", type="api_ready")  # optional

4. If Backend changes the API
   └─ Frontend receives the change through get_api_changes()
```

### Bug Fix Flow

```
1. Verifier finds a bug
   └─ message_bus.send(to="backend", type="bug_report", ...)

2. Backend fixes it
   └─ crdt.update_my_status("working", task="Fixing bug")

3. Verifier validates the fix
   └─ crdt.record_build("backend", "success")
```

