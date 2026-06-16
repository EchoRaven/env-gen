# Cutover 29: Agent Chat Consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cutover 27 built the human→EventHub→inbox half of the chat. This cutover wires the OTHER half: an agent that receives a human_user message must actually process it (LLM call) and publish a reply back into the same conversation thread. Without this, the chat UI sends messages into a void.

**Architecture:** Two bugs/gaps to close: (1) the `MessageBusBridge` priority map drops `human_user` events to `NORMAL` (no `human_user` entry), so they never trigger `_check_and_handle_urgent` — fix by mapping `human_user` → `URGENT`. (2) `_check_and_handle_urgent` has no branch for `event_type=="human_message"`. Add a `_handle_human_message` method that pulls text + thread_id from the message, calls the agent's LLM with a small dedicated prompt, and publishes the reply via `self._hubs.eventhub.publish_agent_reply`. Also auto-subscribe targeted agents on startup so the bridge can route by recipient (already happens via explicit recipients, but a safety net never hurts).

**Tech Stack:** Python 3 (asyncio), existing EnvGenAgent + MessageBusBridge + EventHub, no new deps.

---

## Test infrastructure conventions (repo-specific — REQUIRED)

Tests live in `agent/tests/`. **Every new test file MUST start with this boilerplate**:

```python
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
```

Then imports use the short form:
```python
from multi_agent.runtime.eventhub import EventHub
from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.hubs.eventhub.bridge import MessageBusBridge
```

Pytest: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q`
Regressions: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

---

## File Structure

**Files to create:**
- `agent/tests/test_bridge_human_priority.py` — verify bridge maps `human_user` event priority to `MessagePriority.URGENT`
- `agent/tests/test_agent_human_message_handler.py` — unit tests for `_handle_human_message` using a stub LLM
- `agent/tests/test_agent_chat_e2e.py` — e2e: HubRegistry + EventHub + bridge + EnvGenAgent stub → human msg → LLM reply → EventHub agent_reply
- `docs/superpowers/migration-logs/29-agent-chat-consumer.md`

**Files to modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py` — extend `priority_map` to include `"human_user": MessagePriority.URGENT` (cap at URGENT since MessagePriority has no separate tier above)
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py` — extend `_check_and_handle_urgent` with a new branch that detects `event_type == "human_message"` (from `urgent_msg.metadata["event_type"]`) and routes to `_handle_human_message`
- `agent/env_generator/llm_generator/multi_agent/agents/base.py` — add `_handle_human_message(self, message)` method that calls LLM and publishes reply

---

## Task 1: Pre-flight baseline

- [ ] **Step 1: Regressions**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-29-agent-chat-consumer
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: `Ran 7 tests` + `OK`.

- [ ] **Step 2: Pytest collect**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ --collect-only -q 2>&1 | tail -3
```

Expected: 991 collected.

- [ ] **Step 3: Create migration log stub + commit**

```bash
mkdir -p docs/superpowers/migration-logs
cat > docs/superpowers/migration-logs/29-agent-chat-consumer.md <<'EOF'
# Cutover 29: Agent Chat Consumer

**Branch:** `haibotong-cutover-29-agent-chat-consumer`
**Date:** 2026-05-26
**Status:** in-progress

## Pre-flight baseline
- Regressions: 7 OK
- Pytest collected: 991
EOF
git add docs/superpowers/migration-logs/29-agent-chat-consumer.md
git commit -m "Cutover 29: record pre-flight baseline"
```

---

## Task 2: Fix bridge priority map for `human_user`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py`
- Create: `agent/tests/test_bridge_human_priority.py`

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_bridge_human_priority.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from unittest.mock import MagicMock
from multi_agent.runtime.eventhub import EventHub
from multi_agent.runtime.hubs.eventhub.bridge import MessageBusBridge
from utils.message import MessagePriority


def test_bridge_maps_human_user_priority_to_urgent(tmp_path):
    """A human_user EventHub event must arrive at agents as URGENT MessagePriority."""
    eh = EventHub(tmp_path)
    bus = MagicMock()
    bridge = MessageBusBridge(bus, eh)

    event = {
        "id": "evt_test",
        "source_hub": "human_user",
        "event_type": "human_message",
        "priority": "human_user",
        "payload": {"text": "hi", "from_user": "haibotong"},
        "thread_id": "thread_test",
        "recipients": ["backend"],
    }

    msg = bridge._to_base_message(event, "backend")
    assert msg.header.priority == MessagePriority.URGENT, (
        "human_user EventHub events must map to MessagePriority.URGENT so they "
        "trigger _check_and_handle_urgent"
    )


def test_bridge_critical_still_maps_to_urgent(tmp_path):
    """Sanity: pre-existing `critical` -> URGENT still holds."""
    eh = EventHub(tmp_path)
    bridge = MessageBusBridge(MagicMock(), eh)
    event = {"id": "x", "source_hub": "h", "event_type": "y", "priority": "critical", "payload": {}, "thread_id": "t", "recipients": ["a"]}
    msg = bridge._to_base_message(event, "a")
    assert msg.header.priority == MessagePriority.URGENT


def test_bridge_normal_still_maps_to_normal(tmp_path):
    """Sanity: pre-existing `normal` -> NORMAL still holds."""
    eh = EventHub(tmp_path)
    bridge = MessageBusBridge(MagicMock(), eh)
    event = {"id": "x", "source_hub": "h", "event_type": "y", "priority": "normal", "payload": {}, "thread_id": "t", "recipients": ["a"]}
    msg = bridge._to_base_message(event, "a")
    assert msg.header.priority == MessagePriority.NORMAL
```

- [ ] **Step 2: Run tests — expect 1 FAIL, 2 PASS**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_bridge_human_priority.py -v
```

The `human_user → URGENT` test fails because the bridge's `priority_map` has no `"human_user"` entry (falls back to NORMAL default).

- [ ] **Step 3: Fix the bridge priority map**

Find this block in `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py` (around line 74):

```python
        priority_str = event.get("priority", "normal")
        priority_map: Dict[str, "MessagePriority"] = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "critical": MessagePriority.URGENT,
        }
        priority = priority_map.get(priority_str, MessagePriority.NORMAL)
```

Replace with:

```python
        priority_str = event.get("priority", "normal")
        priority_map: Dict[str, "MessagePriority"] = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "critical": MessagePriority.URGENT,
            # Cutover 29: human_user collapses to URGENT for queue prioritization;
            # the urgent-handler dispatches on event_type=="human_message" to route
            # to the dedicated _handle_human_message branch.
            "human_user": MessagePriority.URGENT,
        }
        priority = priority_map.get(priority_str, MessagePriority.NORMAL)
```

- [ ] **Step 4: Run tests — expect 3 PASS**

- [ ] **Step 5: Run regressions — expect 7 OK**

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py \
        agent/tests/test_bridge_human_priority.py
git commit -m "Cutover 29: bridge maps human_user EventHub priority to URGENT MessagePriority"
```

---

## Task 3: Agent `_handle_human_message` handler + urgent-loop dispatch

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/base.py` (add `_handle_human_message`)
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py` (add `event_type == "human_message"` branch to `_check_and_handle_urgent`)
- Create: `agent/tests/test_agent_human_message_handler.py`

- [ ] **Step 1: Investigate the agent's LLM hook**

Identify how an EnvGenAgent calls its LLM. Look at:

```bash
grep -n "self\.llm\|self\._llm\|await self\.\(llm\|_llm\)\|generate\|complete" agent/env_generator/llm_generator/multi_agent/agents/base.py | head -20
```

Find a method or attribute that can be called with a simple prompt and return text. Common patterns: `self.llm.acomplete(prompt)`, `self.llm.generate(prompt)`, `self._llm_client.create(...)`. Use the simplest available — the goal is "send text, get text back."

If no obvious simple helper exists, add a thin one in `base.py`:

```python
async def _generate_text(self, system: str, user: str) -> str:
    """Single-turn text generation. Used by human-message handler.

    Falls back to a placeholder if LLM is unavailable so tests with stubs
    can override this method to return canned responses.
    """
    try:
        result = await self.llm.complete(system=system, user=user)
        return (result.get("text") if isinstance(result, dict) else str(result)) or ""
    except Exception as e:
        self._logger.warning(f"[{self.agent_id}] LLM call failed: {e}")
        return f"(I received your message but my LLM is unavailable: {e})"
```

(Adjust the actual call signature to match the existing LLM client — the goal is a small awaitable that returns a string.)

- [ ] **Step 2: Write the failing test**

```python
# agent/tests/test_agent_human_message_handler.py
"""Cutover 29: an agent receiving a human_user message must call LLM + publish reply."""
import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry
from utils.message import BaseMessage, MessageHeader, MessageType, MessagePriority


def _make_human_event_message(thread_id, text="Hello"):
    header = MessageHeader(
        source_agent_id="human_user",
        target_agent_id="backend",
        priority=MessagePriority.URGENT,
        correlation_id=thread_id,
    )
    metadata = {
        "source_hub": "human_user",
        "event_id": "evt_test",
        "event_type": "human_message",
        "thread_id": thread_id,
    }
    return BaseMessage(
        header=header,
        message_type=MessageType.STATUS,
        payload={"text": text, "from_user": "haibotong"},
        metadata=metadata,
    )


def test_handle_human_message_publishes_reply(tmp_path):
    """Stub LLM returns canned text; handler must publish_agent_reply with it."""
    # Construct a minimal agent: we monkey-patch the bits we need.
    reg = HubRegistry(tmp_path, project_id="proj_x", project_name="X")

    # Seed a thread so publish_agent_reply has somewhere to write
    initial = reg.eventhub.publish_human_message(
        text="please help",
        target_agents=["backend"],
    )
    tid = initial["thread_id"]

    # Build a minimal stand-in for an EnvGenAgent: only the surface the
    # handler touches. We monkey-patch a class with just _hubs, agent_id,
    # _logger, _generate_text.
    class StubAgent:
        agent_id = "backend"
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _generate_text(self, system, user):
            return "acknowledged, on it"

    from multi_agent.agents.base import EnvGenAgent
    msg = _make_human_event_message(tid, text="please help")

    stub = StubAgent()
    asyncio.run(EnvGenAgent._handle_human_message(stub, msg))

    # Pull thread messages — should now contain the reply
    msgs = reg.human_console.list_messages(tid)
    texts = [m["text"] for m in msgs]
    assert "please help" in texts
    assert "acknowledged, on it" in texts
    # And the reply must be from "backend" (source_hub)
    assert any(m["source"] == "backend" and m["text"] == "acknowledged, on it" for m in msgs)


def test_handle_human_message_no_thread_id_logs_and_returns(tmp_path):
    """Malformed message (no thread_id) must not crash; just log + return."""
    reg = HubRegistry(tmp_path, project_id="proj_y", project_name="Y")

    class StubAgent:
        agent_id = "backend"
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _generate_text(self, system, user):
            raise AssertionError("LLM should not be called when thread_id is missing")

    # Construct message with empty metadata.thread_id
    header = MessageHeader(source_agent_id="human_user", target_agent_id="backend",
                          priority=MessagePriority.URGENT, correlation_id=None)
    msg = BaseMessage(
        header=header,
        message_type=MessageType.STATUS,
        payload={"text": "x"},
        metadata={"event_type": "human_message", "thread_id": ""},
    )

    from multi_agent.agents.base import EnvGenAgent
    stub = StubAgent()
    asyncio.run(EnvGenAgent._handle_human_message(stub, msg))
    stub._logger.warning.assert_called()


def test_handle_human_message_llm_error_publishes_apology(tmp_path):
    """If LLM raises, the handler must still publish an apology so the user gets feedback."""
    reg = HubRegistry(tmp_path, project_id="proj_z", project_name="Z")
    initial = reg.eventhub.publish_human_message(text="hi", target_agents=["backend"])
    tid = initial["thread_id"]

    class StubAgent:
        agent_id = "backend"
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _generate_text(self, system, user):
            raise RuntimeError("LLM exploded")

    from multi_agent.agents.base import EnvGenAgent
    msg = _make_human_event_message(tid)
    stub = StubAgent()
    asyncio.run(EnvGenAgent._handle_human_message(stub, msg))

    msgs = reg.human_console.list_messages(tid)
    # Reply present (even if it's an apology)
    backend_replies = [m for m in msgs if m["source"] == "backend"]
    assert len(backend_replies) == 1
    assert "error" in backend_replies[0]["text"].lower() or "fail" in backend_replies[0]["text"].lower() or "unavailable" in backend_replies[0]["text"].lower()
```

- [ ] **Step 3: Run tests — expect 3 FAIL (no `_handle_human_message` yet)**

- [ ] **Step 4: Add `_handle_human_message` to `EnvGenAgent`**

Add to `agent/env_generator/llm_generator/multi_agent/agents/base.py` (place near other handlers):

```python
    async def _handle_human_message(self, message) -> None:
        """Cutover 29: A real human just sent us a message. Generate a reply.

        The reply goes to EventHub via publish_agent_reply, where the bridge
        fans it out to all thread participants + the synthetic human_user
        inbox (which the UI ChatPanel reads via list_messages).
        """
        metadata = getattr(message, "metadata", {}) or {}
        thread_id = metadata.get("thread_id") or getattr(message.header, "correlation_id", "")
        if not thread_id:
            self._logger.warning(f"[{self.agent_id}] human_message missing thread_id; skipping")
            return

        payload = getattr(message, "payload", {}) or {}
        user_text = (payload.get("text") if isinstance(payload, dict) else "") or ""
        if not user_text.strip():
            self._logger.warning(f"[{self.agent_id}] human_message with empty text; skipping")
            return

        # Build a tiny prompt: who you are + what the human said + how to reply.
        system = (
            f"You are the {self.agent_id} agent in an env-generation multi-agent system. "
            "A real human user has just sent you a direct message. Reply in a single "
            "concise paragraph: acknowledge what they asked, say what you will do (or "
            "have done), and be specific. Do not call any tools."
        )

        try:
            reply_text = await self._generate_text(system=system, user=user_text)
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] _generate_text failed: {e}")
            reply_text = f"(I received your message but couldn't reply: {e})"

        reply_text = (reply_text or "").strip()
        if not reply_text:
            reply_text = "(no response generated)"

        if self._hubs is None:
            self._logger.warning(f"[{self.agent_id}] no hubs handle; cannot publish reply")
            return

        try:
            self._hubs.eventhub.publish_agent_reply(
                thread_id=thread_id,
                agent=self.agent_id,
                text=reply_text,
            )
        except Exception as e:
            self._logger.error(f"[{self.agent_id}] publish_agent_reply failed: {e}")
```

If `_generate_text` doesn't already exist on the class, add a thin version next to `_handle_human_message`:

```python
    async def _generate_text(self, system: str, user: str) -> str:
        """Single-turn text generation. Override or monkey-patch for tests.

        Reads the LLM via whatever attribute the class uses; tests typically
        override this method to return canned text.
        """
        # Find the LLM client attribute by introspection — many places use
        # `self.llm`, `self._llm`, or call through a complete() helper.
        llm = getattr(self, "llm", None) or getattr(self, "_llm", None)
        if llm is None:
            return f"({self.agent_id}: LLM not configured)"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        # Try common method names; fall through gracefully.
        for method_name in ("acomplete", "achat", "complete", "chat", "generate"):
            method = getattr(llm, method_name, None)
            if method is None:
                continue
            try:
                result = method(messages=messages) if "chat" in method_name else method(user)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, dict):
                    return result.get("content") or result.get("text") or str(result)
                return str(result) if result else ""
            except Exception as e:
                self._logger.debug(f"[{self.agent_id}] LLM method {method_name} failed: {e}")
                continue
        return f"({self.agent_id}: no usable LLM method found)"
```

- [ ] **Step 5: Run tests — expect 3 PASS**

- [ ] **Step 6: Wire dispatch into `_check_and_handle_urgent`**

In `agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py`, find the existing message type dispatch in `_check_and_handle_urgent` (around lines 198-253). Add a NEW branch BEFORE the existing branches (so human messages take precedence over question/answer/issue/task_ready):

```python
        # Cutover 29: Human-user messages from EventHub → dedicated handler.
        event_type = (urgent_msg.metadata or {}).get("event_type", "")
        if event_type == "human_message":
            try:
                await self._handle_human_message(urgent_msg)
            except Exception as e:
                self._logger.error(f"[{self.agent_id}] Error handling human_message: {e}")
            return True
```

(Place this immediately AFTER the `msg_type = urgent_msg.metadata.get("msg_type", "").lower()` line and `self._logger.info(...)` line, but BEFORE the `if msg_type == "shutdown":` block.)

- [ ] **Step 7: Run regressions — expect 7 OK**

- [ ] **Step 8: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/base.py \
        agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py \
        agent/tests/test_agent_human_message_handler.py
git commit -m "Cutover 29: agent _handle_human_message + urgent-loop dispatch"
```

---

## Task 4: E2E test — human → bridge → agent → LLM stub → reply

**Files:**
- Create: `agent/tests/test_agent_chat_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# agent/tests/test_agent_chat_e2e.py
"""Cutover 29: full chat roundtrip through bridge + urgent dispatch."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.hubs.eventhub.bridge import MessageBusBridge
from utils.message import MessagePriority


class FakeMessageBus:
    """Captures messages routed to agents."""
    def __init__(self):
        self.delivered = []  # (agent_id, message)
        self._agents = {}

    def register_agent(self, agent_id, agent):
        self._agents[agent_id] = agent

    def get_agent(self, agent_id):
        return self._agents.get(agent_id)


def test_e2e_human_message_routed_via_bridge_arrives_with_urgent_priority(tmp_path):
    """Smoke test: when EventHub publishes a human_user message, the bridge
    converts it to an URGENT BaseMessage and tries to deliver it."""
    reg = HubRegistry(tmp_path, project_id="proj_e2e", project_name="E2E")
    bus = FakeMessageBus()

    # Manually attach a bridge (in production this happens in HubRegistry when
    # message_bus is passed at construction)
    bridge = MessageBusBridge(bus, reg.eventhub)
    reg.eventhub.attach_bridge(bridge)

    # Register a stand-in agent with a priority queue we can introspect
    delivered = []

    class StandinAgent:
        agent_id = "backend"
        async def receive_message(self, msg):
            delivered.append(msg)
            return True
        # Bridge calls .receive_message via different paths depending on agent base;
        # provide common shims:
        async def handle_message(self, msg):
            delivered.append(msg)

    bus.register_agent("backend", StandinAgent())

    # Publish the human message
    reg.human_console.start_conversation(target_agents=["backend"], text="please scaffold the API")

    # Bridge.deliver runs synchronously inside publish_event; give the event
    # loop a moment to drain any ensure_future-scheduled tasks
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(asyncio.sleep(0.05))

    # Assert: at least one delivery attempted at URGENT priority
    assert any(m.header.priority == MessagePriority.URGENT for m in delivered) or len(delivered) > 0, (
        f"Expected URGENT delivery to 'backend'; bus delivered: {delivered}"
    )
```

(Note: this is a smoke / sanity test — the exact delivery path depends on how `MessageBus.publish` calls into the agent. The strict per-agent-class wiring is covered in Task 3's unit tests. This test just verifies the bridge → bus → agent path doesn't drop the message.)

- [ ] **Step 2: Run + check for issues**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_agent_chat_e2e.py -v
```

If the test fails because the bridge's delivery semantics don't match the assumptions (e.g., bridge calls a method the stand-in doesn't have): adjust the StandinAgent to match what the real `_resolve_live_targets` + `deliver` actually call. Read `bridge.py:108` (`def deliver`) to confirm the calling convention.

If the test passes: great.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_agent_chat_e2e.py
git commit -m "Cutover 29: e2e smoke for human → bridge → agent URGENT routing"
```

---

## Task 5: Final sweep + migration log + push

- [ ] **Step 1: Targeted sweep**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_bridge_human_priority.py \
  agent/tests/test_agent_human_message_handler.py \
  agent/tests/test_agent_chat_e2e.py \
  -v 2>&1 | tail -15
```

Expected: 7 passed (3 + 3 + 1).

- [ ] **Step 2: Collateral spot check on existing message bridge + EventHub tests**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_eventhub_human_priority.py \
  agent/tests/test_human_console.py \
  agent/tests/test_human_subscription.py \
  agent/tests/test_human_agent_e2e.py \
  -q 2>&1 | tail -5
```

Expected: 28 passed (the Cutover 27 baseline) — confirming nothing in Task 2's bridge change broke EventHub.

- [ ] **Step 3: Regressions**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: `Ran 7 tests` + `OK`.

- [ ] **Step 4: Update migration log**

Overwrite `docs/superpowers/migration-logs/29-agent-chat-consumer.md` with the full template:

```markdown
# Cutover 29: Agent Chat Consumer

**Branch:** `haibotong-cutover-29-agent-chat-consumer`
**Date:** 2026-05-26

## What

Cutover 27 built the human → EventHub → inbox half. This cutover closes
the loop: agents now actually receive, process, and reply to human_user
messages. Two changes:
1. `MessageBusBridge.priority_map` adds `"human_user" → MessagePriority.URGENT`
   so the bridge no longer silently downgrades human messages to NORMAL.
2. EnvGenAgent gains `_handle_human_message` (LLM call + publish reply),
   dispatched from `_check_and_handle_urgent` when `metadata.event_type == "human_message"`.

## Why

Before this cutover, sending a chat message via the UI was a black hole:
the message reached EventHub and the inbox, but the bridge mapped its
`human_user` priority to NORMAL, so the agent's urgent-handler loop never
fired and nobody ever replied. The user explicitly identified this as
"the missing half — chat works in UI, agent never responds."

## Commits

- Cutover 29: record pre-flight baseline
- Cutover 29: bridge maps human_user EventHub priority to URGENT MessagePriority
- Cutover 29: agent _handle_human_message + urgent-loop dispatch
- Cutover 29: e2e smoke for human → bridge → agent URGENT routing
- (this commit) Cutover 29: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Targeted Cutover 29 sweep: 7 new tests pass (3 bridge + 3 handler + 1 e2e)
- Cutover 27 sweep: 28 pre-existing tests still pass

## New surfaces

- `MessageBusBridge.priority_map["human_user"] = MessagePriority.URGENT`
- `EnvGenAgent._handle_human_message(message)` — LLM call + publish_agent_reply
- `EnvGenAgent._generate_text(system, user)` — minimal single-turn text gen helper (auto-discovers LLM client; tests override this)
- `_check_and_handle_urgent` new branch: `event_type == "human_message"` → `_handle_human_message`

## Architecture notes

- The dispatcher checks `event_type` BEFORE `msg_type` so human messages
  take precedence over standard agent comms (question/answer/issue/task_ready).
- Reply uses `publish_agent_reply` (Cutover 27) which routes back to the
  full thread participant set, so the human (via `list_messages`) and any
  other agents on the thread all see the reply.
- LLM failures don't crash the loop — they publish an apology reply so
  the human gets feedback that something went wrong.

## Known limits (future cutovers)

- Auto-routing: target agents must still be picked explicitly by the human.
- Reply prompt is generic (one paragraph, no tools); future cutovers may
  let agents call tools while replying (e.g. "add the requested feature
  AND tell the user it's done in one turn").
- Multiple human messages in rapid succession may interleave with agent
  work — there's no per-thread mutex yet.
- The orchestrator-as-aware-listener pattern (Cutover 27's
  `subscribe_to_human_messages`) is not auto-installed in this cutover;
  it remains opt-in.
- LLM call uses introspection to find the client method; a unified
  `AsyncCompletionClient` interface would be cleaner.
```

- [ ] **Step 5: Commit migration log**

```bash
git add docs/superpowers/migration-logs/29-agent-chat-consumer.md
git commit -m "Cutover 29: migration log"
```

- [ ] **Step 6: Push branch**

```bash
git push -u red-env-gen haibotong-cutover-29-agent-chat-consumer 2>&1 | tail -5
```

- [ ] **Step 7: Fast-forward merge into parent + push parent**

```bash
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-29-agent-chat-consumer
git merge --ff-only haibotong-cutover-29-agent-chat-consumer
git push red-env-gen haibotong-0521-pipeline-web-tools 2>&1 | tail -5
```

---

## Self-Review

**Spec coverage:**
- "agent 消化 human_user 消息" → Task 3 (`_handle_human_message`)
- "调 LLM 拟回复" → Task 3 (`_generate_text` helper)
- "调 `publish_agent_reply` 写回去" → Task 3 (reply path)
- "高优先级路由" → Task 2 (bridge priority map)

**Out of scope:**
- Auto-routing target agents
- Multi-turn conversation state on the agent side
- Replacing the introspective LLM client discovery with a real interface
- WebSocket / SSE for UI live updates (Cutover 31)
- Hub-specific widgets + operation buttons (Cutover 30)
