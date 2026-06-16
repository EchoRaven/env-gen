# Cutover 6 — Hub Tool Surface Fill

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Expose 16 missing LLM tools that wrap existing (or close-to-existing) hub methods so agents can drive every collaboration primitive — subscribe to events, invite attendees, comment, register tables, etc. This is the prerequisite "tool surface fill" before the step-pipeline binding (Cutover 7-8). **No enforcement / step-pipeline changes in this cutover.**

**Architecture:** Each new LLM tool is a 15-25 line `HubTool` subclass in `tools/hub_tools.py` calling an existing hub method. Two new APIHub methods (`register_table_consumer`, `get_table_breaking_changes`) needed to back 2 of the new tools.

**Tech Stack:** Python 3.11 (`dt` conda env), unittest, existing `BaseTool` / `HubTool` patterns.

**Source spec:** `docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md` §9.1, §9.2, §9.3.

**Out of scope (deferred to Cutover 7):**
- `codehub_suggest_reviewers` and `codehub_force_merge` — they come with the reviewer-gate logic
- Schema mismatch / linked_tasks / 2-reviewer enforcement
- `apihub.register_consumer` write-time schema check (only the table version added here)

**Out of scope (deferred to Cutover 8):**
- `hub_pulse` / `hub_commit_gate` step pipeline stages
- Prompt template updates

---

## Pre-Reading

- `agent/env_generator/llm_generator/tools/hub_tools.py` — existing `HubTool` pattern (look at `WorkHubCreatePageTool`, `EventHubInboxTool` for the shape)
- `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` — `subscribe`, `unsubscribe`, `get_subscriptions`, `mark_all_read`, `get_thread`, `thread_reply`, `record_agent_status`, `get_agent_status` already exist
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — `invite_attendee`, `remove_attendee`, `comment`, `reply`, `share_implementation` already exist (last three may need verification — check actual file)
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — `register_table`, `list_tables`, `get_table`, `update_table_schema` exist; `register_table_consumer` and `get_table_breaking_changes` need to be added
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py:_bundle_eventhub_tools / _bundle_workhub_tools / _bundle_apihub_tools` — widen `include_names`

## File Map

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — add `register_table_consumer`, `detect_table_breaking_change`, `get_table_breaking_changes`; wire `update_table_schema` to detect table breaking changes
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — verify `comment / reply / share_implementation` exist; add stubs if missing
- `agent/env_generator/llm_generator/tools/hub_tools.py` — add 16 new `HubTool` subclasses
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — widen include_names for eventhub/workhub/apihub bundles
- `agent/tests/test_apihub_tools.py` — add 4 new APIHub tool names to REQUIRED_TOOLS set
- `agent/tests/test_workhub_tools.py` (or create if absent) — verify new tools exported

**Create:**
- `agent/tests/test_apihub_tables_breaking_change.py` — table breaking-change detection tests
- `agent/tests/test_eventhub_new_tools.py` — 7 new EventHub tools
- `agent/tests/test_workhub_collab_tools.py` — 5 new WorkHub collaboration tools
- `agent/tests/test_apihub_table_tools.py` — 4 new APIHub table tools
- `docs/superpowers/migration-logs/07-tool-surface-fill.md` — cutover report

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1:** Create worktree from parent dir's current tip

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-6-tool-surface-fill -b haibotong-cutover-6-tool-surface-fill red-env-gen/haibotong-0521-pipeline-web-tools
cd .worktrees/haibotong-cutover-6-tool-surface-fill
```

- [ ] **Step 2:** Baseline tests pass

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_architecture agent.tests.test_workhub_completeness agent.tests.test_apihub_strengthen agent.tests.test_apihub_tools agent.tests.test_eventhub_completeness agent.tests.test_codehub_git_ops agent.tests.test_codehub_inline_comments 2>&1 | tail -3
```

Expected: regressions 7 OK; hub suite all green.

- [ ] **Step 3:** Verify which WorkHub collab methods actually exist

```bash
grep -nE "def (comment|reply|share_implementation|invite_attendee|remove_attendee)" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py
```

Note the line numbers. All 5 should be present (Cutovers 3 added them). If any is missing, fix in Task 7 with a small implementation. Otherwise proceed.

---

## Phase A — APIHub Backing Methods

### Task 2: TDD `apihub.register_table_consumer` + table breaking-change

**Files:**
- Create: `agent/tests/test_apihub_tables_breaking_change.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1:** Write failing tests

Create `agent/tests/test_apihub_tables_breaking_change.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class APIHubTableBreakingChangeTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).apihub

    def test_register_table_consumer_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "email": "string"},
                                provider="database", agent="design")
            result = hub.register_table_consumer(
                table_name="users",
                file_path="app/backend/users.py",
                agent="backend",
                metadata={"usage_type": "select"},
            )
            self.assertEqual(result["table_name"], "users")
            self.assertEqual(result["file_path"], "app/backend/users.py")
            self.assertEqual(result["agent"], "backend")

    def test_register_table_consumer_unknown_table_returns_error(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_table_consumer(
                table_name="nonexistent", file_path="x.py", agent="backend",
            )
            self.assertIn("error", result)

    def test_detect_table_breaking_change_removed_column(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int", "name": "string", "email": "string"}
            new = {"id": "int", "name": "string"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("email", result["removed_columns"])

    def test_detect_table_breaking_change_type_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int"}
            new = {"id": "string"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("id", result["type_changed_columns"])

    def test_detect_table_breaking_change_additive_is_not_breaking(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int"}
            new = {"id": "int", "created_at": "timestamp"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertFalse(result["is_breaking"])

    def test_update_table_schema_records_breaking_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "email": "string"},
                                provider="database", agent="design")
            hub.update_table_schema("users", {"id": "int"}, agent="database")  # removes email
            changes = hub.get_table_breaking_changes()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["table_name"], "users")
            self.assertIn("email", changes[0]["breaking"]["removed_columns"])

    def test_get_table_breaking_changes_filters_by_since_ts(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "x": "string"},
                                provider="database", agent="design")
            hub.update_table_schema("users", {"id": "int"}, agent="database")
            future = time.time() + 1.0
            self.assertEqual(hub.get_table_breaking_changes(since_ts=future), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_tables_breaking_change -v 2>&1 | tail -15
```

Expected: all 7 tests fail with `AttributeError: 'APIHub' object has no attribute 'register_table_consumer'` (or similar for `detect_table_breaking_change` / `get_table_breaking_changes`).

- [ ] **Step 3:** Add a `_table_consumers` store

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`, find the `__init__` method (around line 16). Add this store after the existing `_tables` line (search for `self._tables = CRDTStore(...)`):

```python
        self._table_consumers = CRDTStore(self.crdt_dir / "apihub_table_consumers.json", LWWMap)
        self._table_breaking_changes = CRDTStore(self.crdt_dir / "apihub_table_breaking_changes.json", LWWMap)
```

Then find `ensure_documents` and add both stores to the iteration list there.

- [ ] **Step 4:** Implement `register_table_consumer`

Add this method to `APIHub` (place right after the existing `update_table_schema` method, around line 386 of current state — confirm via grep):

```python
    def register_table_consumer(self, table_name: str, file_path: str, agent: str,
                                  metadata: dict = None) -> dict:
        if not self.get_table(table_name):
            return {"error": f"Table not registered: {table_name}",
                    "hint": "Call apihub.register_table first."}
        ts = Timestamp.now(agent)
        key = f"{table_name}|{file_path}|{agent}"
        consumer = {
            "id": key,
            "table_name": table_name,
            "file_path": file_path,
            "agent": agent,
            "metadata": metadata or {},
            "created_at": ts.wall_time,
            "_updated_by": agent,
            "_updated_at": ts.wall_time,
        }
        self._table_consumers.update(lambda m: m.set(key, consumer, ts))
        self._emit("table_consumer_registered", consumer, recipients=[])
        return consumer
```

- [ ] **Step 5:** Implement `detect_table_breaking_change`

Add right after `register_table_consumer`:

```python
    def detect_table_breaking_change(self, old_schema: dict, new_schema: dict) -> dict:
        old_schema = old_schema or {}
        new_schema = new_schema or {}
        removed_columns: list = sorted(set(old_schema.keys()) - set(new_schema.keys()))
        type_changed_columns: list = sorted(
            k for k in old_schema.keys() & new_schema.keys()
            if old_schema[k] != new_schema[k]
        )
        is_breaking = bool(removed_columns or type_changed_columns)
        return {
            "is_breaking": is_breaking,
            "removed_columns": removed_columns,
            "type_changed_columns": type_changed_columns,
        }
```

- [ ] **Step 6:** Implement `get_table_breaking_changes`

Add right after `detect_table_breaking_change`:

```python
    def get_table_breaking_changes(self, since_ts: float = None) -> list:
        items = list(self._table_breaking_changes.value().values())
        if since_ts is not None:
            items = [b for b in items if b.get("created_at", 0) >= since_ts]
        items.sort(key=lambda b: b.get("created_at", 0), reverse=True)
        return items
```

- [ ] **Step 7:** Wire `update_table_schema` to detect breaking changes

Find the existing `update_table_schema` (around line 386). Modify it to call `detect_table_breaking_change` and persist:

```python
    def update_table_schema(self, name: str, schema: dict, agent: str = "") -> dict:
        table = self.get_table(name)
        if not table:
            return {"error": f"Table not found: {name}"}
        old_schema = table.get("schema") or {}
        new_schema = schema or {}
        breaking = self.detect_table_breaking_change(old_schema, new_schema)
        if breaking["is_breaking"]:
            ts = Timestamp.now(agent or "apihub")
            key = f"breaking_table:{name}:{ts.wall_time}"
            payload = {
                "id": key, "table_name": name, "breaking": breaking,
                "created_at": ts.wall_time, "_updated_by": agent,
            }
            self._table_breaking_changes.update(lambda m: m.set(key, payload, ts))
            self._emit("table_breaking_change_detected", payload,
                       recipients=[], priority="urgent")
        return self.register_table(name, schema=new_schema, provider=table.get("provider"),
                                    agent=agent, status=table.get("status", "defined"))
```

- [ ] **Step 8:** Run, confirm PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_tables_breaking_change -v 2>&1 | tail -12
```

Expected: 7 OK.

- [ ] **Step 9:** Confirm no other test regressed

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_strengthen agent.tests.test_apihub_tools agent.tests.test_hub_architecture 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 10:** Commit

```bash
git add agent/tests/test_apihub_tables_breaking_change.py \
        agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
git commit -m "Add APIHub.register_table_consumer + table breaking-change detection"
```

---

## Phase B — EventHub Tools (7 tools)

### Task 3: TDD 3 subscription-mgmt tools

**Files:**
- Create: `agent/tests/test_eventhub_new_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1:** Write failing tests for `eventhub_subscribe / eventhub_unsubscribe / eventhub_list_subscriptions`

Create `agent/tests/test_eventhub_new_tools.py`:

```python
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_EVENTHUB_TOOLS = {
    "eventhub_subscribe",
    "eventhub_unsubscribe",
    "eventhub_list_subscriptions",
    "eventhub_get_thread",
    "eventhub_reply_in_thread",
    "eventhub_mark_all_read",
    "eventhub_get_agent_status",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class EventHubNewToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="backend", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_eventhub_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_EVENTHUB_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_eventhub_subscribe_persists_full_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["eventhub_subscribe"]
            result = _run(tool._run(source_hub="apihub", event_type="breaking_change_detected",
                                     filter={"x": 1}, priority_floor="high"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["source_hub"], "apihub")
            self.assertEqual(data["event_type"], "breaking_change_detected")
            self.assertEqual(data["priority_floor"], "high")

    def test_eventhub_unsubscribe_removes(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            sub = hubs.eventhub.subscribe(agent="backend", source_hub="apihub")
            tool = tool_by_name["eventhub_unsubscribe"]
            result = _run(tool._run(subscription_id=sub["id"]))
            data = result.data if hasattr(result, "data") else result
            self.assertTrue(data.get("removed"))
            subs = hubs.eventhub.get_subscriptions(agent="backend")
            self.assertEqual(subs, [])

    def test_eventhub_list_subscriptions_returns_filter(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.subscribe(agent="backend", source_hub="apihub")
            hubs.eventhub.subscribe(agent="backend", source_hub="codehub")
            tool = tool_by_name["eventhub_list_subscriptions"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(len(data["subscriptions"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL (missing tools)

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_new_tools -v 2>&1 | tail -10
```

- [ ] **Step 3:** Add 3 tool classes to `agent/env_generator/llm_generator/tools/hub_tools.py`

Find the existing `EventHubInboxTool` class. Add these 3 classes immediately after it:

```python
class EventHubSubscribeTool(HubTool):
    NAME = "eventhub_subscribe"
    DESCRIPTION = "Subscribe to events from a specific hub/type with optional filter."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "source_hub": {"type": "string", "description": "apihub/codehub/workhub/system/*"},
            "event_type": {"type": "string", "description": "Specific event_type or * for all"},
            "filter": {"type": "object", "description": "Optional filter dict"},
            "priority_floor": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            "delivery": {"type": "string", "enum": ["live", "inbox_only"]},
        },
    }

    async def _run(self, source_hub: str = "*", event_type: str = "*",
                   filter: dict = None, priority_floor: str = "low",
                   delivery: str = "live") -> ToolResult:
        return ToolResult(data=self._hubs.eventhub.subscribe(
            agent=self._agent_id, source_hub=source_hub, event_type=event_type,
            filter=filter, priority_floor=priority_floor, delivery=delivery))


class EventHubUnsubscribeTool(HubTool):
    NAME = "eventhub_unsubscribe"
    DESCRIPTION = "Cancel an existing EventHub subscription by id."
    PARAMETERS = {
        "type": "object",
        "properties": {"subscription_id": {"type": "string"}},
        "required": ["subscription_id"],
    }

    async def _run(self, subscription_id: str) -> ToolResult:
        removed = self._hubs.eventhub.unsubscribe(subscription_id)
        return ToolResult(data={"removed": removed, "subscription_id": subscription_id})


class EventHubListSubscriptionsTool(HubTool):
    NAME = "eventhub_list_subscriptions"
    DESCRIPTION = "List your active EventHub subscriptions."
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data={"subscriptions": self._hubs.eventhub.get_subscriptions(agent=self._agent_id)})
```

Add the three new class names to the `HUB_TOOL_CLASSES` list (near the existing `EventHubInboxTool` entry):

```python
HUB_TOOL_CLASSES = [
    ...
    EventHubInboxTool,
    EventHubSubscribeTool,
    EventHubUnsubscribeTool,
    EventHubListSubscriptionsTool,
    ...
]
```

- [ ] **Step 4:** Run the 3 subscription-tool tests, confirm PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_new_tools.EventHubNewToolsTests.test_eventhub_subscribe_persists_full_subscription agent.tests.test_eventhub_new_tools.EventHubNewToolsTests.test_eventhub_unsubscribe_removes agent.tests.test_eventhub_new_tools.EventHubNewToolsTests.test_eventhub_list_subscriptions_returns_filter -v 2>&1 | tail -10
```

Expected: 3 OK. The `test_all_new_eventhub_tools_exported` still fails because the other 4 EventHub tools come in Tasks 4-5.

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_eventhub_new_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add EventHub subscribe/unsubscribe/list_subscriptions LLM tools"
```

### Task 4: TDD `eventhub_get_thread` + `eventhub_reply_in_thread`

**Files:**
- Modify: `agent/tests/test_eventhub_new_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1:** Append 2 tests to `EventHubNewToolsTests`

```python
    def test_eventhub_get_thread_returns_chronological_events(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            e1 = hubs.eventhub.publish_event(source_hub="codehub", event_type="pr_opened",
                                               payload={}, recipients=[], thread_id="thread:pr:pr_x")
            e2 = hubs.eventhub.publish_event(source_hub="codehub", event_type="review_requested",
                                               payload={}, recipients=[], thread_id="thread:pr:pr_x")
            tool = tool_by_name["eventhub_get_thread"]
            result = _run(tool._run(thread_id="thread:pr:pr_x"))
            data = result.data if hasattr(result, "data") else result
            ids = [e["id"] for e in data["events"]]
            self.assertEqual(ids, [e1["id"], e2["id"]])

    def test_eventhub_reply_in_thread_creates_event(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.publish_event(source_hub="codehub", event_type="pr_opened",
                                          payload={}, recipients=[], thread_id="thread:pr:pr_y")
            tool = tool_by_name["eventhub_reply_in_thread"]
            result = _run(tool._run(thread_id="thread:pr:pr_y", body="Looks good"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["thread_id"], "thread:pr:pr_y")
            thread = hubs.eventhub.get_thread("thread:pr:pr_y")
            self.assertEqual(len(thread), 2)
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 2 tool classes to `tools/hub_tools.py` (after `EventHubListSubscriptionsTool`):

```python
class EventHubGetThreadTool(HubTool):
    NAME = "eventhub_get_thread"
    DESCRIPTION = "Get all events in a thread (chronological order)."
    PARAMETERS = {
        "type": "object",
        "properties": {"thread_id": {"type": "string"}},
        "required": ["thread_id"],
    }

    async def _run(self, thread_id: str) -> ToolResult:
        return ToolResult(data={"events": self._hubs.eventhub.get_thread(thread_id)})


class EventHubReplyInThreadTool(HubTool):
    NAME = "eventhub_reply_in_thread"
    DESCRIPTION = "Reply in an existing event thread."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "thread_id": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["thread_id", "body"],
    }

    async def _run(self, thread_id: str, body: str) -> ToolResult:
        return ToolResult(data=self._hubs.eventhub.thread_reply(thread_id, self._agent_id, body))
```

Add both to `HUB_TOOL_CLASSES` after `EventHubListSubscriptionsTool`.

- [ ] **Step 4:** Run tests, confirm PASS (the 2 new ones + the 3 from Task 3).

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_eventhub_new_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add EventHub get_thread + reply_in_thread LLM tools"
```

### Task 5: TDD `eventhub_mark_all_read` + `eventhub_get_agent_status`

**Files:**
- Modify: `agent/tests/test_eventhub_new_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1:** Append 2 tests

```python
    def test_eventhub_mark_all_read_returns_count(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.publish_event(source_hub="apihub", event_type="x", payload={},
                                          recipients=["backend"])
            hubs.eventhub.publish_event(source_hub="apihub", event_type="y", payload={},
                                          recipients=["backend"])
            tool = tool_by_name["eventhub_mark_all_read"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["marked"], 2)

    def test_eventhub_get_agent_status_returns_latest_payload(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.eventhub.record_agent_status("frontend", {"state": "thinking"})
            hubs.eventhub.record_agent_status("frontend", {"state": "writing"})
            tool = tool_by_name["eventhub_get_agent_status"]
            result = _run(tool._run(agent_id="frontend"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["status"]["state"], "writing")
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 2 tool classes:

```python
class EventHubMarkAllReadTool(HubTool):
    NAME = "eventhub_mark_all_read"
    DESCRIPTION = "Mark all unread events in your inbox as read; optionally only those before before_ts."
    PARAMETERS = {
        "type": "object",
        "properties": {"before_ts": {"type": "number"}},
    }

    async def _run(self, before_ts: float = None) -> ToolResult:
        return ToolResult(data={"marked": self._hubs.eventhub.mark_all_read(
            self._agent_id, before_ts=before_ts)})


class EventHubGetAgentStatusTool(HubTool):
    NAME = "eventhub_get_agent_status"
    DESCRIPTION = "Get the most recent reported status for an agent."
    PARAMETERS = {
        "type": "object",
        "properties": {"agent_id": {"type": "string"}},
        "required": ["agent_id"],
    }

    async def _run(self, agent_id: str) -> ToolResult:
        return ToolResult(data={"status": self._hubs.eventhub.get_agent_status(agent_id)})
```

Add to `HUB_TOOL_CLASSES`. Run tests, confirm PASS.

- [ ] **Step 4:** Run the full `test_all_new_eventhub_tools_exported` — should now PASS too.

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_new_tools -v 2>&1 | tail -10
```

Expected: 7 OK (1 export check + 6 individual).

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_eventhub_new_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add EventHub mark_all_read + get_agent_status LLM tools"
```

---

## Phase C — WorkHub Tools (5 tools)

### Task 6: TDD `workhub_invite_attendee` + `workhub_remove_attendee`

**Files:**
- Create: `agent/tests/test_workhub_collab_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1:** Write tests

Create `agent/tests/test_workhub_collab_tools.py`:

```python
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_WORKHUB_TOOLS = {
    "workhub_invite_attendee",
    "workhub_remove_attendee",
    "workhub_comment",
    "workhub_reply",
    "workhub_share_implementation",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class WorkHubCollabToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="orchestrator", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_workhub_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_WORKHUB_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_workhub_invite_attendee_adds_record(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            tool = tool_by_name["workhub_invite_attendee"]
            result = _run(tool._run(resource_id=page["id"], agent_id="backend", role="reviewer"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["agent_id"], "backend")
            self.assertEqual(data["role"], "reviewer")

    def test_workhub_remove_attendee_marks_removed(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            hubs.workhub.invite_attendee(page["id"], "backend", role="reviewer", invited_by="orchestrator")
            tool = tool_by_name["workhub_remove_attendee"]
            result = _run(tool._run(resource_type="page", resource_id=page["id"], agent_id="backend"))
            data = result.data if hasattr(result, "data") else result
            # remove_attendee returns a dict marking the soft delete
            self.assertTrue(data.get("removed") or data.get("_removed"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 2 tool classes to `tools/hub_tools.py` (after the existing `WorkHubCreatePageTool` cluster):

```python
class WorkHubInviteAttendeeTool(HubTool):
    NAME = "workhub_invite_attendee"
    DESCRIPTION = "Invite an agent as an attendee of a page/plan/task."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "role": {"type": "string", "enum": ["owner", "reviewer", "contributor", "viewer"]},
        },
        "required": ["resource_id", "agent_id"],
    }

    async def _run(self, resource_id: str, agent_id: str, role: str = "viewer") -> ToolResult:
        return ToolResult(data=self._hubs.workhub.invite_attendee(
            resource_id, agent_id, role=role, invited_by=self._agent_id))


class WorkHubRemoveAttendeeTool(HubTool):
    NAME = "workhub_remove_attendee"
    DESCRIPTION = "Remove an agent from attendees of a page/plan/task."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_type": {"type": "string", "enum": ["page", "plan", "task"]},
            "resource_id": {"type": "string"},
            "agent_id": {"type": "string"},
        },
        "required": ["resource_type", "resource_id", "agent_id"],
    }

    async def _run(self, resource_type: str, resource_id: str, agent_id: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.remove_attendee(
            resource_type, resource_id, agent_id, by=self._agent_id))
```

Add both to `HUB_TOOL_CLASSES`.

- [ ] **Step 4:** Run, confirm PASS (3 of the WorkHub collab tests; the rest fail on other tools).

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_workhub_collab_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add WorkHub invite_attendee + remove_attendee LLM tools"
```

### Task 7: TDD `workhub_comment` + `workhub_reply` + `workhub_share_implementation`

- [ ] **Step 1:** Append 3 tests to `WorkHubCollabToolsTests`

```python
    def test_workhub_comment_persists_with_mentions(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            tool = tool_by_name["workhub_comment"]
            result = _run(tool._run(resource_id=page["id"], body="Need help on auth",
                                     mentions=["backend"]))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["body"], "Need help on auth")
            self.assertIn("backend", data.get("mentions", []))

    def test_workhub_reply_links_to_parent_comment(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            parent = hubs.workhub.comment(resource_id=page["id"], body="Question",
                                            agent="orchestrator")
            tool = tool_by_name["workhub_reply"]
            result = _run(tool._run(comment_id=parent["id"], body="Answer here"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["body"], "Answer here")
            self.assertEqual(data.get("parent_id") or data.get("comment_id"), parent["id"])

    def test_workhub_share_implementation_creates_knowledge_block(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["workhub_share_implementation"]
            result = _run(tool._run(title="JWT auth pattern", content="use bcrypt + jwt..."))
            data = result.data if hasattr(result, "data") else result
            # Could be a block or a record; verify it's stored
            blocks = hubs.workhub.get_shared_implementations()
            self.assertGreaterEqual(len(blocks), 1)
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 3 tool classes:

```python
class WorkHubCommentTool(HubTool):
    NAME = "workhub_comment"
    DESCRIPTION = "Post a comment on a WorkHub resource (page/plan/task) with optional @mentions."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "resource_id": {"type": "string"},
            "body": {"type": "string"},
            "mentions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resource_id", "body"],
    }

    async def _run(self, resource_id: str, body: str, mentions: list = None) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.comment(
            resource_id=resource_id, body=body, agent=self._agent_id,
            mentions=mentions or []))


class WorkHubReplyTool(HubTool):
    NAME = "workhub_reply"
    DESCRIPTION = "Reply to a WorkHub comment, optionally @mentioning agents."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "comment_id": {"type": "string"},
            "body": {"type": "string"},
            "mentions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["comment_id", "body"],
    }

    async def _run(self, comment_id: str, body: str, mentions: list = None) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.reply(
            comment_id=comment_id, body=body, agent=self._agent_id,
            mentions=mentions or []))


class WorkHubShareImplementationTool(HubTool):
    NAME = "workhub_share_implementation"
    DESCRIPTION = "Share a reusable implementation pattern as a WorkHub knowledge block."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["title", "content"],
    }

    async def _run(self, title: str, content: str) -> ToolResult:
        return ToolResult(data=self._hubs.workhub.share_implementation(
            title=title, content=content, agent=self._agent_id))
```

Add all 3 to `HUB_TOOL_CLASSES`.

- [ ] **Step 4:** Run all WorkHub collab tests, confirm 6 OK (1 export + 5 individual).

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_collab_tools -v 2>&1 | tail -10
```

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_workhub_collab_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add WorkHub comment / reply / share_implementation LLM tools"
```

---

## Phase D — APIHub Table Tools (4 tools)

### Task 8: TDD `apihub_register_table` + `apihub_list_tables`

**Files:**
- Create: `agent/tests/test_apihub_table_tools.py`
- Modify: `agent/env_generator/llm_generator/tools/hub_tools.py`

- [ ] **Step 1:** Write tests

```python
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_APIHUB_TABLE_TOOLS = {
    "apihub_register_table",
    "apihub_list_tables",
    "apihub_register_table_consumer",
    "apihub_get_table_breaking_changes",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class APIHubTableToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="database", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_apihub_table_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_APIHUB_TABLE_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_apihub_register_table_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["apihub_register_table"]
            result = _run(tool._run(name="users", schema={"id": "int", "email": "string"}))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["name"], "users")
            self.assertEqual(data["provider"], "database")

    def test_apihub_list_tables_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_table(name="users", schema={"id": "int"}, provider="database", agent="design")
            tool = tool_by_name["apihub_list_tables"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertIn("users", data["tables"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 2 tool classes (after APIHubSubmitReviewTool or similar last APIHub class):

```python
class APIHubRegisterTableTool(HubTool):
    NAME = "apihub_register_table"
    DESCRIPTION = "Register a database table schema (called by database/design agent)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "schema": {"type": "object", "description": "Map column name -> type string"},
            "status": {"type": "string", "enum": ["defined", "implemented", "deprecated"]},
        },
        "required": ["name", "schema"],
    }

    async def _run(self, name: str, schema: dict, status: str = "defined") -> ToolResult:
        return ToolResult(data=self._hubs.apihub.register_table(
            name=name, schema=schema, provider=self._agent_id, agent=self._agent_id, status=status))


class APIHubListTablesTool(HubTool):
    NAME = "apihub_list_tables"
    DESCRIPTION = "List registered tables, optionally filtered by provider."
    PARAMETERS = {
        "type": "object",
        "properties": {"provider": {"type": "string"}},
    }

    async def _run(self, provider: str = None) -> ToolResult:
        return ToolResult(data={"tables": self._hubs.apihub.list_tables(provider=provider)})
```

Add to `HUB_TOOL_CLASSES`.

- [ ] **Step 4:** Run, confirm PASS (2 of the table tool tests).

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_apihub_table_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add APIHub register_table + list_tables LLM tools"
```

### Task 9: TDD `apihub_register_table_consumer` + `apihub_get_table_breaking_changes`

- [ ] **Step 1:** Append 2 tests to `APIHubTableToolsTests`

```python
    def test_apihub_register_table_consumer_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_table(name="users", schema={"id": "int"}, provider="database", agent="design")
            tool = tool_by_name["apihub_register_table_consumer"]
            result = _run(tool._run(table_name="users", file_path="app/backend/users.py",
                                     metadata={"usage_type": "select"}))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["table_name"], "users")
            self.assertEqual(data["agent"], "database")  # tool injects agent_id

    def test_apihub_get_table_breaking_changes_returns_list(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.apihub.register_table(name="users", schema={"id": "int", "email": "string"},
                                         provider="database", agent="design")
            hubs.apihub.update_table_schema("users", {"id": "int"}, agent="database")  # removes email
            tool = tool_by_name["apihub_get_table_breaking_changes"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(len(data["breaking_changes"]), 1)
            self.assertIn("email", data["breaking_changes"][0]["breaking"]["removed_columns"])
```

- [ ] **Step 2:** Run, confirm FAIL.

- [ ] **Step 3:** Add 2 tool classes:

```python
class APIHubRegisterTableConsumerTool(HubTool):
    NAME = "apihub_register_table_consumer"
    DESCRIPTION = "Declare that a file consumes a specific table (used for breaking-change tracking)."
    PARAMETERS = {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "file_path": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["table_name", "file_path"],
    }

    async def _run(self, table_name: str, file_path: str, metadata: dict = None) -> ToolResult:
        return ToolResult(data=self._hubs.apihub.register_table_consumer(
            table_name=table_name, file_path=file_path, agent=self._agent_id,
            metadata=metadata or {}))


class APIHubGetTableBreakingChangesTool(HubTool):
    NAME = "apihub_get_table_breaking_changes"
    DESCRIPTION = "List recorded table breaking changes (newest first)."
    PARAMETERS = {
        "type": "object",
        "properties": {"since_ts": {"type": "number"}},
    }

    async def _run(self, since_ts: float = None) -> ToolResult:
        return ToolResult(data={"breaking_changes": self._hubs.apihub.get_table_breaking_changes(since_ts=since_ts)})
```

Add to `HUB_TOOL_CLASSES`.

- [ ] **Step 4:** Run, confirm all 5 table tool tests PASS.

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_table_tools -v 2>&1 | tail -8
```

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_apihub_table_tools.py \
        agent/env_generator/llm_generator/tools/hub_tools.py
git commit -m "Add APIHub register_table_consumer + get_table_breaking_changes LLM tools"
```

---

## Phase E — Bundle Wiring + Final

### Task 10: Widen `_bundle_*` include_names for all new tools

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`

- [ ] **Step 1:** Update `_bundle_eventhub_tools`

Find the function. Replace its body to include all 7 new tools + existing:

```python
def _bundle_eventhub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "eventhub_inbox",
            "eventhub_subscribe",
            "eventhub_unsubscribe",
            "eventhub_list_subscriptions",
            "eventhub_get_thread",
            "eventhub_reply_in_thread",
            "eventhub_mark_all_read",
            "eventhub_get_agent_status",
            "hub_snapshot",
        },
    )
    builder.add(tools, "eventhub", "hub")
```

- [ ] **Step 2:** Update `_bundle_workhub_tools`

Add the 5 new collab tools to its include_names (keep all existing entries):

```python
            # existing entries...
            "workhub_invite_attendee",
            "workhub_remove_attendee",
            "workhub_comment",
            "workhub_reply",
            "workhub_share_implementation",
```

- [ ] **Step 3:** Update `_bundle_apihub_tools`

Add 4 new table tools:

```python
            # existing entries...
            "apihub_register_table",
            "apihub_list_tables",
            "apihub_register_table_consumer",
            "apihub_get_table_breaking_changes",
```

- [ ] **Step 4:** Sanity-test bundle expansion

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from multi_agent.tool_bundles import TOOL_BUNDLE_REGISTRY
print('registered bundles:', sorted(TOOL_BUNDLE_REGISTRY.keys()))
"
```

Expected: prints a list including `eventhub_tools`, `workhub_tools`, `apihub_tools` (and others).

- [ ] **Step 5:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/tool_bundles.py
git commit -m "Widen eventhub/workhub/apihub tool bundles to include 16 new tools"
```

### Task 11: Update existing test REQUIRED_TOOLS sets

**Files:**
- Modify: `agent/tests/test_apihub_tools.py`

- [ ] **Step 1:** Find the existing `REQUIRED_TOOLS` set in `test_apihub_tools.py`

```bash
grep -n "REQUIRED_TOOLS" agent/tests/test_apihub_tools.py
```

- [ ] **Step 2:** Add 4 new APIHub table tools to the set

Append these to `REQUIRED_TOOLS`:

```python
    "apihub_register_table",
    "apihub_list_tables",
    "apihub_register_table_consumer",
    "apihub_get_table_breaking_changes",
```

- [ ] **Step 3:** Run all apihub tool tests, confirm PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_tools -v 2>&1 | tail -8
```

- [ ] **Step 4:** Commit

```bash
git add agent/tests/test_apihub_tools.py
git commit -m "Add APIHub table tools to REQUIRED_TOOLS set in test_apihub_tools"
```

### Task 12: Full regression + migration log + push

- [ ] **Step 1:** Run all tests

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all green; total ~140 hub-related tests + 7 regressions.

- [ ] **Step 2:** Confirm tool count

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from tools.hub_tools import HUB_TOOL_CLASSES
print(f'Total hub tools: {len(HUB_TOOL_CLASSES)}')
print('\n'.join(sorted(c.NAME for c in HUB_TOOL_CLASSES)))
" | head -80
```

Expected: count includes the 16 new ones (was ~43, now ~59).

- [ ] **Step 3:** Confirm zero Claude trailers

```bash
git log --pretty=%B red-env-gen/haibotong-0521-pipeline-web-tools..HEAD | grep -c "Co-Authored-By:"
```

Expected: 0.

- [ ] **Step 4:** Write migration log

Create `docs/superpowers/migration-logs/07-tool-surface-fill.md`:

```markdown
# 07 — Hub Tool Surface Fill Cutover

**Branch:** haibotong-cutover-6-tool-surface-fill
**Predecessor:** haibotong-0521-pipeline-web-tools tip (post-CRDT strip merge)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §9.1-9.3

## Summary

Adds 16 LLM tools wrapping previously-unexposed hub methods, plus 2 new APIHub
methods backing the table-consumer / table-breaking-change tools. No
enforcement / step-pipeline changes yet — those come in Cutovers 7 and 8.

## Tools added

EventHub (7):
- eventhub_subscribe, eventhub_unsubscribe, eventhub_list_subscriptions
- eventhub_get_thread, eventhub_reply_in_thread
- eventhub_mark_all_read, eventhub_get_agent_status

WorkHub (5):
- workhub_invite_attendee, workhub_remove_attendee
- workhub_comment, workhub_reply, workhub_share_implementation

APIHub (4):
- apihub_register_table, apihub_list_tables
- apihub_register_table_consumer, apihub_get_table_breaking_changes

## Hub methods added

APIHub:
- register_table_consumer(table_name, file_path, agent, metadata)
- detect_table_breaking_change(old_schema, new_schema)
- get_table_breaking_changes(since_ts=None)
- update_table_schema now fires _record_table_breaking_change on detected breakage

## Test additions

- test_apihub_tables_breaking_change.py (7 tests)
- test_eventhub_new_tools.py (7 tests)
- test_workhub_collab_tools.py (6 tests)
- test_apihub_table_tools.py (5 tests)

## Regression evidence

<paste last 5 lines of run_regressions.py output>

Total hub tools after this cutover: <NN> (was 43).

## Next

Cutover 7 — schema 3-layer + reviewer gate (codehub_suggest_reviewers,
codehub_force_merge, apihub.register_consumer write-time gate,
codehub.merge_pull_request premerge gate, open_pr 2-reviewer enforcement).
```

- [ ] **Step 5:** Commit log + push

```bash
git add docs/superpowers/migration-logs/07-tool-surface-fill.md
git commit -m "Add Cutover 6 migration log"
git push red-env-gen haibotong-cutover-6-tool-surface-fill -u 2>&1 | tail -3
```

- [ ] **Step 6:** Print PR compare URL

```bash
echo "PR compare: https://github.com/Virtue-AI/red-env-gen/compare/haibotong-0521-pipeline-web-tools...haibotong-cutover-6-tool-surface-fill"
```

---

## Constraints

- **No `Co-Authored-By: Claude` trailer on any commit.**
- Use `dt` conda env: `/home/haibotong/miniconda3/envs/dt/bin/python`.
- Branch from `red-env-gen/haibotong-0521-pipeline-web-tools` (the consolidated parent).
- Each task = one commit; 12 tasks → 12 commits.

## Recovery Notes

Each task is independently revertable. If `register_table_consumer` schema causes
existing test breakage, revert Task 2 and reconsider the field-naming convention
(e.g., `agent_id` vs `agent`). Tool registration is additive — adding a class to
`HUB_TOOL_CLASSES` cannot break anything that doesn't already reference it.

## Out of Scope

- `codehub_suggest_reviewers` / `codehub_force_merge` → Cutover 7
- L1 schema_subset_check for endpoint consumer (only the table consumer added here is gate-less for now) → Cutover 7
- L2 merge premerge gate → Cutover 7
- `open_pr` 2-reviewer + linked_tasks enforcement → Cutover 7
- `hub_pulse` / `hub_commit_gate` stages → Cutover 8
- Prompt updates → Cutover 8
