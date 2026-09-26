"""#1202vj — the events store is a bounded ring buffer; the thread store written beside
it in the same publish was never bounded, and it outgrew the capped one.

    tiktok-r107     13640 threads / 3.25 MB   (its capped events file holds 5001)
    tiktok-r125     12976 threads / 3.19 MB
    googlemaps-r16   9849 threads / 2.36 MB

99% of the corpus's 445254 threads hold exactly ONE event — a standalone publish derives
its thread id from its own event id — and in the largest stores 37-63% reference only
events the cap already evicted, so `get_thread_transcript` on them is provably empty.
They were re-serialised on every publish for the rest of the run anyway.
"""
import os
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.eventhub import (
    _set_and_prune_threads_1202vj as prune,
    _events_retention_cap,
)
from env_generator.llm_generator.multi_agent.runtime.json_store import _MapView

_SRC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/eventhub.py")


def _view(threads):
    return _MapView(dict(threads))


def _thread(i, updated):
    return {"id": f"t{i}", "event_ids": [f"evt_{i}"], "participants": [],
            "created_at": updated, "updated_at": updated}


def _many(n, start=0):
    return {f"t{i}": _thread(i, 1000.0 + i) for i in range(start, start + n)}


def test_under_the_cap_nothing_is_evicted(monkeypatch):
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "10")
    v = prune(_view(_many(5)), "tNEW", _thread(99, 2000.0), "a")
    assert len(v.value()) == 6
    assert "tNEW" in v.value()


def test_past_the_cap_the_oldest_go_first(monkeypatch):
    """`updated_at` moves only when an event joins a thread, so the oldest threads are
    exactly the ones whose events left the event window first."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "5")
    v = prune(_view(_many(8)), "tNEW", _thread(99, 2000.0), "a")
    kept = v.value()
    assert len(kept) == 5
    assert "tNEW" in kept
    assert "t0" not in kept and "t1" not in kept and "t2" not in kept
    assert "t7" in kept          # the newest survivors stay


def test_the_thread_this_publish_just_wrote_is_never_evicted(monkeypatch):
    """Even when its timestamp is the oldest in the store — losing it would drop the
    event's own thread the moment it was created."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "3")
    v = prune(_view(_many(6)), "tNEW", _thread(99, 0.0), "a")
    assert "tNEW" in v.value()
    assert len(v.value()) == 3


def test_a_cap_of_zero_disables_eviction(monkeypatch):
    """Same contract as the events cap: `<= 0` means unbounded."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "0")
    v = prune(_view(_many(50)), "tNEW", _thread(99, 2000.0), "a")
    assert len(v.value()) == 51


def test_a_thread_with_no_usable_timestamp_sorts_oldest(monkeypatch):
    """Missing/garbage timestamps must not raise, and such a record is the best eviction
    candidate — it cannot be shown to be recent."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "2")
    threads = {"tA": {"id": "tA"}, "tB": _thread(1, 5000.0), "tC": _thread(2, 6000.0)}
    v = prune(_view(threads), "tNEW", _thread(9, 7000.0), "a")
    kept = v.value()
    assert "tA" not in kept
    assert "tNEW" in kept


def test_it_shares_the_events_cap_setting(monkeypatch):
    """Threads are 1:1 with events in 99% of cases, so one setting governs both; two
    would drift apart (#1032)."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "7")
    assert _events_retention_cap() == 7
    v = prune(_view(_many(20)), "tNEW", _thread(99, 9000.0), "a")
    assert len(v.value()) == 7


def test_publish_event_routes_the_thread_write_through_the_prune():
    """Behavioural tests above prove the function; this pins that publish_event actually
    uses it, since the old call was a bare `m.set(...)`. Anchored, not a byte window
    (#943)."""
    src = _SRC.read_text()
    block = src[src.index('thread["updated_at"] = now'):]
    block = block[:block.index("PULSE-ONLY")]
    assert "_set_and_prune_threads_1202vj(m, thread_id, thread, actor)" in block


def _conversation(i, updated, n=5):
    return {"id": f"c{i}", "event_ids": [f"evt_{i}_{j}" for j in range(n)],
            "participants": ["backend"], "created_at": updated, "updated_at": updated}


def test_a_real_conversation_is_never_evicted(monkeypatch):
    """The events cap exempts `pinned`; this exempts a thread that ever carried a second
    event. Load-bearing, not decorative: r125 holds 34 conversations of which 12 are
    FINISHED test-user agents — long idle, so a plain oldest-first rule evicts exactly
    those 12. r107's five conversations sort newest and would have survived either way,
    which is why the r125 reading is the one that settles the design."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "3")
    threads = dict(_many(6))                      # singletons at t=1000..1005
    threads["cIDLE"] = _conversation(1, 1.0)      # the oldest record in the store
    v = prune(_view(threads), "tNEW", _thread(99, 9000.0), "a")
    kept = v.value()
    assert "cIDLE" in kept, "an idle conversation must survive the cap"
    assert "tNEW" in kept
    assert len(kept) == 3


def test_conversations_past_the_cap_are_kept_rather_than_dropped(monkeypatch):
    """When conversations alone exceed the cap there is nothing safe left to evict, so
    the store is allowed over — the same way a store of pinned events is. Measured: in
    all 23 over-cap runs the singletons alone always suffice, so this is the tail."""
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "2")
    threads = {f"c{i}": _conversation(i, 100.0 + i) for i in range(5)}
    v = prune(_view(threads), "tNEW", _thread(99, 9000.0), "a")
    assert len(v.value()) == 6
    assert all(f"c{i}" in v.value() for i in range(5))


def test_singletons_are_still_evicted_around_a_conversation(monkeypatch):
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "4")
    threads = dict(_many(8))
    threads["cKEEP"] = _conversation(1, 1.0)
    v = prune(_view(threads), "tNEW", _thread(99, 9000.0), "a")
    kept = v.value()
    assert "cKEEP" in kept and "tNEW" in kept
    assert "t0" not in kept and "t1" not in kept
