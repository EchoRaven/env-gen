r"""#679: every task lifecycle transition re-sent the whole record, description and all.

#257 added `[tool-io]` accounting so a future run could answer "which tool grows the prompt".
That accounting now has a corpus, and it names one:

    401M chars of tool output, per the authoritative per-run `tool_io_rollup` tables
    check_inbox is 187.3M of it — 46.7%, mean 24,044 over 7788 calls, max 1,515,342

(A first pass reconstructed this from the per-call log lines and got 62.9% / mean 73k. Those
lines are only emitted above _TOOL_IO_LOG_THRESHOLD = 20000 chars, so summing them counts only
the big calls and inflates every mean. The rollup is the authoritative total and the ranking is
unchanged — check_inbox is still first by a wide margin.)

The read side is already settled and must not be touched. #302 previews already-READ bodies at
240 chars, and #274 forbids clipping UNREAD ones after a `[:500]` cap left a receiver unable to
see a task_ready contract or ask for the rest, wedging the pipeline. #274 also names the only
sanctioned lever: *"context savings for oversized bodies must come from the SENDER (send a
summary + a hub pointer), not from clipping on read."*

Nothing had aimed at the sender because nothing recorded which one. The event payloads do — of
257M chars across 288,562 events:

    task_created    40.0M  (15.6%)   mean 3140
    task_claimed    36.9M  (14.3%)   mean 3142
    task_completed  34.5M  (13.4%)   mean 2700

claimed and completed carry the SAME mean as created: every transition re-sends the description
that was delivered once at creation.

`task_created` is untouched — it is #274's wedge case verbatim, the only one with a real
recipient, and the assignee needs the contract. Only the four transitions are trimmed, and only
when large:

    25496 transition events, 76.1M chars, median 733 — most are already small
    p90 2441, p99 74967, max 128438 — a tiny tail holds everything
    a cut at 2000 touches 14% of events and reclaims 76% of the bytes

So 86% pass through byte-identical, and the trimmed ones keep every identifying field plus a
pointer to `workhub_get_task(id)` — nothing is unrecoverable, which is the condition #274's
wedge failed.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.workhub.service import (
    _TRANSITION_BODY_CHARS_679 as CAP,
    _transition_payload_679 as trim,
)


def _big(**kw):
    t = {"id": "t2", "title": "Build the browse page", "status": "completed",
         "assignee": "frontend", "claimed_by": "frontend", "description": "D" * 4000}
    t.update(kw)
    return t


# --- small records are untouched ---------------------------------------------------------------

def test_a_small_record_is_returned_unchanged():
    small = {"id": "t1", "title": "x", "status": "completed", "description": "short"}
    assert trim(small) is small


def test_a_record_at_the_cap_is_untouched():
    t = {"id": "t", "description": "x" * (CAP - 60)}
    assert trim(t) is t


def test_the_cap_matches_the_measured_knee():
    """14% of transition events, 76% of the bytes — the p90/p99 elbow."""
    assert CAP == 2000


# --- large records keep their identity -----------------------------------------------------------

@pytest.mark.parametrize("key", ["id", "title", "status", "assignee", "claimed_by"])
def test_every_identifying_field_survives(key):
    assert key in trim(_big())


def test_the_description_is_dropped():
    assert "description" not in trim(_big())


def test_it_actually_shrinks():
    big = _big()
    assert len(str(trim(big))) < len(str(big)) / 5


def test_a_small_result_is_kept():
    assert trim(_big(result={"ok": True}))["result"] == {"ok": True}


def test_an_oversized_result_is_dropped():
    assert "result" not in trim(_big(result={"blob": "z" * 5000}))


def test_a_cancel_reason_is_kept():
    """#672's cancellations are diagnosed by their reason; it must not be trimmed away."""
    assert trim(_big(cancel_reason="duplicate of task_x"))["cancel_reason"] == "duplicate of task_x"


# --- nothing becomes unrecoverable -----------------------------------------------------------

def test_it_says_the_body_was_omitted():
    assert "_body_omitted" in trim(_big())


def test_it_names_the_original_size():
    """Silent omission reads as 'that was all there was'."""
    big = _big()
    assert f"{len(str(big))} chars" in trim(big)["_body_omitted"]


def test_it_points_at_the_fetch_tool():
    """#274's wedge was that the receiver could not get the rest. It can."""
    note = trim(_big())["_body_omitted"]
    assert "workhub_get_task(task_id='t2')" in note


def test_it_says_when_the_full_record_was_delivered():
    assert "delivered when the task was CREATED" in trim(_big())["_body_omitted"]


# --- it must never break an emit ------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, "x", 42, [], ("a",)])
def test_a_non_dict_is_passed_through(junk):
    assert trim(junk) == junk


def test_missing_fields_are_simply_absent():
    out = trim({"id": "t", "description": "D" * 4000})
    assert out["id"] == "t"
    assert "assignee" not in out


# --- only the transitions are wrapped -----------------------------------------------------------

def test_task_created_is_NOT_trimmed():
    """#274's wedge case: the assignee needs the whole contract."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    src = inspect.getsource(sv)
    i = src.index('self._emit("task_created"')
    assert "_transition_payload_679" not in src[i:src.index("\n", i)]


@pytest.mark.parametrize("ev", ["task_claimed", "task_completed", "task_failed", "task_cancelled"])
def test_each_transition_is_wrapped(ev):
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    src = inspect.getsource(sv)
    i = src.index(f'self._emit("{ev}"')
    assert "_transition_payload_679" in src[i:src.index("\n", i)]


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    flat = " ".join(inspect.getsource(sv).replace("#", " ").split())
    assert "check_inbox is 187.3M" in flat
    assert "_TOOL_IO_LOG_THRESHOLD" in flat, "the biased first pass must be recorded"
    assert "reclaims 76% of the bytes" in flat


def test_the_read_side_rules_are_credited():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    # strip comment markers: the rationale wraps across lines
    flat = " ".join(inspect.getsource(sv).replace("#", " ").split())
    assert "274 forbids clipping UNREAD" in flat
    assert "302 already previews already-READ bodies" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
