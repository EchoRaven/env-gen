"""An agent receiving a human_user message runs the chat mini-loop + publishes reply.

History: this used to test the single-shot ``_generate_text`` path with the
"Do not call any tools" system-prompt ban. That contract was replaced by the
bounded mini-loop (max_steps=5, full tool surface) — see
``test_human_chat_mini_loop.py`` for the broader coverage; this file keeps the
classic happy-path / error-path checks at the ``_handle_human_message`` seam.
"""
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
    reg = HubRegistry(tmp_path, project_id="proj_x", project_name="X", human_user_id="test_user")

    # Seed a thread so publish_agent_reply has somewhere to write
    initial = reg.eventhub.publish_human_message(
        text="please help",
        target_agents=["backend"],
        from_user="test_user",
    )
    tid = initial["thread_id"]

    # Minimal stand-in for an EnvGenAgent — the handler now delegates the
    # actual LLM work to ``_run_chat_mini_loop``, so that's the seam we stub.
    class StubAgent:
        agent_id = "backend"
        _chat_mode_thread_id = None
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _run_chat_mini_loop(self, *, user_text, thread_id, max_steps):
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
    reg = HubRegistry(tmp_path, project_id="proj_y", project_name="Y", human_user_id="test_user")

    class StubAgent:
        agent_id = "backend"
        _chat_mode_thread_id = None
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _run_chat_mini_loop(self, *, user_text, thread_id, max_steps):
            raise AssertionError("mini-loop should not be called when thread_id is missing")

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
    reg = HubRegistry(tmp_path, project_id="proj_z", project_name="Z", human_user_id="test_user")
    initial = reg.eventhub.publish_human_message(text="hi", target_agents=["backend"], from_user="test_user")
    tid = initial["thread_id"]

    class StubAgent:
        agent_id = "backend"
        _chat_mode_thread_id = None
        def __init__(self):
            self._hubs = reg
            self._logger = MagicMock()
        async def _run_chat_mini_loop(self, *, user_text, thread_id, max_steps):
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
