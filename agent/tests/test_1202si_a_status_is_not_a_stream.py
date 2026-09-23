r"""#1202si: an agent_status is a current value, and every reader treats it as one.

All three readers take only the latest. `get_agent_status` returns the most recent for an
agent, `get_all_agent_statuses` the latest per agent, and human_console filters heartbeats out
of the transcript entirely. Every superseded one was kept anyway.

That is not just space. `JsonStore.update` rewrites the WHOLE file on every publish -- 247.6ms
measured against tiktok-r125's real 6.4MB eventhub_events.json -- so each stale heartbeat is
re-serialised on every publish that follows it.

Measured across the corpus's own event stores, and the split matters:

    138 runs below the retention cap    30% of retained events are heartbeats   -29% store
     32 runs at the cap                  6%                                      -6%

The capped runs are already thin because `#673` made heartbeats the first thing evicted. The
138 that never reach the cap carry them for the whole run: r74 55%, r75 53%, r58 53% -- which
is `#673`'s own stream-wide figure showing up where it actually costs something. At ~4,000
publishes and 247.6ms each, 29% off the store is about 4.8 minutes of wall clock per run.

(My first estimate was 9.7 minutes. It applied `#673`'s stream-wide 55% to the RETAINED store,
which is a different population -- the corpus stores on disk had already been pruned. The
number above is measured on the stores themselves.)

`#673` reached this one step short: it changed the eviction ORDER at the cap. This removes the
redundancy where it is created, which also hands that ring-buffer budget back to the
substantive events #673 measured being crowded out.
"""
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub


def _hub(tmp_path):
    return EventHub(tmp_path)


def _statuses(hub):
    return [e for e in hub._events.value().values()
            if isinstance(e, dict) and e.get("event_type") == "agent_status"]


# --- the supersede ---------------------------------------------------------------------

def test_forty_heartbeats_leave_one(tmp_path):
    hub = _hub(tmp_path)
    for i in range(40):
        hub.record_agent_status("backend", {"agent_id": "backend", "tick": i})
    assert len(_statuses(hub)) == 1


def test_each_agent_keeps_its_own(tmp_path):
    hub = _hub(tmp_path)
    for i in range(10):
        for who in ("backend", "frontend", "verifier"):
            hub.record_agent_status(who, {"agent_id": who, "tick": i})
    assert len(_statuses(hub)) == 3


def test_the_readers_still_see_the_latest(tmp_path):
    hub = _hub(tmp_path)
    for i in range(25):
        hub.record_agent_status("backend", {"agent_id": "backend", "tick": i})
        hub.record_agent_status("frontend", {"agent_id": "frontend", "tick": i})
    assert hub.get_agent_status("backend")["tick"] == 24
    assert {k: v["tick"] for k, v in hub.get_all_agent_statuses().items()} == {
        "backend": 24, "frontend": 24}


def test_an_agent_that_never_reported_has_no_status(tmp_path):
    hub = _hub(tmp_path)
    hub.record_agent_status("backend", {"agent_id": "backend", "tick": 1})
    assert hub.get_agent_status("frontend") is None


# --- and everything it must not touch ---------------------------------------------------

def test_ordinary_events_are_history_and_stay(tmp_path):
    hub = _hub(tmp_path)
    for i in range(6):
        hub.publish_event(source_hub="t", event_type="task_created",
                          payload={"i": i}, recipients=["backend"], caller="t")
        hub.record_agent_status("backend", {"agent_id": "backend", "tick": i})
    kinds = [e.get("event_type") for e in hub._events.value().values()]
    assert kinds.count("task_created") == 6
    assert kinds.count("agent_status") == 1


def test_a_pinned_heartbeat_survives(tmp_path):
    hub = _hub(tmp_path)
    hub.record_agent_status("backend", {"agent_id": "backend", "tick": 0, "pinned": True})
    for i in range(1, 5):
        hub.record_agent_status("backend", {"agent_id": "backend", "tick": i})
    ticks = sorted(e["payload"]["tick"] for e in _statuses(hub))
    assert 0 in ticks, "a pinned heartbeat was superseded"
    assert hub.get_agent_status("backend")["tick"] == 4


def test_a_heartbeat_with_no_agent_id_supersedes_nothing(tmp_path):
    """If we cannot tell whose status it is, we cannot tell what it replaces."""
    hub = _hub(tmp_path)
    for i in range(4):
        hub.publish_event(source_hub="system", event_type="agent_status",
                          payload={"tick": i}, recipients=[], caller="system")
    assert len(_statuses(hub)) == 4


def test_a_status_from_another_hub_is_not_superseded(tmp_path):
    """Narrow on purpose: only the system topic's heartbeats are a current value."""
    hub = _hub(tmp_path)
    for i in range(4):
        hub.publish_event(source_hub="workhub", event_type="agent_status",
                          payload={"agent_id": "backend", "tick": i},
                          recipients=[], caller="workhub")
    assert len(_statuses(hub)) == 4


def test_the_event_just_written_is_never_its_own_victim(tmp_path):
    hub = _hub(tmp_path)
    hub.record_agent_status("backend", {"agent_id": "backend", "tick": 7})
    assert hub.get_agent_status("backend") is not None


def test_recipients_still_receive_a_status_event(tmp_path):
    """Superseding the store must not touch delivery."""
    hub = _hub(tmp_path)
    event = hub.publish_event(source_hub="system", event_type="agent_status",
                              payload={"agent_id": "backend", "tick": 1},
                              recipients=["frontend"], caller="system")
    eid = event.get("id") or event.get("event_id")
    assert eid in hub._inboxes.get("frontend")["items"]
