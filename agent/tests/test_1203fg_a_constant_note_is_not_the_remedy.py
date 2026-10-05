r"""#1203fg: a CONSTANT framework note spent the whole evidence window, as the remedy would.

r158's hold ledger, verbatim:

    business_chain:ck the traceback: if it names custom_routes.py the fix is there, and
    only if it names a _proj

150 characters of generic advice, starting mid-word, naming neither the chain nor the step
nor the status. r153 is the same branch with a JSON payload. 2 of the 17 fresh_smoke records
on disk.

THE MECHANISM, proven end to end before anything was changed:

  1. `_HINT_SEP_1202DF` is `" — "` -- an ordinary spaced em-dash.
  2. `chain_executor._BOTH_DECLARE_NOTE_1202NG` is a 260-character CONSTANT that contains
     one: "...declare this path — main.py decides per route which one serves...".
  3. So `out.rfind(" — ")` landed INSIDE the note and `hint` became its tail.
  4. `_clip_keeping_guidance_1202df` then did what #1202df says: "Spend the cap on the remedy
     rather than on the banner in front of it" -- correct for a remedy `_unknown_id_hint`
     COMPUTED for this step, wrong for a constant that says nothing about it.
  5. And the note contains "traceback", one of `_ERR_MARKERS`, which is why the line took the
     marker path to that clipper at all. The advice argued itself into the error branch.

THREE CONSUMER-SIDE FIXES WERE TRIED AND MEASURED AWAY FIRST, which is why the mark lives
with the APPENDER:

  * widening `_salient_error`'s tail fallback -- that branch never runs for this data (the
    marker path is taken).
  * capping the clause at half the window -- breaks #1202df, whose computed remedy needs
    ~160 of 200 characters to carry "Create the resource as THIS actor". Its test said so.
  * "a long bracketed clause at the end is a constant note" -- the corpus refutes it: only
    25 of 70 notes END the detail, and 2 of 11 computed remedies DO end with "]".

So the producer marks its own output. One shared `_FW_NOTE_MARK_1203FG` rather than a list of
known texts, so a note added later is covered (#947: a hardcoded list of today's strings
cannot say tomorrow's are safe), and the stub keeps the omission audible (#883).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import framework_validation as FV   # noqa: E402
from multi_agent.runtime import chain_executor as CE         # noqa: E402

_CLIP = FV._clip_keeping_guidance_1202df
_FINDING = ("[tenant_control_lifecycle] POST /oauth/authorize → 422 (expected [2xx]) — "
            "`POST /api/v1/admin/init-tenant` failed earlier")


class TestTheTwoSidesAgree:
    """A literal copied by value is how two sides drift apart; pin them together."""

    def test_the_mark_is_the_same_on_both_sides(self):
        assert FV._FW_NOTE_MARK_1203FG == CE._FW_NOTE_MARK_1203FG

    def test_both_constant_notes_carry_it(self):
        for note in (CE._PROJECTED_NOTE_1202NG, CE._BOTH_DECLARE_NOTE_1202NG):
            assert note.startswith(CE._FW_NOTE_MARK_1203FG), note[:40]

    def test_the_substrings_existing_tests_assert_on_survive(self):
        assert "FRAMEWORK-PROJECTED" in CE._PROJECTED_NOTE_1202NG
        assert "lane cannot edit it" in CE._PROJECTED_NOTE_1202NG
        assert "BOTH a _projected_ handler" in CE._BOTH_DECLARE_NOTE_1202NG


class TestTheFindingKeepsTheWindow:
    def test_the_r158_shape_now_reports_the_finding(self):
        out = _CLIP(_FINDING + CE._BOTH_DECLARE_NOTE_1202NG, 150)
        assert "tenant_control_lifecycle" in out, out
        assert "POST /oauth/authorize" in out, out
        assert "422" in out, out

    def test_the_dropped_note_announces_itself(self):
        out = _CLIP(_FINDING + CE._BOTH_DECLARE_NOTE_1202NG, 150)
        assert out.endswith("[fw-note]"), out
        assert "check the traceback" not in out, out

    def test_the_projected_note_is_dropped_the_same_way(self):
        out = _CLIP(_FINDING + CE._PROJECTED_NOTE_1202NG, 150)
        assert "tenant_control_lifecycle" in out and out.endswith("[fw-note]"), out

    def test_a_detail_that_fits_is_untouched_note_and_all(self):
        short = "step failed" + CE._PROJECTED_NOTE_1202NG
        assert _CLIP(short, 4000) == short

    def test_the_cap_is_respected(self):
        for cap in (40, 60, 150, 300):
            out = _CLIP(_FINDING + CE._BOTH_DECLARE_NOTE_1202NG, cap)
            assert len(out) <= cap, (cap, len(out), out)


class TestTheComputedRemedyStillWins:
    """#1202df's case must be untouched: that remedy is worth the window."""

    _HINT = (" — you sent profile_id=1; title_id=1, and this caller does not own it. The "
             "refusal is CORRECT; the step is what is wrong. Create the resource as THIS "
             "actor in an earlier step and `save` its id, or make this a deliberate "
             "cross-user denial step that expects 403 alone.")

    def test_the_remedy_survives_without_a_note(self):
        out = _CLIP("POST /api/my-list -> 403 (expected [200, 201])" + self._HINT, 200)
        assert "Create the resource as THIS actor" in out, out

    def test_the_remedy_survives_even_beside_a_note(self):
        """The note is dropped first, so the remedy gets the window it needs."""
        detail = ("POST /api/my-list -> 403 (expected [200, 201])" + self._HINT
                  + CE._BOTH_DECLARE_NOTE_1202NG)
        out = _CLIP(detail, 200)
        assert "Create the resource as THIS actor" in out, out
        assert out.endswith("[fw-note]"), out


class TestItCannotLoop:
    def test_a_detail_with_two_notes_terminates(self):
        detail = _FINDING + CE._PROJECTED_NOTE_1202NG + CE._BOTH_DECLARE_NOTE_1202NG
        out = _CLIP(detail, 120)
        assert "tenant_control_lifecycle" in out and len(out) <= 120, out

    def test_a_note_with_nothing_before_it_does_not_recurse_away(self):
        out = _CLIP(CE._BOTH_DECLARE_NOTE_1202NG.lstrip(), 60)
        assert out and len(out) <= 60, out
