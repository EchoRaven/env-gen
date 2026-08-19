"""#976: do not send a delivery receipt to a hub.

82 warnings per run of `MessageBus: Target agent not found: messagebus`, deferred four times
as unlocalizable (item 365 records the mechanisms ruled out). The chain:

    communication_tools     publish_event(source_hub="messagebus", ...)
    eventhub/bridge.py:87   MessageHeader(source_agent_id=event["source_hub"], ...)
    messaging._send_delivery_ack   sender = header.source_agent_id  -> "messagebus"
                                   ack target = sender              -> not an agent
    communication.py:175    [W] Target agent not found: messagebus

A bridged EVENT has no agent sender; the bridge puts the HUB there. Acking it addresses
something that was never registered on the bus.

Nothing was ever lost — the ack is a courtesy receipt and the message it acknowledges had
already reached a real target — which is exactly why this survived four passes: the warning
reads like failed delivery and measuring the actual traffic said otherwise every time. What
finally named it was the SEQUENCE, not the code: the warning always fired immediately after
a `send_message` whose own target had resolved fine.
"""

import asyncio

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.messaging import AgentMessaging
from utils.message import BaseMessage, MessageHeader, MessagePriority


class _Bus:
    def __init__(self, agents):
        self._agents = list(agents)
        self.sent = []

    def list_agents(self):
        return list(self._agents)

    async def publish(self, message):
        self.sent.append(message.header.target_agent_id)
        return True


class _Lane(AgentMessaging):
    def __init__(self, bus):
        self.agent_id = "backend"
        self._external_bus = bus

        import logging
        self._logger = logging.getLogger("test.ack976")


def _incoming(source):
    return BaseMessage(
        header=MessageHeader(source_agent_id=source, target_agent_id="backend",
                             priority=MessagePriority.NORMAL),
        payload="hi", metadata={"msg_type": "info"})


def _ack(bus, source):
    lane = _Lane(bus)
    asyncio.run(lane._send_delivery_ack(_incoming(source)))
    return bus.sent


def test_a_hub_sender_gets_no_receipt():
    """The bridge stamps the source_hub as the sender; hubs are not on the bus."""
    assert _ack(_Bus(["backend", "frontend", "orchestrator"]), "messagebus") == []


@pytest.mark.parametrize("hub", ["workhub", "eventhub", "registryhub"])
def test_no_hub_gets_a_receipt(hub):
    """messagebus is the one that showed up in the logs; every hub has the same shape."""
    assert _ack(_Bus(["backend", "orchestrator"]), hub) == []


def test_a_real_agent_still_gets_its_receipt():
    """The regression that would matter — acks between agents must be untouched."""
    assert _ack(_Bus(["backend", "orchestrator"]), "orchestrator") == ["orchestrator"]


def test_an_unknowable_roster_still_acks():
    """If the bus cannot enumerate its agents, fall back to sending. Suppressing a real ack
    would be a worse failure than the warning this fixes."""
    class _Opaque(_Bus):
        def list_agents(self):
            raise RuntimeError("no roster")

    assert _ack(_Opaque([]), "orchestrator") == ["orchestrator"]


def test_the_control_acks_the_hub():
    """Planted control: the PRE-FIX rule — ack whoever the header names — sends to the hub.
    Synthetic, so fixing the real path can never turn this red."""
    sender = "messagebus"
    roster = ["backend", "orchestrator"]
    pre_fix_target = sender if sender and sender != "backend" else None
    assert pre_fix_target == "messagebus" and pre_fix_target not in roster, (
        "the control was supposed to address a non-agent; if it does not, the assertions "
        "above prove nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
