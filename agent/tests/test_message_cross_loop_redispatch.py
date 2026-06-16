"""Cross-loop delivery guard in AgentMessaging.receive_message.

A hub event emitted from inside a ``to_thread`` tool worker reaches
``receive_message`` on a DIFFERENT event loop than the one the agent's queues
(asyncio.Lock/Event) are bound to. Without the guard, ``queue.put`` raises
"got Future attached to a different loop" / "bound to a different event loop"
and the message is silently dropped — this flooded orchestrator delivery in the
2026-06-06 smokes (174 errors crashed smoke #2; 30 degraded #3).

The guard redispatches the call onto the agent's ``_home_loop`` thread-safely and
returns, so the queue ops only ever run on the loop they're bound to.
"""

import asyncio
import os
import sys

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))

from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402


def test_cross_loop_call_redispatches_and_never_touches_queue():
    calls = []

    class FakeHomeLoop:
        def call_soon_threadsafe(self, fn):
            calls.append(fn)  # capture; do NOT run (would build the inner coro)

    class ExplodingQueue:
        async def put(self, _m):
            raise AssertionError("queue.put must NOT run on a foreign loop")

    agent = AgentMessaging.__new__(AgentMessaging)
    agent._home_loop = FakeHomeLoop()
    agent._priority_queue = ExplodingQueue()
    agent._message_queue = ExplodingQueue()

    # asyncio.run gives us a running loop that is NOT FakeHomeLoop → cross-loop.
    asyncio.run(agent.receive_message(object()))

    assert len(calls) == 1  # redispatched exactly once onto the home loop


def test_no_home_loop_falls_through_to_original_path():
    """Before run_loop captures the home loop (_home_loop is None), behaviour is
    unchanged — the guard must not swallow the message."""
    reached = {"put": 0}

    class Queue:
        async def put(self, _m):
            reached["put"] += 1

    class Tracker:
        def mark_delivered(self, *a, **k): pass
        def mark_read(self, *a, **k): pass

    import logging

    agent = AgentMessaging.__new__(AgentMessaging)
    agent.agent_id = "t"
    agent._home_loop = None  # not yet captured
    agent._priority_queue = Queue()
    agent._message_queue = Queue()
    agent._logger = logging.getLogger("t")
    agent._message_tracker = Tracker()
    agent._subscription_inbox = []
    agent._interrupt_messages = []

    async def _noop(*a, **k):
        return None

    agent._send_delivery_ack = _noop
    agent._maybe_schedule_resident_message_wakeup = _noop

    class Hdr:
        message_id = "m1"
        source_agent_id = "x"
        priority = __import__(
            "utils.message", fromlist=["MessagePriority"]
        ).MessagePriority.NORMAL

    class Msg:
        header = Hdr()
        message_type = type("MT", (), {"value": "status"})()
        payload = "hi"
        metadata = {"msg_type": "status"}

    asyncio.run(agent.receive_message(Msg()))
    assert reached["put"] == 2  # both queues received it (priority + message)
