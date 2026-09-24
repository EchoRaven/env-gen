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
    converts it to an URGENT BaseMessage and delivers it to the agent."""
    reg = HubRegistry(
        tmp_path, project_id="proj_e2e", project_name="E2E",
        human_user_id="test_user_e2e",
    )
    bus = FakeMessageBus()

    # Manually attach a bridge (in production this happens in HubRegistry when
    # message_bus is passed at construction)
    bridge = MessageBusBridge(bus, reg.eventhub)
    reg.eventhub.add_bridge(bridge)

    # Register a stand-in agent — the bridge calls agent.receive_message(msg).
    delivered = []

    class StandinAgent:
        agent_id = "backend"

        async def receive_message(self, msg):
            delivered.append(msg)
            return True

    bus.register_agent("backend", StandinAgent())

    # Ensure there's a usable (non-running) event loop for the eventhub's
    # best-effort delivery path. Prior tests in the same pytest session that
    # call asyncio.run leave the thread without a "current" event loop,
    # which would cause eventhub.publish_event's best-effort try/except to
    # silently skip the bridge call.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Publish the human message — bridge.deliver runs synchronously inside
    # publish_event when there is no running event loop.
    reg.human_console.start_conversation(target_agents=["backend"], text="please scaffold the API")

    # Assert: bridge delivered exactly one message to backend at URGENT priority.
    assert len(delivered) == 1, (
        f"Expected exactly 1 delivery to 'backend'; got {len(delivered)}: {delivered}"
    )
    msg = delivered[0]
    assert msg.header.priority == MessagePriority.URGENT, (
        f"Expected URGENT priority; got {msg.header.priority}"
    )
    assert (msg.metadata or {}).get("event_type") == "human_message"
    assert msg.payload.get("text") == "please scaffold the API"
