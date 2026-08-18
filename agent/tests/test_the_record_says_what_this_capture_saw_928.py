r"""#928: the per-screen record was high-water only, so a collapsed screen read as a good one.

#500 merges each screen with the prior verdict and keeps the MAX, which is right for
MEASUREMENT — a screen that renders once should not be scored 0.00 by a capture taken mid-rebuild.
The aggregate already reports the other side of that trade (`blocking_average_live`, and #711's
`record_exceeds_live_by`). The eight per-screen numbers a reader actually looks at carried no such
mark: every one of them was the best capture ever taken, with one aggregate caveat beside them.

Measured over the runs holding both `verdict.json` and `rounds.jsonl`:

    runs with a screen recorded above its last live capture   8 of 10
    screens affected                                          46   median gap 0.54, max 0.88
    ★ recorded >=0.40 while the live capture was <=0.05       24

r148 is five of those 24 — browse_home 0.80/0.00, new_and_popular 0.75/0.00, my_list 0.72/0.00,
movies 0.70/0.00, games 0.62/0.00 — which is how the run whose SPA crashed on every route came to
record ~0.7 fidelity. r154 produced the same shape live while this was being written:
title_detail 0.60 -> 0.00 and movies 0.62 -> 0.05, with landing IMPROVING 0.40 -> 0.72 in the same
round, so "worse by 0.20" spread over eight screens is not what happened to any of them.

The fix keeps #500's number and adds what this capture saw next to it.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _res(name, sim, route="/x"):
    return {"name": name, "route": route, "similarity": sim, "passed": sim >= 0.65,
            "dimensions": {}, "deviations": [], "fixes": [], "summary": ""}


def _persist(tmp, results, **kw):
    vf._persist_verdict(tmp, passed=False, min_similarity=0.65, summary="s",
                        coverage=kw.get("coverage") or {}, results=results)
    return json.loads((Path(tmp) / "design" / "visual_gate" / "verdict.json")
                      .read_text(encoding="utf-8"))


def _by_name(v):
    return {s["name"]: s for s in v["screens"]}


# --------------------------------------------------------------------------- the merge

def test_a_collapsed_screen_carries_what_this_capture_saw(tmp_path):
    """★ r148's shape: recorded 0.80, this capture 0.00."""
    _persist(tmp_path, [_res("browse_home", 0.80)])
    v = _persist(tmp_path, [_res("browse_home", 0.00)])
    s = _by_name(v)["browse_home"]
    assert s["similarity"] == 0.80, "#500's high-water must survive — that is its purpose"
    assert s["similarity_live"] == 0.00, "and the record must say the app renders 0.00 now"
    assert "#928" in s["similarity_live_note"]


def test_an_improving_screen_gets_no_divergence_mark(tmp_path):
    _persist(tmp_path, [_res("landing", 0.40)])
    v = _persist(tmp_path, [_res("landing", 0.72)])
    s = _by_name(v)["landing"]
    assert s["similarity"] == 0.72
    assert "similarity_live" not in s, "nothing diverged; do not annotate a screen that improved"


def test_an_equal_score_is_not_a_divergence(tmp_path):
    _persist(tmp_path, [_res("games", 0.55)])
    v = _persist(tmp_path, [_res("games", 0.55)])
    assert "similarity_live" not in _by_name(v)["games"]


def test_the_top_level_list_names_exactly_the_collapsed_screens(tmp_path):
    """★ The point of the ticket: 'worse by 0.20' reads like eight screens each a little dimmer.
    r154 was two screens falling to zero while a third improved."""
    _persist(tmp_path, [_res("title_detail", 0.60), _res("movies", 0.62), _res("landing", 0.40)])
    v = _persist(tmp_path, [_res("title_detail", 0.00), _res("movies", 0.05), _res("landing", 0.72)])
    assert v["screens_below_record_928"] == ["movies", "title_detail"]


def test_no_list_when_nothing_diverged(tmp_path):
    _persist(tmp_path, [_res("landing", 0.40)])
    v = _persist(tmp_path, [_res("landing", 0.72)])
    assert "screens_below_record_928" not in v


def test_a_first_capture_has_no_divergence(tmp_path):
    v = _persist(tmp_path, [_res("landing", 0.10)])
    assert "screens_below_record_928" not in v
    assert "similarity_live" not in _by_name(v)["landing"]


# --------------------------------------------------------------------------- carry-over

def test_a_screen_not_captured_this_round_says_so(tmp_path):
    """★ The same lie one level down: a screen this capture never photographed must not keep a
    `similarity_live` earned in an earlier round."""
    _persist(tmp_path, [_res("player", 0.88), _res("landing", 0.40)])
    _persist(tmp_path, [_res("player", 0.00), _res("landing", 0.40)])   # player collapses
    v = _persist(tmp_path, [_res("landing", 0.45)])                      # player not captured
    s = _by_name(v)["player"]
    assert s["similarity"] == 0.88
    assert s["similarity_live"] is None, "not captured is not 'rendered 0.00'"
    assert "not captured" in s["similarity_live_note"]


def test_a_carried_over_screen_is_not_in_the_collapsed_list(tmp_path):
    """It did not collapse — it was not looked at. Naming it would send a lane to fix a page
    nobody photographed (#714's lesson, one field over)."""
    _persist(tmp_path, [_res("player", 0.88), _res("landing", 0.40)])
    v = _persist(tmp_path, [_res("landing", 0.45)])
    assert "player" not in (v.get("screens_below_record_928") or [])


def test_a_stale_live_value_does_not_survive_a_recapture(tmp_path):
    """Round 2 collapses, round 3 recovers: the record must show round 3, not round 2."""
    _persist(tmp_path, [_res("movies", 0.70)])
    v2 = _persist(tmp_path, [_res("movies", 0.05)])
    assert v2["screens"][0]["similarity_live"] == 0.05
    v3 = _persist(tmp_path, [_res("movies", 0.68)])
    s = _by_name(v3)["movies"]
    assert s["similarity"] == 0.70
    assert s["similarity_live"] == 0.68, "the live value must track the LATEST capture"


# --------------------------------------------------------------------------- it changes nothing else

def test_the_recorded_average_and_pass_are_untouched(tmp_path):
    """#500's docstring: verdict.json is diagnostic-only. This must stay a pure addition."""
    _persist(tmp_path, [_res("a", 0.80), _res("b", 0.60)])
    v = _persist(tmp_path, [_res("a", 0.00), _res("b", 0.60)])
    assert v["blocking_average"] == pytest.approx(0.70), v["blocking_average"]
    assert [s["similarity"] for s in sorted(v["screens"], key=lambda x: x["name"])] == [0.80, 0.60]


def test_every_prior_field_survives_the_annotation(tmp_path):
    """`{**p, ...}` must add, not replace — #771/#771b lost three fields to a fixed-key
    projection on this same path."""
    first = _res("browse_home", 0.80)
    first.update({"screenshot": "/s.png", "reference": "/r.jpg", "console_errors": ["boom"],
                  "deviations": [{"d": 1}]})
    _persist(tmp_path, [first])
    v = _persist(tmp_path, [_res("browse_home", 0.00)])
    s = _by_name(v)["browse_home"]
    for k, expect in (("screenshot", "/s.png"), ("reference", "/r.jpg"),
                      ("console_errors", ["boom"]), ("deviations", [{"d": 1}])):
        assert s.get(k) == expect, (k, s.get(k))


def test_the_note_says_whose_evidence_the_other_fields_are(tmp_path):
    """#931: `similarity_live: 0.00` sits beside a deviations list that describes the RECORDED
    capture. A reader takes that list as the reason for the 0.00; it is the reason the BETTER
    capture fell short of 1.0. Verified first that no lane is misdirected by it —
    `remediation_text` is called with `run_visual_fidelity`'s live return value, not this file."""
    first = _res("title_detail", 0.60)
    first["deviations"] = ["Title placement: reference overlays the title on the hero image"]
    _persist(tmp_path, [first])
    v = _persist(tmp_path, [_res("title_detail", 0.00)])
    s = _by_name(v)["title_detail"]
    assert s["deviations"] == first["deviations"], "the recorded capture's evidence is kept"
    assert "describe the RECORDED capture" in s["similarity_live_note"], s["similarity_live_note"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
