"""#1202jl: the field that explains a live zero must travel with the live zero.

#950 added `capture_missing_live` and `capture_error_live` beside `similarity_live` so a
reader could tell a failed CAPTURE from a failed JUDGE. It left `blank` behind, and blank is
the third way a live score becomes zero — the commonest one.

r111's `fyp_feed_comments_panel` is the case. Its record reads

    similarity: 0.62   similarity_live: 0.0
    capture_missing_live: False   capture_error_live: None   blank: None

— three fields insisting nothing went wrong. What happened: the DOM probe found the page empty
after three re-polls, so NO shot was taken and none was judged (that screen's verdict cache
holds 0.46/0.54/0.61/0.62 and no 0.0 anywhere). `blank: None` is not even wrong about the live
capture; it belongs to the earlier round whose 0.62 was kept by #500's merge. The gate summary
gets this right — it reads `_blank_screens` directly — but the per-screen record a human opens
did not, and the two disagreed.

No verdict changes: #619's live average already excludes the screen (r111 recorded 0.6663,
which is the mean of the OTHER eight, not of nine), and #750's veto reads `capture_transient`
and `console_errors`, never this field.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import json                                                             # noqa: E402
from pathlib import Path                                                # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf  # noqa: E402


def _res(name, sim, blank=None, route="/x"):
    r = {"name": name, "route": route, "similarity": sim, "passed": sim >= 0.65,
         "dimensions": {}, "deviations": [], "fixes": [], "summary": ""}
    if blank is not None:
        r["blank"] = blank
    return r


def _persist(tmp, results):
    vf._persist_verdict(tmp, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return {s["name"]: s
            for s in json.loads((Path(tmp) / "design" / "visual_gate" / "verdict.json")
                                .read_text(encoding="utf-8"))["screens"]}


def test_a_blank_live_capture_says_so_on_the_record(tmp_path):
    """r111's shape: recorded 0.62, this round's DOM probe found the page empty."""
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False)])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True)])["comments_panel"]
    assert s["similarity"] == 0.62, "#500's high-water must survive"
    assert s["similarity_live"] == 0.00
    assert s["blank_live"] is True, (
        "the live zero must carry the one field that explains it — otherwise the record "
        "reads 0.00 beside three fields saying nothing failed")


def test_the_kept_records_own_blank_is_not_overwritten(tmp_path):
    """#931's invariant: every unsuffixed field describes the RECORDED capture."""
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False)])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True)])["comments_panel"]
    assert s.get("blank") is False, (
        "dimensions/deviations/screenshot all describe the kept 0.62 capture; `blank` "
        "must keep describing it too, or #931's rule holds for every field but this one")


def test_a_live_zero_that_was_not_blank_says_that_too(tmp_path):
    """Non-vacuity: the flag must track the input, not be hardcoded truthy."""
    _persist(tmp_path, [_res("player", 0.88, blank=False)])
    s = _persist(tmp_path, [_res("player", 0.00, blank=False)])["player"]
    assert s["similarity_live"] == 0.00
    assert s["blank_live"] is False, "a rendered page that merely scored 0.00 is a different bug"


def test_a_screen_not_captured_has_no_live_blank_state(tmp_path):
    """Absent would read as False — 'not blank' — for a screen nobody photographed."""
    _persist(tmp_path, [_res("player", 0.88, blank=False), _res("landing", 0.40)])
    _persist(tmp_path, [_res("player", 0.00, blank=True), _res("landing", 0.40)])
    s = _persist(tmp_path, [_res("landing", 0.45)])["player"]
    assert s["similarity_live"] is None
    assert "blank_live" in s and s["blank_live"] is None, (
        "not captured is neither blank nor rendered")


def test_the_note_names_every_live_field(tmp_path):
    """One fact, two emitters: the note enumerates the live fields and must stay in step."""
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False)])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True)])["comments_panel"]
    note = s["similarity_live_note"]
    for f in ("similarity_live", "capture_missing_live", "capture_error_live", "blank_live"):
        assert f"`{f}`" in note, f"{f} missing from the note that lists the live fields"
