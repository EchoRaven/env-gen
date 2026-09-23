r"""#1202sh: publish_event wrote the inbox store once per recipient.

The write-side twin of `#1202sg`. `JsonStore.update` is a whole-file read-modify-write under
the lock — 107ms measured against tiktok-r125's real 2.1MB eventhub_inboxes.json — and
`publish_event` paid it inside `for agent in recipients`. A broadcast to r130's 23-agent roster
was 23 whole-store rewrites, about 2.5 seconds, on a synchronous path that blocks the event
loop for all of it.

Counted from the corpus's own inbox stores, which record exactly how many entries were written:

    r125    4,251 events -> 6,404 inbox entries     2,153 writes collapse    ~3.8 min
    r130    1,893 events -> 4,373 inbox entries     2,480 writes collapse    ~4.4 min

r130's distribution is the shape that matters: 1,564 events went to one recipient and 89 went
to 23. The single-recipient majority saves nothing; the broadcasts pay for everything.

The thing these tests must actually protect is DELIVERY. Collapsing N writes into one is only
worth doing if every one of the N recipients still receives the event, so the assertions are on
the inboxes, with the write count checked separately.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub


_ROSTER = ["a%d" % i for i in range(23)]


def _publish(hub, recipients, payload=None, event_type="status"):
    return hub.publish_event(source_hub="t", event_type=event_type,
                             payload=payload or {"x": 1}, recipients=recipients, caller="t")


def _eid(event):
    return event.get("id") or event.get("event_id")


def _inbox_writes(hub, monkeypatch):
    seen = []
    real = hub._inboxes.update

    def counted(*a, **kw):
        seen.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(hub._inboxes, "update", counted)
    return seen


# --- delivery, which is the thing worth protecting ------------------------------------

def test_every_recipient_of_a_broadcast_receives_it(tmp_path):
    hub = EventHub(tmp_path)
    event = _publish(hub, _ROSTER)
    boxes = json.loads((tmp_path / "eventhub_inboxes.json").read_text())
    got = [a for a in _ROSTER if _eid(event) in ((boxes.get(a) or {}).get("items") or {})]
    assert got == _ROSTER


def test_a_single_recipient_still_receives_it(tmp_path):
    hub = EventHub(tmp_path)
    event = _publish(hub, ["solo"])
    assert _eid(event) in hub._inboxes.get("solo")["items"]


def test_a_second_event_does_not_displace_the_first(tmp_path):
    hub = EventHub(tmp_path)
    first = _publish(hub, ["a0", "a1"])
    second = _publish(hub, ["a1", "a2"])
    items = hub._inboxes.get("a1")["items"]
    assert _eid(first) in items and _eid(second) in items
    assert _eid(second) not in hub._inboxes.get("a0")["items"]


def test_the_inbox_entry_carries_what_it_carried_before(tmp_path):
    hub = EventHub(tmp_path)
    event = _publish(hub, ["a0"])
    item = hub._inboxes.get("a0")["items"][_eid(event)]
    assert item["read"] is False and item["delivered"] is False
    assert item["event_id"] == _eid(event)
    assert item["received_at"] > 0 and item["priority"]


# --- and the saving -------------------------------------------------------------------

def test_a_broadcast_costs_one_inbox_write(tmp_path, monkeypatch):
    hub = EventHub(tmp_path)
    writes = _inbox_writes(hub, monkeypatch)
    _publish(hub, _ROSTER)
    assert len(writes) == 1, "%d writes for %d recipients" % (len(writes), len(_ROSTER))


def test_no_recipients_means_no_inbox_write(tmp_path, monkeypatch):
    hub = EventHub(tmp_path)
    writes = _inbox_writes(hub, monkeypatch)
    _publish(hub, [])
    assert not writes


def test_the_loop_no_longer_writes_per_recipient():
    """Source-level, because a future edit could reintroduce the loop while every delivery
    test above still passes."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import eventhub

    src = inspect.getsource(eventhub.EventHub.publish_event)
    after_loop = src.index("for agent in (")
    loop_body = src[after_loop:src.index("if _fanout:", after_loop)]
    assert "self._inboxes.update(" not in loop_body, \
        "the per-recipient write is back inside the loop"
    # ...and the batched write is still there, after it
    assert "self._inboxes.update(" in src[src.index("if _fanout:"):]


# --- #1202sn: the read was still in the loop -------------------------------------------

def _store_reads(hub, monkeypatch):
    """Count whole-store parses, which is what `JsonStore.get`/`value` each cost."""
    seen = []
    real_get, real_value = hub._inboxes.get, hub._inboxes.value

    def counted_get(*a, **kw):
        seen.append("get")
        return real_get(*a, **kw)

    def counted_value(*a, **kw):
        seen.append("value")
        return real_value(*a, **kw)

    monkeypatch.setattr(hub._inboxes, "get", counted_get)
    monkeypatch.setattr(hub._inboxes, "value", counted_value)
    return seen


def test_a_broadcast_reads_the_inbox_store_once(tmp_path, monkeypatch):
    """`#1202sh` collapsed the WRITES and left the read per recipient. `JsonStore.get` is a
    whole-store parse — 23.3ms against the real 2.1MB eventhub_inboxes.json — so a
    23-recipient broadcast re-parsed it 23 times, 0.53s, before writing anything."""
    hub = EventHub(tmp_path)
    reads = _store_reads(hub, monkeypatch)
    _publish(hub, _ROSTER)
    assert len(reads) == 1, "%d store reads for %d recipients: %s" % (
        len(reads), len(_ROSTER), reads)


def test_a_pulse_only_event_reads_nothing(tmp_path, monkeypatch):
    """Pulse-only types get no inbox item at all, so they must not pay for the map either."""
    hub = EventHub(tmp_path)
    pulse = sorted(hub._PULSE_ONLY_EVENT_TYPES)
    if not pulse:
        pytest.skip("no pulse-only event types declared")
    reads = _store_reads(hub, monkeypatch)
    _publish(hub, _ROSTER, event_type=pulse[0])
    assert not reads


def test_an_existing_inbox_is_extended_not_replaced(tmp_path):
    """Reading the map once must still see what earlier events put there."""
    hub = EventHub(tmp_path)
    first = _publish(hub, ["a0", "a1"])
    second = _publish(hub, ["a0"])
    items = hub._inboxes.get("a0")["items"]
    assert _eid(first) in items and _eid(second) in items
    assert _eid(first) in hub._inboxes.get("a1")["items"]
