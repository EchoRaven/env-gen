# Hub-Bound Step Pipeline + Schema Alignment — Design Spec

**Status:** Approved, ready for implementation planning
**Author:** haibotong + Claude (Opus 4.7, 1M context)
**Date:** 2026-05-22
**Builds on:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` + the 5-cutover CRDT strip
**Audit:** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md`

---

## 1. Goal

Tightly bind every agent's step pipeline to the four hubs so that:

1. **Every step pulls** the agent's view of CodeHub / APIHub / WorkHub / EventHub + MessageBus before the LLM thinks (`hub_pulse` stage).
2. **Every step ends** with a code-level integrity check for orphan work — uncommitted edits, unpushed branches, stale claimed tasks, stale review requests, unhandled breaking changes (`hub_commit_gate` stage).
3. **Frontend / backend API contracts and table schemas stay strictly aligned** via a three-layer defense: APIHub write-time reject + CodeHub merge-time verifier gate + step-time visibility.
4. **Every PR has ≥ 2 reviewers** including `orchestrator`, plus ≥ 1 linked WorkHub task, and a smart reviewer suggester (`codehub_suggest_reviewers`) to make the rule cheap to follow.

## 2. Non-Goals

- Changing the four-hub architecture itself (out of scope).
- Replacing the in-process `MessageBus` (kept untouched).
- Adding multi-tenant / cross-org / UI-rendering features to any hub.
- Real-time bidirectional collaborative editing of WorkHub blocks (LWW retained).

## 3. Strategic Decisions (locked)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Hybrid enforcement** — code-forced stages, agent-autonomous actions | Stages pull data and render prompts; LLM decides what to do. Forces visibility without forcing action. |
| 2 | **Three-layer schema alignment** | Independent layers; any single failure is caught by another. |
| 3 | **2-reviewer hard gate** with `orchestrator` always one, smart picker for the other | Matches real engineering practice: lead approver + domain peer. |
| 4 | **`linked_tasks` mandatory on PRs**, `linked_apis` optional | Every PR traces to a WorkHub task; pure UI/CSS work allowed without API links. |
| 5 | **Force-merge bypass** for orchestrator only, ≥ 20-char reason, audit logged | Verifier offline must not deadlock the pipeline. |
| 6 | **All reviewers must approve** (not just one) | Stricter "approval set ⊇ required reviewers" semantics. |
| 7 | **Schema validator uses simple dict subset check**, no `jsonschema` dependency | YAGNI; can be upgraded later if needed. |
| 8 | **`hub_pulse` and `hub_commit_gate` are code-forced**, not config-driven | Cannot be turned off via `agents_config.yaml` typo or omission. |

## 4. Architecture Overview

```
┌───────────────────────────────────────────────────────────────┐
│  AGENT STEP                                                    │
├───────────────────────────────────────────────────────────────┤
│  STAGE: hub_pulse        ◄── NEW, code-forced first stage      │
│    Pulls "my view" from CodeHub + APIHub + WorkHub + EventHub │
│    + MessageBus inbox, renders STATUS CHECK prompt block       │
│                                                                  │
│  STAGE: runtime_team_status                                    │
│  STAGE: planning                                               │
│  STAGE: retrieve_context                                       │
│  STAGE: action                                                 │
│                                                                  │
│  STAGE: hub_commit_gate  ◄── NEW, code-forced last stage       │
│    Scans 6 loose-end categories; emits INTEGRITY CHECK         │
│    prompt block for next step + publishes system event         │
│                                                                  │
│  STAGE: knowledge_sync                                         │
└───────────────────────────────────────────────────────────────┘

Schema alignment (orthogonal, all three layers active simultaneously):
  L1 WRITE-TIME    apihub_register_consumer / register_table_consumer
                   → schema_subset_check; reject mismatch immediately
  L2 MERGE-TIME    codehub_merge_pr → premerge verifier gate
                   → contract test fail or missing → PR conflict + fix task
  L3 STEP-TIME     hub_pulse surfaces unresolved breaking changes
                   on every step prompt for consumer agents
```

**Invariants (code-enforced):**

1. Every step's first stage MUST be `hub_pulse`; the engine injects it even if `agents_config.yaml` omits it.
2. Every step's last stage MUST be `hub_commit_gate`; engine injects regardless.
3. `codehub.open_pull_request(reviewers=[], linked_tasks=[])` returns `error: "insufficient_reviewers"` if `len(reviewers - {author}) < 2`.
4. `codehub.open_pull_request(linked_tasks=[])` returns `error: "linked_tasks_required"` if empty.
5. `codehub.open_pull_request` auto-injects `"orchestrator"` into `reviewers` if `author != "orchestrator"` and orchestrator not already present.
6. `codehub.merge_pull_request` calls `_run_premerge_verifier_gate` before any `git merge`; failure marks PR `premerge_failed` and creates a WorkHub fix task.
7. `codehub.merge_pull_request` requires `set(reviewers) ⊆ {r.reviewer for r in approved_reviews}`. Not just one approval.
8. `apihub.register_consumer(endpoint_id, ...)` returns error if endpoint unknown, deprecated, or `metadata.expected_schema` provided and is not a subset of the endpoint's `schema`.
9. `apihub.update_schema` detects breaking change → auto-creates WorkHub fix task for each consumer agent (existing) AND increments `apihub_schema_versions` history.
10. `codehub.force_merge_pull_request` only callable by `agent="orchestrator"`, requires `reason >= 20 chars`, emits urgent EventHub event + records in `team_practice_store`.

## 5. `hub_pulse` Stage Detail

### 5.1 What it pulls

A `HubPulse` object containing the agent's view across all 4 hubs + MessageBus. Each section is bounded (top-K only) to control token usage.

```python
{
  "codehub": {
    "branch": "agent/<id>",
    "branch_status": {
      "clean": bool, "dirty_files": [str],
      "commits_ahead_of_main": int, "unpushed_commits": int,
    },
    "my_open_prs": [
      {"id": str, "merge_state": str,
       "approvals_received": int, "approvals_needed": int,
       "linked_apis": [str], "linked_tasks": [str]},
    ],  # author == me
    "prs_needing_my_review": [
      {"id": str, "author": str, "files_changed_count": int,
       "step_age": int},
    ],  # me in reviewers, no submitted decision
  },

  "apihub": {
    "my_endpoints_with_failed_tests": [
      {"id": str, "last_contract_test_status": str, "evidence": dict},
    ],  # provider == me
    "my_consumed_endpoints_with_breaking_changes": [
      {"endpoint_id": str, "my_file": str,
       "removed_response_fields": [str], "type_changed_fields": [str], ...},
    ],
    "api_reviews_pending_my_decision": [
      {"review_id": str, "endpoint_id": str, "requested_by": str},
    ],
  },

  "workhub": {
    "tasks_assigned_to_me_pending": [{"id": str, "title": str, "priority": str,
                                       "metadata": dict}],
    "tasks_in_progress_by_me": [{"id": str, "claimed_at": float, "step_age": int}],
    "mentions_unread": [{"comment_id": str, "resource_id": str,
                          "from": str, "body": str}],
    "plans_i_own": [{"id": str, "tasks_total": int, "tasks_completed": int}],
  },

  "eventhub": {
    "unread_count_by_priority": {"urgent": int, "high": int, ...},
    "top_unread": [{"event_id": str, "source_hub": str,
                     "event_type": str, "resource_id": str}],  # top 3
    "active_subscriptions": int,
  },

  "messagebus": "<existing inbox snapshot>",  # reuse current MessageBus inbox prompt
}
```

### 5.2 What it renders

Markdown block, emoji-prefixed sections. Empty sections collapse (not rendered). Each item carries a hint of the next tool call.

```markdown
### 🔄 HUB PULSE  [step T+47]

🌳 **CodeHub** — branch `agent/backend`
  • Working tree: **dirty** (1 file: src/feed.py)
  • 3 commits ahead of main, NO PR open yet
    → consider `codehub_commit(...)` then `codehub_open_pr(...)`
  • PRs needing your review (1):
    - pr_b21c by frontend (2 files)
      → `codehub_get_diff(pr_b21c)` then `codehub_review_pr(...)`

🔌 **APIHub**
  • 1 of your endpoints has FAILED contract test:
    - POST /api/posts — status 422 validation_error
  • ⚠️  1 BREAKING CHANGE on endpoint you consume:
    - GET /api/feed lost field `total` (your file: src/Feed.jsx)
    → see workhub.tasks_assigned_to_me for the auto-created fix task

📋 **WorkHub**
  • 2 tasks pending assigned to you:
    - [URGENT] task_xx13 "Fix breaking change in GET /api/feed"
    - [HIGH] task_xx12 "Add feed pagination"
  • 0 in progress, 1 plan owned (2/5 done)
  • 1 unread @mention: orchestrator asked for ETA on pr_a8f3

📬 **EventHub** — Inbox 3 unread (1 urgent, 1 high, 1 normal)
  • Top: pull_request_conflict pr_abc from codehub

📨 **MessageBus** — <inbox snapshot>
```

### 5.3 Implementation

- **New file** `agents/runtime/hub_pulse.py`:
  - `collect_hub_pulse(hubs, agent_id, step_num) -> dict` — parallel reads across 4 hubs
  - `build_hub_pulse_prompt(pulse_dict) -> Optional[str]` — markdown; returns `None` if everything is empty
  - `should_render(pulse_dict) -> bool`
- **Integration** `agents/runtime/step_pipeline/helpers.py`:
  - First stage of every step calls `collect_hub_pulse` then prepends prompt
  - Cannot be disabled via `agents_config.yaml`; engine forces it
- **CodeHub new helpers** (support `pulse`):
  - `get_branch_status(agent_id) -> dict` — wraps `git status` + `rev-list`
  - `list_prs_needing_review(reviewer) -> List[dict]`
- **Replaces** the deleted `_collect_crdt_change_summary`; extends `_collect_eventhub_catchup_summary` to run every step.

### 5.4 Token budget

- Whole block ≤ 30 lines
- top_unread truncated to 3
- task / PR lists truncated to 5; overflow `+N more, call <list_tool>`
- All-empty pulse → skip section entirely (no "(nothing)" lines)

## 6. `hub_commit_gate` Stage Detail

### 6.1 What it scans

Six loose-end categories, evaluated at step end:

| Category | Detection | Severity |
|---|---|---|
| Dirty worktree | `git status --porcelain` in agent's worktree non-empty | 🔴 |
| Unpushed commits | branch ahead of main ≥ 1 with no open PR | 🟡 |
| Stale claimed task | task `status=in_progress` AND `step_age >= stale_task_steps` | 🔴 |
| Forgotten review | PR has me as reviewer, no decision submitted, `step_age >= stale_review_steps` | 🟡 |
| Unhandled breaking change | I consume endpoint with active breaking change AND no `task.linked_apis = [endpoint_id] AND assignee=me AND status=in_progress` | 🔴 |
| Conflict PR unresolved | my PR `status=conflict` AND `conflict_files` unchanged since last step | 🔴 |

Configurable thresholds via `agents_config.yaml`:
```yaml
execution_pipeline_defaults:
  commit_gate:
    stale_task_steps: 5
    stale_review_steps: 3
    stale_pr_steps: 10
    enabled: true
```

### 6.2 Effect

- **Never blocks the current step.** Renders an `INTEGRITY CHECK` markdown block.
- The block is stored on the agent instance as `_pending_integrity_prompt`.
- Next step's `hub_pulse` prepends `_pending_integrity_prompt` before its own output.
- Also published as `EventHub.publish_event(source_hub="system", event_type="integrity_check", recipients=[agent_id], priority="high")` so other agents and dashboards can see.

### 6.3 Decay / silence

Same loose end reported for ≥ 3 consecutive steps → severity downgraded to silent line: `(silenced after 3 reports: dirty wt, no open PR)`. Agent can explicitly silence with `hub_commit_gate_clear(reason)` if it's intentional.

### 6.4 Out of scope

- Auto-commit, auto-open-PR, auto-review — none of these. Gate produces visibility, not automation.

## 7. Schema Alignment — Three-Layer Defense

### 7.1 Layer 1: APIHub Write-Time

**Trigger:** any agent calls `apihub.register_consumer(endpoint_id, file_path, agent, metadata)` or `apihub.register_table_consumer(table_name, file_path, agent, metadata)`.

**Checks:**

```python
def register_consumer(self, endpoint_id, file_path, agent, metadata=None) -> dict:
    endpoint = self._endpoints.value().get(endpoint_id)
    if not endpoint:
        return {"error": "endpoint_not_registered",
                "hint": f"Backend must register_endpoint({endpoint_id}) first."}
    if endpoint.get("status") == "deprecated":
        return {"error": "endpoint_deprecated",
                "replacement_id": endpoint.get("replacement_id")}
    if metadata and "expected_schema" in metadata:
        mismatch = _schema_subset_check(metadata["expected_schema"],
                                         endpoint.get("schema", {}))
        if mismatch:
            return {"error": "schema_mismatch",
                    "missing_fields": mismatch.get("missing"),
                    "type_mismatches": mismatch.get("type_mismatches"),
                    "hint": "Fix consumer code, or apihub_request_review to negotiate."}
    # ...existing write...
```

`_schema_subset_check(expected: dict, actual: dict) -> Optional[dict]`:

- Walks `expected` recursively
- For each key, requires same key in `actual` AND `actual[key]` type matches `expected[key]` type
- Allows `actual` to have additional keys (additive endpoints OK)
- Returns `None` if expected ⊆ actual, else `{"missing": [...], "type_mismatches": [...]}`
- Pure dict comparison; no `jsonschema` dependency

### 7.2 Layer 2: CodeHub Merge-Time

**Trigger:** any agent calls `codehub.merge_pull_request(pr_id, ...)`.

**Checks (before any `git merge`):**

```python
def _run_premerge_verifier_gate(self, pr: dict) -> dict:
    failed = []

    # Check 1: every linked_apis must have a recent passing contract test
    for endpoint_id in pr.get("linked_apis") or []:
        tests = self._apihub.get_contract_test_results(endpoint_id) if self._apihub else []
        if not tests:
            failed.append({"kind": "contract_test_missing", "endpoint": endpoint_id})
            continue
        latest = max(tests, key=lambda t: t.get("created_at", 0))
        if latest.get("result", {}).get("passed") is not True:
            failed.append({"kind": "contract_test_failed",
                           "endpoint": endpoint_id,
                           "evidence": latest.get("evidence")})

    # Check 2: every linked_tasks must be completed
    for task_id in pr.get("linked_tasks") or []:
        task = self._workhub.get_task(task_id) if self._workhub else None
        if not task:
            failed.append({"kind": "linked_task_missing", "task_id": task_id})
        elif task.get("status") != "completed":
            failed.append({"kind": "linked_task_incomplete",
                           "task_id": task_id, "status": task.get("status")})

    return {"passed": not failed, "failed_checks": failed}
```

On `passed=False`:
1. PR `status=premerge_failed`, `premerge_failures=failed`
2. Auto-create WorkHub task `assignee=pr.author`, `source="codehub_premerge_gate"`, `priority=urgent`, `linked_pr=pr_id`
3. Return error to caller; no `git merge` happens
4. Emit `EventHub.publish_event("premerge_failed", recipients=[pr.author, "orchestrator"], priority="urgent")`

### 7.3 Layer 3: Step-Time (via `hub_pulse`)

Already covered in §5.1 — `apihub.my_consumed_endpoints_with_breaking_changes` section. Frontend / consumer agents see unresolved breaking changes every single step until either:
- The breaking change's auto-created fix task is `completed`
- The consumer's endpoint dependency is removed (file no longer uses that endpoint)

### 7.4 Closed loop

```
update_schema(endpoint) detects breaking
     ↓ APIHub._record_breaking_change
     ↓ workhub.create_task(assignee=consumer_agent, priority=urgent, source=apihub_breaking_change)
     ↓ EventHub.publish_event(recipients=[consumer_agent], priority=urgent)
     ↓ MessageBusBridge → consumer_agent.receive_message  (if online)
     OR
     ↓ next consumer_agent step → hub_pulse renders the task as URGENT
     ↓ consumer_agent claims task → makes commits → opens PR with linked_apis=[endpoint]
     ↓ codehub_merge_pr → L2 verifier gate runs contract test
     ↓ Pass: merge; Fail: PR=premerge_failed + new fix task
```

### 7.5 Tables get the same treatment

Mirrors endpoints. New on APIHub:
- `register_table_consumer(table_name, file_path, agent, metadata) -> dict` — same L1 logic
- `detect_table_breaking_change(old_schema, new_schema) -> dict` — 7 dimensions: removed_columns, type_changes, removed_pk, removed_unique, added_required_column, added_fk_constraint, dropped_default
- `get_table_breaking_changes(since_ts=None) -> List[dict]`
- `update_table_schema(name, schema, agent)` fires `_record_table_breaking_change` analogously

## 8. Reviewer Enforcement + Smart Picker

### 8.1 `codehub.open_pull_request` gate

```python
def open_pull_request(self, branch, target="main", reviewers=None,
                      linked_tasks=None, linked_apis=None,
                      title="", body="", author="", repo_id="main") -> dict:
    reviewers = list(reviewers or [])
    linked_tasks = list(linked_tasks or [])

    if not linked_tasks:
        return {"error": "linked_tasks_required",
                "hint": "Every PR must reference at least one WorkHub task."}

    if author != "orchestrator" and "orchestrator" not in reviewers:
        reviewers.append("orchestrator")

    distinct = [r for r in reviewers if r != author]
    if len(distinct) < 2:
        return {"error": "insufficient_reviewers",
                "current": distinct, "required": 2,
                "hint": "Call codehub_suggest_reviewers(...) for candidates."}
    # ...existing create logic...
```

### 8.2 `codehub.suggest_reviewers(branch, linked_apis, linked_tasks, author, k=3)`

Weighted-sum picker:

| Signal | Weight | Source |
|---|---|---|
| Orchestrator (mandatory) | +100 | Always |
| Consumer of any linked_api | +3.0 | `apihub.get_consumers(endpoint_id)` |
| Recent committer on files changed in `branch` | +1.0 | `git log --grep "[agent: X]"` on touched files |
| Attendee of a plan referenced by linked_tasks | +0.5 | `workhub.snapshot().attendees` |

Returns `[{agent, score, reasons}]` sorted desc, top-k.

### 8.3 `_is_pr_approved` strictness

```python
def _is_pr_approved(self, pr: dict, extra_review=None) -> bool:
    reviews = [r for r in self.stores.code_reviews.value().values()
               if r.get("pr_id") == pr.get("id")]
    if extra_review: reviews.append(extra_review)
    approved = {r["reviewer"] for r in reviews if r.get("state") == "approve"}
    required = set(pr.get("reviewers") or [])
    return required.issubset(approved)   # ALL required reviewers must approve
```

### 8.4 `codehub.force_merge_pull_request(pr_id, reason, agent)`

```python
def force_merge_pull_request(self, pr_id, reason, agent) -> dict:
    if agent != "orchestrator":
        return {"error": "force_merge_orchestrator_only"}
    if not reason or len(reason) < 20:
        return {"error": "force_merge_reason_too_short", "min_length": 20}
    pr = self.stores.pull_requests.get().get(pr_id)
    if not pr:
        return {"error": f"PR not found: {pr_id}"}
    pr["merge_state"] = "ready"
    pr["force_merged"] = True
    pr["force_reason"] = reason
    pr["force_by"] = agent
    self.stores.pull_requests.update(lambda m: m.set(pr_id, pr, Timestamp.now(agent)))
    self._emit("pr_force_merged",
               {"pr_id": pr_id, "reason": reason, "agent": agent},
               recipients=["orchestrator"], priority="urgent")
    return self.merge_pull_request(pr_id, strategy="squash", agent=agent)
```

## 9. New / Modified LLM Tools

**Total surface: 48 → 62 tools** (14 new, 4 modified).

### 9.1 EventHub (+7 — major gap fill)

| Tool | Hub method |
|---|---|
| `eventhub_subscribe` | `subscribe(source_hub, event_type, filter, priority_floor, delivery)` |
| `eventhub_unsubscribe` | `unsubscribe(subscription_id)` |
| `eventhub_list_subscriptions` | `get_subscriptions(agent=None)` |
| `eventhub_get_thread` | `get_thread(thread_id)` |
| `eventhub_reply_in_thread` | `thread_reply(thread_id, body)` |
| `eventhub_mark_all_read` | `mark_all_read(agent, before_ts)` |
| `eventhub_get_agent_status` | `get_agent_status(agent_id)` |

### 9.2 WorkHub (+5)

| Tool | Hub method |
|---|---|
| `workhub_invite_attendee` | `invite_attendee(resource_id, agent_id, role, invited_by)` |
| `workhub_remove_attendee` | `remove_attendee(resource_type, resource_id, agent_id, by)` |
| `workhub_comment` | `comment(resource_id, body, mentions)` |
| `workhub_reply` | `reply(comment_id, body, mentions)` |
| `workhub_share_implementation` | `share_implementation(title, content, **metadata)` |

### 9.3 APIHub (+4 — tables + breaking-change for tables)

| Tool | Hub method |
|---|---|
| `apihub_register_table` | `register_table(name, schema, provider, status, **meta)` |
| `apihub_list_tables` | `list_tables(provider=None)` |
| `apihub_register_table_consumer` | `register_table_consumer(name, file_path, agent, metadata)` (new) |
| `apihub_get_table_breaking_changes` | `get_table_breaking_changes(since_ts)` (new) |

### 9.4 CodeHub (+2)

| Tool | Hub method |
|---|---|
| `codehub_suggest_reviewers` | `suggest_reviewers(branch, linked_apis, linked_tasks, author, k=3)` (new) |
| `codehub_force_merge` | `force_merge_pull_request(pr_id, reason, agent)` (new, orchestrator-only) |

### 9.5 Modified

| Tool | Change |
|---|---|
| `codehub_open_pr` | enforces linked_tasks non-empty + ≥ 2 reviewers + auto-orchestrator |
| `codehub_merge_pr` | runs premerge verifier gate before any git merge |
| `apihub_register_consumer` | accepts `metadata.expected_schema` for write-time L1 check |
| `apihub_register_endpoint` | breaking-change detection includes table-style dimensions for unified semantics |

## 10. Step Pipeline Changes

### 10.1 Stage list

Before:
```yaml
stages: [inbox_status, crdt_changes, runtime_team_status, planning,
         retrieve_context, action, crdt_sync, knowledge_sync]
```

After (changes marked):
```yaml
stages: [hub_pulse,            # NEW (subsumes inbox_status + crdt_changes)
         runtime_team_status,
         planning,
         retrieve_context,
         action,
         hub_commit_gate,      # NEW (replaces crdt_sync)
         knowledge_sync]
```

### 10.2 Engine-level forcing

`agents/runtime/step_pipeline/helpers.py` ensures `hub_pulse` is always the first stage and `hub_commit_gate` is always the last stage, regardless of yaml content. Agents cannot opt out via config typo.

### 10.3 Per-stage tool-call caps

```yaml
max_tool_calls_per_stage:
  hub_pulse: 0           # pulse is observability; uses no LLM tool calls
  planning: 1
  retrieve_context: 2
  hub_commit_gate: 0
  knowledge_sync: 1
```

`hub_pulse` and `hub_commit_gate` collect data via direct hub method calls, not LLM tool calls — so their tool-call cap is 0.

## 11. File-Level Implementation Map

| File | Type | LoC estimate |
|---|---|---|
| `agents/runtime/hub_pulse.py` | new | ~180 |
| `agents/runtime/commit_gate.py` | new | ~150 |
| `runtime/hubs/codehub/service.py` | modify (+force_merge, +suggest_reviewers, +premerge_gate, +branch helpers) | +200 |
| `runtime/apihub.py` | modify (+register_table_consumer, +table breaking change, +write-time L1) | +150 |
| `tools/hub_tools.py` | modify (+14 new tool classes) | +400 |
| `multi_agent/tool_bundles.py` | modify (widen include_names) | +20 |
| `agents/runtime/step_pipeline/helpers.py` | modify (inject pulse + gate) | +80 |
| `agents/agents_config.yaml` | modify (stage list + commit_gate config) | +20 |
| `prompts/v2/*.j2` (7 files) | modify (explain pulse + gate sections) | +30 each |
| `agent/tests/test_hub_pulse.py` | new | ~200 |
| `agent/tests/test_commit_gate.py` | new | ~180 |
| `agent/tests/test_codehub_force_merge.py` | new | ~80 |
| `agent/tests/test_codehub_suggest_reviewers.py` | new | ~120 |
| `agent/tests/test_apihub_schema_alignment.py` | new (L1 + L2) | ~200 |
| `agent/tests/test_apihub_table_consumer.py` | new | ~100 |
| `agent/tests/test_eventhub_new_tools.py` | new | ~150 |
| `agent/tests/test_workhub_new_tools.py` | new | ~150 |

**Approximate total: 17 files, ~2400 LoC new + tests.**

## 12. Implementation Sequence

Three sequential cutovers — each a clean PR boundary.

### Cutover 6 — Tool surface fill (~1 week)
- All 14 new LLM tools wired to existing hub methods (where method exists)
- Add missing hub methods (`register_table_consumer`, `get_table_breaking_changes`)
- Widen `include_names` in tool bundles
- Tests for each new tool's happy path + 1 error path
- **No step-pipeline change yet.** Agents can use the tools, but nothing is forced.

### Cutover 7 — Schema 3-layer + reviewer gate (~1 week)
- L1: `apihub.register_consumer` + `register_table_consumer` schema_subset_check
- L2: `codehub.merge_pull_request` premerge verifier gate + `force_merge_pull_request`
- `codehub.open_pull_request` linked_tasks + 2-reviewer hard gates + orchestrator auto-injection
- `codehub.suggest_reviewers` smart picker
- `_is_pr_approved` strict ALL-approve semantics
- Schema mismatch / missing reviewer / missing task link all reject at code level

### Cutover 8 — Step-pipeline integration (~5 days)
- `hub_pulse` stage + `commit_gate` stage modules
- `step_pipeline/helpers.py` forces them in
- Delete dead stages `inbox_status / crdt_changes / crdt_sync` from yaml + helpers
- Update 7 agent prompts to describe pulse / gate sections
- End-to-end smoke: full Facebook generation completes with stages running on every step

## 13. Acceptance Criteria

A. Every PR has `linked_tasks` non-empty, ≥ 2 reviewers including `orchestrator`, all reviewers approved before merge.
B. Every `apihub_register_consumer` with mismatched expected_schema returns error and does not write.
C. Every `codehub_merge_pr` runs premerge gate; contract test failures or incomplete linked_tasks block merge and auto-create fix tasks.
D. Every agent step first stage is `hub_pulse`; agent sees own 4-hub view + MessageBus inbox before LLM thinks.
E. Every agent step last stage is `hub_commit_gate`; loose ends roll forward to next step prompt.
F. Frontend / consumer agents see breaking-change tasks in pulse until resolved.
G. Tables get identical L1+L2+L3 protection as endpoints.
H. Force merge requires `orchestrator` agent, ≥ 20-char reason, audit-emits urgent EventHub event.
I. All existing test suites + 7 new test files green.
J. Three cutovers (6, 7, 8) carry zero `Co-Authored-By: Claude` trailers.

## 14. Out-of-Date Triggers

Revisit when:
- A new hub is added (would need new pulse section).
- Tool-name regex changes to disallow underscores.
- Multi-repo support requires per-repo branch state tracking.
- An agent type emerges that legitimately should bypass `hub_pulse` (would need explicit allowlist).

## 15. Open Items (deferred — file as follow-up plans)

- **Per-file blame surface in `suggest_reviewers`** — currently uses `[agent: X]` commit trailer; could parse `git blame` per file line range for finer-grained ownership.
- **Decay window for `hub_pulse` consumer breaking-change** — currently shows until task completes; could add explicit acknowledgment to silence.
- **`hub_commit_gate` autoperformance** — could profile gate cost; if it becomes a per-step bottleneck, parallelize with `asyncio.gather`.
