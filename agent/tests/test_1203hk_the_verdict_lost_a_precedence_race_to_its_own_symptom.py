"""#1203hk — a derived verdict must not lose a precedence race to its own symptom.

`_note_keeping_the_evidence_1202wx` picks ONE window, anchored on the FIRST mark in
`_NOTE_EVIDENCE_MARKS_1202WX` that the note contains. #1203hj appended the framework's two
which-side verdicts to that tuple, which works only when nothing earlier matches.

MEASURED over all 42134 distinct step notes in every chain registry on disk: 228 long notes
carry the derived "this step is NOT the root cause" clause and **51 across 11 runs lose it**;
in 45 of those a `{"detail"` from the step's OWN symptom sits earlier and takes the window.
Both fixtures below are verbatim corpus notes, not constructions.
"""

import ast
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

clip = rd._note_keeping_the_evidence_1202wx

# tiktok-web-r126, 1412 chars. The window kept "you sent video_id=80, and no such row
# exists" -- a CONSEQUENCE of the earlier failure -- and dropped the clause naming the
# step that actually broke.
R126_NOTE = (
    "POST /api/comments → 404 (expected [200, 201]; SUBSTITUTED ${video_id} save failed "
    "at step 'feed_returns_video' (`items` came back EMPTY (0 rows), so `items.0.id` had "
    "nothing to read -- the capture is correct; the READ returned no data for this actor, "
    "which is a scoping/seed question, not a chain one) — the ladder sent an UNRELATED id "
    "— fix that capture, not this endpoint. {\"detail\":\"referenced resource not found\"} "
    "— you sent video_id=80, and no such row exists. A hardcoded id is a guess: ids differ "
    "between the dataset, the seed and the staged ASSET names. Read one from an earlier step "
    "in this chain (list the collection, `save` an id from the response) instead of writing a "
    "literal. | NOT THE FIRST FAILURE in this chain — `GET /api/explore?limit=6` failed "
    "earlier (Internal Server Error). Any state that step was to create does not exist, so "
    "fix that one first and re-run before treating this step as a defect.) ⚠ the route "
    "RAN: this 404 is the backend's referenced-row marker, not a missing route — the id "
    "this step sent does not resolve. Fix the CHAIN's captured id or the seed, not the "
    "endpoint (#1052)."
)

# tiktok-web-r173, 421 chars. Here the detail STRADDLES the head boundary, so #1202wx
# extended the head to hold it whole -- and the rescue must keep that longer head, which is
# what lets both the detail and the verdict survive.
R173_NOTE = (
    "DENIAL-PROBE got success — the request was NOT rejected (expected denial [403, 404]). "
    "{\"item\":{\"id\":1,\"created_at\":\"2025-10-09T18:14:03+00:00\",\"updated_at\":"
    "\"2025-10-12T09:26:41+00:00\"}} | NOT THE FIRST FAILURE in this chain — "
    "`DELETE /api/creators/12/follow` failed earlier ({\"detail\":\"not found\"}). Any state "
    "that step was to create does not exist, so fix that one first and re-run before "
    "treating this step as a defect."
)

MARKER = re.compile(r"…\[(\d+) chars cut; the full note is on the step record\]")


def test_the_lane_is_told_which_step_actually_broke():
    """The derived half names the earlier step; that is the thing the lane must act on."""
    out = clip(R126_NOTE)
    assert "`GET /api/explore?limit=6` failed earlier" in out, out


def test_the_consequence_is_kept_too_the_decision_does_not_take_its_window():
    """★ The first version of this patch re-spent the evidence window on the decision, and
    #1202wx's and #1203hj's regression guards caught it. Both MEASURED that the app's own
    words are the most actionable fragment in THEIR cases, so the decision is appended
    after the evidence, never instead of it."""
    out = clip(R126_NOTE)
    assert "you sent video_id=80, and no such row exists" in out, out
    assert out.index("you sent video_id=80") < out.index("NOT THE FIRST FAILURE"), out


def test_the_verdict_survives_beside_the_detail_it_is_a_verdict_about():
    out = clip(R173_NOTE)
    assert "`DELETE /api/creators/12/follow` failed earlier" in out, out
    assert '{"item":{"id":1' in out, out


# tiktok-web-r126, 455 chars. Here `{"detail"` sits at 66, so 66 + _NOTE_EVIDENCE_KEEP
# lands at 186 -- PAST the 180 head -- and #1202wx deliberately extended the head to hold
# the fragment whole (r102 kept `{"deta` when it sliced at the boundary instead). The
# rescue must re-spend the KEPT window and leave that extension alone.
R126_STRADDLE = (
    "unresolved ${video_id} save failed at step 'feed_returns_video' \u2014 "
    "{\"detail\":[{\"type\":\"int_parsing\",\"loc\":[\"path\",\"video_id\"],\"msg\":"
    "\"Input should be a valid integer, unable to parse string as an integer\","
    "\"input\":\"${video_id}\"}] | NOT THE FIRST FAILURE in this chain \u2014 "
    "`GET /api/explore?limit=6` failed earlier (Internal Server Error). Any state that step "
    "was to create does not exist, so fix that one first and re-run before treating this "
    "step as a defect."
)


def test_the_rescue_keeps_the_head_1202wx_extended_past_the_boundary():
    """Premise, stated so the test fails if it stops holding: this note's detail STRADDLES
    the head boundary, so #1202wx's head is longer than _NOTE_HEAD_1202WX."""
    at = R126_STRADDLE.find('{"detail"')
    assert at >= 0 and at <= rd._NOTE_HEAD_1202WX
    extended = at + rd._NOTE_EVIDENCE_KEEP_1202WX
    assert extended > rd._NOTE_HEAD_1202WX, (at, extended)

    out = clip(R126_STRADDLE)
    assert out.startswith(R126_STRADDLE[:extended]), out[:extended + 20]
    assert "`GET /api/explore?limit=6` failed earlier" in out, out


def test_a_note_with_no_derived_verdict_is_byte_identical():
    """#1202wx's own class must not move. Same note, every verdict clause removed --
    #1203hm added two more marks, and one of them is in this note's ladder sentence."""
    without = R126_NOTE.split("| NOT THE FIRST FAILURE")[0]
    without = without.replace(" \u2014 the ladder sent an UNRELATED id "
                              "\u2014 fix that capture, not this endpoint.", "")
    assert not [m for m in rd._decision_marks_1203hm() if m in without], without
    assert len(without) > rd._NOTE_CAP_1202WX
    out = clip(without)
    at = min(without.find(m) for m in rd._NOTE_EVIDENCE_MARKS_1202WX[:3]
             if m in without)
    head = without[:rd._NOTE_HEAD_1202WX]
    kept = without[at:at + rd._NOTE_EVIDENCE_KEEP_1202WX]
    assert out.startswith(head), out[:60]
    assert out.endswith(kept), out[-60:]


def test_a_verdict_the_normal_window_already_keeps_is_left_alone():
    """The rescue is a second pass, so the 177 notes that already carried it do not move."""
    short_tail = ("GET /api/x → 500 " + "z" * 280
                  + " NOT THE FIRST FAILURE in this chain — `POST /api/y` failed earlier.")
    assert len(short_tail) > rd._NOTE_CAP_1202WX
    out = clip(short_tail)
    assert "NOT THE FIRST FAILURE" in out
    # No detail mark anywhere, so #1202wx's blind-tail branch already caught it; the
    # rescue must not have re-sliced, which would have moved the head.
    assert out.startswith(short_tail[:rd._NOTE_HEAD_1202WX])


def test_the_dropped_count_still_accounts_for_every_character():
    """One cut, one count -- now spanning head + evidence on one side of the marker and
    the decision on the other. The segments are joined with a single space this function
    inserted, so the accounting is exact up to those joins."""
    for note in (R126_NOTE, R173_NOTE, R126_STRADDLE):
        out = clip(note)
        m = MARKER.search(out)
        assert m, out
        dropped = int(m.group(1))
        before = out[:m.start()].rstrip()
        after = out[m.end():].lstrip("… ")
        # The separators this function inserts: one space before the evidence window when
        # there is one, and " ... " between decision windows. Ask the function that
        # computed the split rather than guessing which branch the note took.
        _, kept = rd._note_window_1202wx(note)
        joins = (1 if kept else 0) + 3 * len(re.findall(" … ", after))
        accounted = len(before) + len(after) + dropped - joins
        assert accounted == len(note), (
            accounted, len(note), joins, before[-40:], after[:40])


def test_every_decision_mark_is_rescued_not_only_the_root_cause_one():
    """Generality: the mechanism is about derived verdicts, not about one clause."""
    for mark in rd._NOTE_DECISION_MARKS_1203HK:
        note = ('GET /api/x → 500 ' + 'q' * 160
                + ' {"detail":"boom"} ' + 'w' * 200 + ' ' + mark + ' and then some tail.')
        out = clip(note)
        assert mark in out, (mark, out)


def test_the_earliest_lost_verdict_wins():
    """Two verdicts, both lost; the one the framework stated first is the one kept."""
    note = ('GET /api/x → 500 ' + 'q' * 160 + ' {"detail":"boom"} ' + 'w' * 200
            + ' THAT is the defect ' + 'e' * 40
            + ' NOT THE FIRST FAILURE in this chain — `POST /z` failed earlier.')
    out = clip(note)
    assert "THAT is the defect" in out, out


def test_a_short_note_is_returned_whole():
    note = 'GET /api/x → 500 NOT THE FIRST FAILURE in this chain — `POST /z` failed.'
    assert clip(note) == note


def test_it_never_raises_on_junk():
    for bad in (None, 0, [], {"a": 1}):
        clip(bad)  # must not raise


def test_the_rescue_runs_on_the_value_the_function_returns():
    """Structural: defined-but-uncalled would pass every text assertion above on the
    fixtures that happen not to need it. Pin it to the RETURN of #1202wx."""
    src = inspect.getsource(rd._note_keeping_the_evidence_1202wx)
    tree = ast.parse(src.strip())
    fn = tree.body[0]
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    calls = [
        n for n in returns
        if isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_note_rescue_the_decision_1203hk"
    ]
    assert calls, ast.dump(fn)


def test_the_window_split_has_one_definition():
    """#1202wx's branch chain must not exist twice -- the rescue reuses the head, and a
    second copy would silently diverge from it (the `truncate`-defined-twice shape)."""
    src = inspect.getsource(rd)
    assert src.count("for mark in _NOTE_EVIDENCE_MARKS_1202WX:") == 1, (
        src.count("for mark in _NOTE_EVIDENCE_MARKS_1202WX:"))
    assert src.count("def _note_window_1202wx") == 1


def test_the_rescue_is_bounded_by_the_evidence_keep_budget():
    """The decision gets one evidence-sized window, not the rest of the note."""
    out = clip(R126_NOTE)
    m = MARKER.search(out)
    decision = out[m.end():].lstrip("… ")
    budget = (rd._NOTE_EVIDENCE_KEEP_1202WX * rd._NOTE_DECISION_WINDOWS_1203HM
              + 4 * rd._NOTE_DECISION_WINDOWS_1203HM)
    assert len(decision) <= budget, (len(decision), budget)
