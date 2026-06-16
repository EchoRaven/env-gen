# Human Chat Mini-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn agent↔human chat into a first-class signal: agent can use tools while replying, the conversation persists as durable context with auto-compression, the next step sees the human's directive, and the user watches tool calls happen live in the chat panel.

**Architecture:** Keep canonical message storage in EventHub (already exists). Add a thread-summary field that the agent reads every step ("Active human directives" block injected into system prompt). Rewrite `_handle_human_message` as a bounded mini-loop with full tool access (max_steps=5). Emit `agent_chat_step` events as each tool runs; UI renders them inline below the typing dots until the final `agent_reply` arrives.

**Tech Stack:** Python EventHub on JsonStore, agent runtime via `run_agentic_loop`, live_monitor_server SSE, React chat_panel.jsx.

**Non-goals (this plan):** Tool whitelisting/safety gating (deferred); per-thread auth (deferred); multi-thread directive injection (only the most recent thread).

---

## Decisions locked in

| Decision | Value |
|---|---|
| Mini-loop step budget | `max_steps=5` |
| Tool surface in chat | Full — same as the agent's normal step tools |
| Directive injection scope | Latest 1 thread: `thread.summary` + last 3 raw turns |
| Compression trigger | `> 4000` tokens of raw transcript OR `> 50` events, whichever first |
| Compression keeps | Last 10 turns verbatim; older bundled into bullet summary |
| Storage | Canonical = EventHub threads/events (no new table); thread gains `summary`, `summary_until_ts`, `summary_updated_at` fields |

## File Structure

**Create:**
- `multi_agent/agents/runtime/human_chat.py` — directive block builder, transcript-to-prompt formatter, compressor invocation glue. Single responsibility: shape data for the LLM.
- `tests/multi_agent/test_human_chat_mini_loop.py` — exercises `_handle_human_message` end-to-end with mocked LLM that calls tools.
- `tests/multi_agent/test_human_chat_directive_injection.py` — verifies the injected block appears in the step system prompt.
- `tests/multi_agent/test_human_chat_compression.py` — verifies summary gets written when threshold crossed.

**Modify:**
- `multi_agent/runtime/eventhub.py` — add `get_thread_transcript`, `update_thread_summary`, `estimate_thread_tokens` helpers.
- `multi_agent/agents/base.py:450-501` — replace `_handle_human_message` body with mini-loop.
- `multi_agent/agents/base.py:_get_system_prompt` (or step-pipeline preamble) — call `human_chat.build_directive_block()` and append to system prompt.
- `multi_agent/agents/runtime/step_pipeline/action.py` — when running in `chat_mode`, after each successful tool dispatch publish an `agent_chat_step` event.
- `live_monitor_server.py` — pass-through forwarder for `agent_chat_step` events on the chat SSE channel (existing event bridge usually covers this — verify and patch if not).
- `live_monitor/src/chat_panel.jsx` — accumulate `agent_chat_step` per-thread under each agent's pending typing indicator; render compact step list; clear on `agent_reply`.

---

### Task 1: EventHub transcript + summary fields

**Files:**
- Modify: `multi_agent/runtime/eventhub.py` (after `get_thread`, ~line 466)
- Test: `tests/multi_agent/test_eventhub_transcript.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/multi_agent/test_eventhub_transcript.py
import tempfile
from pathlib import Path
from multi_agent.runtime.eventhub import EventHub

def make_hub():
    d = Path(tempfile.mkdtemp())
    hub = EventHub(d)
    hub.ensure_documents()
    return hub

def test_get_thread_transcript_shapes_events_for_llm():
    hub = make_hub()
    ev = hub.publish_human_message(text="Hi", target_agents=["design"])
    tid = ev["thread_id"]
    hub.publish_agent_reply(thread_id=tid, agent="design", text="On it.")
    transcript = hub.get_thread_transcript(tid)
    assert transcript == [
        {"role": "user", "speaker": "human_user", "text": "Hi", "ts": transcript[0]["ts"]},
        {"role": "assistant", "speaker": "design", "text": "On it.", "ts": transcript[1]["ts"]},
    ]

def test_update_thread_summary_persists_fields():
    hub = make_hub()
    ev = hub.publish_human_message(text="x", target_agents=["design"])
    tid = ev["thread_id"]
    hub.update_thread_summary(tid, summary="user wants X done", summary_until_ts=ev["created_at"])
    thread = hub._threads.get(tid)
    assert thread["summary"] == "user wants X done"
    assert thread["summary_until_ts"] == ev["created_at"]
    assert thread["summary_updated_at"] > 0

def test_estimate_thread_tokens_grows_with_text():
    hub = make_hub()
    ev = hub.publish_human_message(text="short", target_agents=["design"])
    tid = ev["thread_id"]
    small = hub.estimate_thread_tokens(tid)
    hub.publish_agent_reply(thread_id=tid, agent="design", text="x " * 500)
    big = hub.estimate_thread_tokens(tid)
    assert big > small * 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/common/haibotong/env-gen/agent/env_generator/llm_generator && python -m pytest tests/multi_agent/test_eventhub_transcript.py -v`
Expected: FAIL — `EventHub` has no `get_thread_transcript`/`update_thread_summary`/`estimate_thread_tokens`.

- [ ] **Step 3: Implement the three EventHub methods**

Add after `get_thread` (~line 466) in `multi_agent/runtime/eventhub.py`:

```python
def get_thread_transcript(self, thread_id: str) -> List[dict]:
    """Return thread events shaped for LLM consumption.

    Each entry is ``{role, speaker, text, ts}`` where ``role`` is
    ``"user"`` for ``human_message`` events and ``"assistant"`` for
    ``agent_reply`` events. Other event types are skipped — this is the
    surface designed for prompt injection, not a generic event log.
    """
    transcript: List[dict] = []
    for ev in self.get_thread(thread_id):
        etype = ev.get("event_type")
        payload = ev.get("payload") or {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue
        if etype == "human_message":
            transcript.append({
                "role": "user",
                "speaker": payload.get("from_user", "human_user"),
                "text": text,
                "ts": ev.get("created_at", 0),
            })
        elif etype == "agent_reply":
            transcript.append({
                "role": "assistant",
                "speaker": payload.get("reply_from") or ev.get("source_hub", "?"),
                "text": text,
                "ts": ev.get("created_at", 0),
            })
    return transcript

def update_thread_summary(
    self,
    thread_id: str,
    summary: str,
    summary_until_ts: float,
) -> dict:
    """Persist a rolling summary onto the thread document.

    ``summary_until_ts`` marks the cutoff: events with ``created_at <=
    summary_until_ts`` are considered captured by the summary; only
    events newer than this need to be replayed verbatim or re-summarized
    later.
    """
    import time
    thread = self._threads.get(thread_id)
    if not thread:
        raise ValueError(f"thread {thread_id!r} does not exist")
    updated = dict(thread)
    updated["summary"] = summary
    updated["summary_until_ts"] = float(summary_until_ts)
    updated["summary_updated_at"] = time.time()
    self._threads.upsert(thread_id, updated)
    return updated

def estimate_thread_tokens(self, thread_id: str) -> int:
    """Rough token estimate for a thread's transcript (~4 chars/token).

    Used to decide when to trigger compression. Intentionally cheap —
    a real tokenizer is overkill for a threshold check.
    """
    transcript = self.get_thread_transcript(thread_id)
    chars = sum(len(entry.get("text", "")) for entry in transcript)
    return max(1, chars // 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_eventhub_transcript.py -v`
Expected: PASS — all 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/runtime/eventhub.py tests/multi_agent/test_eventhub_transcript.py
git commit -m "eventhub: add transcript reader + thread summary fields

- get_thread_transcript(): shaped {role, speaker, text, ts} entries for LLM
- update_thread_summary(): persists summary + summary_until_ts + summary_updated_at
- estimate_thread_tokens(): cheap chars/4 estimator for compression trigger
"
```

---

### Task 2: human_chat module — directive block + transcript formatter

**Files:**
- Create: `multi_agent/agents/runtime/human_chat.py`
- Test: `tests/multi_agent/test_human_chat_module.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/multi_agent/test_human_chat_module.py
from multi_agent.agents.runtime import human_chat

def test_build_directive_block_returns_empty_when_no_threads():
    block = human_chat.build_directive_block(
        threads=[],
        transcripts={},
        max_raw_turns=3,
    )
    assert block == ""

def test_build_directive_block_uses_summary_plus_last_n_turns():
    threads = [{
        "thread_id": "t1",
        "summary": "user wants X done by Friday",
        "summary_updated_at": 100.0,
        "last_message_at": 200.0,
    }]
    transcripts = {
        "t1": [
            {"role": "user", "speaker": "human_user", "text": "old 1", "ts": 50},
            {"role": "assistant", "speaker": "design", "text": "old 2", "ts": 60},
            {"role": "user", "speaker": "human_user", "text": "recent A", "ts": 180},
            {"role": "assistant", "speaker": "design", "text": "recent B", "ts": 190},
            {"role": "user", "speaker": "human_user", "text": "recent C", "ts": 200},
        ],
    }
    block = human_chat.build_directive_block(threads, transcripts, max_raw_turns=3)
    assert "Active human directives" in block
    assert "user wants X done by Friday" in block
    assert "recent A" in block and "recent B" in block and "recent C" in block
    assert "old 1" not in block

def test_format_transcript_for_compression_orders_chronologically():
    entries = [
        {"role": "user", "speaker": "human_user", "text": "two", "ts": 200},
        {"role": "assistant", "speaker": "design", "text": "one-reply", "ts": 150},
        {"role": "user", "speaker": "human_user", "text": "one", "ts": 100},
    ]
    text = human_chat.format_transcript_for_compression(entries)
    assert text.index("one") < text.index("one-reply") < text.index("two")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/multi_agent/test_human_chat_module.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the module**

```python
# multi_agent/agents/runtime/human_chat.py
"""Human-chat support for agents.

Two responsibilities:

1. ``build_directive_block`` — produce the "Active human directives"
   block injected into the agent's system prompt every step, so the
   agent always knows what the human last said.
2. ``format_transcript_for_compression`` — flatten transcript entries
   into the plain text passed to the compressor LLM.

Storage stays in EventHub (canonical). This module only shapes data.
"""

from __future__ import annotations
from typing import Iterable, List, Mapping, Sequence


def build_directive_block(
    threads: Sequence[dict],
    transcripts: Mapping[str, List[dict]],
    max_raw_turns: int = 3,
) -> str:
    """Render the Active-human-directives block for system prompt injection.

    ``threads`` should already be filtered to the threads the agent
    cares about (typically the single most-recently-active one — the
    caller decides). ``transcripts[tid]`` should be ``get_thread_transcript``
    output. Returns empty string when there's nothing to inject so the
    caller can splice unconditionally.
    """
    if not threads:
        return ""

    lines: List[str] = ["=== Active human directives ==="]
    for thread in threads:
        tid = thread.get("thread_id")
        summary = (thread.get("summary") or "").strip()
        if summary:
            lines.append(f"[thread {tid}] Summary: {summary}")
        recent = (transcripts.get(tid) or [])[-max_raw_turns:]
        if recent:
            lines.append("Recent turns:")
            for entry in recent:
                speaker = entry.get("speaker", "?")
                text = (entry.get("text") or "").strip().replace("\n", " ")
                if len(text) > 280:
                    text = text[:277] + "…"
                lines.append(f"  - [{speaker}] {text}")
    lines.append("")  # trailing blank
    return "\n".join(lines)


def format_transcript_for_compression(entries: Iterable[dict]) -> str:
    """Flatten transcript entries into the text fed to the summarizer."""
    ordered = sorted(entries, key=lambda e: e.get("ts", 0))
    parts: List[str] = []
    for entry in ordered:
        speaker = entry.get("speaker", "?")
        text = (entry.get("text") or "").strip()
        parts.append(f"[{speaker}]: {text}")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_human_chat_module.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/agents/runtime/human_chat.py tests/multi_agent/test_human_chat_module.py
git commit -m "human_chat: directive block builder + transcript formatter"
```

---

### Task 3: Inject directive block into agent system prompt each step

**Files:**
- Modify: `multi_agent/agents/base.py` — locate `_get_system_prompt`; append directive block
- Test: `tests/multi_agent/test_human_chat_directive_injection.py`

- [ ] **Step 1: Locate the system-prompt entry point**

Run: `grep -n "_get_system_prompt\b" multi_agent/agents/base.py`
Expected: shows the method definition and call sites.

- [ ] **Step 2: Write the failing test**

```python
# tests/multi_agent/test_human_chat_directive_injection.py
from unittest.mock import MagicMock
from multi_agent.agents.base import BaseAgent  # adjust import to actual class

def test_directive_block_appended_when_human_thread_exists(make_agent):
    """make_agent fixture: returns an agent with fake hubs and one human_message
    already in eventhub addressed to this agent."""
    agent = make_agent("design")
    # publish a human message to design
    ev = agent._hubs.eventhub.publish_human_message(
        text="please continue working", target_agents=["design"]
    )
    sys_prompt = agent._get_system_prompt()
    assert "Active human directives" in sys_prompt
    assert "please continue working" in sys_prompt

def test_directive_block_absent_when_no_recent_thread(make_agent):
    agent = make_agent("design")
    sys_prompt = agent._get_system_prompt()
    assert "Active human directives" not in sys_prompt
```

The `make_agent` fixture goes in `tests/multi_agent/conftest.py` and constructs a minimal agent — copy the pattern from the nearest existing test that builds a BaseAgent. (If you can't find one, build a thin Fake that subclasses BaseAgent with stub `_get_system_prompt` super(); inject a real EventHub on a tmpdir.)

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/multi_agent/test_human_chat_directive_injection.py -v`
Expected: FAIL — directive block not appearing in system prompt.

- [ ] **Step 4: Implement injection in `_get_system_prompt`**

In `multi_agent/agents/base.py`, at the end of `_get_system_prompt` (right before the final return), splice in:

```python
# Active human directives — keep the agent aware of in-flight chat
# instructions. Sourced fresh from EventHub every step so a new
# human_message becomes visible on the next decision tick.
try:
    if self._hubs is not None and hasattr(self._hubs, "eventhub"):
        eh = self._hubs.eventhub
        # Latest thread this agent participates in (descending by last_message_at).
        convs = [
            c for c in eh.list_conversations(participant=self.agent_id)
            if c.get("thread_id")
        ]
        convs.sort(key=lambda c: c.get("last_message_at", 0), reverse=True)
        latest = convs[:1]
        transcripts = {
            c["thread_id"]: eh.get_thread_transcript(c["thread_id"])
            for c in latest
        }
        from multi_agent.agents.runtime.human_chat import build_directive_block
        block = build_directive_block(latest, transcripts, max_raw_turns=3)
        if block:
            prompt = f"{prompt}\n\n{block}"
except Exception as _inj_err:
    # Never fail prompt assembly because of chat injection.
    self._logger.debug(f"[{self.agent_id}] directive injection skipped: {_inj_err}")
```

(Replace `prompt` with whatever the local variable name is — Read the method first so the splice uses the right name.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_human_chat_directive_injection.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add multi_agent/agents/base.py tests/multi_agent/test_human_chat_directive_injection.py tests/multi_agent/conftest.py
git commit -m "base: inject Active human directives into system prompt each step"
```

---

### Task 4: Rewrite `_handle_human_message` as bounded mini-loop with tools

**Files:**
- Modify: `multi_agent/agents/base.py:450-501` (the current `_handle_human_message`)
- Test: `tests/multi_agent/test_human_chat_mini_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/multi_agent/test_human_chat_mini_loop.py
import asyncio
from unittest.mock import patch, AsyncMock
from multi_agent.runtime.message import BaseMessage, MessageHeader  # adjust

def test_mini_loop_calls_tools_then_publishes_reply(make_agent):
    agent = make_agent("design")
    # Stage a human_message thread
    ev = agent._hubs.eventhub.publish_human_message(
        text="please claim the next task and start", target_agents=["design"]
    )
    tid = ev["thread_id"]

    # Stub the agentic loop to record max_steps + call a fake tool + emit a reply.
    seen = {}
    async def fake_loop(system_prompt, initial_prompt, max_steps):
        seen["system_prompt"] = system_prompt
        seen["initial_prompt"] = initial_prompt
        seen["max_steps"] = max_steps
        agent._hubs.eventhub.publish_agent_reply(
            thread_id=tid, agent="design", text="Claimed T-3; on it."
        )
        return {"ok": True}

    msg = BaseMessage(
        header=MessageHeader(message_id="m1", source_agent_id="human_user",
                             target_agent_id="design", priority="urgent"),
        message_type="HUMAN_MESSAGE",
        payload={"text": "please claim the next task and start"},
        metadata={"thread_id": tid},
    )
    with patch.object(agent, "run_agentic_loop", new=fake_loop):
        asyncio.run(agent._handle_human_message(msg))

    assert seen["max_steps"] == 5
    assert "please claim the next task and start" in seen["initial_prompt"]
    # The bounded loop must NOT forbid tools
    assert "Do not call any tools" not in seen["system_prompt"]
    # A reply event reached EventHub
    transcript = agent._hubs.eventhub.get_thread_transcript(tid)
    assert any(e["role"] == "assistant" and "Claimed" in e["text"] for e in transcript)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/multi_agent/test_human_chat_mini_loop.py -v`
Expected: FAIL — current handler uses `_generate_text` (no loop) and the "Do not call any tools" string is in the system prompt.

- [ ] **Step 3: Replace `_handle_human_message` body**

```python
async def _handle_human_message(self, message) -> None:
    """A real human sent us a message. Run a bounded agentic mini-loop
    so we can actually act on it (call tools), then publish a reply.

    Budget: ``max_steps=5``. Tool surface = the agent's normal step
    pipeline. The reply is published by the agent's own `send_message`
    call OR — if it forgets — by a fallback after the loop returns.
    """
    metadata = getattr(message, "metadata", {}) or {}
    thread_id = (
        metadata.get("thread_id")
        or getattr(message.header, "correlation_id", "")
    )
    if not thread_id:
        self._logger.warning(
            f"[{self.agent_id}] human_message missing thread_id; skipping"
        )
        return

    payload = getattr(message, "payload", {}) or {}
    user_text = (payload.get("text") if isinstance(payload, dict) else "") or ""
    if not user_text.strip():
        self._logger.warning(
            f"[{self.agent_id}] human_message with empty text; skipping"
        )
        return

    base_system = self._get_system_prompt()
    chat_system = (
        f"{base_system}\n\n"
        "=== Direct human message ===\n"
        "A real human user has just sent you a direct message in chat. "
        "You may use any of your tools to act on what they asked. "
        "Be efficient — you have a small step budget. When you've done "
        "what you can, finish by calling `publish_agent_reply` (via "
        "the chat reply tool) OR by emitting a final short message "
        "describing what you did. Do NOT spin on tools indefinitely."
    )
    initial_prompt = (
        f"## Direct message from human user\n\n"
        f"Thread: `{thread_id}`\n\n"
        f"> {user_text}\n\n"
        f"Decide what to do: (a) take immediate action with tools if "
        f"asked, (b) reply with information, or (c) both. Keep the "
        f"final reply concise."
    )

    # Mark chat-mode so the action pipeline emits agent_chat_step events.
    prev_chat_thread = getattr(self, "_chat_mode_thread_id", None)
    self._chat_mode_thread_id = thread_id
    try:
        await self.run_agentic_loop(
            system_prompt=chat_system,
            initial_prompt=initial_prompt,
            max_steps=5,
        )
    except Exception as e:
        self._logger.warning(
            f"[{self.agent_id}] mini-loop failed: {e}"
        )
        # Best-effort fallback reply so the user isn't left hanging.
        try:
            self._hubs.eventhub.publish_agent_reply(
                thread_id=thread_id,
                agent=self.agent_id,
                text=f"(I hit an error handling your message: {e})",
            )
        except Exception:
            pass
    finally:
        self._chat_mode_thread_id = prev_chat_thread

    # If the loop ended without ever publishing a reply, drop a stub so
    # the UI doesn't show "thinking…" forever.
    transcript = self._hubs.eventhub.get_thread_transcript(thread_id)
    already_replied = any(
        e["role"] == "assistant"
        and e["speaker"] == self.agent_id
        and e["ts"] >= message_ts(message)
        for e in transcript
    )
    if not already_replied:
        try:
            self._hubs.eventhub.publish_agent_reply(
                thread_id=thread_id,
                agent=self.agent_id,
                text="(Mini-loop completed without an explicit reply.)",
            )
        except Exception as e:
            self._logger.warning(
                f"[{self.agent_id}] fallback reply failed: {e}"
            )


def message_ts(message) -> float:
    """Best-effort wall-clock for the incoming message. Used to detect
    whether a reply published during the mini-loop is 'new enough' to
    count as the response to this specific message."""
    meta = getattr(message, "metadata", {}) or {}
    ts = meta.get("received_at") or meta.get("created_at")
    if ts:
        return float(ts)
    import time
    return time.time()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_human_chat_mini_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-run the existing human-message tests**

Run: `python -m pytest tests/multi_agent/ -k "human" -v`
Expected: previously passing human-message tests still pass (or are updated alongside this change if the contract changed).

- [ ] **Step 6: Commit**

```bash
git add multi_agent/agents/base.py tests/multi_agent/test_human_chat_mini_loop.py
git commit -m "base: rewrite _handle_human_message as bounded mini-loop with tools

Was: single _generate_text call with 'Do not call any tools' in the
system prompt. Could only reply, never act.

Now: run_agentic_loop(max_steps=5) with the agent's normal tool
surface. Sets self._chat_mode_thread_id so the action pipeline can
emit agent_chat_step events while the loop runs. Falls back to a
stub reply if the loop exits without one so the UI doesn't hang."
```

---

### Task 5: Emit `agent_chat_step` events from action pipeline

**Files:**
- Modify: `multi_agent/agents/runtime/step_pipeline/action.py` — at the tool-call result loop, when `self._chat_mode_thread_id` is set, publish an event per tool.
- Test: `tests/multi_agent/test_human_chat_step_events.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_mode_emits_agent_chat_step_per_tool(make_agent):
    agent = make_agent("design")
    ev = agent._hubs.eventhub.publish_human_message(
        text="ls and reply", target_agents=["design"]
    )
    tid = ev["thread_id"]
    agent._chat_mode_thread_id = tid

    # Fabricate tool_calls and run through the pipeline path that emits.
    fake_calls = [
        FakeToolCall(name="codehub_list_branches", args={"repo": "design"}),
    ]
    fake_result = "branches: main, feature/x"
    publish_chat_step_call = (...)  # invoke the pipeline helper directly

    # Assert
    steps = [
        e for e in agent._hubs.eventhub.get_thread(tid)
        if e.get("event_type") == "agent_chat_step"
    ]
    assert len(steps) == 1
    p = steps[0]["payload"]
    assert p["tool"] == "codehub_list_branches"
    assert p["status"] in {"done", "ok"}
    assert "main" in p["result_preview"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/multi_agent/test_human_chat_step_events.py -v`
Expected: FAIL — no `agent_chat_step` events exist yet.

- [ ] **Step 3: Add the emit hook**

In `multi_agent/agents/runtime/step_pipeline/action.py`, immediately after each tool result is recorded inside `_process_tool_calls` (locate via `grep -n "_process_tool_calls" multi_agent/agents/`), add:

```python
# Chat-mode visibility: when this step is happening inside the
# human-chat mini-loop, surface each tool call to the chat UI so the
# user sees what we're doing in real time.
chat_thread = getattr(self, "_chat_mode_thread_id", None)
if chat_thread and self._hubs is not None:
    try:
        args_preview = _short_repr(tool_args)
        result_preview = _short_repr(tool_result)
        self._hubs.eventhub.publish_event(
            source_hub=self.agent_id,
            event_type="agent_chat_step",
            payload={
                "agent": self.agent_id,
                "tool": tool_name,
                "args_preview": args_preview,
                "status": "error" if tool_failed else "done",
                "result_preview": result_preview,
            },
            recipients=["human_user"],
            priority="normal",
            thread_id=chat_thread,
        )
    except Exception as _emit_err:
        self._logger.debug(
            f"[{self.agent_id}] agent_chat_step emit failed: {_emit_err}"
        )
```

Add helper at module top:

```python
def _short_repr(value, limit: int = 240) -> str:
    """Compact preview of an arbitrary tool arg/result for chat UI."""
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else __import__("json").dumps(value, default=str)
    except Exception:
        text = str(value)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
```

Use the names that exist in the file (`tool_name`, `tool_args`, `tool_result`, `tool_failed`) — Read the surrounding code first to bind to the actual locals.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_human_chat_step_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/agents/runtime/step_pipeline/action.py tests/multi_agent/test_human_chat_step_events.py
git commit -m "action pipeline: emit agent_chat_step events during chat mini-loop"
```

---

### Task 6: live_monitor_server SSE forwarder for `agent_chat_step`

**Files:**
- Modify: `live_monitor_server.py` — verify the existing event-to-SSE bridge passes `agent_chat_step`; add explicit allowlist if it filters.

- [ ] **Step 1: Inspect the existing SSE event forwarder**

Run: `grep -n "agent_reply\|agent_status\|event_type" live_monitor_server.py | head -30`

Identify whether SSE-publish is allowlisted by event_type or pass-through. Read the relevant function.

- [ ] **Step 2: Patch (if needed)**

If `agent_chat_step` would be filtered, add it to the allowlist. If pass-through, no change.

Expected diff (illustrative):

```python
# In whatever function emits SSE for thread events:
ALLOWED = {"human_message", "agent_reply", "agent_status", "agent_chat_step"}
```

- [ ] **Step 3: Manual smoke test**

Start the live monitor with the in-progress run; trigger a chat message; tail `curl http://localhost:<port>/api/projects/<pid>/events` (or the SSE endpoint) and confirm `agent_chat_step` events appear.

- [ ] **Step 4: Commit**

```bash
git add live_monitor_server.py
git commit -m "live_monitor: pass agent_chat_step events through SSE bridge"
```

---

### Task 7: Render tool-call steps in chat_panel.jsx

**Files:**
- Modify: `live_monitor/src/chat_panel.jsx`
- Modify: `live_monitor/styles/design-tokens.css` (or chat-specific stylesheet)

- [ ] **Step 1: Extend SSE handler**

In the SSE message handler (around the `agent_reply`/`agent_status` switch), add:

```jsx
if (data.event_type === "agent_chat_step") {
  const { agent, tool, args_preview, status, result_preview } = data.payload || {};
  setChatSteps(prev => {
    const tid = data.thread_id;
    const list = prev[tid] || [];
    return { ...prev, [tid]: [...list, { agent, tool, args_preview, status, result_preview, ts: data.created_at || Date.now()/1000 }] };
  });
}
```

Add at top of component:

```jsx
const [chatSteps, setChatSteps] = useState({});  // thread_id -> [{agent, tool, args_preview, status, result_preview, ts}]
```

Clear steps when an `agent_reply` arrives for that thread:

```jsx
if (data.event_type === "agent_reply") {
  setChatSteps(prev => { const n = { ...prev }; delete n[data.thread_id]; return n; });
  // ... existing reply-handling logic
}
```

- [ ] **Step 2: Render the step list under each typing indicator**

In the typing-indicator render block (search for `typingAgents` map), wrap each agent's row to also render its accumulated steps:

```jsx
{Object.entries(typingAgents).map(([aid, info]) => {
  const steps = (chatSteps[activeThread] || []).filter(s => s.agent === aid);
  return (
    <div key={aid} className="typing-row">
      <AgentGlyph agent={aid} />
      <span className="typing-name">{aid}</span>
      <span className="typing-dots"><span className="dot"/><span className="dot"/><span className="dot"/></span>
      {steps.length > 0 && (
        <ul className="chat-steps">
          {steps.map((s, i) => (
            <li key={i} className={`chat-step chat-step--${s.status}`}>
              <code className="chat-step__tool">{s.tool}</code>
              {s.args_preview && <span className="chat-step__args">({s.args_preview})</span>}
              {s.result_preview && <span className="chat-step__result">→ {s.result_preview}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
})}
```

- [ ] **Step 3: Add styles**

In `live_monitor/styles/design-tokens.css` (or wherever chat styles live):

```css
.chat-steps {
  list-style: none;
  margin: 4px 0 0 24px;
  padding: 0;
  border-left: 2px solid var(--border-subtle);
  padding-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.chat-step { margin: 2px 0; line-height: 1.4; }
.chat-step__tool { color: var(--accent); font-family: var(--font-mono); }
.chat-step__args { opacity: 0.7; margin-left: 2px; }
.chat-step__result { display: block; opacity: 0.85; }
.chat-step--error .chat-step__tool { color: var(--danger); }
```

- [ ] **Step 4: Manual smoke test**

With a fresh agent run, send a chat message that requires a tool call ("@design list your current tasks"). Confirm the chat panel shows the typing dots + a live-updating step list, then the final reply replaces the dots.

- [ ] **Step 5: Commit**

```bash
git add live_monitor/src/chat_panel.jsx live_monitor/styles/design-tokens.css
git commit -m "chat_panel: render live tool-call steps inline during mini-loop"
```

---

### Task 8: Transcript compression at threshold

**Files:**
- Modify: `multi_agent/agents/runtime/human_chat.py` (add `compress_thread_if_needed`)
- Modify: `multi_agent/agents/base.py` (call it at the start of `_handle_human_message`, before injecting the directive block)
- Test: `tests/multi_agent/test_human_chat_compression.py`

- [ ] **Step 1: Write the failing test**

```python
def test_compression_runs_when_token_threshold_crossed(make_agent):
    agent = make_agent("design")
    eh = agent._hubs.eventhub
    ev = eh.publish_human_message(text="x" * 16000, target_agents=["design"])
    tid = ev["thread_id"]
    # Fake compressor: replace `_generate_text` to return a canned summary
    async def fake_text(system, user):
        assert "x" * 100 in user  # got the raw transcript
        return "user sent a long lorem ipsum; no actionable directive yet"
    agent._generate_text = fake_text

    from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
    import asyncio
    asyncio.run(compress_thread_if_needed(
        agent=agent, thread_id=tid,
        token_limit=4000, keep_last_n=10,
    ))
    thread = eh._threads.get(tid)
    assert thread["summary"].startswith("user sent a long lorem ipsum")
    assert thread["summary_until_ts"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/multi_agent/test_human_chat_compression.py -v`
Expected: FAIL — function does not exist.

- [ ] **Step 3: Implement**

Append to `multi_agent/agents/runtime/human_chat.py`:

```python
async def compress_thread_if_needed(
    *,
    agent,
    thread_id: str,
    token_limit: int = 4000,
    keep_last_n: int = 10,
) -> bool:
    """Summarize older turns when the thread exceeds the token budget.

    Returns True if a new summary was written, False otherwise. Uses the
    agent's own ``_generate_text`` so the LLM client/config is reused
    without duplication.
    """
    eh = agent._hubs.eventhub
    tokens = eh.estimate_thread_tokens(thread_id)
    if tokens < token_limit:
        return False

    transcript = eh.get_thread_transcript(thread_id)
    if len(transcript) <= keep_last_n:
        # Too few turns to bother splitting — let it grow.
        return False

    older = transcript[:-keep_last_n]
    cutoff_ts = older[-1].get("ts", 0)
    body = format_transcript_for_compression(older)

    system = (
        "You compress chat transcripts between a human user and a "
        "software agent into a single short paragraph: what the user "
        "asked for, what the agent committed to, what remains open. "
        "No greetings, no filler — just the durable facts."
    )
    summary = await agent._generate_text(system=system, user=body)
    summary = (summary or "").strip()
    if not summary:
        return False

    eh.update_thread_summary(
        thread_id=thread_id,
        summary=summary,
        summary_until_ts=cutoff_ts,
    )
    return True
```

Wire it into `_handle_human_message` (add near the top, after thread_id is resolved):

```python
try:
    from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
    await compress_thread_if_needed(agent=self, thread_id=thread_id)
except Exception as _cmp_err:
    self._logger.debug(
        f"[{self.agent_id}] compression skipped: {_cmp_err}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/multi_agent/test_human_chat_compression.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/agents/runtime/human_chat.py multi_agent/agents/base.py tests/multi_agent/test_human_chat_compression.py
git commit -m "human_chat: compress long threads via _generate_text"
```

---

### Task 9: End-to-end smoke test

- [ ] **Step 1: Restart envgen run**

Stop the current `main.py` process. Restart with the same args (facebook-clone) and a fresh `--fresh` to avoid stale state from before.

- [ ] **Step 2: Send a chat message that requires a tool**

In the live monitor: `@design list your current tasks and pick one to start`.

- [ ] **Step 3: Verify**

- Typing dots appear immediately
- Below the typing dots, a step list grows in real time: `workhub_list_tasks(...) → [{...}]`, then `claim_task(task_id=...) → ok`, etc.
- Within a few seconds, a coherent reply appears: "Claimed T-N; starting now."
- Next step of design's normal loop picks up its system prompt with the **Active human directives** block, and starts working on the claimed task.

- [ ] **Step 4: Verify persistence**

Close the chat panel, reopen it. The transcript should still be visible (canonical EventHub data). Send a second message — the directive block should now include both turns.

- [ ] **Step 5: Verify compression**

Send ~50 short messages back and forth (or one big message). Confirm `thread.summary` gets written and `Recent turns:` in the directive block shows only the last 3.

---

## Self-review

**Spec coverage:**
- ✅ Persistent chat record — Task 1 (EventHub already canonical; transcript reader added)
- ✅ Compression when too long — Task 8
- ✅ Agent returns to workflow with directive — Task 3 (system prompt injection)
- ✅ Tools usable in chat — Task 4 (mini-loop with full tool surface)
- ✅ Live tool-call visibility — Tasks 5–7

**Risk register:**
- The mini-loop runs while the agent might also be inside its normal step pipeline. `_handle_human_message` is invoked from the urgent message handler — verify that path doesn't conflict with an in-progress `run_agentic_loop`. If it does, may need to defer or queue. Investigate during Task 4 step 5.
- Tool call surfaces during chat are wide — destructive tools (e.g., `delete_repo`) would also be callable. The user accepted this ("该用就用"). Punt safety gating to a follow-up.
- Cross-process delivery already addressed earlier (`_pickup_undelivered_inbox_events`). Don't regress that path.

**Type consistency check:** `get_thread_transcript` returns entries with keys `{role, speaker, text, ts}`. All downstream code (directive builder, compressor, mini-loop tests) uses these exact keys. ✅

**Naming consistency:** `_chat_mode_thread_id` is the single flag the action pipeline reads. Set in mini-loop, cleared in `finally`. Don't introduce a parallel `_in_chat` boolean.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-human-chat-mini-loop.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute in this session with checkpoints

Which approach?
