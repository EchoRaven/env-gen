"""#1203i9: the contract the lanes code to never said what `total` counts.

`_AGENT_NOTES` is written to `design/agent_notes.md` in every run (220 on disk) and its
heading says "Contract & response shapes (FIXED -- code to them exactly)". It prescribed

    list -> {"items": [...], "total": N}

and never said what N counts, and never mentioned cursor pagination at all -- the string
`next_cursor` appeared nowhere in the framework's guidance, only in the validator that
polices it.

Meanwhile the framework HAD settled the meaning internally: `#1202os` made the projected
collection reads emit `"total": query.count()`, and `_list_total_unreachable_1202w0`'s own
comment states it outright -- "the framework's own projected reads settle the meaning of
the word: `"total": query.count()` (#1202os), the size of the collection." That decision
never reached the document the lanes read.

Measured: 628 `#1202w0` warnings across the corpus, 89% of them on the feed endpoint
(/api/feed/foryou 177, /api/videos/feed 166, /api/feed 147, /api/feed/for-you 70), in 7 of
the last 11 tiktok runs. In r183 it fired from 22:33:08 to 02:24:25 -- the whole run --
and was never resolved. The lane's own `custom_routes.py` shows both behaviours side by
side: line 852 computes a correct `total` with a cursor, line 1149 returns
`{"items": [...], "total": len(page), "next_cursor": next_cursor}`.

The validator's words for what that costs: "A client that follows `next_cursor` stops
early and the rest of the data is unreachable through the app."

This test does NOT match the notes against a copy of their own wording -- that would drift
the day the sentence is reworded (#1032). It checks that the notes and the validator AGREE
BEHAVIOURALLY: a response shaped the way the notes now prescribe must come back clean from
the validator, and the shape the notes previously left open must still be flagged.
"""
import json

from env_generator.llm_generator.multi_agent.runtime.reference_materials import _AGENT_NOTES
from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
    _list_total_unreachable_1202w0 as detect,
)


def _body(total, n_items, cursor):
    return json.dumps({"items": [{"id": i} for i in range(n_items)],
                       "total": total, "next_cursor": cursor})


def test_the_shape_the_notes_prescribe_is_clean_to_the_validator(monkeypatch):
    """A paginated read whose `total` counts the collection: 35 rows, a 5-row page, and a
    cursor that actually reaches the rest. This is what the notes now tell the lane to
    build, and the validator has to call it clean.

    When `total` exceeds the page the validator WALKS the cursor, so this needs a server.
    Only `_http` is replaced -- the external world -- and the walk itself runs for real;
    stubbing the walk would be stubbing the thing the assertion rests on."""
    from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr

    TOTAL, PAGE = 35, 5

    def _fake_http(method, url, token=None, **kw):
        off = 0
        if "cursor=" in url:
            off = int(url.split("cursor=")[1].split("&")[0])
        rows = list(range(off, min(off + PAGE, TOTAL)))
        nxt = off + PAGE if off + PAGE < TOTAL else None
        return {"status": 200, "body_text": json.dumps(
            {"items": [{"id": i} for i in rows], "total": TOTAL, "next_cursor": nxt})}

    monkeypatch.setattr(vr, "_http", _fake_http)
    assert detect("http://x", "/api/videos/feed", None,
                  _body(total=TOTAL, n_items=PAGE, cursor=PAGE)) == ""


def test_a_cursor_that_cannot_reach_the_total_is_still_flagged(monkeypatch):
    """The other direction the validator owns, kept as a control: an honest-looking
    `total` whose cursor dead-ends after one page is still a finding. Without this, the
    test above could be satisfied by a validator that had stopped walking at all."""
    from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr

    monkeypatch.setattr(vr, "_http", lambda *a, **k: {"status": 200, "body_text": json.dumps(
        {"items": [], "total": 35, "next_cursor": None})})
    msg = detect("http://x", "/api/videos/feed", None,
                 _body(total=35, n_items=5, cursor=5))
    assert "reachable" in msg, msg


def test_the_shape_the_notes_left_open_is_still_flagged():
    """The counter-control, and the corpus's actual failure: `total` equals the page while
    a cursor offers more. If this came back clean the test above would prove nothing."""
    msg = detect("http://x", "/api/videos/feed", None,
                 _body(total=5, n_items=5, cursor="abc"))
    assert msg, "the validator stopped flagging the condition this patch documents"
    assert "not the collection size" in msg


def test_the_notes_answer_the_question_the_validator_asks():
    """The two facts the validator's verdict turns on had to reach the document the lanes
    read: what `total` counts, and that a cursor does not change it. Checked as presence of
    the concepts in the contract section, not as an exact sentence."""
    head = _AGENT_NOTES.split("## Ground truth files")[0]
    assert "next_cursor" in head, (
        "the contract section still never mentions cursor pagination, which is the one "
        "case #1202w0 flags")
    low = head.lower()
    assert "whole collection" in low or "collection the endpoint lists" in low, (
        "the contract section still does not say what `total` counts")
    # and it must say what total is NOT, since `len(items)` is the shape 628 warnings hit
    assert "len(items)" in head or "page size" in low


def test_the_notes_still_reach_disk():
    """A contract nobody receives is not a contract. `_AGENT_NOTES` is the body written to
    design/agent_notes.md; if this ever stops being the written text the fix is inert."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
    src = inspect.getsource(rm)
    assert "dest.write_text(_AGENT_NOTES" in src, (
        "_AGENT_NOTES is no longer the text written to agent_notes.md")


def test_a_complete_single_page_list_is_clean():
    """The shape that must NOT be flagged, and the reason the validator checks for a
    cursor at all: a list that fits in one page legitimately has `total == len(items)`
    and offers no next page. Nothing here is a contradiction.

    This is the control that makes the cursor guard load-bearing. Without it, deleting the
    guard -- which would flag every complete one-page list in every app -- passed the whole
    file, because the other cases either carry a cursor or take the walk branch instead."""
    assert detect("http://x", "/api/settings", None,
                  _body(total=3, n_items=3, cursor=None)) == ""
    # and with the key absent entirely, not merely null
    assert detect("http://x", "/api/settings", None,
                  json.dumps({"items": [{"id": 1}], "total": 1})) == ""


def test_the_falsification_is_recorded_where_the_text_lives():
    """#1203i9 did not work online, and that has to be readable HERE.

    r184 received this file's `total` definition — `WHOLE COLLECTION` is in its
    `design/agent_notes.md` — and shipped `{"items": items, "total": len(items),
    "next_cursor": next_cursor}` at two endpoints anyway, in release-v1.1.0. Offending
    endpoints per run: r182 0, r183 1, r184 2 (the run WITH the text).

    What worked was routing the finding to a TASK (#1203ie publishes it in the gate result,
    #1203ii dispatches a backend task): r186 ended with zero offending endpoints and the task
    completed. The note below #1203i9's marker stays because it is true and free, but a reader
    must not mistake its presence for the defect being handled — which is exactly what I would
    have done without this.
    """
    # #1203mc: the first branch read a `_ROOT` this module never defines, guarded by
    # `"_ROOT" in globals()` -- so it could never run and the fallback always did. Dropped,
    # because `scripts/undefined_names.py` is only usable as a tripwire from a clean
    # baseline, and this was the last candidate in 2588 files.
    import os
    import pathlib
    src = pathlib.Path(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "env_generator/llm_generator/multi_agent/runtime/reference_materials.py"
    ).read_text(encoding="utf-8")
    assert "#1203i9 WAS FALSIFIED ONLINE" in src, (
        "the falsification note is gone; a reader will take the paragraph as a fix")
    assert "#1203ii" in src, "the note does not name what actually worked"
    assert "WEAK LEVERAGE" in src
