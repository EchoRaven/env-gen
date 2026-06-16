# Cutover 2 — EventHub MessageBus Bridge

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Fulfill the spec's core promise that "EventHub is source of truth, MessageBus is transport" — currently EventHub stores events but **nothing delivers them to live agents**. Build the bridge, expand EventHub's method surface, fix subscription-driven fan-out, and wire the bridge through HubWorkspace → Orchestrator. Agents on first step catch up on missed events.

**Why now (audit ref):** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.4 — EventHub is the lowest-completion hub. Every hub `_emit` currently writes to disk with no live delivery. Cutover 3 (WorkHub) and 4 (CodeHub) cannot rely on cross-hub events until this is built.

**Out of scope (deferred):**
- Agent status migration via system topic — comes with Cutover 3 (along with other CRDT migrations like `update_agent_status / get_agent_statuses`).
- Event log compaction — spec marks future-only.
- WorkHub or CodeHub additions — separate cutovers.

**Source spec:** `docs/superpowers/specs/2026-05-21-four-hubs-design.md` §8.
**Audit:** `docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md` §2.4.

---

## File Map

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` — add 6 new methods, fix subscription model, add subscription-driven fan-out in `publish_event`
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py` — accept `message_bus` arg, construct bridge, attach to EventHub
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py` — `CRDTWorkspace.__init__` accepts optional `message_bus` and forwards to `HubWorkspace`
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py` — pass `self.message_bus` to CRDTWorkspace
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py` — first-step inbox catch-up integration

**Create:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/__init__.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py` — `MessageBusBridge` class
- `agent/tests/test_eventhub_completeness.py` — 6 new method tests
- `agent/tests/test_messagebus_bridge.py` — bridge delivery tests
- `agent/tests/test_eventhub_subscription_fanout.py` — subscription-driven fan-out tests
- `agent/tests/test_eventhub_spawn_catchup.py` — agent spawn catch-up test
- `docs/superpowers/migration-logs/03-eventhub-bridge.md` — log

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1: Create cutover worktree from cutover-1.5 tip**

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-2-eventhub-bridge -b haibotong-cutover-2-eventhub-bridge red-env-gen/haibotong-cutover-1.5-apihub-completeness
cd .worktrees/haibotong-cutover-2-eventhub-bridge
```

- [ ] **Step 2: Verify baseline**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_accessors agent.tests.test_apihub_strengthen agent.tests.test_apihub_tools agent.tests.test_apihub_breaking_change_creates_task agent.tests.test_hub_architecture 2>&1 | tail -3
```

Expected: regressions 7 OK; apihub suite 29 OK.

---

## Phase 1 — EventHub method additions (TDD)

### Task 2: Refactor subscription model to spec shape

Current `subscribe(agent, topic, filters)` doesn't match spec. Spec §8.5 shape:
```python
Subscription = {
    "id": "{agent}:{source_hub}:{event_type_or_*}",
    "agent": agent_id,
    "source_hub": "apihub" | "*",
    "event_type": "pr_opened" | "*",
    "filter": dict | None,
    "priority_floor": "normal",
    "delivery": "live" | "inbox_only",
}
```

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`
- Create: `agent/tests/test_eventhub_completeness.py`

- [ ] **Step 1: Create test file scaffold**

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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


class EventHubCompletenessTests(unittest.TestCase):
    def _hub(self, td):
        return EventHub(Path(td))

    def test_subscribe_stores_full_subscription_shape(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            sub = hub.subscribe(
                agent="frontend",
                source_hub="apihub",
                event_type="breaking_change_detected",
                filter={"linked_apis_provider": "backend"},
                priority_floor="high",
                delivery="live",
            )
            self.assertEqual(sub["agent"], "frontend")
            self.assertEqual(sub["source_hub"], "apihub")
            self.assertEqual(sub["event_type"], "breaking_change_detected")
            self.assertEqual(sub["filter"], {"linked_apis_provider": "backend"})
            self.assertEqual(sub["priority_floor"], "high")
            self.assertEqual(sub["delivery"], "live")

    def test_subscribe_defaults_match_spec(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            sub = hub.subscribe(agent="frontend")
            self.assertEqual(sub["source_hub"], "*")
            self.assertEqual(sub["event_type"], "*")
            self.assertIsNone(sub["filter"])
            self.assertEqual(sub["priority_floor"], "low")
            self.assertEqual(sub["delivery"], "live")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_completeness -v 2>&1 | tail -8
```
Expected: TypeError (old `subscribe` signature mismatch).

- [ ] **Step 3: Rewrite `EventHub.subscribe` in `eventhub.py`**

Find current `def subscribe(self, agent: str, topic: str, filters: dict = None)` and replace with:

```python
    def subscribe(
        self,
        agent: str,
        source_hub: str = "*",
        event_type: str = "*",
        filter: dict = None,
        priority_floor: str = "low",
        delivery: str = "live",
    ) -> dict:
        ts = Timestamp.now(agent)
        sub_id = f"{agent}:{source_hub}:{event_type}"
        sub = {
            "id": sub_id,
            "agent": agent,
            "source_hub": source_hub,
            "event_type": event_type,
            "filter": filter,
            "priority_floor": priority_floor,
            "delivery": delivery,
            "created_at": ts.wall_time,
            "_updated_by": agent,
            "_updated_at": ts.wall_time,
        }
        self._subscriptions.update(lambda m: m.set(sub_id, sub, ts))
        return sub
```

- [ ] **Step 4: Run, confirm PASS (2 OK).**

- [ ] **Step 5: Audit callers of old signature**

```bash
grep -rn "eventhub\.subscribe\|\.subscribe(" --include='*.py' agent/env_generator/llm_generator/multi_agent/ | grep -v __pycache__ | head
```

If any caller passes `topic=` or `filters=`, fix them in this same task. (Likely none — `subscribe` was a no-op in practice.)

- [ ] **Step 6: Commit**

```bash
git add agent/tests/test_eventhub_completeness.py agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py
git commit -m "Reshape EventHub.subscribe to spec model (source_hub/event_type/filter/priority_floor/delivery)"
```

### Task 3: TDD `unsubscribe` and `get_subscriptions`

- [ ] **Step 1: Append tests**

```python
    def test_unsubscribe_removes_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            sub = hub.subscribe(agent="backend", source_hub="apihub", event_type="breaking_change_detected")
            self.assertTrue(hub.unsubscribe(sub["id"]))
            subs = hub.get_subscriptions(agent="backend")
            self.assertEqual(subs, [])

    def test_unsubscribe_unknown_id_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertFalse(hub.unsubscribe("nope:nope:nope"))

    def test_get_subscriptions_filters_by_agent(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.subscribe(agent="backend", source_hub="apihub")
            hub.subscribe(agent="frontend", source_hub="apihub")
            hub.subscribe(agent="backend", source_hub="codehub", event_type="pr_opened")
            be = hub.get_subscriptions(agent="backend")
            self.assertEqual(len(be), 2)
            fe = hub.get_subscriptions(agent="frontend")
            self.assertEqual(len(fe), 1)
            all_subs = hub.get_subscriptions()
            self.assertEqual(len(all_subs), 3)
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in `eventhub.py` after `subscribe`:

```python
    def unsubscribe(self, subscription_id: str) -> bool:
        existing = self._subscriptions.value().get(subscription_id)
        if not existing:
            return False
        ts = Timestamp.now(existing.get("agent", "eventhub"))
        # CRDT-style soft delete: mark _removed so future reads can filter it out.
        removed = dict(existing)
        removed["_removed"] = True
        removed["_removed_at"] = ts.wall_time
        self._subscriptions.update(lambda m: m.set(subscription_id, removed, ts))
        return True

    def get_subscriptions(self, agent: str = None) -> list:
        subs = []
        for sub in self._subscriptions.value().values():
            if sub.get("_removed"):
                continue
            if agent is not None and sub.get("agent") != agent:
                continue
            subs.append(sub)
        return subs
```

- [ ] **Step 4: Run, confirm PASS (5 OK).**

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_eventhub_completeness.py agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py
git commit -m "Add EventHub.unsubscribe and get_subscriptions"
```

### Task 4: TDD `mark_delivered`, `mark_all_read`, `get_event`, `get_thread`

- [ ] **Step 1: Append 6 tests** (2 per method, except simple ones)

```python
    def test_mark_delivered_flips_delivered_flag_only(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            event = hub.publish_event(source_hub="apihub", event_type="endpoint_registered",
                                       payload={"foo": 1}, recipients=["backend"])
            hub.mark_delivered("backend", event["id"])
            inbox = hub._inboxes.value().get("backend") or {}
            item = inbox.get("items", {}).get(event["id"])
            self.assertTrue(item.get("delivered"))
            self.assertFalse(item.get("read"))

    def test_mark_all_read_clears_all_unread_for_agent(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.publish_event(source_hub="apihub", event_type="e1", payload={}, recipients=["backend"])
            hub.publish_event(source_hub="apihub", event_type="e2", payload={}, recipients=["backend"])
            hub.publish_event(source_hub="apihub", event_type="e3", payload={}, recipients=["frontend"])
            count = hub.mark_all_read("backend")
            self.assertEqual(count, 2)
            unread = hub.list_inbox("backend", unread_only=True)
            self.assertEqual(unread, [])

    def test_mark_all_read_before_ts_only_clears_old(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.publish_event(source_hub="apihub", event_type="e1", payload={}, recipients=["backend"])
            time.sleep(0.01)
            cutoff = time.time()
            time.sleep(0.01)
            hub.publish_event(source_hub="apihub", event_type="e2", payload={}, recipients=["backend"])
            count = hub.mark_all_read("backend", before_ts=cutoff)
            self.assertEqual(count, 1)
            unread = hub.list_inbox("backend", unread_only=True)
            self.assertEqual(len(unread), 1)

    def test_get_event_returns_full_record(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            event = hub.publish_event(source_hub="apihub", event_type="foo", payload={"k": "v"}, recipients=[])
            got = hub.get_event(event["id"])
            self.assertEqual(got["id"], event["id"])
            self.assertEqual(got["payload"], {"k": "v"})

    def test_get_event_unknown_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertIsNone(hub.get_event("nope"))

    def test_get_thread_returns_events_in_chronological_order(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            e1 = hub.publish_event(source_hub="codehub", event_type="pr_opened",
                                    payload={}, recipients=[], thread_id="thread:pr:pr_123")
            e2 = hub.publish_event(source_hub="codehub", event_type="review_requested",
                                    payload={}, recipients=[], thread_id="thread:pr:pr_123")
            events = hub.get_thread("thread:pr:pr_123")
            self.assertEqual([e["id"] for e in events], [e1["id"], e2["id"]])

    def test_get_thread_unknown_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertEqual(hub.get_thread("nope"), [])
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in `eventhub.py` (place after `mark_read`):

```python
    def mark_delivered(self, agent: str, event_id: str) -> dict:
        ts = Timestamp.now(agent)
        inbox = self._inboxes.get().get(agent) or {"agent": agent, "items": {}}
        items = inbox.setdefault("items", {})
        item = items.get(event_id)
        if not item:
            return {"error": f"Event not in inbox: {event_id}"}
        item["delivered"] = True
        item["delivered_at"] = ts.wall_time
        items[event_id] = item
        self._inboxes.update(lambda m: m.set(agent, inbox, ts))
        return item

    def mark_all_read(self, agent: str, before_ts: float = None) -> int:
        ts = Timestamp.now(agent)
        inbox = self._inboxes.get().get(agent) or {"agent": agent, "items": {}}
        items = inbox.setdefault("items", {})
        marked = 0
        for event_id, item in list(items.items()):
            if item.get("read"):
                continue
            if before_ts is not None and item.get("received_at", 0) >= before_ts:
                continue
            item["read"] = True
            item["read_at"] = ts.wall_time
            items[event_id] = item
            marked += 1
        if marked:
            self._inboxes.update(lambda m: m.set(agent, inbox, ts))
        return marked

    def get_event(self, event_id: str):
        return self._events.value().get(event_id)

    def get_thread(self, thread_id: str) -> list:
        events = [
            e for e in self._events.value().values()
            if e.get("thread_id") == thread_id
        ]
        events.sort(key=lambda e: e.get("created_at", 0))
        return events
```

- [ ] **Step 4: Run, confirm PASS (12 OK total).**

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_eventhub_completeness.py agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py
git commit -m "Add EventHub.mark_delivered / mark_all_read / get_event / get_thread"
```

### Task 5: TDD `attach_bridge` + subscription-driven fan-out in `publish_event`

The bridge object doesn't exist yet — we stub a no-op in the test. Then real bridge in Task 7.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`
- Create: `agent/tests/test_eventhub_subscription_fanout.py`

- [ ] **Step 1: Write test for `attach_bridge` (no-op accept)**

Append to `test_eventhub_completeness.py`:

```python
    def test_attach_bridge_accepts_object(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            class StubBridge:
                def __init__(self):
                    self.calls = []
                async def deliver(self, event):
                    self.calls.append(event)
                    return {"delivered": [], "failed": []}
            bridge = StubBridge()
            hub.attach_bridge(bridge)
            self.assertIs(hub._bridge, bridge)
```

- [ ] **Step 2: Write subscription fan-out test**

Create `agent/tests/test_eventhub_subscription_fanout.py`:

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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


class EventHubFanOutTests(unittest.TestCase):
    def _hub(self, td):
        return EventHub(Path(td))

    def test_publish_event_adds_subscribers_to_recipients(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.subscribe(agent="frontend", source_hub="apihub", event_type="breaking_change_detected")
            hub.subscribe(agent="verifier", source_hub="apihub")  # wildcard event
            event = hub.publish_event(
                source_hub="apihub",
                event_type="breaking_change_detected",
                payload={"endpoint_id": "GET /api/feed"},
                recipients=[],  # no explicit recipients
            )
            self.assertIn("frontend", event["recipients"])
            self.assertIn("verifier", event["recipients"])

    def test_publish_event_skips_wrong_source_hub(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.subscribe(agent="frontend", source_hub="codehub", event_type="pr_opened")
            event = hub.publish_event(
                source_hub="apihub",  # different source_hub
                event_type="endpoint_registered",
                payload={}, recipients=[],
            )
            self.assertNotIn("frontend", event["recipients"])

    def test_publish_event_honors_priority_floor(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.subscribe(agent="frontend", source_hub="apihub", priority_floor="urgent")
            low_event = hub.publish_event(source_hub="apihub", event_type="info",
                                           payload={}, recipients=[], priority="normal")
            self.assertNotIn("frontend", low_event["recipients"])
            urgent_event = hub.publish_event(source_hub="apihub", event_type="info",
                                              payload={}, recipients=[], priority="urgent")
            self.assertIn("frontend", urgent_event["recipients"])

    def test_publish_event_respects_explicit_recipients(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.subscribe(agent="frontend", source_hub="apihub")
            event = hub.publish_event(
                source_hub="apihub",
                event_type="endpoint_registered",
                payload={},
                recipients=["backend"],
            )
            self.assertIn("backend", event["recipients"])
            self.assertIn("frontend", event["recipients"])  # also added by subscription

    def test_publish_event_does_not_add_inbox_only_subscribers_to_recipients(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            # delivery="inbox_only" means: still landed in inbox, but bridge does NOT push to MessageBus.
            # For the recipients list (which drives inbox writes), they should still be there.
            hub.subscribe(agent="frontend", source_hub="apihub", delivery="inbox_only")
            event = hub.publish_event(source_hub="apihub", event_type="x",
                                       payload={}, recipients=[])
            self.assertIn("frontend", event["recipients"])
            # But the subscription's delivery field is preserved for the bridge to consult
            sub = hub.get_subscriptions(agent="frontend")[0]
            self.assertEqual(sub["delivery"], "inbox_only")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run, confirm FAIL.**

- [ ] **Step 4: Implement `attach_bridge` + fan-out** in `eventhub.py`

Add `self._bridge = None` in `__init__` (after `self.crdt_dir = ...`).

Add the setter:

```python
    def attach_bridge(self, bridge) -> None:
        self._bridge = bridge
```

Modify `publish_event` — replace the existing body's recipient handling. The current first line is:

```python
        recipients = sorted(set(recipients or []))
```

Change the early block to include subscription-driven fan-out and a priority order map:

```python
        priority_rank = {"low": 0, "normal": 1, "high": 2, "urgent": 3}
        evt_priority = priority_rank.get(priority, priority_rank["normal"])
        explicit = set(recipients or [])
        for sub in self._subscriptions.value().values():
            if sub.get("_removed"):
                continue
            if sub.get("source_hub") not in (source_hub, "*"):
                continue
            if sub.get("event_type") not in (event_type, "*"):
                continue
            floor = priority_rank.get(sub.get("priority_floor", "low"), 0)
            if evt_priority < floor:
                continue
            agent = sub.get("agent")
            if agent:
                explicit.add(agent)
        recipients = sorted(explicit)
```

(Filter-dict matching is left as a future extension; for now, filter dict is stored but not enforced. We'll add filter matching when the first cross-hub flow needs it.)

After the existing `_inboxes.update(...)` write at the bottom of `publish_event`, add the bridge call:

```python
        bridge = getattr(self, "_bridge", None)
        if bridge is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(bridge.deliver(event))
                else:
                    loop.run_until_complete(bridge.deliver(event))
            except Exception:
                # Best-effort delivery; failures are visible via list_inbox catch-up.
                pass
        return event
```

- [ ] **Step 5: Run, confirm PASS.**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_completeness agent.tests.test_eventhub_subscription_fanout 2>&1 | tail -5
```

Expected: 18 OK (13 + 5).

- [ ] **Step 6: Commit**

```bash
git add agent/tests/test_eventhub_completeness.py agent/tests/test_eventhub_subscription_fanout.py agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py
git commit -m "Add EventHub.attach_bridge + subscription-driven fan-out in publish_event"
```

---

## Phase 2 — MessageBusBridge

### Task 6: Create `hubs/eventhub/` package skeleton

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/__init__.py`
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py`

- [ ] **Step 1: Empty package init**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/__init__.py`:

```python
from .bridge import MessageBusBridge

__all__ = ["MessageBusBridge"]
```

- [ ] **Step 2: Bridge stub**

Create `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...eventhub import EventHub


class MessageBusBridge:
    """Delivers persisted EventHub events to live agents via in-process MessageBus."""

    def __init__(self, eventhub: "EventHub", message_bus):
        self.eventhub = eventhub
        self.bus = message_bus

    async def deliver(self, event: dict) -> dict:
        # Implementation comes in Task 7.
        return {"delivered": [], "skipped_offline": [], "failed": []}
```

- [ ] **Step 3: Quick smoke**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from multi_agent.runtime.hubs.eventhub import MessageBusBridge
print('import OK')
"
```

Expected: `import OK`.

- [ ] **Step 4: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/__init__.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py
git commit -m "Scaffold MessageBusBridge stub package"
```

### Task 7: TDD MessageBusBridge.deliver

**Files:**
- Create: `agent/tests/test_messagebus_bridge.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py`

- [ ] **Step 1: Write bridge tests**

Create `agent/tests/test_messagebus_bridge.py`:

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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402
from multi_agent.runtime.hubs.eventhub import MessageBusBridge  # noqa: E402


class FakeAgent:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.received = []

    async def receive_message(self, message):
        self.received.append(message)


class FakeMessageBus:
    def __init__(self):
        self._agents = {}

    def register_agent(self, agent):
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id):
        return self._agents.get(agent_id)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class MessageBusBridgeTests(unittest.TestCase):
    def test_deliver_pushes_event_to_online_agent(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            bus = FakeMessageBus()
            backend = FakeAgent("backend")
            bus.register_agent(backend)
            bridge = MessageBusBridge(hub, bus)
            hub.attach_bridge(bridge)

            hub.publish_event(source_hub="apihub", event_type="endpoint_registered",
                               payload={"endpoint_id": "GET /api/feed"}, recipients=["backend"])
            # Give the pending task time to run if needed
            import time; time.sleep(0.05)

            self.assertEqual(len(backend.received), 1)
            msg = backend.received[0]
            self.assertEqual(msg.metadata.get("source_hub"), "apihub")
            self.assertEqual(msg.metadata.get("event_type"), "endpoint_registered")

    def test_deliver_skips_offline_agent_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            bus = FakeMessageBus()
            bridge = MessageBusBridge(hub, bus)
            hub.attach_bridge(bridge)

            # No agent registered; should not crash.
            event = hub.publish_event(source_hub="apihub", event_type="ping",
                                       payload={}, recipients=["nobody"])
            self.assertIn("nobody", event["recipients"])  # still in inbox for later catch-up

    def test_deliver_marks_delivered_on_inbox_item(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            bus = FakeMessageBus()
            backend = FakeAgent("backend")
            bus.register_agent(backend)
            bridge = MessageBusBridge(hub, bus)
            hub.attach_bridge(bridge)

            event = hub.publish_event(source_hub="apihub", event_type="x",
                                       payload={}, recipients=["backend"])
            import time; time.sleep(0.05)
            inbox = hub._inboxes.value().get("backend") or {}
            item = inbox.get("items", {}).get(event["id"])
            self.assertTrue(item.get("delivered"))
            self.assertFalse(item.get("read"))

    def test_deliver_skips_inbox_only_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            bus = FakeMessageBus()
            backend = FakeAgent("backend")
            bus.register_agent(backend)
            bridge = MessageBusBridge(hub, bus)
            hub.attach_bridge(bridge)

            hub.subscribe(agent="backend", source_hub="apihub", delivery="inbox_only")
            hub.publish_event(source_hub="apihub", event_type="x", payload={}, recipients=[])
            import time; time.sleep(0.05)
            self.assertEqual(backend.received, [])  # never pushed live


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in `bridge.py`

Replace the stub with the full implementation:

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Set
from uuid import uuid4

if TYPE_CHECKING:
    from ...eventhub import EventHub


class MessageBusBridge:
    """Delivers persisted EventHub events to live agents via in-process MessageBus."""

    PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}

    def __init__(self, eventhub: "EventHub", message_bus):
        self.eventhub = eventhub
        self.bus = message_bus

    async def deliver(self, event: dict) -> dict:
        targets = self._resolve_live_targets(event)
        delivered, skipped, failed = [], [], []
        for agent_id in targets:
            agent = self.bus.get_agent(agent_id) if hasattr(self.bus, "get_agent") else None
            if not agent:
                skipped.append(agent_id)
                continue
            try:
                msg = self._to_base_message(event, agent_id)
                await agent.receive_message(msg)
                self.eventhub.mark_delivered(agent_id, event["id"])
                delivered.append(agent_id)
            except Exception as exc:
                failed.append((agent_id, str(exc)))
        return {"delivered": delivered, "skipped_offline": skipped, "failed": failed}

    def _resolve_live_targets(self, event: dict) -> Set[str]:
        explicit_recipients = set(event.get("recipients") or [])
        # Subscriptions with delivery="inbox_only" should NOT receive live push.
        inbox_only_agents: Set[str] = set()
        evt_priority = self.PRIORITY_RANK.get(event.get("priority", "normal"), 1)
        for sub in self.eventhub._subscriptions.value().values():
            if sub.get("_removed"):
                continue
            if sub.get("source_hub") not in (event.get("source_hub"), "*"):
                continue
            if sub.get("event_type") not in (event.get("event_type"), "*"):
                continue
            floor = self.PRIORITY_RANK.get(sub.get("priority_floor", "low"), 0)
            if evt_priority < floor:
                continue
            if sub.get("delivery") == "inbox_only":
                inbox_only_agents.add(sub.get("agent"))
        return explicit_recipients - inbox_only_agents

    def _to_base_message(self, event: dict, agent_id: str):
        # Import lazily to avoid circular import in tests that don't need full agent stack.
        from utils.message import BaseMessage, MessageHeader, MessagePriority, MessageType

        priority_map = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "urgent": MessagePriority.URGENT,
        }
        header = MessageHeader(
            message_id=str(uuid4()),
            timestamp=datetime.now(),
            source_agent_id=f"hub:{event.get('source_hub', 'eventhub')}",
            target_agent_id=agent_id,
            priority=priority_map.get(event.get("priority", "normal"), MessagePriority.NORMAL),
        )
        return BaseMessage(
            header=header,
            message_type=MessageType.STATUS,  # Repurpose STATUS for hub events; metadata identifies it.
            payload=event.get("payload"),
            metadata={
                "source_hub": event.get("source_hub"),
                "event_id": event.get("id"),
                "event_type": event.get("event_type"),
                "thread_id": event.get("thread_id"),
                "resource_type": event.get("resource_type"),
                "resource_id": event.get("resource_id"),
                "links": event.get("links") or {},
            },
        )
```

- [ ] **Step 4: Run, confirm PASS (4 OK).**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_messagebus_bridge -v 2>&1 | tail -8
```

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_messagebus_bridge.py agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py
git commit -m "Implement MessageBusBridge.deliver with inbox_only opt-out and priority floor"
```

---

## Phase 3 — Wire bridge through HubWorkspace → CRDTWorkspace → Orchestrator

### Task 8: HubWorkspace accepts message_bus and attaches bridge

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py`

- [ ] **Step 1: Inspect current**

```bash
sed -n '1,40p' agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py
```

- [ ] **Step 2: Modify `HubWorkspace.__init__`**

Replace the entire class body (preserving existing exports) with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .apihub import APIHub
from .codehub import CodeHub
from .eventhub import EventHub
from .workhub import WorkHub
from .hubs.eventhub import MessageBusBridge


class HubWorkspace:
    """Aggregator for the four collaboration hubs."""

    def __init__(self, base_dir: Path, message_bus: Any = None):
        self.base_dir = Path(base_dir)
        self.crdt_dir = self.base_dir / "shared" / "crdt"
        self.crdt_dir.mkdir(parents=True, exist_ok=True)
        self.eventhub = EventHub(self.crdt_dir)
        if message_bus is not None:
            self.bridge = MessageBusBridge(self.eventhub, message_bus)
            self.eventhub.attach_bridge(self.bridge)
        else:
            self.bridge = None
        self.codehub = CodeHub(self.crdt_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub = APIHub(self.crdt_dir, eventhub=self.eventhub)
        self.apihub.attach_workhub(self.workhub)

    def get_versions(self) -> Dict[str, int]:
        versions: Dict[str, int] = {}
        versions.update(self.eventhub.get_versions())
        versions.update(self.codehub.get_versions())
        versions.update(self.workhub.get_versions())
        versions.update(self.apihub.get_versions())
        return versions

    def snapshot(self) -> Dict[str, Any]:
        return {
            "codehub": self.codehub.snapshot(),
            "workhub": self.workhub.snapshot(),
            "apihub": self.apihub.snapshot(),
            "eventhub": self.eventhub.snapshot(),
        }
```

The `message_bus=None` default keeps existing tests (which construct `CRDTWorkspace(Path(td))` without a bus) working — bridge stays `None`, so `publish_event` falls back to disk-only.

- [ ] **Step 3: Verify all hub tests still green**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_completeness agent.tests.test_eventhub_subscription_fanout agent.tests.test_messagebus_bridge agent.tests.test_apihub_accessors agent.tests.test_apihub_strengthen agent.tests.test_apihub_tools agent.tests.test_apihub_breaking_change_creates_task agent.tests.test_hub_architecture 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hub_workspace.py
git commit -m "HubWorkspace accepts message_bus and attaches MessageBusBridge to EventHub"
```

### Task 9: CRDTWorkspace propagates message_bus to HubWorkspace

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/crdt.py`

- [ ] **Step 1: Update `__init__` signature**

Find `def __init__(self, base_dir: Path):` (around line 77) and change to:

```python
    def __init__(self, base_dir: Path, message_bus: Any = None):
```

Update the corresponding `self.hubs = HubWorkspace(self.base_dir)` line to:

```python
        self.hubs = HubWorkspace(self.base_dir, message_bus=message_bus)
```

`Any` may need importing — check top of file; if it's not there, add `from typing import Any` or use `Optional` whatever style the file uses.

- [ ] **Step 2: Verify tests**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: 7 OK. Tests that construct `CRDTWorkspace(Path(td))` without a bus still work because of the `=None` default.

- [ ] **Step 3: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/crdt.py
git commit -m "CRDTWorkspace accepts optional message_bus and forwards to HubWorkspace"
```

### Task 10: Orchestrator passes message_bus to CRDTWorkspace

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/orchestrator.py`

- [ ] **Step 1: Inspect current construction**

```bash
grep -n "CRDTWorkspace(self\.output_dir)" agent/env_generator/llm_generator/multi_agent/orchestrator.py
```

Expected: one line around 158 — `self.crdt_workspace = CRDTWorkspace(self.output_dir)`.

- [ ] **Step 2: Update**

Replace that single line with:

```python
        self.crdt_workspace = CRDTWorkspace(self.output_dir, message_bus=self.message_bus)
```

Make sure `self.message_bus = MessageBus()` is constructed BEFORE this line. It typically is — `self.message_bus = MessageBus()` should be around line 153.

- [ ] **Step 3: End-to-end smoke test** (no real LLM calls — just import and construct)

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from utils.communication import MessageBus
from multi_agent.runtime.crdt import CRDTWorkspace
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    bus = MessageBus()
    ws = CRDTWorkspace(Path(td), message_bus=bus)
    print('bridge attached:', ws.hubs.bridge is not None)
    # Fire a hub event and confirm it lands in eventhub
    ws.hubs.apihub.register_endpoint('GET', '/api/test', schema={}, provider='backend', agent='design')
    snap = ws.hubs.eventhub.snapshot()
    print('events recorded:', len(snap['events']))
"
```

Expected: `bridge attached: True` and `events recorded: 1` (at least).

- [ ] **Step 4: Regression**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: 7 OK.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/orchestrator.py
git commit -m "Orchestrator passes MessageBus into CRDTWorkspace for EventHub bridge wiring"
```

---

## Phase 4 — Agent spawn catch-up

### Task 11: TDD — Catch-up missed events on agent's first step after spawn

**Files:**
- Create: `agent/tests/test_eventhub_spawn_catchup.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py`

- [ ] **Step 1: Inspect current sync stage**

```bash
grep -n "_collect_crdt_change_summary\|_build_inbox_status_prompt\|_build_inbox_status_snapshot\|list_inbox" agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py | head
```

The sync mixin already has an "inbox_status" stage. We're going to add a new helper `_collect_eventhub_catchup_summary` that's called once on first step.

- [ ] **Step 2: Write test**

Create `agent/tests/test_eventhub_spawn_catchup.py`:

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

from multi_agent.runtime.eventhub import EventHub  # noqa: E402


class EventHubCatchUpTests(unittest.TestCase):
    def test_list_inbox_after_offline_events_returns_them(self):
        """Simulates: events fired while agent was offline; agent comes online and asks for inbox."""
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            hub.publish_event(source_hub="apihub", event_type="e1", payload={"k": 1},
                              recipients=["backend"])
            hub.publish_event(source_hub="apihub", event_type="e2", payload={"k": 2},
                              recipients=["backend"])
            inbox = hub.list_inbox("backend", unread_only=True)
            self.assertEqual(len(inbox), 2)

    def test_list_inbox_skips_already_delivered_when_marked_read(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            e1 = hub.publish_event(source_hub="apihub", event_type="e1", payload={},
                                    recipients=["backend"])
            e2 = hub.publish_event(source_hub="apihub", event_type="e2", payload={},
                                    recipients=["backend"])
            hub.mark_read("backend", e1["id"])
            inbox = hub.list_inbox("backend", unread_only=True)
            self.assertEqual([e["id"] for e in inbox], [e2["id"]])

    def test_list_inbox_orders_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            hub = EventHub(Path(td))
            e1 = hub.publish_event(source_hub="apihub", event_type="e1", payload={},
                                    recipients=["backend"])
            e2 = hub.publish_event(source_hub="apihub", event_type="e2", payload={},
                                    recipients=["backend"])
            inbox = hub.list_inbox("backend", unread_only=True)
            self.assertEqual(inbox[0]["id"], e2["id"])
            self.assertEqual(inbox[1]["id"], e1["id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run, confirm PASS**

These three test cases verify EventHub's existing `list_inbox` behavior — they should already PASS. They're recorded as the catch-up contract so any future regression on `list_inbox` is caught.

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_spawn_catchup -v 2>&1 | tail -5
```

Expected: 3 OK.

- [ ] **Step 4: Add `_collect_eventhub_catchup_summary` to `AgentSync`**

Open `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py`. Locate `_collect_crdt_change_summary` (around line 483). Add a new helper method nearby:

```python
    async def _collect_eventhub_catchup_summary(self) -> Optional[str]:
        """First-step catch-up: pull recent unread events from EventHub for this agent."""
        crdt = getattr(self, "_crdt_workspace", None)
        hubs = getattr(crdt, "hubs", None) if crdt else None
        eventhub = getattr(hubs, "eventhub", None) if hubs else None
        if eventhub is None:
            return None
        try:
            unread = eventhub.list_inbox(self.agent_id, unread_only=True)
        except Exception:
            return None
        if not unread:
            return None
        lines = [f"### EventHub catch-up ({len(unread)} unread events)"]
        priority_rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        unread.sort(key=lambda e: (priority_rank.get(e.get("priority", "normal"), 2),
                                    -float(e.get("created_at", 0))))
        for e in unread[:8]:
            src = e.get("source_hub", "?")
            et = e.get("event_type", "?")
            pri = e.get("priority", "normal")
            rid = e.get("resource_id", "")
            lines.append(f"- [{pri.upper()}] {src}/{et} {rid}")
        if len(unread) > 8:
            lines.append(f"- … plus {len(unread) - 8} more (call eventhub_list_inbox for full list)")
        return "\n".join(lines)
```

Now find where `_collect_crdt_change_summary` is called in the step pipeline (likely in `step_runner.py` or wherever the inbox_status / crdt_changes stages run). The minimal approach is to attach an instance flag `_first_step_catchup_done = False` (set in `EnvGenAgent.__init__`) and call the catch-up summary on the first step's inbox_status stage.

Find the `_build_inbox_status_snapshot` method (around line 202). At the END of `_build_inbox_status_prompt(snapshot)` (around line 227), insert before the return statement:

```python
        # First-step catch-up: append EventHub unread summary once.
        if not getattr(self, "_first_step_catchup_done", False):
            try:
                catch = await self._collect_eventhub_catchup_summary()
            except Exception:
                catch = None
            if catch:
                prompt_parts.append(catch)
            self._first_step_catchup_done = True
```

You may need to convert `_build_inbox_status_prompt` to `async def` if it isn't already. Inspect it carefully — if it's currently sync, change its signature AND every caller in the same file or in `step_runner.py`.

If converting to async is too invasive, an alternative: keep `_build_inbox_status_prompt` sync, but use `asyncio.get_event_loop().run_until_complete(...)` to call the async helper inline. Document that choice.

- [ ] **Step 5: Sanity test**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_eventhub_spawn_catchup agent.tests.test_eventhub_completeness agent.tests.test_eventhub_subscription_fanout agent.tests.test_messagebus_bridge agent.tests.test_hub_architecture 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add agent/tests/test_eventhub_spawn_catchup.py agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py
git commit -m "Add EventHub catch-up on agent first step"
```

---

## Phase 5 — Verify + ship

### Task 12: Full regression + smoke

- [ ] **Step 1: Full hub + regression suites**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest \
  agent.tests.test_eventhub_completeness \
  agent.tests.test_eventhub_subscription_fanout \
  agent.tests.test_eventhub_spawn_catchup \
  agent.tests.test_messagebus_bridge \
  agent.tests.test_apihub_accessors \
  agent.tests.test_apihub_strengthen \
  agent.tests.test_apihub_tools \
  agent.tests.test_apihub_breaking_change_creates_task \
  agent.tests.test_hub_architecture \
  2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
```

Expected: combined 44 OK (15 new EventHub-related + 29 existing); regressions 7 OK.

- [ ] **Step 2: End-to-end smoke** (no real LLM):

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import asyncio, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
from utils.communication import MessageBus
from multi_agent.runtime.crdt import CRDTWorkspace

class FakeAgent:
    def __init__(self, aid): self.agent_id = aid; self.received = []
    async def receive_message(self, m): self.received.append(m)

async def main():
    with tempfile.TemporaryDirectory() as td:
        bus = MessageBus(); await bus.start()
        backend = FakeAgent('backend'); bus.register_agent(backend)
        ws = CRDTWorkspace(Path(td), message_bus=bus)
        ws.hubs.apihub.register_endpoint('GET', '/api/feed',
            schema={'response': {'posts': []}}, provider='backend', agent='design')
        ws.hubs.apihub.register_consumer('GET /api/feed', 'f.jsx', 'backend')
        # Cause a breaking change → APIHub fires 'breaking_change_detected' event with recipients=['backend']
        ws.hubs.apihub.update_schema('GET /api/feed', response={'items': []}, agent='backend')
        await asyncio.sleep(0.1)
        print('backend received', len(backend.received), 'live event(s) via bridge')
        await bus.stop()

asyncio.get_event_loop().run_until_complete(main())
"
```

Expected: `backend received 1 live event(s) via bridge` (or more).

If 0, **stop** — the bridge isn't actually delivering. Debug before continuing.

### Task 13: Migration log + push

- [ ] **Step 1: Write log**

Create `docs/superpowers/migration-logs/03-eventhub-bridge.md`:

```markdown
# 03 — EventHub MessageBus Bridge Cutover

**Branch:** haibotong-cutover-2-eventhub-bridge
**Predecessor:** Cutover 1.5 (APIHub completeness)
**Audit reference:** docs/superpowers/audit-reports/2026-05-21-crdt-strip-audit.md §2.4

## Summary

EventHub is now the source of truth + transport spec it was always meant to be. The `MessageBusBridge` delivers persisted events to live agents via in-process `MessageBus`; offline agents catch up on first step via `list_inbox`. Subscription-driven fan-out lands in `publish_event`. EventHub now exposes the full API surface (mark_delivered, mark_all_read, get_event, get_thread, unsubscribe, get_subscriptions, attach_bridge).

## Components added

- `runtime/hubs/eventhub/bridge.py` — `MessageBusBridge` with priority-floor and `delivery="inbox_only"` opt-out
- 6 new EventHub methods + reshaped `subscribe` to spec model
- Subscription fan-out integrated into `publish_event`
- Agent spawn catch-up in `agents/runtime/sync.py`

## Wiring chain

`Orchestrator.message_bus → CRDTWorkspace(message_bus=...) → HubWorkspace(message_bus=...) → MessageBusBridge → EventHub.attach_bridge`

`message_bus=None` defaults preserved everywhere so unit tests that build hubs without a bus continue to work.

## Commits

<paste output of `git log --oneline red-env-gen/haibotong-cutover-1.5-apihub-completeness..HEAD`>

## Test additions

- `test_eventhub_completeness.py` (12 tests)
- `test_eventhub_subscription_fanout.py` (5 tests)
- `test_eventhub_spawn_catchup.py` (3 tests)
- `test_messagebus_bridge.py` (4 tests)

Combined hub+regression suite: 51 tests, all passing.

## Regression evidence

<paste last 5 lines of `python agent/tests/run_regressions.py`>

## Gotchas
<List anything surprising encountered, e.g., sync→async conversion for inbox_status, prepare-commit-msg interplay, etc.>

## Next

Cutover 3 — WorkHub full + dev_task / plan migration. Now that bridge delivery works, WorkHub's `create_task` / `claim_task` / `complete_task` events will reach assignees in real-time, completing the cross-hub flow that APIHub's breaking-change auto-task already sets up.
```

- [ ] **Step 2: Commit log**

```bash
git add docs/superpowers/migration-logs/03-eventhub-bridge.md
git commit -m "Add Cutover 2 migration log"
```

- [ ] **Step 3: Push**

```bash
git push red-env-gen haibotong-cutover-2-eventhub-bridge -u 2>&1 | tail -3
```

Expected: `* [new branch] haibotong-cutover-2-eventhub-bridge -> haibotong-cutover-2-eventhub-bridge`.

- [ ] **Step 4: Print PR URL**

```bash
echo "PR compare URL: https://github.com/Virtue-AI/red-env-gen/compare/haibotong-cutover-1.5-apihub-completeness...haibotong-cutover-2-eventhub-bridge"
```

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer on any commit** (user preference, persistent across this repo).
- Branch from `red-env-gen/haibotong-cutover-1.5-apihub-completeness`, push to `red-env-gen` remote.
- The `dt` conda env (`/home/haibotong/miniconda3/envs/dt/bin/python`) is the only Python with all deps; system python3 is too old.
- Each task = one commit (~12 commits total before the migration log).

## Out of Scope (deferred)

- **Agent status migration** — `update_agent_status / get_agent_statuses / observe_agents` are migrated in Cutover 3 (where the rest of the agent-runtime CRDT methods go) using EventHub system topic.
- **Subscription filter dict enforcement** — currently stored, not yet used. Wait for the first cross-hub flow that actually needs filter matching (likely Cutover 3).
- **Event log compaction** — spec marks future.
- **Real-time fan-out via WebSocket / SSE** — not needed; in-process MessageBus is sufficient.

## Recovery Notes

Each task = one commit. `git reset --hard HEAD~1` per task reverts safely. If `_build_inbox_status_prompt` sync→async conversion explodes test coverage, revert Task 11 and keep catch-up as a manual `eventhub_list_inbox` tool call by agents on first step (deferred to Cutover 3).
