# Four-Hub Architecture — Design Spec

**Status:** Approved, ready for implementation planning
**Author:** haibotong + Claude (Opus 4.7, 1M context)
**Date:** 2026-05-21
**Replaces:** `CRDTWorkspace` in `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py`

---

## 1. Goal

Replace the 1994-line monolithic `CRDTWorkspace` (and its 787-line satellite `file_coordination.py`) with four focused collaboration hubs that mirror real software-engineering practice:

| Hub | Analog | Owns |
|---|---|---|
| **CodeHub** | GitHub + real `git` | repos, branches, commits, PRs, reviews, checks, merges, releases, agent worktrees |
| **APIHub** | Apifox | endpoint contracts, schemas, examples, mocks, consumers, contract tests, breaking-change detection |
| **WorkHub** | Notion + Jira/Linear | docs (pages/blocks), plans/stages/tasks, attendees, comments, decisions |
| **EventHub** | Gmail + inbox | durable event log, per-agent inbox, subscriptions, threads — **source of truth for cross-hub events** |

The existing `MessageBus` (`agent/utils/communication.py`, 453 lines) is kept untouched as the in-process async **transport** for live event delivery. A new `MessageBusBridge` connects `EventHub.publish` to `MessageBus.send`/`broadcast`.

## 2. Non-Goals

- Replacing the in-process `MessageBus` itself.
- Replacing the `WorkspaceManager` (it becomes a thinner path resolver post-CodeHub).
- Designing a UI on top of the hubs (out of scope, separate workstream).
- Re-architecting the agent runtime (`agents/base.py`, mixins) — agents continue to access hubs only through tools.

## 3. Strategic Decisions (already locked)

| # | Decision | Rationale |
|---|---|---|
| 1 | `CRDTWorkspace` and `crdt.py` / `crdt_dev_tasks.py` / `crdt_validation.py` / `crdt_projection.py` are **deleted entirely** | Avoids two parallel naming systems; eliminates dual-write drift permanently |
| 2 | File coordination uses **real `git worktree`**, not CRDT regions/anchors | Matches real engineering; agents work on isolated branches and resolve conflicts via merge |
| 3 | **CodeHub wraps real `git`** via subprocess; agents never call `git` directly | Single chokepoint for git operations; metadata + git state stay aligned |
| 4 | **EventHub is the source of truth**, MessageBus is transport | Agents that were offline still see events on next start; live agents are notified instantly |
| 5 | Migration is **per-hub atomic cutover**, order: APIHub → EventHub bridge → WorkHub → CodeHub | First cut is lowest risk; CodeHub last because real-git introduction is highest blast radius |

## 4. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│  Orchestrator (holds HubRegistry + MessageBus)               │
└───────────────────────┬──────────────────────────────────────┘
                        │
        ┌───────────────┼────────────────┬─────────────────┐
        ▼               ▼                ▼                 ▼
   ┌────────┐      ┌────────┐       ┌────────┐       ┌──────────┐
   │CodeHub │      │ APIHub │       │WorkHub │       │ EventHub │
   └───┬────┘      └────┬───┘       └────┬───┘       └────┬─────┘
       │                │                │                │
       │                └──── _emit ─────┴────────────────┘
       │                                                  │
       │ wraps                                            │ on publish
       ▼                                                  ▼
  ┌─────────┐                                      ┌──────────────┐
  │ git     │                                      │ MessageBus   │
  │worktree │                                      │ (in-process) │
  └─────────┘                                      └──────┬───────┘
                                                          │ deliver
                                                          ▼
                                              ┌────────────────────┐
                                              │  Agent.receive_msg │
                                              └────────────────────┘
```

**Invariants:**

1. Hubs are source of truth (CRDT JSON on disk + real git for CodeHub).
2. Every hub write: `update store → EventHub.publish (synchronous, includes disk flush) → MessageBusBridge.deliver (async)`.
3. `_emit` returns only after the event is persisted, so hub methods returning success guarantee event recoverability.
4. CodeHub is the only hub that touches `git`; other hubs are pure JSON CRDT stores.
5. Cross-hub references are loose string IDs (`pr.linked_tasks=["task_xxx"]`). Each hub maintains its own inverse indexes when it cares (e.g., APIHub `consumers` for breaking-change fan-out).
6. Agents never hold a hub reference directly — only via tools. Agents hold MessageBus (for live receive) and a workspace path.

**Deleted components:**

- `multi_agent/runtime/crdt.py` (1994 lines)
- `multi_agent/runtime/crdt_dev_tasks.py` (406 lines)
- `multi_agent/runtime/crdt_validation.py` (493 lines)
- `multi_agent/runtime/crdt_projection.py` (255 lines)
- `multi_agent/runtime/crdt_observer.py` (298 lines) — push-driven EventHub replaces polling observation
- `multi_agent/runtime/file_coordination.py` (787 lines)
- `multi_agent/runtime/hub_workspace.py` — replaced by new `runtime/hubs.py:HubRegistry`
- `multi_agent/runtime/workhub.py` and `codehub.py` (5-line re-export shims) — direct import from `runtime/hubs/`
- `tools/crdt_tools.py` (1351 lines), `tools/crdt_dev_task_tools.py`, `tools/crdt_file_coordination_tools.py`, `tools/crdt_validation_tools.py`, `tools/crdt_tool_base.py`

## 5. APIHub (Apifox-style)

### 5.1 Responsibility
Sole authority on API contracts. Lifecycle from design spec → backend implementation → verifier contract test → consumer registration → deprecation.

### 5.2 Stores
```
shared/crdt/
├── apihub_endpoints.json
├── apihub_schemas.json        # historical versions for diff
├── apihub_examples.json       # request/response samples
├── apihub_mocks.json          # mock responses for frontend pre-implementation
├── apihub_consumers.json      # {endpoint_id, file_path, agent, line_no}
├── apihub_contract_tests.json # verifier results with evidence
├── apihub_reviews.json        # review requests with state
└── apihub_breaking_changes.json
```

> No separate `providers.json` — provider is a field on endpoint.

### 5.3 Endpoint Lifecycle
`defined` → `implementing` → `implemented` → `tested` → (optional `deprecated`)

Frontend can use an endpoint as soon as status is `defined` (against mocks). The full machine lives in `apihub.register_endpoint(status=...)` and `apihub.update_schema(...)`.

### 5.4 Public API
```python
class APIHub:
    # writes
    register_endpoint(method, path, schema, provider, agent, status, **meta) -> dict
    update_schema(endpoint_id, request=None, response=None, agent) -> dict
    register_consumer(endpoint_id, file_path, agent, metadata) -> dict
    unregister_consumer(endpoint_id, file_path, agent) -> dict
    record_contract_test(endpoint_id, result, evidence, agent) -> dict
    add_mock(endpoint_id, mock_response, agent) -> dict
    add_example(endpoint_id, request_example, response_example, agent) -> dict
    request_review(endpoint_id, reviewers, reason, agent) -> dict
    submit_review(review_id, reviewer, decision, comments) -> dict
    deprecate_endpoint(endpoint_id, replacement_id, agent) -> dict

    # reads
    get_endpoint(endpoint_id) -> dict
    get_endpoints(status_filter=None, provider=None) -> Dict[str, dict]
    get_consumers(endpoint_id) -> List[dict]
    get_dependencies_for_file(file_path) -> List[dict]
    get_breaking_changes(since_ts=None) -> List[dict]
    get_contract_test_results(endpoint_id) -> List[dict]

    # internal
    _detect_breaking_change(old_schema, new_schema) -> dict
    _emit(event_type, payload, recipients, priority)
```

### 5.5 Breaking-Change Detection (enhanced over current stub)

```python
breaking = {
    "removed_response_fields": [],
    "type_changed_fields": [],
    "required_added_in_request": [],
    "path_changed": False,
    "method_changed": False,
    "response_key_changed": False,
    "auth_added": False,
}
is_breaking = any(...)
```

On `is_breaking`:
1. Write to `apihub_breaking_changes.json`.
2. Look up affected agents via `apihub_consumers`.
3. `EventHub.publish("breaking_change_detected", recipients=affected_agents, priority="urgent", links={"endpoint_ids":[endpoint_id]})`.
4. **Auto-create a WorkHub fix task** per affected agent (`assignee=affected_agent`, `domain` derived from agent, `linked_apis=[endpoint_id]`).

### 5.6 Tool Surface (10 tools, `apihub_*` prefix)

> **Naming convention:** LLM-facing tool names use underscore (`apihub_register_endpoint`) to match the existing `tools/hub_tools.py` convention. Python method names on the `APIHub` class stay short (`register_endpoint`); the prefix is only on the tool wrapper.

Provider side: `apihub_register_endpoint`, `apihub_update_schema`, `apihub_record_contract_test`, `apihub_deprecate_endpoint`, `apihub_request_review`.
Consumer side: `apihub_list_endpoints`, `apihub_get_endpoint`, `apihub_register_consumer`, `apihub_get_dependencies_for_file`, `apihub_get_breaking_changes`.

### 5.7 Old → New Call Map
| Old | New |
|---|---|
| `workspace.update_endpoint(key, data, agent)` | `apihub.register_endpoint(method, path, schema, ...)` |
| `workspace.get_endpoints()` | `apihub.get_endpoints()` |
| `workspace.register_api_usage(...)` | `apihub.register_consumer(...)` |
| `workspace.get_api_consumers(key)` | `apihub.get_consumers(endpoint_id)` |
| `workspace.get_api_change_notifications(agent)` | `apihub.get_breaking_changes()` + `eventhub.list_inbox` |
| `workspace._notify_api_consumers(...)` | **Deleted** — breaking change auto-fires WorkHub task |

## 6. WorkHub (Notion + Jira/Linear)

### 6.1 Responsibility
All collaboration content not code/contract: shared docs, plans, tasks, comments, attendees, decisions.

### 6.2 Internal Namespaces
- `docs/` — Notion-style pages + blocks
- `board/` — Jira/Linear-style plans + tasks
- `shared/` — attendees, comments, reactions, decisions

Single hub, single process today. Namespace split keeps future process-split low-cost.

### 6.3 Stores
```
shared/crdt/
├── workhub_pages.json
├── workhub_blocks.json
├── workhub_plans.json
├── workhub_tasks.json
├── workhub_attendees.json
├── workhub_comments.json
├── workhub_reactions.json
└── workhub_decisions.json
```

### 6.4 Data Shapes

```python
Page = {
    "id": "page_xxx", "title": str,
    "parent": page_id | None,
    "kind": "spec" | "rfc" | "notes" | "postmortem" | "decision_log",
    "status": "draft" | "active" | "archived",
    "attendees": [agent_ids],
    "created_by": agent, "created_at": ts,
    "_updated_by": agent, "_updated_at": ts,
}

Block = {
    "id": "block_xxx", "page_id": page_id,
    "ord": int,                  # +1024 default for insert-between
    "type": "text" | "code" | "checklist_item" | "decision" | "table_row",
    "content": str | dict,
    "metadata": dict,
    "created_by": agent, "_updated_by": agent, "_updated_at": ts,
}

Plan = {
    "id": "plan_xxx", "page_id": page_id | None, "title": str,
    "stages": [{"id": "design", "name": "Design", "order": 0}, ...],
    "task_ids": [task_id, ...],
    "status": "active" | "completed" | "cancelled",
    "owner": agent, "_updated_by": agent, "_updated_at": ts,
}

Task = {
    "id": "task_xxx", "plan_id": plan_id | None, "stage_id": stage_id | None,
    "title": str, "description": str,
    "assignee": agent | None,
    "domain": "database" | "backend" | "frontend" | "design" | "verifier" | "any",
    "status": "pending" | "in_progress" | "completed" | "failed" | "cancelled",
    "depends_on": [task_id, ...], "blocks": [task_id, ...],
    "claimed_by": agent | None, "claim_token": str | None,
    "claimed_at": ts, "completed_at": ts,
    "result": dict, "evidence": dict,
    "linked_pr": pr_id | None, "linked_apis": [endpoint_id, ...],
    "priority": "urgent" | "high" | "normal" | "low",
    "metadata": dict, "_updated_by": agent, "_updated_at": ts,
}

Attendee = {
    "id": "{resource_type}:{resource_id}:{agent}",
    "resource_type": "page" | "plan" | "task",
    "resource_id": str, "agent": agent_id,
    "role": "owner" | "reviewer" | "contributor" | "viewer",
    "invited_by": agent, "joined_at": ts,
}
```

### 6.5 Critical Semantics (preserved from `crdt_dev_tasks.py`)
- `claim_task` uses **write-then-read-verify** to defeat CRDT-level race (two agents both think they claimed).
- `domain` permission matrix (e.g., `backend` agent can only claim `backend`/`any` tasks; `worker` can claim any) is **moved out of Python into `agents_config.yaml`** under `task_domains:`.
- `depends_on`/`blocks` is bidirectional; `complete_task` auto-updates dependent `blocks` lists.

### 6.6 Blocks Are LWW, Not Rich-Text CRDT
Block-level last-writer-wins is the conflict policy. Same block edited twice: later write wins. Block size is intentionally small to keep loss bounded. Agents needing finer collaboration split blocks.

### 6.7 Tool Surface (12 tools, `workhub_*` prefix)
`workhub_create_page`, `workhub_append_block`, `workhub_list_pages`, `workhub_get_page`,
`workhub_create_plan`, `workhub_create_task`, `workhub_claim_task`, `workhub_complete_task`,
`workhub_list_tasks`, `workhub_available_tasks`,
`workhub_invite`, `workhub_comment`.

(`record_decision`, `react`, `link_*`, `archive_page` are second-tier — opted in via `tool_bundles` per profile.)

### 6.8 Old → New Call Map
| Old | New |
|---|---|
| `workspace.publish_dev_task(...)` | `workhub.create_task(...)` |
| `workspace.claim_dev_task(...)` | `workhub.claim_task(...)` |
| `workspace.complete_dev_task(...)` | `workhub.complete_task(...)` |
| `workspace.update_plan(plan_id, plan)` | `workhub.create_plan(...)` / `workhub.update_plan_metadata(...)` |
| `workspace.claim_plan_task(plan, stage, task, agent)` | `workhub.claim_task(stable_task_id, agent)` |
| `workspace.update_page(name, data)` | `workhub.create_page(...)` / `workhub.append_block(...)` (shape change — audit every old call site) |

## 7. CodeHub (GitHub + real git)

### 7.1 Disk Topology
```
output_dir/
├── .git/                        # primary repo
├── main/                        # main branch worktree (orchestrator + verifier)
├── workspaces/
│   ├── design/                  # worktree, branch: agent/design
│   ├── backend/                 # worktree, branch: agent/backend
│   ├── frontend/
│   ├── database/
│   ├── verifier/
│   ├── knowledge/
│   └── worker-xxx/              # dynamic worker worktree, branch: worker/xxx
└── shared/crdt/                 # all hub JSON state (NOT in git, see 7.10.2)
```

### 7.2 Branch Convention
| Use | Pattern |
|---|---|
| Mainline | `main` |
| Resident agent | `agent/{agent_id}` (long-lived) |
| Dynamic worker | `worker/{worker_id}` (deleted after PR merge) |
| Feature/fix | `feat/{slug}` / `fix/{slug}` |
| Release tag | `v0.x.y` |

### 7.3 Agent Write Model
1. Agent receives a WorkHub task.
2. Agent edits files freely in its own worktree (no region locks).
3. Agent calls `codehub.commit(message, files=...)` — runs real `git add` + `git commit` in that worktree.
4. Agent calls `codehub.open_pr(target="main", reviewers, linked_tasks, linked_apis)` — records PR metadata, **does not merge**.
5. Reviewer agent receives EventHub notification → `codehub.get_diff(pr_id)` → `codehub.review(pr_id, "approve" | "request_changes" | "comment", inline_comments)`.
6. All required reviewers approve + checks pass → `pr.merge_state = "ready"`.
7. Authorized merger calls `codehub.merge_pr(pr_id, strategy="squash")`.
8. Conflict on merge → CodeHub auto-creates WorkHub task assigned to `pr.author`, `pr.status = "conflict"`; clean merge → `pr.status = "merged"`, EventHub notifies linked task owners.

### 7.4 Invariants
1. Only `main` is authoritative — agents don't cross-merge.
2. Agents never call `git` directly — only via CodeHub.
3. On startup, CodeHub runs `_reconcile()` to sync `codehub_branches.json` HEADs from real `git` (drift is warned, not fatal).
4. Every `commit` records `(commit_hash, branch, files_changed, author_agent, related_task_id)` to `codehub_commits.json` so LLM agents can read commit history without learning git.

### 7.5 Stores
```
shared/crdt/
├── codehub_repos.json
├── codehub_branches.json
├── codehub_commits.json
├── codehub_pull_requests.json
├── codehub_code_reviews.json
├── codehub_checks.json
└── codehub_releases.json
```

### 7.6 Public API
```python
class CodeHub:
    def __init__(self, repo_root, crdt_dir, eventhub):
        self.git = GitOps(repo_root)

    # worktree lifecycle (called during agent spawn)
    ensure_repo() -> dict
    register_agent_worktree(agent_id) -> dict
    cleanup_worktree(agent_id) -> dict

    # write
    commit(agent_id, message, files=None) -> dict
    open_pr(branch, target, title, body, reviewers, linked_tasks, linked_apis, agent) -> dict
    push_more_commits(pr_id) -> dict

    # review
    get_diff(pr_id, format="unified", max_lines=5000) -> str
    get_files_in_pr(pr_id) -> List[dict]
    get_file_content(pr_id, file_path) -> str
    review(pr_id, reviewer, state, inline_comments=[]) -> dict
    request_review(pr_id, reviewers, paths=None, reason) -> dict

    # checks (verifier)
    record_check(pr_id, name, status, evidence, agent="verifier") -> dict

    # merge
    merge_pr(pr_id, strategy="squash", agent) -> dict
    resolve_conflict(pr_id, resolution_files, agent) -> dict

    # read
    get_pr(pr_id) -> dict
    list_prs(status=None, author=None, reviewer=None) -> List[dict]
    get_commit(hash) -> dict
    get_branches() -> List[dict]
    get_blob(commit_hash, path) -> str

    # release
    create_release(tag, source="main", notes, agent) -> dict
```

### 7.7 `GitOps` Thin Wrapper (`runtime/hubs/codehub/git_ops.py`)
Direct `subprocess.run(["git", ...])` — no GitPython dependency. ~15 git commands needed: `init`, `add`, `commit`, `worktree`, `checkout`, `branch`, `merge`, `diff`, `show`, `log`, `rev-parse`, `status`, `push`, `fetch`, `tag`.

### 7.8 Spawn Integration (`agent_spawn_service.py`)
```python
async def spawn(self, request: AgentSpawnRequest) -> Agent:
    # ... existing setup ...
    if not request.is_dynamic_worker_inheriting_worktree:
        await self.orch.hubs.codehub.register_agent_worktree(request.agent_id)
    agent.workspace_path = output_dir / "workspaces" / request.agent_id
    # ... rest ...
```

Dynamic workers may opt in to `inherit_worktree=True` (share parent's worktree; useful for review/analysis workers).

### 7.9 Tool Surface (13 tools, `codehub_*` prefix)
`codehub_commit`, `codehub_open_pr`, `codehub_list_prs`, `codehub_get_pr`, `codehub_get_diff`, `codehub_get_file_content`, `codehub_request_review`, `codehub_review_pr`, `codehub_merge_pr`, `codehub_resolve_conflict`, `codehub_record_check`, `codehub_create_release`, `codehub_get_blob`.

### 7.10 Old → New Call Map (largest delta)
| Old | New |
|---|---|
| `workspace.publish_file_region` / `claim_file_region` / `complete_file_region` | **Deleted** — git branches isolate writers |
| `workspace.reserve_file_anchor` / `record_file_anchor_op` | **Deleted** |
| `workspace.record_file_read` / `record_file_write` / `sync_file_change` | **Deleted** — `git log --name-status` is the answer |
| `workspace.sync_text_document_snapshot` | **Deleted** |
| `file_coordination.py:FileCoordinator` | **Deleted entirely** |
| `WorkspaceManager` per-agent dir isolation | `codehub.register_agent_worktree(agent_id)`; `WorkspaceManager` reduced to path resolution |
| `read_file('../backend/...')` | `codehub.get_blob(commit_hash, path)` or `read_file('../main/...')` |

### 7.10.1 `git` Dependency
The Docker base image used by `run_*_generation.sh` must include `git`. Verify this in the cutover PR.

### 7.10.2 `shared/crdt/` Excluded from `git`
Hub CRDT state is project runtime state, not source code. `ensure_repo()` writes `.gitignore` including `shared/crdt/`, `node_modules/`, `__pycache__/`, `.checkpoint.json`.

### 7.10.3 Large PR Diffs
`get_diff(pr_id, max_lines=5000)` returns truncation marker + per-file summary above limit, avoiding LLM context blowout.

### 7.10.4 Commit Message Trailers
CodeHub auto-appends `[agent: backend] [task: task_xxx]` for `git log --grep` reverse lookup.

## 8. EventHub + MessageBus Bridge

### 8.1 Stores
```
shared/crdt/
├── eventhub_events.json
├── eventhub_threads.json
├── eventhub_subscriptions.json
└── eventhub_inboxes.json
```

### 8.2 Event Shape
```python
Event = {
    "id": "evt_xxx",
    "thread_id": "thread_xxx",
    "source_hub": "apihub" | "workhub" | "codehub" | "system",
    "event_type": str,
    "resource_type": str,
    "resource_id": str,
    "payload": dict,
    "recipients": [agent_id, ...],
    "priority": "urgent" | "high" | "normal" | "low",
    "actor": agent_id,
    "created_at": float,
    "links": {"task_ids": [...], "pr_ids": [...], "endpoint_ids": [...], "page_ids": [...]},
}
```

### 8.3 Thread ID Convention
| Hub | Event type | thread_id |
|---|---|---|
| APIHub | endpoint_*, schema_*, breaking_change_*, review_* | `thread:endpoint:{id}` |
| WorkHub | task_* | `thread:task:{id}` |
| WorkHub | page_*, block_*, comment_* | `thread:page:{id}` |
| WorkHub | plan_* | `thread:plan:{id}` |
| CodeHub | pr_*, review_*, check_* | `thread:pr:{id}` |
| CodeHub | commit_* | `thread:branch:{name}` |

### 8.4 Publish Flow
```
hub._emit(event_type, payload, recipients)
   └─> EventHub.publish(...)
         ├─ persist event + thread + per-recipient inbox  (synchronous, blocks until disk flush)
         └─ await bridge.deliver(event)                    (async; live recipients get MessageBus.send)
```

`_emit` returns only after persistence + bridge enqueue. MessageBus delivery itself is async — does not block hub method return.

### 8.5 Subscription
```python
Subscription = {
    "id": "{agent}:{source_hub}:{event_type_or_*}",
    "agent": agent_id,
    "source_hub": "apihub" | "*",
    "event_type": "pr_opened" | "*",
    "filter": dict | None,                    # e.g., {"linked_apis_provider": "backend"}
    "priority_floor": "normal",
    "delivery": "live" | "inbox_only",
}
```

Default subscriptions declared in `agents_config.yaml`:
```yaml
backend:
  default_subscriptions:
    - source_hub: apihub
      event_type: breaking_change_detected
      filter: {linked_apis_provider: backend}
    - source_hub: workhub
      event_type: task_created
      filter: {assignee: backend}
    - source_hub: codehub
      event_type: review_requested
      filter: {reviewers: backend}
```

Auto-registered at spawn; agents may add/remove via `eventhub.subscribe/unsubscribe` tools.

### 8.6 `MessageBusBridge` (`runtime/hubs/eventhub/bridge.py`)
```python
class MessageBusBridge:
    def __init__(self, eventhub: EventHub, message_bus: MessageBus):
        self.eventhub, self.bus = eventhub, message_bus

    async def deliver(self, event: Event) -> DeliveryResult:
        targets = self._resolve_targets(event)
        for agent_id in targets:
            agent = self.bus.get_agent(agent_id)
            if not agent:
                continue                          # offline; inbox already has it
            msg = self._to_base_message(event, agent_id)
            try:
                await agent.receive_message(msg)
                self.eventhub.mark_delivered(agent_id, event.id)
            except Exception as e:
                # logged, not retried; agent will see via list_inbox catch-up
                pass

    def _resolve_targets(self, event) -> Set[str]:
        return set(event.recipients or []) | {
            sub["agent"]
            for sub in self.eventhub.get_subscriptions()
            if self._matches(sub, event) and sub["delivery"] == "live"
        }
```

`mark_delivered` flips `delivered=True` (still `read=False`); agent flips `read=True` when it actually consumes the event.

### 8.7 Agent-Side Reception
1. **Live (push)**: `EnvGenAgent.receive_message` gets a `BaseMessage` with `message_type=HUB_EVENT`; header carries original `event_id` for trace.
2. **Catch-up (pull)**: `agents/runtime/sync.py` calls `eventhub.list_inbox(agent, unread_only=True, since_ts=last_seen)` on first step after spawn / restart, injects priority-sorted summary into LLM context. `last_seen` is the `max(received_at)` over already-read inbox items for that agent (persisted in `eventhub_inboxes.json` per item; no separate cursor store needed).
3. Resident agents recheck inbox every N steps via the same `_collect_eventhub_summary()` flow — bounded summary, not full event dump, to control token usage.

### 8.8 EventHub Public API
```python
class EventHub:
    publish(source_hub, event_type, payload, recipients=[], priority="normal",
            resource_type=None, resource_id=None, thread_id=None, actor=None,
            links={}) -> Event

    subscribe(agent, source_hub="*", event_type="*", filter=None,
              priority_floor="low", delivery="live") -> Subscription
    unsubscribe(subscription_id) -> bool
    get_subscriptions(agent=None) -> List[Subscription]

    list_inbox(agent, unread_only=True, since_ts=None, limit=50, priority_min=None) -> List[Event]
    mark_read(agent, event_id) -> dict
    mark_all_read(agent, before_ts=None) -> int
    mark_delivered(agent, event_id) -> dict     # called by bridge

    get_event(event_id) -> Event
    get_thread(thread_id) -> List[Event]
    reply_in_thread(thread_id, agent, body, recipients=[]) -> Event

    attach_bridge(bridge: MessageBusBridge) -> None
```

### 8.9 Tool Surface (6 tools, `eventhub_*` prefix)
`eventhub_list_inbox`, `eventhub_mark_read`, `eventhub_get_thread`, `eventhub_reply`, `eventhub_subscribe`, `eventhub_unsubscribe`.

### 8.10 Old → New Call Map
| Old | New |
|---|---|
| `MessageBus.publish(...)` (direct) | hub `_emit` → `EventHub.publish` → bridge → `MessageBus.send` |
| Lost events when agent offline | EventHub inbox preserves, agent replays on next spawn |
| `crdt_workspace.get_*` polling | Push-driven: bridge delivers + catch-up on spawn |
| `crdt_observer.py` polling | **Deleted** — push model needs no observer |
| `progress.EventEmitter` (local) | **Kept** — orthogonal: console/jsonl logging only, not agent comms |

## 9. Tool Layer Restructure

### 9.1 New Layout
```
tools/
├── hub_tools/
│   ├── __init__.py             # get_hub_tools(agent, hubs, include_hubs, include_names)
│   ├── base.py                 # HubToolBase
│   ├── apihub_tools.py
│   ├── workhub_tools.py
│   ├── codehub_tools.py
│   ├── eventhub_tools.py
│   └── tests/
│       ├── test_apihub_tools.py
│       ├── test_workhub_tools.py
│       ├── test_codehub_tools.py
│       └── test_eventhub_tools.py
├── system_tools.py             # cross-hub metrics: get_versions, snapshot, token usage dashboard
                                # absorbs the non-CRDT-specific parts of crdt_metrics_tools.py
```

`crdt_metrics_tools.py` is **deleted** at the end of the CodeHub cutover (last hub), with its surviving methods migrated into `system_tools.py` (cross-hub) or the relevant hub_tools file (hub-specific). `crdt_validation_tools.py` is **deleted** during the APIHub and CodeHub cuts — its `record_contract_test` family goes to `apihub_tools.py`, its `record_build_attempt` / `record_check` family goes to `codehub_tools.py`.

### 9.2 `HubToolBase` (`hub_tools/base.py`)
```python
class HubToolBase(BaseTool):
    HUB_ATTR: str = ""   # subclass: "apihub" | "workhub" | "codehub" | "eventhub"
    def __init__(self, agent_id, hubs):
        super().__init__()
        self.agent_id, self.hubs = agent_id, hubs
    @property
    def hub(self): return getattr(self.hubs, self.HUB_ATTR)
    def _ok(self, data): return ToolResult(success=True, data=data)
    def _err(self, msg, **extra): return ToolResult(success=False, error=msg, data=extra)
    def _enforce_actor(self, kwargs):
        kwargs["agent"] = self.agent_id
        return self.agent_id
```

Every concrete tool: schema + one hub call. ~20 lines each.

### 9.3 `HubRegistry` (`runtime/hubs.py`) — replaces `HubWorkspace`
```python
class HubRegistry:
    def __init__(self, output_dir: Path, message_bus: MessageBus):
        crdt_dir = output_dir / "shared" / "crdt"
        crdt_dir.mkdir(parents=True, exist_ok=True)
        self.eventhub = EventHub(crdt_dir)
        self.bridge = MessageBusBridge(self.eventhub, message_bus)
        self.eventhub.attach_bridge(self.bridge)
        self.apihub = APIHub(crdt_dir, self.eventhub)
        self.workhub = WorkHub(crdt_dir, self.eventhub)
        self.codehub = CodeHub(output_dir, crdt_dir, self.eventhub)
```

`Orchestrator.__init__`:
```python
# old: self.crdt_workspace = CRDTWorkspace(self.output_dir)
self.hubs = HubRegistry(self.output_dir, self.message_bus)
```

All 16 `crdt_workspace.*` call sites rewritten to `hubs.<hubname>.*`.

### 9.4 Tool Names
All tools prefixed `<hub>_<verb>` (underscore). This matches the existing convention in `tools/hub_tools.py` (`apihub_endpoint`, `codehub_register_repo`) and avoids any tool-runtime ambiguity around dot characters.

### 9.5 Profile-Driven Tool Assignment (`agents_config.yaml`)

The existing yaml already uses bundle names (`apihub_tools`, `workhub_tools`, etc.) referenced by `tool_bundles.py:_bundle_*`. We keep this structure and **broaden** the `include_names=` set in each bundle helper as new tools land:

```yaml
backend:
  tool_bundles:
    - file_tools
    - reasoning_tools
    - apihub_tools     # bundle helper expands to underscore tool names
    - workhub_tools
    - codehub_tools
    - eventhub_tools
```

```python
# tool_bundles.py
def _bundle_apihub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "apihub_register_endpoint",
            "apihub_update_schema",
            "apihub_list_endpoints",
            "apihub_get_endpoint",
            "apihub_register_consumer",
            "apihub_get_dependencies_for_file",
            "apihub_get_breaking_changes",
            "apihub_record_contract_test",
            "apihub_deprecate_endpoint",
            "apihub_request_review",
        },
    )
    builder.add(tools, "apihub", "hub")
```

Per-agent fine-grained allow/deny still goes through `deny_tools:` and `tool_categories:` already in the yaml — no new config syntax required.

### 9.6 Prompt Template Changes
Templates live under `multi_agent/prompts/v2/<role>_agent.j2`. Per cutover, update the relevant ones:
- APIHub cut → `v2/design_agent.j2`, `v2/backend_agent.j2`, `v2/frontend_agent.j2` (endpoint sections)
- WorkHub cut → all `v2/*_agent.j2` (task/plan sections) + `agents/shared/agent_definition.j2` for shared dev-task vocabulary
- CodeHub cut → all `v2/*_agent.j2` (build/PR sections); largest delta
- EventHub cut → all `v2/*_agent.j2` sync/inbox sections

### 9.7 Test Strategy
Each `hub_tools/tests/test_*.py`:
1. Schema correctness (tool_definition matches hub method signature).
2. Happy path (tool → hub state + EventHub event).
3. Error paths (missing args, permission denied, hub method error).
4. **Parity test** (temporary; deleted at cutover Step 5): assert old + new produce same store state for the same input.

## 10. Migration SOP (template for each hub)

### 10.1 Per-Hub Cutover (7 Steps)
```
Step 0  Pre-flight
        - git checkout -b haibotong-hub-cutover-{N}-{hub}
        - run_regressions.py + test_hub_architecture.py = 100% green
Step 1  Strengthen the hub (TDD)
        - Add hub-only tests for every method the hub will absorb
        - Implement missing pieces to make them green
Step 2  Build the new tool layer
        - tools/hub_tools/<hub>_tools.py + matching tests
        - Hub tools exist but agents_config.yaml does NOT reference them yet
Step 3  Dual-call audit (parity)
        - Add temporary parity tests: old workspace.X vs new hub.X store equality
        - Record parity report under docs/superpowers/migration-logs/
Step 4  Switch callers (one file per commit)
        - grep workspace.<old> call sites; rewrite atomically
        - Update agent prompt .j2 templates in lockstep
        - Re-run full regressions
Step 5  Remove legacy code
        - Delete absorbed methods from crdt.py / crdt_dev_tasks.py / crdt_validation.py
        - Delete dual-write try/except stubs
        - Delete parity tests
        - Full regressions + end-to-end sanity (e.g., facebook generation)
Step 6  Update docs
        - Update agent/env_generator/README.md
        - Write docs/superpowers/migration-logs/<NN>-<hub>.md (files touched, new tools, prompt diffs, gotchas, regression evidence)
Step 7  Merge + cleanup
        - Self-review (/code-review)
        - Merge to main
        - Delete working branch
```

### 10.2 Go/No-Go Gates
| Transition | Gate |
|---|---|
| Step 0 → 1 | Baseline regressions 100% green |
| Step 2 → 3 | hub_tools unit tests 100% green |
| Step 3 → 4 | Parity 100% across all touched methods |
| Step 4 → 5 | Full regressions + e2e sanity green |
| Step 5 → 6 | Full e2e green (facebook generation completes + API contract tests pass) |
| Step 6 → 7 | Docs committed, self-review done |

A failing gate means **back up one step and fix** — never force the cut.

### 10.3 Risk & Rollback
- Each cutover is exactly one PR. Pre-merge revert is free.
- Dual-write window is bounded to one PR cycle (Steps 3–4). Step 5 immediately removes it.
- Do not bundle unrelated refactors into a cutover PR. Spawn follow-ups for code-smell sightings.
- Disk JSON formats are forward-compatible (hub JSON ⊇ old CRDT JSON in the affected stores). Add a one-shot loader compat shim for `.checkpoint.json` references to deleted fields if needed.

### 10.4 Total Cutover Order
| # | Hub | Code delta | Primary risk |
|---|---|---|---|
| 1 | APIHub | ~600 new, ~290 deleted | Parity coverage; breaking-change cross-hub fan-out |
| 2 | EventHub bridge | ~400 new, ~50 deleted | MessageBus integration; online/offline delivery correctness |
| 3 | WorkHub | ~900 new, ~700 deleted | Task domain matrix migration; `update_page` call-site audit |
| 4 | CodeHub | ~1200 new, ~787 deleted (file_coordination) + ~500 deleted (crdt.py) | Real `git` introduction, spawn flow change, Docker image dependency |

### 10.5 Concrete Step-by-Step for Cutover #1 (APIHub)
| Step | Action | Verification |
|---|---|---|
| 0 | Branch `haibotong-hub-cutover-1-apihub`; run baseline regressions + `test_hub_architecture` | Both green |
| 1.1 | Add `test_hub_architecture.py` to `run_regressions.py` | Regressions include hub test |
| 1.2 | Implement APIHub additions: `update_schema`, `add_mock`, `add_example`, `deprecate_endpoint`, enhanced `_detect_breaking_change`, breaking-change → auto WorkHub task | Unit tests green |
| 1.3 | Cross-hub: APIHub breaking-change calls `hubs.workhub.create_task` | Integration test green |
| 2.1 | New `tools/hub_tools/base.py` + `apihub_tools.py` (10 tools) | Tool schema tests green |
| 2.2 | New `runtime/hubs.py:HubRegistry` exists (orchestrator NOT yet switched) | Import does not break |
| 3.1 | Parity tests for `update_endpoint`, `register_api_usage`, `get_endpoints`, `get_api_consumers` | Parity 100% |
| 4.1 | `orchestrator.py:711` → `self.hubs.apihub.get_endpoints()` | Orchestrator starts OK |
| 4.2 | `crdt_projection.py:80` → single-write to apihub | Projection test green |
| 4.3 | Remove 6 endpoint/consumer tools from `crdt_tools.py`; `tool_bundles.py` references `apihub_tools` | Tool list correct |
| 4.4 | Update `prompts/v2/design_agent.j2`, `v2/backend_agent.j2`, `v2/frontend_agent.j2` (replace `update_endpoint` with `apihub.register_endpoint`; replace `register_api_usage` with `apihub.register_consumer`) | Prompt render has no undefined refs |
| 4.5 | End-to-end small project (`run_facebook_generation.sh` 30-min cap, generate-only) | No crash; API path behavior correct |
| 5.1 | Delete from `crdt.py`: `update_endpoint`, `_detect_breaking_change`, `get_endpoint`, `get_endpoints`, `get_usable_endpoints`, `observe_endpoints`, `register_api_usage`, `unregister_api_usage`, `get_api_consumers`, `get_file_api_dependencies`, `_notify_api_consumers`, `get_api_change_notifications`, `get_api_dependency_graph` (~290 lines) | crdt.py reduced |
| 5.2 | Delete `_endpoints` and `_api_consumers` stores + their `ensure_core_documents` entries | Start without field-missing errors |
| 5.3 | Delete 6 endpoint/consumer tool classes from `crdt_tools.py` + their `get_crdt_tools` references | crdt_tools.py reduced |
| 5.4 | Delete parity tests | Test dir clean |
| 5.5 | Full end-to-end facebook generation | API path fully on APIHub |
| 6 | Write `docs/superpowers/migration-logs/01-apihub.md` | Includes change list, gotchas, regression evidence |
| 7 | `/code-review` + merge | PR merges cleanly |

## 11. Open Items for Future Polish (out of scope this round)

- Event log compaction strategy (currently unbounded growth in `eventhub_events.json`).
- Multi-repo CodeHub (today only one repo per project).
- WorkHub real-time block CRDT (today LWW at block level).
- Splitting WorkHub `docs/` and `board/` into separate hubs once volume warrants.
- Replacement of `update_endpoint`-style polling in any agent prompt that wasn't migrated.

## 12. Acceptance Criteria

A. All four hubs (APIHub, EventHub, WorkHub, CodeHub) exist with the full APIs in §§5-8.
B. The following files are deleted: `multi_agent/runtime/crdt.py`, `multi_agent/runtime/crdt_dev_tasks.py`, `multi_agent/runtime/crdt_validation.py`, `multi_agent/runtime/crdt_projection.py`, `multi_agent/runtime/crdt_observer.py`, `multi_agent/runtime/file_coordination.py`, `multi_agent/runtime/hub_workspace.py`, `multi_agent/runtime/workhub.py` (re-export shim), `multi_agent/runtime/codehub.py` (re-export shim), `tools/crdt_tools.py`, `tools/crdt_dev_task_tools.py`, `tools/crdt_file_coordination_tools.py`, `tools/crdt_validation_tools.py`, `tools/crdt_metrics_tools.py`, `tools/crdt_tool_base.py`. No `CRDTWorkspace` symbol remains in the codebase.
C. `runtime/hubs.py:HubRegistry` replaces all `crdt_workspace` usages.
D. Every hub method that writes also fires an EventHub event with a stable `thread_id`.
E. `MessageBusBridge` delivers live to online agents; offline agents catch up via `eventhub.list_inbox` on next spawn.
F. `agents_config.yaml` controls tool exposure and default subscriptions; no hardcoded tool lists per agent in Python.
G. Each agent's worktree is a real `git worktree`; PRs are real `git merge` operations; commit history is queryable via both `codehub.get_commit/get_blob` and standard `git log`.
H. `agent/tests/run_regressions.py` includes `test_hub_architecture.py` and all four `tools/hub_tools/tests/`.
I. End-to-end `run_facebook_generation.sh` completes with API contract tests passing.

## 13. Out-of-Date Trigger Conditions

This spec should be revisited if:
- A new hub is proposed (e.g., MemoryHub, DataHub).
- LLM tool-name regex changes to disallow dots.
- Multiple repos per project become required.
- An external system needs to read/write hub state (today: in-process Python only).
