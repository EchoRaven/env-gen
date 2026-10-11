"""#1203ht — only urgent/high go into the urgent-only queue.

#1203hp established the audit: the only reads of `_priority_queue` are `get_if_urgent`,
which pops `priority <= 1`, and `PrioritizedMessage.from_message` maps URGENT->0, HIGH->1,
NORMAL->2, LOW->3. `get()` has no caller anywhere in the framework. So a NORMAL or LOW copy
put there can never be retrieved -- it occupies one of 100 slots until a later `put` evicts
it.

#1203hp's counter then measured the cost. r179, one run to completion:

    dispatch queue FULL          3310
    of those, an eviction too    2881   (87%)
    evictions across 16 agents   2844   (orchestrator 338, each test-user 180-210)

2844 silent discards per run, every one a copy nothing would ever read. Not putting them in
is behaviour-identical for every consumer -- there is none -- and it retires the drop
instead of counting it.
"""

import asyncio
import inspect
import types

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import messaging as _msg
from env_generator.llm_generator.multi_agent.agents.priority_queue import (
    PriorityMessageQueue,
)
from utils.message import BaseMessage, MessageHeader, MessagePriority


class _Logger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Host(_msg.AgentMessaging):
    """Minimal host for `receive_message`: a real priority queue, an unbounded dispatch
    queue (so #150's drop never fires here) and no hubs."""

    def __init__(self):
        self.agent_id = "t"
        self._logger = _Logger()
        self._priority_queue = PriorityMessageQueue(maxsize=100)
        self._message_queue = asyncio.Queue()
        self._interrupt_messages = []
        self._subscription_inbox = []

    async def _send_delivery_ack(self, message):  # pragma: no cover - not under test
        return None

    async def _maybe_schedule_resident_message_wakeup(self, message, inbox_msg):
        return None


def _msg_with(priority, i=0):
    return BaseMessage(
        header=MessageHeader(message_id=f"m{i}", source_agent_id="src",
                             target_agent_id="t", priority=priority),
        payload=f"p{i}",
        metadata={"msg_type": "note"},
    )


def _receive(host, priority):
    asyncio.run(host.receive_message(_msg_with(priority)))


@pytest.mark.parametrize("priority", [MessagePriority.URGENT, MessagePriority.HIGH])
def test_urgent_and_high_still_enter_the_queue(priority):
    h = _Host()
    _receive(h, priority)
    assert h._priority_queue.qsize() == 1, priority


@pytest.mark.parametrize("priority", [MessagePriority.NORMAL, MessagePriority.LOW])
def test_normal_and_low_no_longer_enter_it(priority):
    """★ Nothing can read them: `get_if_urgent` pops only `priority <= 1` and `get()`
    has no caller. They used to sit in a slot until a later put evicted them."""
    h = _Host()
    _receive(h, priority)
    assert h._priority_queue.qsize() == 0, priority
    assert h._priority_queue.evicted == 0


def test_the_inbox_still_carries_every_priority():
    """★ THE CHANNEL THAT MATTERS MUST NOT CHANGE. #1203hp established the inbox is what
    still carries an ordinary message once #150 drops the dispatch copy."""
    h = _Host()
    for p in (MessagePriority.URGENT, MessagePriority.HIGH,
              MessagePriority.NORMAL, MessagePriority.LOW):
        _receive(h, p)
    assert len(h._subscription_inbox) == 4, h._subscription_inbox


def test_the_dispatch_copy_is_still_enqueued_for_every_priority():
    h = _Host()
    for p in (MessagePriority.URGENT, MessagePriority.HIGH,
              MessagePriority.NORMAL, MessagePriority.LOW):
        _receive(h, p)
    assert h._message_queue.qsize() == 4, h._message_queue.qsize()


def test_a_hundred_ordinary_messages_evict_nothing_now():
    """The r179 number was 2844 evictions in one run; ordinary traffic must produce none."""
    h = _Host()
    for i in range(250):
        asyncio.run(h.receive_message(_msg_with(MessagePriority.NORMAL, i)))
    assert h._priority_queue.evicted == 0, h._priority_queue.evicted
    assert h._priority_queue.qsize() == 0


def test_an_urgent_message_still_comes_back_out():
    h = _Host()
    _receive(h, MessagePriority.NORMAL)
    _receive(h, MessagePriority.URGENT)
    got = asyncio.run(h._priority_queue.get_if_urgent())
    assert got is not None, "the urgent copy must still be retrievable"


def test_the_guard_names_the_two_priorities_the_reader_accepts():
    """Structural: a hardcoded truth value or a different pair would pass the cases above
    on these fixtures. Pin the guard to the priorities `get_if_urgent` actually pops."""
    src = inspect.getsource(_msg.AgentMessaging.receive_message)
    i = src.index("self._priority_queue.put")
    guard = src[src.rindex("if ", 0, i):i]
    assert "MessagePriority.URGENT" in guard, guard
    assert "MessagePriority.HIGH" in guard, guard
    assert "NORMAL" not in guard and "LOW" not in guard, guard
