"""#1203i3: the dispatch-full warning said the identical sentence up to 2955 times.

With #1203i2 taking the previous record, this is the loudest line in the framework: 17620
lines across the last 13 runs. Deduplicated per run:

    r173 2955 / 1 distinct     r171 2879 / 1     r177 1983 / 1
    r175 1698 / 1              r176 1252 / 1     r181  864 / 1
    r179 3310 / 318            r180 1024 / 27

-- the identical sentence one to three thousand times. ★ The two outliers are MINE:
#1203hp appended `evicted=N` to this line and #1203hu kept it, so once that counter starts
moving every line differs. A monotonically incrementing serial number makes a heartbeat pass
#1202ad's "a count that moves is news" test while saying nothing new, and r179's 318 distinct
lines are exactly what that looks like.

What IS news is the ORDER OF MAGNITUDE: "saturated, 1000 drops so far" is a different fact
from "saturated, 1 drop so far" in a way that the 999 lines between them are not. The count
stays IN the message -- it is the memo STATE that is bucketed, not the number reported.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime import messaging as _msg  # noqa: E402
from multi_agent.agents.priority_queue import PriorityMessageQueue  # noqa: E402
from multi_agent.runtime.message_format import reset_state_memo_1202ad  # noqa: E402
from utils.message import BaseMessage, MessageHeader, MessagePriority  # noqa: E402

SITE = "messaging.dispatch_full_150"


@pytest.fixture(autouse=True)
def _fresh():
    reset_state_memo_1202ad(SITE)
    yield
    reset_state_memo_1202ad(SITE)


class _Logger:
    def __init__(self): self.warnings = []
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass
    def warning(self, m, *a, **k): self.warnings.append(str(m) % a if a else str(m))


class _Host(_msg.AgentMessaging):
    """A dispatch queue that is ALWAYS full, so every enqueue takes the #150 path."""

    def __init__(self, agent_id="lane", evicted=0):
        self.agent_id = agent_id
        self._logger = _Logger()
        self._priority_queue = PriorityMessageQueue(maxsize=100)
        self._priority_queue.evicted = evicted
        self._message_queue = asyncio.Queue(maxsize=1)
        self._message_queue.put_nowait("already full")
        self._interrupt_messages = []
        self._subscription_inbox = []

    async def _send_delivery_ack(self, message):
        return None

    async def _maybe_schedule_resident_message_wakeup(self, message, inbox_msg):
        return None


def _mk(i=0):
    return BaseMessage(
        header=MessageHeader(message_id="m%d" % i, source_agent_id="src",
                             target_agent_id="t", priority=MessagePriority.NORMAL),
        payload="p", metadata={"msg_type": "note"})


def _drop(host, n=1):
    async def _go():
        for i in range(n):
            await host._enqueue_for_dispatch(_mk(i))
    asyncio.run(_go())


def _full(host):
    return [w for w in host._logger.warnings if "dispatch queue FULL" in w]


# ------------------------------------------------------------------ the magnitudes


def test_a_thousand_drops_are_four_lines_not_a_thousand():
    host = _Host()
    _drop(host, 1000)
    said = _full(host)
    assert len(said) == 4, "1000 drops produced %d lines" % len(said)


def test_it_speaks_at_the_first_drop():
    host = _Host()
    _drop(host, 1)
    assert len(_full(host)) == 1


def test_the_lines_land_on_the_magnitudes():
    host = _Host()
    _drop(host, 150)
    said = _full(host)
    assert len(said) == 3, said                       # 1, 10, 100
    assert "1 such drop(s) so far" in said[0], said[0]
    assert "10 such drop(s) so far" in said[1], said[1]
    assert "100 such drop(s) so far" in said[2], said[2]


def test_nine_drops_are_one_line():
    """The bucket is the digit count, so 1..9 is one order of magnitude."""
    host = _Host()
    _drop(host, 9)
    assert len(_full(host)) == 1


# ------------------------------------------------------------- nothing else changes


def test_the_sentence_is_unchanged():
    host = _Host()
    _drop(host, 1)
    said = _full(host)[0]
    for phrase in ("dispatch queue FULL",
                   "dropping the ordinary-dispatch copy",
                   "the inbox copy is what still carries an ordinary message",
                   "instead of parking the sender (FIX #150)"):
        assert phrase in said, (phrase, said)


def test_the_eviction_count_still_rides_along():
    """#1203hp's number is why a reader looks here; bucketing the memo must not drop it."""
    host = _Host(evicted=24)
    _drop(host, 1)
    assert "priority-queue evicted=24 so far (#1203hp)" in _full(host)[0]


def test_a_zero_eviction_count_is_still_omitted():
    host = _Host(evicted=0)
    _drop(host, 1)
    assert "evicted=" not in _full(host)[0], _full(host)[0]


def test_the_message_still_names_the_agent_and_the_queue_size():
    host = _Host(agent_id="frontend")
    _drop(host, 1)
    said = _full(host)[0]
    assert "[frontend]" in said, said
    assert "(1 pending)" in said, said


# --------------------------------------------------------------- per-agent isolation


def test_two_agents_do_not_silence_each_other():
    a, b = _Host("frontend"), _Host("backend")
    _drop(a, 1)
    _drop(b, 1)
    assert len(_full(a)) == 1, _full(a)
    assert len(_full(b)) == 1, _full(b)


def test_one_saturated_agent_does_not_mute_a_later_one():
    """Interleaved, the way a run actually dispatches."""
    a, b = _Host("frontend"), _Host("backend")
    for _ in range(12):
        _drop(a, 1)
        _drop(b, 1)
    assert len(_full(a)) == 2, _full(a)        # 1 and 10
    assert len(_full(b)) == 2, _full(b)


def test_a_memo_failure_must_not_silence_the_report(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_memo(name, *a, **k):
        if "message_format" in name:
            raise ImportError("memo unavailable")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_memo)
    host = _Host()
    _drop(host, 5)
    assert len(_full(host)) == 5, "a memo failure silenced the report"


def test_the_drop_counter_itself_keeps_counting():
    """The number reported must be the true total, not the bucket."""
    host = _Host()
    _drop(host, 1000)
    assert host._drops_1203i3 == 1000
    assert "1000 such drop(s) so far" in _full(host)[-1]
