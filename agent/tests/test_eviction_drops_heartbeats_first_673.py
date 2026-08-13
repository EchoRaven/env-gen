r"""#673: the event ring buffer spent its budget on heartbeats and evicted the anchors.

`eventhub_events` — 288,562 records over 144 runs, 415 MB on disk, median 2.4 MB and up to
9.3 MB per run — was the largest unopened store. Its composition:

    agent_status              158383  (55% of every event ever published)
    task_completed             12771      task_created          12752
    endpoint_registered        11983      task_claimed          11736
    meeting_decision_added     10056      ui_page_registered     7657
    breaking_change_detected    3902

The store is a ring buffer capped at 5000 (#6, because JsonStore rewrites the whole file on
every publish). Eviction was oldest-first across the WHOLE stream, and the stream is a median
53% heartbeats — up to 97% in the worst run. Comparing the 5 runs that reached the cap against
the 139 that did not, every substantive type is scarcer among the survivors:

    agent_status        63.7% vs 54.1%      breaking_change_detected  0.7% vs 1.4%
    task_created         3.0% vs  4.6%      meeting_decision_added    1.7% vs 3.7%
    ui_page_registered   1.6% vs  2.8%      task_completed            3.3% vs 4.5%

n=5 at the cap and capped runs are also longer, so the sizes are indicative — but the direction
is what a FIFO over a heartbeat-dominated stream must produce.

The cap's own docstring says "recent events / unread inbox items are what agents actually read".
A stale heartbeat is neither. The `pinned` escape hatch exists but nothing has ever used it:
0 of 288,562 events carry the flag.

This is a REORDER inside the existing eviction — the same number of events is removed, ordering
stays oldest-first within each class, so the newest heartbeats still survive.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import eventhub as eh


def _mk(eid, typ, ts, pinned=False):
    e = {"id": eid, "event_type": typ, "created_at": ts}
    if pinned:
        e["pinned"] = True
    return e


class _View:
    def __init__(self, data):
        self.d = dict(data)

    def value(self):
        return self.d

    def set(self, k, v, actor=None):
        self.d[k] = v
        return self

    def delete(self, k, actor=None):
        self.d.pop(k, None)
        return self


def _prune(existing, new_id, new_ev, cap=5):
    import os
    os.environ["ENVGEN_EVENTHUB_MAX_EVENTS"] = str(cap)
    try:
        v = _View(existing)
        eh.EventHub._set_and_prune_events(v, new_id, new_ev, "test")
        return v.value()
    finally:
        os.environ.pop("ENVGEN_EVENTHUB_MAX_EVENTS", None)


# --- heartbeats go first ------------------------------------------------------------------------

def test_an_old_heartbeat_is_evicted_before_a_newer_anchor():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(5)}
    data["a1"] = _mk("a1", "breaking_change_detected", 100)
    out = _prune(data, "new", _mk("new", "task_created", 200))
    assert "a1" in out, "the anchor must survive"


def test_the_oldest_anchor_outlives_every_heartbeat():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", 500 + i) for i in range(5)}
    data["old_anchor"] = _mk("old_anchor", "task_created", 1)      # oldest of all
    out = _prune(data, "new", _mk("new", "task_created", 999))
    assert "old_anchor" in out


def test_heartbeats_are_still_evicted_oldest_first_among_themselves():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(8)}
    out = _prune(data, "new", _mk("new", "agent_status", 99))
    survivors = sorted(int(k[1:]) for k in out if k.startswith("h"))
    assert survivors == survivors and min(survivors) > 0, "the oldest heartbeats went first"


def test_the_newest_heartbeats_survive():
    """Liveness reads are recent-first, so recency must be preserved within the class."""
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(8)}
    out = _prune(data, "new", _mk("new", "task_created", 99))
    assert "h7" in out


# --- the cap's contract is unchanged --------------------------------------------------------------

def test_the_same_number_of_events_is_removed():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(10)}
    out = _prune(data, "new", _mk("new", "task_created", 99), cap=5)
    assert len(out) == 5


def test_the_event_just_published_is_never_evicted():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(10)}
    out = _prune(data, "new", _mk("new", "agent_status", 0), cap=5)
    assert "new" in out


def test_pinned_events_are_still_never_evicted():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(10)}
    data["keep"] = _mk("keep", "agent_status", -1, pinned=True)
    out = _prune(data, "new", _mk("new", "task_created", 99), cap=3)
    assert "keep" in out


def test_a_cap_of_zero_disables_eviction():
    data = {f"h{i}": _mk(f"h{i}", "agent_status", i) for i in range(10)}
    out = _prune(data, "new", _mk("new", "task_created", 99), cap=0)
    assert len(out) == 11


def test_under_the_cap_nothing_is_touched():
    data = {"a": _mk("a", "agent_status", 1)}
    out = _prune(data, "new", _mk("new", "task_created", 2), cap=10)
    assert set(out) == {"a", "new"}


def test_malformed_entries_do_not_crash_the_sort():
    data = {"junk": "not a dict", "h": _mk("h", "agent_status", 1)}
    _prune(data, "new", _mk("new", "task_created", 2), cap=2)


# --- the class list ------------------------------------------------------------------------------

def test_only_liveness_is_classed_low_value():
    assert eh._LOW_VALUE_EVENT_TYPES_673 == frozenset({"agent_status"})


@pytest.mark.parametrize("typ", ["task_created", "breaking_change_detected",
                                 "endpoint_registered", "meeting_decision_added"])
def test_coordination_types_are_not_low_value(typ):
    assert typ not in eh._LOW_VALUE_EVENT_TYPES_673


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(eh).replace("#", " ").split())
    assert "158383 of the corpus's 288562 events" in flat
    assert "63.7% vs 54.1%" in flat


def test_the_sample_size_caveat_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(eh).split())
    assert "n=5 at the cap" in flat and "indicative" in flat


def test_the_unused_pin_hatch_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(eh).split())
    assert "0 of 288562 events carry the flag" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
