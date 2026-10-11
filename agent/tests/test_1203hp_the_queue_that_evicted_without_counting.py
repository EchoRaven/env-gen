"""#1203hp — the only drop in the message path that counted nothing.

`FIX #150` drops the ordinary-dispatch copy of a message when the bounded dispatch queue
fills, and says so LOUDLY: 125022 warnings across 157 run logs on disk, r173 alone 2955.
Its stated grounds are that "the message already reached `_subscription_inbox`, the
priority queue, and the interrupt channel for urgent types".

Two of those three are urgent-only. Every use of `_priority_queue` in the framework is
`put` (for EVERY message), `get_if_urgent` (which pops only `priority <= 1`) and its
constructor -- `get()` has no caller. So an ORDINARY message's priority-queue copy is
never read, the heap fills with copies nothing will take, and from then on every `put`
evicts one, with no counter and no log line.
"""

import ast
import asyncio
import inspect
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.agents.priority_queue import (
    PriorityMessageQueue,
)
from env_generator.llm_generator.multi_agent.agents.runtime import messaging as _msg
from utils.message import MessagePriority


# --- the counter --------------------------------------------------------------------

def _put_n(q, n, priority):
    async def _run():
        for i in range(n):
            await q.put(_fake(priority, i))
    asyncio.run(_run())


class _Hdr:
    def __init__(self, priority, i):
        self.priority = priority
        self.message_id = f"id{i}"
        self.source_agent_id = "src"
        self.timestamp = None


class _Fake:
    """Minimal stand-in for BaseMessage: only what PrioritizedMessage.from_message reads."""
    def __init__(self, priority, i):
        self.header = _Hdr(priority, i)
        self.payload = f"m{i}"
        self.metadata = {}
        self.message_type = type("T", (), {"value": "generic"})()


def _fake(priority, i=0):
    return _Fake(priority, i)


def test_a_full_queue_counts_what_it_throws_away():
    q = PriorityMessageQueue(maxsize=10)
    assert q.evicted == 0
    _put_n(q, 10, MessagePriority.NORMAL)
    assert q.evicted == 0, "nothing should go while there is room"
    _put_n(q, 5, MessagePriority.NORMAL)
    assert q.evicted == 5, q.evicted
    assert q.qsize() == 10


def test_the_eviction_takes_the_lowest_priority_not_the_highest():
    """★ Found by mutation: a heap filled only with LOW cannot tell `pop()` from
    `pop(0)`. The urgent one must be ALREADY IN the heap when it overflows."""
    q = PriorityMessageQueue(maxsize=5)
    asyncio.run(q.put(_fake(MessagePriority.URGENT, 99)))     # in first, must survive
    _put_n(q, 4, MessagePriority.LOW)                         # heap now full at 5
    assert q.evicted == 0
    _put_n(q, 3, MessagePriority.LOW)                         # three overflows
    assert q.evicted == 3, q.evicted

    got = asyncio.run(q.get_if_urgent())
    assert got is not None, "the urgent copy was evicted -- the eviction took the wrong end"
    assert got.payload == "m99", got.payload


def test_an_urgent_message_arriving_into_a_full_heap_still_comes_out():
    q = PriorityMessageQueue(maxsize=5)
    _put_n(q, 5, MessagePriority.LOW)
    asyncio.run(q.put(_fake(MessagePriority.URGENT, 77)))
    got = asyncio.run(q.get_if_urgent())
    assert got is not None and got.payload == "m77", got
    assert q.evicted == 1


def test_an_empty_queue_never_claims_an_eviction():
    q = PriorityMessageQueue(maxsize=3)
    assert q.evicted == 0
    asyncio.run(q.put(_fake(MessagePriority.NORMAL, 1)))
    assert q.evicted == 0


# --- the claim the drop rests on ----------------------------------------------------

_SRC_ROOT = pathlib.Path(_msg.__file__).resolve().parents[3]


def test_the_priority_queue_still_has_no_ordinary_consumer():
    """★ THE PREMISE, pinned. The whole reason an ordinary message's priority-queue copy
    is dead is that nothing calls `get()`. If a caller appears, #1203hp's reasoning -- and
    the wording of the #150 warning -- has to be revisited."""
    callers = []
    for p in _SRC_ROOT.rglob("*.py"):
        if "/tests/" in str(p) or p.name.startswith("test_"):
            continue
        try:
            src = p.read_text(errors="replace")
        except Exception:
            continue
        if "_priority_queue" not in src:
            continue
        for m in re.finditer(r"_priority_queue\.(\w+)\s*\(", src):
            callers.append((p.name, m.group(1)))
    methods = sorted({c[1] for c in callers})
    assert methods == ["get_if_urgent", "put"], callers


def test_the_warning_no_longer_claims_the_priority_copy_is_kept():
    src = inspect.getsource(_msg)
    i = src.index("dispatch queue FULL")
    block = src[i:src.index("async def", i)]
    assert "inbox + priority-queue copies kept" not in block, block
    assert "URGENT/HIGH" in block, block


def test_the_warning_carries_the_eviction_count():
    """Structural: a counter nobody reports is the defect one level up."""
    tree = ast.parse(inspect.getsource(_msg))
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name == "_enqueue_for_dispatch"]
    assert len(fns) == 1, [getattr(n, "name", None) for n in fns]
    # The count is read through `getattr(..., "evicted", None)`, so it is a string
    # constant in this function, not an attribute node. Assert on what is actually there.
    consts = [n.value for n in ast.walk(fns[0])
              if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "evicted" in consts, consts
    assert any("#1203hp" in c for c in consts), consts
    assert any("evicted=" in c for c in consts), consts
