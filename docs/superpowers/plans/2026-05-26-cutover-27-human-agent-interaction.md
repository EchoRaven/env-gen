# Cutover 27: Human-Agent Interaction Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class **human-agent conversation** surface on EventHub. A real user can target one or many agents with a message; messages carry a new top-tier priority `human_user` (above `critical`) so any agent that receives one knows to interrupt and respond. Conversations persist on EventHub (threads + events) so the new UI (Cutover 28) can render history and resume.

**Architecture:** Extend `EventHub` with a `"human_user"` priority above `"critical"` and three helper methods: `publish_human_message(text, target_agents, thread_id?, from_user=...)`, `publish_agent_reply(thread_id, agent, text)`, and `list_conversations(participant?, status?)`. Conversations are EventHub threads where source_hub is `"human_user"`; replies use source_hub equal to the agent id. A `HumanConsole` helper on `HubRegistry` (composition, not subclass) wraps these for the UI/CLI. Agent-side: existing inbox delivery already handles routing; we add a subscription helper agents call once to receive human messages without specifying themselves as recipient.

**Tech Stack:** Python 3, existing EventHub (JsonStore-backed), dataclasses. No external deps.

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

Then imports use short form:
```python
from multi_agent.runtime.eventhub import EventHub          # YES
from multi_agent.runtime.hub_registry import HubRegistry   # YES
```

Pytest invocation:
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q
```

Regressions (NOT pytest):
```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

---

## File Structure

**Files to create:**
- `agent/env_generator/llm_generator/multi_agent/runtime/human_console.py` — `HumanConsole` wrapper (start_conversation, send_message, list_conversations, list_messages, mark_resolved)
- `agent/tests/test_eventhub_human_priority.py` — unit tests for `human_user` priority tier
- `agent/tests/test_human_console.py` — unit tests for HumanConsole API
- `agent/tests/test_human_agent_e2e.py` — e2e: human → agent → reply roundtrip; conversation persistence across HubRegistry restart
- `docs/superpowers/migration-logs/27-human-agent-interaction.md` — post-merge log

**Files to modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` — add `"human_user"` to `_PRIORITY_RANK` (rank 4); add `publish_human_message`, `publish_agent_reply`, `list_conversations`; add `subscribe_to_human_messages(agent)` convenience
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — instantiate `self.human_console = HumanConsole(self)` post-construction
- `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` — export `HumanConsole`

---

## Task 1: Pre-flight baseline (uses Cutover 26 baseline)

**Files:**
- None

- [ ] **Step 1: Run regressions + record baseline**

Run:

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-27-human-agent-interaction
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -10
```

Expected: 7 regressions OK, ~944 discover OK (post-Cutover 26).

- [ ] **Step 2: Create migration log stub + commit**

```bash
mkdir -p docs/superpowers/migration-logs
cat > docs/superpowers/migration-logs/27-human-agent-interaction.md <<'EOF'
# Cutover 27: Human-Agent Interaction Backend

**Branch:** `haibotong-cutover-27-human-agent-interaction`
**Date:** 2026-05-26
**Status:** in-progress

## Pre-flight baseline
- Regressions: 7 OK
- Discover: <BASELINE> OK
EOF
# Replace <BASELINE> with the actual number from Step 1
git add docs/superpowers/migration-logs/27-human-agent-interaction.md
git commit -m "Cutover 27: record pre-flight baseline"
```

---

## Task 2: human_user priority tier on EventHub (TDD)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py:37` (extend `_PRIORITY_RANK`)
- Create: `agent/tests/test_eventhub_human_priority.py`

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_eventhub_human_priority.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.eventhub import EventHub


def test_human_user_is_highest_priority(tmp_path):
    assert EventHub._PRIORITY_RANK["human_user"] > EventHub._PRIORITY_RANK["critical"]


def test_human_user_event_delivered_to_inbox(tmp_path):
    eh = EventHub(tmp_path)
    eh.publish_event(
        source_hub="human_user",
        event_type="human_message",
        payload={"text": "hello backend agent"},
        recipients=["backend"],
        priority="human_user",
    )
    inbox = eh.list_inbox("backend", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["priority"] == "human_user"
    assert inbox[0]["payload"]["text"] == "hello backend agent"


def test_human_user_event_passes_critical_floor_subscription(tmp_path):
    """Agents with priority_floor='critical' must still receive human_user events."""
    eh = EventHub(tmp_path)
    eh.subscribe(agent="frontend", source_hub="*", event_type="*", priority_floor="critical")
    eh.publish_event(
        source_hub="human_user",
        event_type="human_message",
        payload={"text": "urgent"},
        recipients=[],   # rely on subscription fan-out
        priority="human_user",
    )
    inbox = eh.list_inbox("frontend", unread_only=False)
    assert len(inbox) == 1


def test_priority_normal_event_does_not_reach_critical_floor(tmp_path):
    """Sanity: confirm priority floor still excludes lower-priority events."""
    eh = EventHub(tmp_path)
    eh.subscribe(agent="frontend", source_hub="*", event_type="*", priority_floor="critical")
    eh.publish_event(
        source_hub="codehub",
        event_type="commit",
        payload={},
        recipients=[],
        priority="normal",
    )
    inbox = eh.list_inbox("frontend", unread_only=False)
    assert inbox == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_eventhub_human_priority.py -v`

Expected: First 3 FAIL with KeyError or empty inbox (priority `human_user` not registered); 4th PASSES.

- [ ] **Step 3: Add human_user to _PRIORITY_RANK**

Replace the existing line at `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py:37`:

```python
    _PRIORITY_RANK: Dict[str, int] = {"low": 0, "normal": 1, "high": 2, "critical": 3}
```

with:

```python
    # Cutover 27: "human_user" is the top tier — messages from a real human
    # interrupt any agent's current work regardless of priority_floor.
    _PRIORITY_RANK: Dict[str, int] = {"low": 0, "normal": 1, "high": 2, "critical": 3, "human_user": 4}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_eventhub_human_priority.py -v`

Expected: 4 PASS.

- [ ] **Step 5: Run regressions to confirm no break**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py \
        agent/tests/test_eventhub_human_priority.py
git commit -m "Cutover 27: add human_user priority tier above critical on EventHub"
```

---

## Task 3: publish_human_message / publish_agent_reply / list_conversations on EventHub (TDD)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`
- Modify: `agent/tests/test_eventhub_human_priority.py` (append tests)

- [ ] **Step 1: Append failing tests for the new EventHub methods**

Append to `agent/tests/test_eventhub_human_priority.py`:

```python
def test_publish_human_message_creates_thread(tmp_path):
    eh = EventHub(tmp_path)
    event = eh.publish_human_message(
        text="please add a login button",
        target_agents=["frontend", "backend"],
        from_user="haibotong",
    )
    assert event["priority"] == "human_user"
    assert event["event_type"] == "human_message"
    assert event["source_hub"] == "human_user"
    assert sorted(event["recipients"]) == ["backend", "frontend"]
    assert event["payload"]["text"] == "please add a login button"
    assert event["payload"]["from_user"] == "haibotong"


def test_publish_human_message_reuses_thread_id(tmp_path):
    eh = EventHub(tmp_path)
    e1 = eh.publish_human_message(text="first", target_agents=["backend"])
    e2 = eh.publish_human_message(text="second", target_agents=["backend"], thread_id=e1["thread_id"])
    assert e2["thread_id"] == e1["thread_id"]


def test_publish_agent_reply_to_thread(tmp_path):
    eh = EventHub(tmp_path)
    initial = eh.publish_human_message(text="hello", target_agents=["backend"])
    reply = eh.publish_agent_reply(
        thread_id=initial["thread_id"],
        agent="backend",
        text="acknowledged, working on it",
    )
    assert reply["thread_id"] == initial["thread_id"]
    assert reply["source_hub"] == "backend"
    assert reply["event_type"] == "agent_reply"
    assert reply["payload"]["text"] == "acknowledged, working on it"
    # Reply must go back to the human (recipient "human_user") AND the original
    # participants so other agents can see it.
    assert "human_user" in reply["recipients"]


def test_list_conversations_returns_threads_with_human_events(tmp_path):
    eh = EventHub(tmp_path)
    e1 = eh.publish_human_message(text="task A", target_agents=["backend"])
    e2 = eh.publish_human_message(text="task B", target_agents=["frontend"])
    convos = eh.list_conversations()
    thread_ids = sorted(c["thread_id"] for c in convos)
    assert thread_ids == sorted([e1["thread_id"], e2["thread_id"]])


def test_list_conversations_filters_by_participant(tmp_path):
    eh = EventHub(tmp_path)
    eh.publish_human_message(text="A", target_agents=["backend"])
    eh.publish_human_message(text="B", target_agents=["frontend"])
    backend_convos = eh.list_conversations(participant="backend")
    assert len(backend_convos) == 1
    assert "backend" in backend_convos[0]["participants"]


def test_list_conversations_includes_message_count_and_last_message(tmp_path):
    eh = EventHub(tmp_path)
    initial = eh.publish_human_message(text="first", target_agents=["backend"])
    eh.publish_agent_reply(thread_id=initial["thread_id"], agent="backend", text="ack")
    eh.publish_human_message(text="follow-up", target_agents=["backend"], thread_id=initial["thread_id"])
    convos = eh.list_conversations()
    assert len(convos) == 1
    c = convos[0]
    assert c["message_count"] == 3
    assert c["last_message_text"] == "follow-up"
    assert c["last_message_source"] == "human_user"


def test_publish_human_message_rejects_empty_target_agents(tmp_path):
    eh = EventHub(tmp_path)
    with pytest.raises(ValueError):
        eh.publish_human_message(text="x", target_agents=[])


def test_publish_human_message_rejects_empty_text(tmp_path):
    eh = EventHub(tmp_path)
    with pytest.raises(ValueError):
        eh.publish_human_message(text="", target_agents=["backend"])
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_eventhub_human_priority.py -v`

Expected: 4 from Task 2 PASS, 8 new ones FAIL with `AttributeError: 'EventHub' object has no attribute 'publish_human_message'`.

- [ ] **Step 3: Implement the three new EventHub methods**

Append to `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` (inside the `EventHub` class, after `get_subscriptions` and before `list_inbox`):

```python
    # ------------------------------------------------------------------
    # Cutover 27: Human-agent conversation surface
    # ------------------------------------------------------------------

    def publish_human_message(
        self,
        text: str,
        target_agents: List[str],
        thread_id: Optional[str] = None,
        from_user: str = "human_user",
    ) -> dict:
        """Publish a top-priority message from a real human user to one or more agents.

        Always uses priority="human_user" and event_type="human_message".
        Recipients = the target agents + the synthetic "human_user" inbox so the
        UI can re-read the message in the conversation transcript.
        """
        if not text or not text.strip():
            raise ValueError("human message text must be non-empty")
        if not target_agents:
            raise ValueError("publish_human_message requires at least one target agent")
        return self.publish_event(
            source_hub="human_user",
            event_type="human_message",
            payload={"text": text, "from_user": from_user},
            recipients=[*target_agents, "human_user"],
            priority="human_user",
            thread_id=thread_id,
        )

    def publish_agent_reply(
        self,
        thread_id: str,
        agent: str,
        text: str,
    ) -> dict:
        """Publish an agent's reply into an existing human conversation thread.

        Replies inherit the thread's participants so the human (via the
        "human_user" inbox) and any other agents involved both see it.
        """
        if not text or not text.strip():
            raise ValueError("agent reply text must be non-empty")
        thread = self._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        # Reply audience: every prior participant + the human inbox.
        prior = set(thread.get("participants") or [])
        prior.add("human_user")
        prior.discard(agent)  # don't echo to the speaker
        return self.publish_event(
            source_hub=agent,
            event_type="agent_reply",
            payload={"text": text, "reply_from": agent},
            recipients=sorted(prior),
            priority="high",          # replies are high but not human_user
            thread_id=thread_id,
        )

    def list_conversations(
        self,
        participant: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        """Return human-agent conversation summaries.

        A "conversation" is any thread whose first event has
        source_hub="human_user". Returned dicts:
            {thread_id, participants, message_count, last_message_at,
             last_message_text, last_message_source, status}
        Sorted by last_message_at descending.
        """
        threads = self._threads.value() or {}
        events = self._events.value() or {}
        out = []
        for tid, thread in threads.items():
            event_ids = thread.get("event_ids") or []
            if not event_ids:
                continue
            first = events.get(event_ids[0])
            if not first or first.get("source_hub") != "human_user":
                continue
            if participant is not None and participant not in (thread.get("participants") or []):
                continue
            last = events.get(event_ids[-1]) or {}
            convo_status = thread.get("status", "open")
            if status is not None and convo_status != status:
                continue
            out.append({
                "thread_id": tid,
                "participants": list(thread.get("participants") or []),
                "message_count": len(event_ids),
                "last_message_at": last.get("created_at", 0.0),
                "last_message_text": (last.get("payload") or {}).get("text", ""),
                "last_message_source": last.get("source_hub", ""),
                "status": convo_status,
                "created_at": thread.get("created_at", 0.0),
            })
        out.sort(key=lambda c: c["last_message_at"], reverse=True)
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_eventhub_human_priority.py -v`

Expected: 12 PASS.

- [ ] **Step 5: Run regressions to confirm no break**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py \
        agent/tests/test_eventhub_human_priority.py
git commit -m "Cutover 27: EventHub.publish_human_message/agent_reply/list_conversations"
```

---

## Task 4: HumanConsole wrapper on HubRegistry (TDD)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/human_console.py`
- Create: `agent/tests/test_human_console.py`

- [ ] **Step 1: Write the failing tests for HumanConsole**

```python
# agent/tests/test_human_console.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry


def test_hub_registry_exposes_human_console(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    assert reg.human_console is not None


def test_start_conversation_returns_thread_id(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(
        target_agents=["backend"],
        text="please scaffold the API",
    )
    assert "thread_id" in convo
    assert convo["participants"] == ["backend"]
    assert convo["first_message_text"] == "please scaffold the API"


def test_send_message_appends_to_existing_thread(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="hi")
    tid = convo["thread_id"]
    reg.human_console.send_message(thread_id=tid, text="follow-up question")
    messages = reg.human_console.list_messages(thread_id=tid)
    assert len(messages) == 2
    assert messages[1]["text"] == "follow-up question"


def test_list_conversations_returns_summaries(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    reg.human_console.start_conversation(target_agents=["backend"], text="A")
    reg.human_console.start_conversation(target_agents=["frontend"], text="B")
    convos = reg.human_console.list_conversations()
    assert len(convos) == 2
    assert {c["last_message_text"] for c in convos} == {"A", "B"}


def test_list_messages_returns_ordered_by_time(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="first")
    reg.hubs.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="ack")
    reg.human_console.send_message(thread_id=convo["thread_id"], text="third")
    messages = reg.human_console.list_messages(thread_id=convo["thread_id"])
    texts = [m["text"] for m in messages]
    assert texts == ["first", "ack", "third"]


def test_mark_resolved_updates_thread_status(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="task")
    reg.human_console.mark_resolved(thread_id=convo["thread_id"])
    resolved = reg.human_console.list_conversations(status="resolved")
    assert len(resolved) == 1
    open_convos = reg.human_console.list_conversations(status="open")
    assert open_convos == []


def test_send_message_to_unknown_thread_raises(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    with pytest.raises(ValueError):
        reg.human_console.send_message(thread_id="nope", text="x")


def test_start_conversation_with_no_agents_raises(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    with pytest.raises(ValueError):
        reg.human_console.start_conversation(target_agents=[], text="x")
```

Note: `reg.hubs` works because `HubRegistry.hubs` returns `self`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_human_console.py -v`

Expected: All FAIL — `AttributeError: HubRegistry has no attribute 'human_console'`.

- [ ] **Step 3: Implement HumanConsole**

Create `agent/env_generator/llm_generator/multi_agent/runtime/human_console.py`:

```python
"""
HumanConsole — user-facing API for human-agent conversations.

Composes EventHub conversation primitives into a chat-like surface for
the UI (Cutover 28) and CLI. A `HubRegistry` exposes `.human_console`
post-construction (see hub_registry.py).
"""

from __future__ import annotations

import time
from typing import List, Optional


class HumanConsole:
    """User-facing wrapper around EventHub human-message helpers."""

    def __init__(self, hubs):
        self._hubs = hubs
        self._eventhub = hubs.eventhub

    def start_conversation(
        self,
        target_agents: List[str],
        text: str,
        from_user: str = "human_user",
    ) -> dict:
        """Begin a new human-agent conversation. Returns a summary dict."""
        event = self._eventhub.publish_human_message(
            text=text,
            target_agents=target_agents,
            from_user=from_user,
        )
        return {
            "thread_id": event["thread_id"],
            "participants": sorted(set(target_agents)),
            "first_message_text": text,
            "first_message_at": event["created_at"],
        }

    def send_message(
        self,
        thread_id: str,
        text: str,
        from_user: str = "human_user",
    ) -> dict:
        """Send another human message into an existing conversation."""
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        # Re-derive target agents from existing thread participants minus the human.
        participants = [a for a in (thread.get("participants") or []) if a != "human_user"]
        if not participants:
            raise ValueError(f"thread {thread_id!r} has no agent participants")
        return self._eventhub.publish_human_message(
            text=text,
            target_agents=participants,
            thread_id=thread_id,
            from_user=from_user,
        )

    def list_conversations(
        self,
        participant: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        return self._eventhub.list_conversations(participant=participant, status=status)

    def list_messages(self, thread_id: str) -> List[dict]:
        """Return chronological message list for a thread.

        Each message: {message_id, source, text, created_at, event_type}.
        """
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        events = self._eventhub._events.value() or {}
        out = []
        for eid in thread.get("event_ids") or []:
            ev = events.get(eid)
            if not ev:
                continue
            payload = ev.get("payload") or {}
            out.append({
                "message_id": eid,
                "source": ev.get("source_hub", ""),
                "text": payload.get("text", ""),
                "created_at": ev.get("created_at", 0.0),
                "event_type": ev.get("event_type", ""),
            })
        out.sort(key=lambda m: m["created_at"])
        return out

    def mark_resolved(self, thread_id: str) -> None:
        """Mark a conversation as resolved (UI can hide it from the active list)."""
        thread = self._eventhub._threads.get(thread_id)
        if not thread:
            raise ValueError(f"thread {thread_id!r} does not exist")
        thread = dict(thread)
        thread["status"] = "resolved"
        thread["updated_at"] = time.time()
        self._eventhub._threads.update(
            lambda m: m.set(thread_id, thread, "human_user"),
            change_info={"agent": "human_user"},
        )
```

- [ ] **Step 4: Wire HumanConsole into HubRegistry**

Modify `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`. Add after the existing `self.runhub.attach_apihub(self.apihub)` line (around line 54):

```python
        from .human_console import HumanConsole
        self.human_console = HumanConsole(self)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_human_console.py -v`

Expected: 8 PASS.

- [ ] **Step 6: Run regressions**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/human_console.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py \
        agent/tests/test_human_console.py
git commit -m "Cutover 27: HumanConsole on HubRegistry (start/send/list/messages/resolve)"
```

---

## Task 5: subscribe_to_human_messages helper (so agents needn't be named recipients)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`
- Create: `agent/tests/test_human_subscription.py`

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_human_subscription.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.eventhub import EventHub


def test_subscribe_to_human_messages_helper_creates_sub(tmp_path):
    eh = EventHub(tmp_path)
    sub = eh.subscribe_to_human_messages(agent="orchestrator")
    assert sub["agent"] == "orchestrator"
    assert sub["source_hub"] == "human_user"
    assert sub["event_type"] == "human_message"
    assert sub["priority_floor"] == "human_user"


def test_subscribed_agent_receives_human_message_even_if_not_targeted(tmp_path):
    """Orchestrator subscribes once and gets all human chatter for awareness."""
    eh = EventHub(tmp_path)
    eh.subscribe_to_human_messages(agent="orchestrator")
    eh.publish_human_message(text="hello backend", target_agents=["backend"])
    inbox = eh.list_inbox("orchestrator", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["payload"]["text"] == "hello backend"


def test_subscribe_helper_is_idempotent(tmp_path):
    eh = EventHub(tmp_path)
    eh.subscribe_to_human_messages(agent="orchestrator")
    eh.subscribe_to_human_messages(agent="orchestrator")
    subs = eh.get_subscriptions(agent="orchestrator")
    # subscribe() uses id = "{agent}:{source}:{type}" so the second call replaces
    assert len(subs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_human_subscription.py -v`

Expected: All FAIL — `AttributeError: subscribe_to_human_messages`.

- [ ] **Step 3: Implement subscribe_to_human_messages**

Append inside the `EventHub` class in `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`, near the other conversation helpers:

```python
    def subscribe_to_human_messages(self, agent: str) -> dict:
        """Convenience: subscribe `agent` to every human_message at the human_user floor.

        Useful for the orchestrator and observability agents that want to see
        all human chatter, not just messages explicitly addressed to them.
        """
        return self.subscribe(
            agent=agent,
            source_hub="human_user",
            event_type="human_message",
            priority_floor="human_user",
            delivery="live",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_human_subscription.py -v`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py \
        agent/tests/test_human_subscription.py
git commit -m "Cutover 27: EventHub.subscribe_to_human_messages helper for awareness subs"
```

---

## Task 6: E2E — human→agent→reply roundtrip + persistence across restart

**Files:**
- Create: `agent/tests/test_human_agent_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# agent/tests/test_human_agent_e2e.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry


def test_e2e_one_human_message_to_one_agent_and_reply(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")

    # 1. Human starts conversation with backend
    convo = reg.human_console.start_conversation(
        target_agents=["backend"],
        text="please add /api/users",
    )
    tid = convo["thread_id"]

    # 2. Backend sees it in its inbox at human_user priority
    inbox = reg.eventhub.list_inbox("backend", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["priority"] == "human_user"
    assert inbox[0]["payload"]["text"] == "please add /api/users"

    # 3. Backend replies into the thread
    reg.eventhub.publish_agent_reply(
        thread_id=tid,
        agent="backend",
        text="endpoint added; tests pass",
    )

    # 4. Human (via list_messages) sees both messages in order
    messages = reg.human_console.list_messages(thread_id=tid)
    assert [m["text"] for m in messages] == ["please add /api/users", "endpoint added; tests pass"]
    assert [m["source"] for m in messages] == ["human_user", "backend"]


def test_e2e_one_human_message_to_multiple_agents(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(
        target_agents=["backend", "frontend", "database"],
        text="add a login page end-to-end",
    )
    tid = convo["thread_id"]
    for agent in ["backend", "frontend", "database"]:
        inbox = reg.eventhub.list_inbox(agent, unread_only=False)
        assert any(item["thread_id"] == tid for item in inbox), f"{agent} missing"


def test_e2e_conversation_persists_across_hub_registry_restart(tmp_path):
    reg1 = HubRegistry(tmp_path, project_name="X")
    convo = reg1.human_console.start_conversation(
        target_agents=["backend"], text="persistent message",
    )
    reg1.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="ack")
    del reg1

    reg2 = HubRegistry(tmp_path)
    convos = reg2.human_console.list_conversations()
    assert len(convos) == 1
    assert convos[0]["message_count"] == 2

    messages = reg2.human_console.list_messages(thread_id=convo["thread_id"])
    assert [m["text"] for m in messages] == ["persistent message", "ack"]


def test_e2e_mark_resolved_hides_from_open_list_but_keeps_history(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="done?")
    reg.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="yes")
    reg.human_console.mark_resolved(thread_id=convo["thread_id"])

    open_convos = reg.human_console.list_conversations(status="open")
    assert open_convos == []
    resolved = reg.human_console.list_conversations(status="resolved")
    assert len(resolved) == 1
    # History still readable
    assert len(reg.human_console.list_messages(thread_id=convo["thread_id"])) == 2


def test_e2e_orchestrator_awareness_via_subscription(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    reg.eventhub.subscribe_to_human_messages(agent="orchestrator")
    reg.human_console.start_conversation(target_agents=["backend"], text="task A")
    reg.human_console.start_conversation(target_agents=["frontend"], text="task B")
    orchestrator_inbox = reg.eventhub.list_inbox("orchestrator", unread_only=False)
    assert len(orchestrator_inbox) == 2
```

- [ ] **Step 2: Run + expect pass (no new code needed)**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_human_agent_e2e.py -v`

Expected: 5 PASS — these test surfaces built in Tasks 2-5.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_human_agent_e2e.py
git commit -m "Cutover 27: e2e human-agent conversation + persistence + multi-agent + awareness"
```

---

## Task 7: __init__ exports + final sweep + migration log + push

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py`
- Modify: `docs/superpowers/migration-logs/27-human-agent-interaction.md`

- [ ] **Step 1: Export HumanConsole**

Read `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` and add (next to the Cutover 26 project exports):

```python
from .human_console import HumanConsole
```

- [ ] **Step 2: Full test sweep**

Run:

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -10
```

Expected:
- Regressions: 7 OK
- Discover: <Cutover-26-baseline> → +~28 (4 priority + 8 EventHub helpers + 3 subscription + 8 HumanConsole + 5 e2e) new

- [ ] **Step 3: Update migration log**

Overwrite `docs/superpowers/migration-logs/27-human-agent-interaction.md`:

```markdown
# Cutover 27: Human-Agent Interaction Backend

**Branch:** `haibotong-cutover-27-human-agent-interaction`
**Date:** 2026-05-26

## What

Backend surface for real users to chat with one or many agents. Adds a
top-tier `human_user` priority on EventHub (rank 4, above `critical`),
three EventHub helpers (`publish_human_message`, `publish_agent_reply`,
`list_conversations`), and a `HumanConsole` wrapper on `HubRegistry`
that the new UI (Cutover 28) and CLIs will call.

## Why

Pre-Cutover 27, the only humans interacting with the system were
developers reading logs. The user asked for a system where they can
"select one or multiple agents and interact with them," with messages
classified as "最高等级的信息" (highest-priority information). The new
`human_user` priority guarantees that any subscribed agent receives
the message regardless of their `priority_floor`, and the conversation
persists on EventHub so it survives orchestrator restarts.

## Commits

- Cutover 27: record pre-flight baseline
- Cutover 27: add human_user priority tier above critical on EventHub
- Cutover 27: EventHub.publish_human_message/agent_reply/list_conversations
- Cutover 27: HumanConsole on HubRegistry (start/send/list/messages/resolve)
- Cutover 27: EventHub.subscribe_to_human_messages helper for awareness subs
- Cutover 27: e2e human-agent conversation + persistence + multi-agent + awareness
- (this commit) Cutover 27: migration log + runtime export

## Test deltas
- Regressions: 7 OK → 7 OK
- Discover: <BASELINE> → <FINAL> OK (+<DELTA> new)

## New surfaces

- `EventHub._PRIORITY_RANK` — added `"human_user": 4` (above `critical`)
- `EventHub.publish_human_message(text, target_agents, thread_id?, from_user?)`
- `EventHub.publish_agent_reply(thread_id, agent, text)`
- `EventHub.list_conversations(participant?, status?)` — summaries with
  `{thread_id, participants, message_count, last_message_at, last_message_text,
   last_message_source, status}`
- `EventHub.subscribe_to_human_messages(agent)` — convenience for orchestrator/observability
- `HubRegistry.human_console: HumanConsole`
- `HumanConsole.start_conversation(target_agents, text, from_user?)`
- `HumanConsole.send_message(thread_id, text, from_user?)`
- `HumanConsole.list_conversations(participant?, status?)`
- `HumanConsole.list_messages(thread_id)` — chronological transcript
- `HumanConsole.mark_resolved(thread_id)`

## Architecture notes

- Conversations are EventHub threads where the first event has
  `source_hub="human_user"` and `event_type="human_message"`. Reusing
  threads keeps the implementation aligned with the existing
  pub/sub/inbox model rather than introducing a parallel data store.
- Replies are routed back to a synthetic `"human_user"` inbox so the UI
  has a single place to read them (no need to subscribe to every agent).
- Agent reply priority is `high`, not `human_user` — a reply isn't a
  fresh top-tier interrupt; the original message was.

## Known limits (future cutovers)

- No agent auto-routing yet: the user must explicitly target agents.
  Future: a router that picks agents based on message intent.
- No attachments / images in messages — text only for now.
- `mark_resolved` is one-way; no reopen.
- Reply audience inheritance is approximate (uses thread.participants);
  if the human adds a NEW agent mid-conversation via send_message, the
  new agent receives the message but past replies aren't backfilled to
  their inbox.
- No rate limiting or auth — assumed trusted operator at this stage.
- LLM agents need to be wired (Cutover 28+) to actually process and
  reply to human messages; the priority-4 inbox delivery happens, but
  individual agent loops may need to be taught to drain it.
```

(Fill in `<BASELINE>`, `<FINAL>`, `<DELTA>` from Step 2's output.)

- [ ] **Step 4: Commit migration log + __init__**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/__init__.py \
        docs/superpowers/migration-logs/27-human-agent-interaction.md
git commit -m "Cutover 27: export HumanConsole + migration log"
```

- [ ] **Step 5: Push branch to Virtue-AI**

```bash
git push -u red-env-gen haibotong-cutover-27-human-agent-interaction 2>&1 | tail -5
```

- [ ] **Step 6: Fast-forward merge into parent + push parent**

```bash
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-27-human-agent-interaction
git merge --ff-only haibotong-cutover-27-human-agent-interaction
git push red-env-gen haibotong-0521-pipeline-web-tools 2>&1 | tail -5
```

---

## Self-Review Notes

**Spec coverage:**
- "弄一个真人和agent system交互的系统" → Task 3-4 (publish_human_message + HumanConsole)
- "user可以选择一个或者多个agent" → Task 3 (target_agents: List[str]) + Task 6 (multi-agent e2e)
- "和他们进行交互" → start_conversation + send_message + publish_agent_reply
- "属于最高等级的信息" → Task 2 (`human_user` rank 4 above `critical`) + Task 5 (subscribe_to_human_messages)

**Out of scope (deferred):**
- UI rendering of conversations — Cutover 28
- Agent-side LLM logic to draft replies — agents already have message-handling loops; this cutover surfaces the API but doesn't rewrite agent runtimes
- Auth, rate limiting, attachments
- Auto-routing to agents based on intent

**Dependency on Cutover 26:**
- Yes — uses `HubRegistry(..., project_name=...)` in tests. If Cutover 26 isn't merged first, fall back to `HubRegistry(tmp_path)` positional-only (functionally equivalent for these tests).
