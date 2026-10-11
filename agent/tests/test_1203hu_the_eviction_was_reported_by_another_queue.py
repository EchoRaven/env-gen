"""#1203hu — an evicted URGENT message reports itself, not via another queue's failure.

#1203ht made `_priority_queue` urgent-only, which turned `PriorityMessageQueue.evicted`
from noise into an alarm: a nonzero value now means an URGENT or HIGH message was thrown
away. r180, the first run on that code, says the alarm does ring -- frontend reached
`evicted=24` -- and also that it is barely audible. The counter's ONLY readout lived in
`_enqueue_for_dispatch`'s `asyncio.QueueFull` handler, i.e. it printed when a DIFFERENT
queue filled up. The two conditions are independent, and on r180:

    agents that received URGENT/HIGH      5  (backend debugger frontend orchestrator
                                              verifier)
    agents that ever hit dispatch-FULL    3  (frontend 259, backend 211, verifier 128)

So the debugger and the orchestrator could discard an URGENT message with nothing
printed -- and even for the three, the line gave a running total without ever saying what
was lost. `put` now returns the evicted message and the caller reports it.

The independence is what the tests below are built around: `_Host._message_queue` is
UNBOUNDED, so `FIX #150` cannot fire, and every assertion about a warning is therefore an
assertion that the urgent heap reported its own loss.
"""

import ast
import asyncio
import inspect
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import messaging as _msg
from env_generator.llm_generator.multi_agent.agents.priority_queue import (
    PriorityMessageQueue,
)
from utils.message import BaseMessage, MessageHeader, MessagePriority


class _Logger:
    def __init__(self):
        self.warnings = []
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass
    def warning(self, m, *a, **k): self.warnings.append(str(m))


class _Host(_msg.AgentMessaging):
    """A real priority queue and an UNBOUNDED dispatch queue, so #150 never fires."""

    def __init__(self, maxsize=100):
        self.agent_id = "t"
        self._logger = _Logger()
        self._priority_queue = PriorityMessageQueue(maxsize=maxsize)
        self._message_queue = asyncio.Queue()
        self._interrupt_messages = []
        self._subscription_inbox = []

    async def _send_delivery_ack(self, message):
        return None

    async def _maybe_schedule_resident_message_wakeup(self, message, inbox_msg):
        return None


def _mk(priority, i=0, msg_type="note", source="src"):
    return BaseMessage(
        header=MessageHeader(message_id=f"m{i}", source_agent_id=source,
                             target_agent_id="t", priority=priority),
        payload=f"p{i}",
        metadata={"msg_type": msg_type},
    )


# --------------------------------------------------------------------------- put


def test_put_returns_nothing_while_there_is_room():
    q = PriorityMessageQueue(maxsize=3)
    returned = [asyncio.run(q.put(_mk(MessagePriority.HIGH, i))) for i in range(3)]
    assert returned == [None, None, None], returned
    assert q.evicted == 0


def test_put_hands_back_what_it_threw_away():
    q = PriorityMessageQueue(maxsize=2)
    asyncio.run(q.put(_mk(MessagePriority.HIGH, 1)))
    asyncio.run(q.put(_mk(MessagePriority.HIGH, 2)))
    thrown = asyncio.run(q.put(_mk(MessagePriority.URGENT, 3)))
    assert thrown is not None, "put evicted (evicted=%d) but reported nothing" % q.evicted
    assert q.evicted == 1
    # the heap is the authority on what is gone: the returned message must NOT be there.
    held = {m.message.header.message_id for m in q._heap}
    assert thrown.header.message_id not in held, (thrown.header.message_id, held)


def test_the_message_handed_back_is_the_least_urgent_one():
    """The eviction must not cost an URGENT when a HIGH is available to lose."""
    q = PriorityMessageQueue(maxsize=3)
    asyncio.run(q.put(_mk(MessagePriority.URGENT, 1)))
    asyncio.run(q.put(_mk(MessagePriority.HIGH, 2)))
    asyncio.run(q.put(_mk(MessagePriority.URGENT, 3)))
    thrown = asyncio.run(q.put(_mk(MessagePriority.URGENT, 4)))
    assert thrown.header.priority is MessagePriority.HIGH, thrown.header.priority
    assert thrown.header.message_id == "m2", thrown.header.message_id


# ------------------------------------------------------- the report, independently


def _warn_on_eviction(msg_type="note", lost_type="note", lost_from="src"):
    """Fill the heap, then deliver one more, with #150 unable to fire."""
    host = _Host(maxsize=2)
    asyncio.run(host.receive_message(_mk(MessagePriority.HIGH, 1, lost_type, lost_from)))
    asyncio.run(host.receive_message(_mk(MessagePriority.HIGH, 2, lost_type, lost_from)))
    before = list(host._logger.warnings)
    asyncio.run(host.receive_message(_mk(MessagePriority.URGENT, 3, msg_type)))
    new = host._logger.warnings[len(before):]
    return host, new


def test_the_eviction_warns_without_the_dispatch_queue_ever_filling():
    host, new = _warn_on_eviction()
    # the premise of this whole file: #150 could not have spoken.
    assert host._message_queue.maxsize == 0, "dispatch queue must be unbounded here"
    assert host._priority_queue.evicted == 1
    assert len(new) == 1, "expected exactly one warning, got %r" % (new,)


def test_the_warning_names_what_was_lost_and_who_sent_it():
    _, new = _warn_on_eviction(lost_type="bug_found", lost_from="orchestrator")
    line = new[0]
    assert "bug_found" in line, line
    assert "orchestrator" in line, line
    assert "HIGH" in line, line


def test_the_warning_names_the_arriving_message_too():
    """Without it the line cannot be told from the one before it."""
    _, new = _warn_on_eviction(msg_type="run_failed")
    assert "run_failed" in new[0], new[0]


def test_a_lost_interrupt_type_and_a_lost_ordinary_one_do_not_read_the_same():
    """`_interrupt_messages` holds a copy for exactly three types; for anything else the
    eviction leaves nothing urgent, and the line has to say which case it is."""
    _, held = _warn_on_eviction(lost_type="task_ready")
    _, gone = _warn_on_eviction(lost_type="bug_found")
    assert held[0] != gone[0]
    assert "interrupt" in held[0], held[0]
    assert "check_inbox" in gone[0], gone[0]
    assert "check_inbox" not in held[0], held[0]


def test_no_warning_when_nothing_was_evicted():
    host = _Host(maxsize=2)
    asyncio.run(host.receive_message(_mk(MessagePriority.HIGH, 1)))
    assert host._logger.warnings == [], host._logger.warnings
    assert host._priority_queue.evicted == 0


def test_an_undescribable_message_still_gets_reported():
    """The describe is best-effort; losing the description must not lose the warning."""
    host = _Host(maxsize=1)
    asyncio.run(host.receive_message(_mk(MessagePriority.HIGH, 1)))
    broken = _mk(MessagePriority.URGENT, 2)
    held = host._priority_queue._heap[0].message
    held.metadata = None
    object.__setattr__(held.header, "priority", "not-an-enum")
    asyncio.run(host.receive_message(broken))
    assert host._priority_queue.evicted == 1
    assert len(host._logger.warnings) == 1, host._logger.warnings


# ------------------------------------------------------------------- structural


def _receive_source():
    return inspect.getsource(_msg.AgentMessaging.receive_message)


def test_the_report_is_reached_from_the_put_not_from_an_exception_handler():
    """The defect was that the only readout sat in another queue's failure path. Pin the
    call to the value `put` returned, in ordinary control flow."""
    tree = ast.parse(textwrap.dedent(_receive_source()))
    fn = tree.body[0]

    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_log_evicted_urgent_1203hu"]
    assert len(calls) == 1, "expected one report call, found %d" % len(calls)

    inside_handler = [n for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
                      for n in ast.walk(h) if n in calls]
    assert not inside_handler, "the report is in an except handler again"

    # and it is guarded by the result of the put, not by a bare priority check.
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)
           and any(c in calls for c in ast.walk(n))]
    assert ifs, "the report is unconditional"
    names = {t.id for n in ifs for t in ast.walk(n.test) if isinstance(t, ast.Name)}
    assigned = {t.id for a in ast.walk(fn) if isinstance(a, ast.Assign)
                for t in a.targets if isinstance(t, ast.Name)
                if isinstance(a.value, ast.Await)
                and isinstance(a.value.value, ast.Call)
                and isinstance(a.value.value.func, ast.Attribute)
                and a.value.value.func.attr == "put"}
    assert names & assigned, (
        "the report must be guarded by what `put` returned; guard reads %r, "
        "`put` assigns %r" % (names, assigned))


def test_put_is_annotated_as_returning_the_evicted_message():
    """A caller that cannot see the return value in the signature will not read it."""
    sig = inspect.signature(PriorityMessageQueue.put)
    assert sig.return_annotation is not None
    assert "Optional" in str(sig.return_annotation), sig.return_annotation
