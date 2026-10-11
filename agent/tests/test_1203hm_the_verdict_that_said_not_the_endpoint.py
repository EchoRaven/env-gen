"""#1203hm — the two verdicts that say "not the endpoint", which a lane otherwise inverts.

#1203hk gave a dropped verdict its own window. MEASURED afterwards over the 1169 long step
notes in every chain registry on disk, two more derived verdicts were still being lost --
and both of them say the endpoint is RIGHT:

    "... the ladder sent an UNRELATED id - fix that capture, not this endpoint."   11 of 347
    "Fix the CHAIN's captured id or the seed, not the endpoint (#1052)."            0 of 143

A lane handed only the 404/422 and the app's `{"detail"}` does the opposite: it edits the
endpoint. #1202qs records that outcome. Two windows, not one: with a single window the
earliest lost mark wins and `NOT THE FIRST FAILURE` drops 228 -> 220.
"""

import inspect
import re

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

clip = rd._note_keeping_the_evidence_1202wx
MARKER = re.compile(r"…\[(\d+) chars cut; the full note is on the step record\]")

# tiktok-web-r126, verbatim (1115 chars). It carries THREE derived verdicts -- the ladder
# clause, the not-root clause and the #1052 clause -- plus the app's own `{"detail"}`.
R126_THREE = (
    "POST /api/comments → 404 (expected [200, 201]; SUBSTITUTED ${video_id} save failed "
    "at step 'feed_returns_video' (`items` came back EMPTY (0 rows), so `items.0.id` had "
    "nothing to read -- the capture is correct) — the ladder sent an UNRELATED id "
    "— fix that capture, not this endpoint. {\"detail\":\"referenced resource not "
    "found\"} — you sent video_id=80, and no such row exists. A hardcoded id is a "
    "guess: ids differ between the dataset, the seed and the staged ASSET names. Read one "
    "from an earlier step in this chain (list the collection, `save` an id from the "
    "response) instead of writing a literal. | NOT THE FIRST FAILURE in this chain — "
    "`GET /api/explore?limit=6` failed earlier (Internal Server Error). Any state that step "
    "was to create does not exist, so fix that one first and re-run before treating this "
    "step as a defect.) ⚠ the route RAN: this 404 is the backend's referenced-row "
    "marker, not a missing route — the id this step sent does not resolve. Fix the "
    "CHAIN's captured id or the seed, not the endpoint (#1052)."
)


def test_the_lane_is_told_not_to_edit_the_endpoint():
    out = clip(R126_THREE)
    assert "fix that capture, not this endpoint" in out, out


def test_both_lost_verdicts_fit_because_there_are_two_windows():
    """One window would keep only the earliest, which is why the budget is two."""
    out = clip(R126_THREE)
    kept = [m for m in rd._decision_marks_1203hm() if m in out]
    assert len(kept) >= 2, (kept, out)


def test_the_apps_own_words_are_still_there():
    """#1202wx's property, which #1203hk's first version broke and this must not."""
    out = clip(R126_THREE)
    assert '{"detail":"referenced resource not found"}' in out, out


def test_the_window_count_is_the_measured_one():
    assert rd._NOTE_DECISION_WINDOWS_1203HM == 2


def test_the_windows_are_in_the_order_the_framework_stated_them():
    """A reader follows the note's own sequence, so the windows must not be reordered."""
    out = clip(R126_THREE)
    kept = [m for m in rd._decision_marks_1203hm() if m in out and m in R126_THREE]
    assert len(kept) >= 2, kept
    by_note = [m for m in sorted(kept, key=R126_THREE.find)]
    by_out = [m for m in sorted(kept, key=out.find)]
    assert by_note == by_out, (by_note, by_out)


def test_the_rescue_is_still_bounded():
    """Two windows, each one evidence-sized -- not the rest of the note."""
    out = clip(R126_THREE)
    m = MARKER.search(out)
    assert m, out
    after = out[m.end():].lstrip("… ")
    budget = (rd._NOTE_EVIDENCE_KEEP_1202WX * rd._NOTE_DECISION_WINDOWS_1203HM
              + 4 * rd._NOTE_DECISION_WINDOWS_1203HM)
    assert len(after) <= budget, (len(after), budget)


def test_the_dropped_count_accounts_for_every_character():
    out = clip(R126_THREE)
    m = MARKER.search(out)
    dropped = int(m.group(1))
    before = out[:m.start()].rstrip()
    after = out[m.end():].lstrip("… ")
    # The joins this function inserts are a single space before `kept` and " … " between
    # windows, so the accounting is exact up to those separators.
    _, kept = rd._note_window_1202wx(R126_THREE)
    joins = (1 if kept else 0) + 3 * len(re.findall(r" … ", after))
    assert len(before) + len(after) + dropped - joins == len(R126_THREE), (
        len(before), len(after), dropped, joins, len(R126_THREE))


def test_a_note_with_one_lost_verdict_uses_one_window():
    note = ('GET /api/x → 500 ' + 'q' * 170 + ' {"detail":"boom"} ' + 'w' * 200
            + ' NOT THE FIRST FAILURE in this chain — `POST /z` failed earlier.')
    out = clip(note)
    assert "NOT THE FIRST FAILURE" in out
    assert "… " not in out[out.index("NOT THE FIRST FAILURE"):], out


def test_both_new_marks_come_from_their_owner():
    """★ #1032's guard caught me copying the #1052 sentence into the dispatcher. A literal
    there stops matching the day the sentence is reworded -- silently, with nothing red.
    So the marks are IMPORTED, and this pins that."""
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    marks = rd._decision_marks_1203hm()
    assert ce.VERDICT_FIX_THE_CAPTURE_1203HM in marks, marks
    assert ce.VERDICT_NOT_THE_ENDPOINT_1203HM in marks, marks
    src = inspect.getsource(rd)
    assert ce.VERDICT_NOT_THE_ENDPOINT_1203HM not in src, "restated instead of imported"
    assert ce.VERDICT_FIX_THE_CAPTURE_1203HM not in src, "restated instead of imported"


def test_the_owner_builds_its_sentences_from_those_constants():
    """Otherwise the constant and the sentence drift apart and the mark matches nothing."""
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    note = ce.route_ran_note_1052({"status": 404,
                                   "note": 'body {"detail":"referenced resource not found"}'})
    if note:
        assert ce.VERDICT_NOT_THE_ENDPOINT_1203HM in note, note
    src = inspect.getsource(ce)
    assert "VERDICT_NOT_THE_ENDPOINT_1203HM + " in src or \
           "+ VERDICT_NOT_THE_ENDPOINT_1203HM" in src, "the sentence no longer uses it"
    assert "+ VERDICT_FIX_THE_CAPTURE_1203HM" in src, "the ladder sentence no longer uses it"


def test_the_window_budget_is_read_not_hardcoded():
    """Structural: the slice must come off the constant, so changing the constant changes
    behaviour (a hardcoded 2 would pass every assertion above)."""
    src = inspect.getsource(rd._note_rescue_the_decision_1203hk)
    assert "_NOTE_DECISION_WINDOWS_1203HM" in src, src
    assert "[:2]" not in src, src


def test_it_never_raises_on_junk():
    for bad in (None, 0, [], {"a": 1}):
        clip(bad)
