r"""#1202sg: check_inbox paid a whole-file rewrite per message.

`check_inbox` was measured burning 19-45 minutes of wall clock per run -- 1,752s across 434
calls on r121, 2,680s across 674 on r120, about 19% of a 2.6-hour run. Three hypotheses were
tested against that data and all three were falsified: reads are not slow (both hub files,
1.1MB + 6.6MB, parse in 0.056s), lock contention runs the wrong way (slow calls happen when
the system is QUIETER, 3.9 log lines/s against 7.5), and compose subprocesses starving the
loop is too weak to explain it (17% overlap against 12%).

The cost was never in reading. `JsonStore.update` is a whole-store read-modify-write under the
file lock, and `check_inbox(clear=True)` called `eventhub.mark_read` ONCE PER MESSAGE.

Measured against a real corpus store -- tiktok-r125's eventhub_inboxes.json, 2.1MB, 36
inboxes, the orchestrator's holding 1,664 items:

    one get                      16 ms
    one update                  107 ms
    mark_read x20             2.132 s
    mark_read_many_1202sg     0.109 s     19.6x, 2.02s saved per call

2.132s against a measured median of 2.8s (r121) and 2.0s (r120). That is the whole gap.

And it explains the finding that falsified the lock-contention hypothesis: `execute` is
SYNCHRONOUS, so each of those twenty writes blocked the event loop. The system was not quiet
while check_inbox was slow — check_inbox was why nothing else could run.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub


def _hub(tmp_path, agent="orchestrator", n=25):
    hub = EventHub(tmp_path)
    items = {"e%d" % i: {"event_id": "e%d" % i, "read": False} for i in range(n)}
    hub._inboxes.update(lambda m: m.set(agent, {"agent": agent, "items": items}, agent),
                        change_info=None)
    return hub


def _writes(hub, monkeypatch):
    """Count store writes without changing what they do."""
    seen = []
    real = hub._inboxes.update

    def counted(*a, **kw):
        seen.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(hub._inboxes, "update", counted)
    return seen


# --- the point of the change ----------------------------------------------------------

def test_twenty_messages_cost_one_write(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    writes = _writes(hub, monkeypatch)
    hub.mark_read_many_1202sg("orchestrator", ["e%d" % i for i in range(20)],
                              caller="orchestrator")
    assert len(writes) == 1, "still one write per message: %d" % len(writes)


def test_the_old_path_costs_one_write_per_message(tmp_path, monkeypatch):
    """The counter-proof: the per-id call is what this replaces."""
    hub = _hub(tmp_path)
    writes = _writes(hub, monkeypatch)
    for i in range(20):
        hub.mark_read("orchestrator", "e%d" % i, caller="orchestrator")
    assert len(writes) == 20


def test_nothing_is_written_when_there_is_nothing_to_mark(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    writes = _writes(hub, monkeypatch)
    assert hub.mark_read_many_1202sg("orchestrator", [], caller="orchestrator") == {
        "read": [], "missing": []}
    hub.mark_read_many_1202sg("orchestrator", ["nope"], caller="orchestrator")
    assert not writes, "a write for ids that do not exist"


# --- and that it does the same thing --------------------------------------------------

def test_it_marks_exactly_what_the_old_path_marks(tmp_path):
    one, many = tmp_path / "one", tmp_path / "many"
    one.mkdir()
    many.mkdir()
    ids = ["e%d" % i for i in range(20)]
    a, b = _hub(one), _hub(many)
    for i in ids:
        a.mark_read("orchestrator", i, caller="orchestrator")
    b.mark_read_many_1202sg("orchestrator", ids, caller="orchestrator")

    def items(h):
        got = h._inboxes.get("orchestrator")["items"]
        return {k: v.get("read") for k, v in got.items()}

    assert items(a) == items(b)


def test_it_reports_what_it_could_not_find(tmp_path):
    hub = _hub(tmp_path, n=3)
    out = hub.mark_read_many_1202sg("orchestrator", ["e0", "ghost", "e2"],
                                    caller="orchestrator")
    assert out["read"] == ["e0", "e2"] and out["missing"] == ["ghost"]


def test_it_stamps_a_read_time(tmp_path):
    hub = _hub(tmp_path, n=2)
    hub.mark_read_many_1202sg("orchestrator", ["e0"], caller="orchestrator")
    assert hub._inboxes.get("orchestrator")["items"]["e0"]["read_at"] > 0


def test_untouched_items_keep_their_state(tmp_path):
    hub = _hub(tmp_path, n=5)
    hub.mark_read_many_1202sg("orchestrator", ["e1"], caller="orchestrator")
    items = hub._inboxes.get("orchestrator")["items"]
    assert items["e1"]["read"] is True
    assert all(items["e%d" % i]["read"] is False for i in (0, 2, 3, 4))


def test_an_unknown_agent_is_not_an_exception(tmp_path):
    hub = _hub(tmp_path)
    assert hub.mark_read_many_1202sg("nobody", ["e0"], caller="nobody")["missing"] == ["e0"]


def test_the_identity_gate_still_applies(tmp_path):
    """O14/Phase 4.1: marking someone else's inbox read must be refused exactly as before."""
    hub = _hub(tmp_path)
    try:
        hub.mark_read("orchestrator", "e0", caller="backend")
    except Exception as one:
        with pytest.raises(type(one)):
            hub.mark_read_many_1202sg("orchestrator", ["e0"], caller="backend")
    else:
        hub.mark_read_many_1202sg("orchestrator", ["e0"], caller="backend")  # no gate: parity


# --- the wiring -----------------------------------------------------------------------

def test_check_inbox_uses_the_batch():
    """The whole saving is in the call site; a batch nobody calls saves nothing."""
    import inspect

    from env_generator.llm_generator.tools import communication_tools

    src = inspect.getsource(communication_tools.CheckInboxTool)
    assert "mark_read_many_1202sg(" in src
    assert "for msg in filtered:" not in src.split("if clear:")[1][:1200], \
        "the per-message loop is back"
