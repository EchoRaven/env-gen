"""#1202df: the framework computes the fix, then truncates it away.

Third face of the mistake #212 and #1119 already fixed twice. #212 replaced a blind
60-char PREFIX with the salient line; #1119 wrote the rule down — "extract the cause,
THEN truncate, not the other way round" — for compose stderr, whose cause sits at the
END. This is the same shape once more, except what lives past the cap is not the cause
but the REMEDY.

`chain_executor._unknown_id_hint` computes, for a 403 on a chain step, exactly what the
lane must do:

    — you sent profile_id=1; title_id=1, and this caller does not own it. The refusal
    is CORRECT; the step is what is wrong. Create the resource as THIS actor in an
    earlier step and `save` its id, or make this a deliberate cross-user denial step
    that expects 403 alone.

`framework_validation` renders it with `_salient_error(detail, cap=200)`. The hint is
APPENDED, so it is the part the cap eats. Captured live from netflix-r43 — every one of
the run's renderings ends mid-word at "Creat":

    FAILED: business_chain | failed=['business_chain:xpected [200, 201]; {"detail":
    "profile_id does not belong to the caller"} — you sent profile_id=1; title_id=1,
    and this caller does not own it. The refusal is CORRECT; the step is what is
    wrong. Creat']

r43 spent 11 framework validation attempts and carried 4 delivery-cut P0 tasks
("business_chain gate still executes stale invalid profile_list_actions_seeded_flow")
on that single step, while the instruction that resolves it was computed correctly and
then discarded before any lane could read it.

The bug is also a coin flip, which is why it hid: `_salient_error` has two exits with
OPPOSITE behavior. With no marker hit it returns `text[-cap:]` — the TAIL — and the
hint survives intact. With a marker hit it returns `_out[:cap]` — a PREFIX — and the
hint is cut. Whether the lane is told how to fix the step therefore depends on whether
some unrelated error marker happens to appear in the same detail.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _salient_error,
)

# The hint chain_executor appends for a cross-owner 403 (lines 1659-1662), verbatim.
HINT = (
    " — you sent profile_id=1; title_id=1, and this caller does not own it. The "
    "refusal is CORRECT; the step is what is wrong. Create the resource as THIS actor "
    "in an earlier step and `save` its id, or make this a deliberate cross-user denial "
    "step that expects 403 alone."
)

# A detail that DOES trip a marker, so the prefix exit is taken. `not found` is in
# _ERR_MARKERS and a chain step legitimately reports one alongside the ownership refusal.
WITH_MARKER = (
    'POST /api/my-list -> 403 (expected [200, 201]; profile not found for caller; '
    '{"detail":"profile_id does not belong to the caller"}' + HINT + ")"
)


def test_the_remedy_survives_the_cap_on_the_marker_path():
    """The actionable half is what the lane needs; it must not be the half that is cut."""
    out = _salient_error(WITH_MARKER, cap=200)
    assert "Create the resource as THIS actor" in out, (
        "the computed remediation was truncated away — this is the r43 failure: the "
        "framework knew the fix and did not deliver it. Got: %r" % out
    )
    # the whole clause, not a fragment of it
    assert out.rstrip(")").endswith("expects 403 alone."), out


def test_the_cause_is_still_reported_alongside_the_remedy():
    """#1119's rule still holds: keeping the remedy must not lose the cause."""
    out = _salient_error(WITH_MARKER, cap=200)
    assert "403" in out, out


def test_the_no_marker_tail_path_is_unchanged():
    """The exit that already worked keeps working — the hint sits at the tail."""
    plain = "POST /api/my-list returned 403" + HINT
    out = _salient_error(plain, cap=200)
    assert "Create the resource as THIS actor" in out, out


def test_a_short_detail_is_returned_whole():
    """No clipping when nothing needs clipping."""
    short = "GET /api/titles -> 500 error: boom"
    assert _salient_error(short, cap=200) == short


def test_a_hint_longer_than_the_cap_still_delivers_its_instruction():
    """When the remedy alone exceeds the cap, the remedy is what the cap is spent on."""
    out = _salient_error(WITH_MARKER, cap=80)
    assert len(out) <= 80
    assert "denial" in out or "403 alone" in out, out


def test_output_never_exceeds_the_cap():
    for cap in (60, 120, 200, 400):
        assert len(_salient_error(WITH_MARKER, cap=cap)) <= cap, cap
