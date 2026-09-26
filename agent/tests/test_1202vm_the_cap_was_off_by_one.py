"""#1202vm — the events ring buffer settled at `cap + 1`, and its docstring said it could not.

`_set_and_prune_events` computes `overflow = len(data) - cap` ONCE and then skipped the
just-published event with a `continue` INSIDE the deletion loop. Whenever the new event
landed in the first `overflow` entries, one slot went unspent and the store stayed one over
the cap — forever, because every later publish did the same.

It is the low-value types that trigger it: #673 sorts `agent_status` FIRST, while a
brand-new event otherwise sorts last by `created_at`. The docstring claimed "the full-file
rewrite never serializes more than ``cap`` events", which was false by one.

`_set_and_prune_threads_1202vj` already excluded the current record from the CANDIDATES
rather than from the loop; this makes the two forms agree.
"""
import os
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub

_SRC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/eventhub.py")


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("ENVGEN_EVENTHUB_MAX_EVENTS", "20")
    return EventHub(str(pathlib.Path(tempfile.mkdtemp())))


def _publish(h, event_type, i=0):
    return h.publish_event("workhub", event_type, {"i": i},
                           recipients=[], priority="normal", caller="workhub")


def test_a_substantive_stream_settles_exactly_at_the_cap(hub):
    for i in range(25):
        _publish(hub, "task_created", i)
    assert len(hub._events.value()) == 20


def test_a_low_value_publish_at_the_cap_does_not_leave_one_over(hub):
    """The defect. #673 sorts `agent_status` first, so the brand-new event landed in the
    eviction window, the `continue` spent no slot on it, and the store went to 21 and
    stayed. Measured before the fix: 25 task_created -> 20, then +agent_status -> 21, 21,
    21, 21."""
    for i in range(25):
        _publish(hub, "task_created", i)
    for i in range(4):
        _publish(hub, "agent_status", i)
        assert len(hub._events.value()) == 20, "the cap must hold across repeats"


def test_the_event_just_published_is_never_the_one_evicted(hub):
    """What the `continue` was protecting, kept by excluding it from the candidates."""
    for i in range(25):
        _publish(hub, "task_created", i)
    rec = _publish(hub, "agent_status", 99)
    assert rec["id"] in hub._events.value()


def test_a_mixed_stream_holds_the_cap(hub):
    for i in range(40):
        _publish(hub, "agent_status" if i % 3 else "task_created", i)
        assert len(hub._events.value()) <= 20


def test_a_pinned_event_still_outlives_the_cap(hub):
    """The exemption the cap has always had must survive this change."""
    rec = hub.publish_event("workhub", "task_created", {"pinned": True},
                            recipients=[], priority="normal", caller="workhub")
    for i in range(40):
        _publish(hub, "task_created", i)
    assert rec["id"] in hub._events.value()


def test_the_exclusion_is_on_the_candidates_not_in_the_loop():
    """A future edit that moves the guard back into the loop restores the off-by-one, and
    the behavioural tests above would catch it — this names the mechanism so the reason is
    findable. Anchored to landmarks, never a byte window (#943)."""
    src = _SRC.read_text()
    body = src[src.index("def _set_and_prune_events"):src.index("def publish_api_requirement")]
    assert "if eid != event_id and not _is_pinned(ev)" in body
    assert "continue  # never evict the event we just published" not in body
