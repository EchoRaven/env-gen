r"""#1203hj: the lane got the contradiction 86 times and the verdict twice.

For a denial probe that got a success, `chain_executor` derives WHICH SIDE IS WRONG — and
the two answers point OPPOSITE ways:

  ①  "...and THAT is the defect: the probe is right. Set auth_required=True on this
      endpoint and let the projected handler get its guard. Do NOT weaken the probe."
  ②  "CONTRACT SAYS PUBLIC: ... so the projected handler carries no guard and a 2xx is
      what it is BUILT to answer — this probe is probably mis-authored. If the endpoint
      really must deny, change the CONTRACT first; the handler follows it."

`#1202ld` built the channel that carries this to a lane, and it works: the annotation
reaches lane tasks 86 times since 2026-10-01. The VERDICT reaches them **2** — ① zero
times, ② twice.

The clipper is why. `_note_keeping_the_evidence_1202wx` keeps `head` plus an EVIDENCE
window anchored on `_NOTE_EVIDENCE_MARKS_1202WX`, which held only the app's own
`{"detail": ...}` shapes. A denial probe that got a 2xx has no error body — so there is
nothing to anchor on, the note falls back to a blind 90-character tail, and the verdict
(which sits past the head) is dropped. Measured on the 62 annotation fragments on disk: 49
(79%) carry no app words at all; 13 (20%) do.

★ LOSING IT IS WORSE THAN SILENCE. The lane is handed "the contract says public and a
chain demands a denial" and left to guess the direction. #1202qs records tiktok-r127 doing
exactly that: it registered the feed `auth_required=true` to match a probe that was wrong,
the frontend was then told auth had been added, and logged-out visitors were fed hard-coded
videos.

★ APPENDED, NOT PREPENDED. The loop takes the FIRST matching mark, so order is precedence,
and #1202wx measured that the app's `{"detail"}` is the most actionable fragment in ITS
cases (40 of 106 long notes lost it). Appending covers the 79% with no change to anything
#1202wx measured — `test_an_app_error_body_still_wins` pins that.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _NOTE_CAP_1202WX, _NOTE_EVIDENCE_MARKS_1202WX,
    _note_keeping_the_evidence_1202wx as clip)

_PROSE = "framework prose that spends the budget. " * 5
_HEAD = ("Step 3 of chain profile_page_authenticated_feed_contract: GET /api/feed expected "
         "a denial [401, 403] and the app answered 200. ")

VERDICT_B = ("CONTRACT SAYS PUBLIC: this endpoint states auth_required=False (last written "
             "by backend), so the projected handler carries no guard and a 2xx is what it "
             "is BUILT to answer — this probe is probably mis-authored. If the endpoint "
             "really must deny, change the CONTRACT first; the handler follows it.")
VERDICT_A = ("The projected handler has no 'me' to answer with. The contract says "
             "auth_required=False (last written by backend), and THAT is the defect: the "
             "probe is right. Set auth_required=True on this endpoint and let the projected "
             "handler get its guard. Do NOT weaken the probe.")


def test_the_probe_is_mis_authored_verdict_survives():
    """★ Verdict ②, which reached a lane twice in 86 annotations."""
    out = clip(_HEAD + _PROSE + VERDICT_B)
    assert "probably mis-authored" in out, out[-140:]
    assert "change the CONTRACT first" in out, out[-140:]


def test_the_probe_is_right_verdict_survives():
    """★ Verdict ①, which reached a lane ZERO times — and it says the OPPOSITE of ②, so
    losing it is not a smaller version of losing ②."""
    out = clip(_HEAD + _PROSE + VERDICT_A)
    assert "THAT is the defect" in out, out[-140:]
    assert "Set auth_required=True" in out, out[-140:]


def test_the_two_verdicts_are_not_confusable():
    """The point of carrying them at all: they prescribe opposite actions, so a lane that
    receives one must not be able to read it as the other. Asserted on the
    DIRECTION-BEARING clause of each, which is what the lane acts on."""
    a = clip(_HEAD + _PROSE + VERDICT_A)
    b = clip(_HEAD + _PROSE + VERDICT_B)
    assert "the probe is right" in a and "Set auth_required=True" in a, a[-150:]
    assert "probably mis-authored" not in a, a[-150:]
    assert "change the CONTRACT first" in b, b[-150:]
    assert "the probe is right" not in b, b[-150:]


def test_what_this_patch_does_NOT_recover():
    """★ STATED, NOT INFLATED. Verdict ① runs ~147 characters from its mark and
    `_NOTE_EVIDENCE_KEEP_1202WX` is 120, so its closing reinforcement — "Do NOT weaken the
    probe." — is still cut; the output ends at "...get its gu".

    I did NOT widen that constant to make this pass. #1202wx measured the evidence segment
    at 38 characters median and 42 at p75, so 120 was already generous for the case it was
    chosen for, and raising it lengthens EVERY step note in every task. The
    direction-bearing clause ("the probe is right. Set auth_required=True") survives, which
    is what the lane acts on; the lost sentence only repeats it. If a later reader wants it,
    the right move is to shorten the verdict in `chain_executor`, not to widen the window
    here."""
    a = clip(_HEAD + _PROSE + VERDICT_A)
    assert "Do NOT weaken the probe" not in a, (
        "the reinforcement now fits — update this test and say which constant moved")
    assert "the probe is right" in a, a[-150:]


def test_an_app_error_body_still_wins():
    """★ THE REGRESSION GUARD for #1202wx. It measured that the app's own words are the
    most actionable fragment in its cases (40 of 106 long notes lost them). The verdict
    marks are APPENDED, so a note carrying both keeps today's behaviour exactly."""
    both = _HEAD + _PROSE + 'the app said {"detail": "forbidden for this actor"} ' + VERDICT_B
    out = clip(both)
    assert '{"detail"' in out, out[-160:]


def test_the_cut_still_declares_itself():
    """#1034: a truncation that does not say so reads as a complete note."""
    out = clip(_HEAD + _PROSE + VERDICT_B)
    assert "chars cut" in out, out
    assert "the full note is on the step record" in out, out


def test_a_short_note_is_untouched():
    """★ The no-op guarantee: #1202wx measured 98.8% of the 1617 step notes pass through
    whole at this cap, and they must keep doing so."""
    short = "Step 1: GET /api/feed → 200"
    assert clip(short) == short
    assert len(short) <= _NOTE_CAP_1202WX


def test_a_note_with_neither_still_gets_head_and_tail():
    """The fallback #1202wx chose for the 27 long notes with no marker at all."""
    plain = _HEAD + ("padding. " * 60) + "the very end of it"
    out = clip(plain)
    assert out.startswith("Step 3 of chain"), out[:40]
    assert "the very end of it" in out, out[-60:]


def test_the_app_marks_come_first_in_the_tuple():
    """★ Order IS precedence in the loop below the tuple, so this is the assertion that
    keeps the append an append. Prepending would silently re-decide #1202wx's 40 cases."""
    marks = list(_NOTE_EVIDENCE_MARKS_1202WX)
    assert marks[:3] == ['{"detail"', '"detail"', "{'detail'"], marks
    assert "THAT is the defect" in marks[3:], marks
    assert "probably mis-authored" in marks[3:], marks


def test_the_clipper_never_raises():
    """It runs while building the lane's task; raising would replace the work item."""
    for junk in (None, "", 12345, "x" * 5000):
        out = clip(junk)
        assert isinstance(out, str)
