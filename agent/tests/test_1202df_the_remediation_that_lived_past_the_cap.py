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


# ---------------- #1203ho: the join was byte-identical to the text it cut ----------------
#
# `_clip_keeping_guidance_1202df` ended on `out[:keep].rstrip() + " " + hint`, and `hint`
# begins at _HINT_SEP_1202DF (" — ") with its leading space stripped -- so the join emitted
# exactly one space before an em dash: the same three characters the sentence it cut uses as
# its own separator. MEASURED over the 1255 long chain details on disk at this writer's cap
# of 300: every one is clipped, 1092 end in this join, and 783 of 1117 (70%) cut the head
# MID-WORD. r178 06:12:47 live: `(a seeded id is 1) — the tab — the id this step sent does
# not resolve.` -- "the tab" is the front of "the table is populated".

from env_generator.llm_generator.multi_agent.runtime import framework_validation as _fv1203ho

# tiktok-web-r178's own step note, verbatim up to the point the writer had to cut.
R178_NOTE_1203HO = (
    "[notifications_activity_page] POST /api/videos/35/comments → 404 "
    "(expected [200, 201]; TABLE `videos` HAS 35 LIVE ROW(S) (a seeded id is 1) "
    "— the table is populated, so the id this step names is the thing that does not "
    "exist. {\"detail\":\"parent resource not found\"}"
    " — the id this step sent does not resolve. Fix the CHAIN's captured id or the "
    "seed, not the endpoint (#1052).)"
)


def test_the_cut_is_visible_instead_of_passing_for_a_separator():
    """★ Found by mutation: the first version asserted
    `_ELISION_1203HO.strip() in out`, which is `"" in out` -- trivially true -- the moment
    the constant becomes a plain space. Name the character the reader has to see."""
    out = _fv1203ho._clip_keeping_guidance_1202df(R178_NOTE_1203HO, 300)
    assert len(R178_NOTE_1203HO) > 300
    assert "\u2026" in out, out


def test_the_marker_cannot_be_mistaken_for_the_text_it_cuts():
    """The whole defect was a join that read as ordinary prose. Whatever the marker is, it
    must not be whitespace and must not be the separator the sentence itself uses."""
    mark = _fv1203ho._ELISION_1203HO
    assert mark.strip(), repr(mark)
    assert mark.strip() != _fv1203ho._HINT_SEP_1202DF.strip(), repr(mark)
    assert not mark.strip().isalnum(), repr(mark)


def test_the_head_no_longer_ends_mid_word():
    """★ The live symptom: "the tab" is the front of "the table is populated"."""
    out = _fv1203ho._clip_keeping_guidance_1202df(R178_NOTE_1203HO, 300)
    head = out.split(_fv1203ho._ELISION_1203HO)[0]
    assert head, out
    # The character that followed the head in the source must not be a letter -- otherwise
    # a word was split.
    assert R178_NOTE_1203HO.startswith(head.rstrip()), (head[-40:], out[:60])
    nxt = R178_NOTE_1203HO[len(head.rstrip()):len(head.rstrip()) + 1]
    assert not nxt.isalnum(), (head[-30:], nxt)


def test_the_instruction_still_survives_whole():
    out = _fv1203ho._clip_keeping_guidance_1202df(R178_NOTE_1203HO, 300)
    assert "not the endpoint (#1052)" in out, out
    assert "the id this step sent does not resolve" in out, out


def test_it_still_fits_the_cap():
    for cap in (120, 200, 300, 400):
        out = _fv1203ho._clip_keeping_guidance_1202df(R178_NOTE_1203HO, cap)
        assert len(out) <= cap, (cap, len(out))


def test_the_budget_leaves_room_for_the_marker_itself():
    """★ Found by mutation: with the old `cap - len(hint) - 1` the head is two characters
    too long, the final `[:cap]` takes them off the END, and the instruction loses its last
    two characters -- `(#1052).` becomes `(#1052`. A fixture whose head happens to backtrack
    far enough hides it, so assert on the hint, across caps, instead."""
    hint = R178_NOTE_1203HO[R178_NOTE_1203HO.rfind(_fv1203ho._HINT_SEP_1202DF):].strip()
    assert len(hint) > 40, hint
    for cap in (len(hint) + 40, len(hint) + 41, len(hint) + 60, 300):
        out = _fv1203ho._clip_keeping_guidance_1202df(R178_NOTE_1203HO, cap)
        assert out.endswith(hint), (cap, out[-len(hint) - 10:])


def test_a_cut_that_already_fell_on_a_boundary_is_not_trimmed_further():
    """★ No gratuitous backtrack, and this is what the first version got wrong: it saw
    only the head, so it could not tell a split word from a word that simply ended, and
    `a complete phrase` came back as `a complete`."""
    wb = _fv1203ho._word_boundary_1203ho
    assert wb("a complete phrase x", 17) == "a complete phrase"   # next char is a space
    assert wb("a complete phrase", 17) == "a complete phrase"     # nothing was dropped
    assert wb('ends on punctuation." more', 21) == 'ends on punctuation."'


def test_a_token_longer_than_the_bound_keeps_its_head():
    """★ Otherwise one pathological token would empty the head entirely."""
    blob = "x" * (_fv1203ho._WORD_BACKTRACK_1203HO + 40)
    keep = _fv1203ho._WORD_BACKTRACK_1203HO + 5
    assert _fv1203ho._word_boundary_1203ho(blob, keep) == blob[:keep]


def test_the_corpus_shapes_are_fixed():
    """The three splits the corpus actually produced. The cut index is DERIVED from the word
    being split, so the fixture cannot drift into cutting at a boundary by accident."""
    wb = _fv1203ho._word_boundary_1203ho
    for whole, word, inside in (
            ("expected [401, 403]; DENIAL-PROBE got success", "DENIAL-PROBE", 11),
            ("for this actor, which is a scoping/seed question", "scoping", 4),
            ("the READ returned no data for this actor, which is a scoping", "which", 1),
    ):
        keep = whole.index(word) + inside
        # The character the cut DROPS, and the one it keeps -- indexed, not sliced with a
        # width. #943's ratchet holds the line on fixed-width windows and its regex reads
        # comments too, so this note describes the shape instead of spelling it.
        dropped = whole[keep] if keep < len(whole) else ""
        kept_last = whole[keep - 1] if keep else ""
        assert dropped.isalnum(), (whole, keep)                   # premise: mid-word
        assert kept_last.isalnum(), (whole, keep)
        got = wb(whole, keep)
        assert got != whole[:keep], (whole[:keep], got)           # it was trimmed
        nxt = whole[len(got):len(got) + 1]
        assert not nxt.isalnum() or not got[-1:].isalnum(), (got, nxt)
        assert whole.startswith(got), (whole, got)


def test_the_join_reads_the_constants():
    """Structural: a hardcoded " " or a hardcoded 24 would pass the cases above on these
    fixtures. Move the constants and the behaviour must move with them."""
    import inspect
    src = inspect.getsource(_fv1203ho._clip_keeping_guidance_1202df)
    tail = src[src.rindex("keep = cap"):]
    assert "_ELISION_1203HO" in tail, tail
    assert "_word_boundary_1203ho" in tail, tail
    assert '+ " " + hint' not in tail, tail
    assert "_WORD_BACKTRACK_1203HO" in inspect.getsource(_fv1203ho._word_boundary_1203ho)


def test_a_short_detail_is_still_returned_whole_1203ho():
    small = "GET /api/x → 500 — do the thing."
    assert _fv1203ho._clip_keeping_guidance_1202df(small, 300) == small
