r"""#641: the selection itself — a pure function, so it is written now, not deferred with the data.

#640 started recording `(code_state, live score)` per capture round. I then said choosing on it
"needs one run's data". That is true of the DATA and false of the LOGIC, and saying it about a
pure function was the last hiding place of a deferral I have now been wrong about four times
(#630, #638, #639, #640).

What it is for: #618 measured that **24 of 39 runs deliver a state worse than their own best**, by
up to +0.44. Only **1 of 40** verdicts ever passed, so release comes through the bounded escape,
which ships whatever the last round happened to leave — not the best one.

Three rules, each a consequence of what the ledger means:

  * rank on `blocking_average_live`, THIS capture's score. `blocking_average` is #500's
    best-of-captures MERGE across rounds, so ranking rounds by it compares each round against a
    mixture that already contains the others.
  * a round with no `code_state` is unusable — there is no tree to go back to.
  * ties go to the EARLIER round: it has survived longer, and later rounds may carry unrelated
    regressions.

It emits a RECOMMENDATION onto the verdict and changes no decision. Acting on it is a release-path
change, and unlike #630 its blast radius cannot be computed yet — the ledger it would read does
not exist in any kept run. That is now a statement about one missing input, not about the idea.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _ledger(tmp_path, rows):
    d = tmp_path / "design" / "visual_gate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "rounds.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return d


def _r(sha, live, **kw):
    return {"code_state": sha, "blocking_average_live": live, **kw}


# --- picking the best -------------------------------------------------------------------------

def test_it_picks_the_highest_live_score(tmp_path):
    d = _ledger(tmp_path, [_r("aaa", 0.31), _r("bbb", 0.62), _r("ccc", 0.44)])
    assert vf.best_recorded_round_641(d)["code_state"] == "bbb"


def test_it_ranks_on_the_LIVE_score_not_the_merge(tmp_path):
    """`blocking_average` is #500's best-of merge — ranking on it compares a round to a mixture
    that already contains the others."""
    d = _ledger(tmp_path, [_r("aaa", 0.20, blocking_average=0.99),
                           _r("bbb", 0.55, blocking_average=0.55)])
    assert vf.best_recorded_round_641(d)["code_state"] == "bbb"


def test_a_round_with_no_commit_is_unusable(tmp_path):
    d = _ledger(tmp_path, [{"code_state": None, "blocking_average_live": 0.9},
                           _r("bbb", 0.40)])
    assert vf.best_recorded_round_641(d)["code_state"] == "bbb"


def test_a_tie_goes_to_the_earlier_round(tmp_path):
    d = _ledger(tmp_path, [_r("early", 0.50), _r("late", 0.50)])
    assert vf.best_recorded_round_641(d)["code_state"] == "early"


def test_no_ledger_yet_is_None(tmp_path):
    assert vf.best_recorded_round_641(tmp_path / "design" / "visual_gate") is None


def test_a_corrupt_line_is_skipped_not_fatal(tmp_path):
    d = tmp_path / "design" / "visual_gate"
    d.mkdir(parents=True)
    (d / "rounds.jsonl").write_text('{"bad json\n' + json.dumps(_r("ok", 0.5)) + "\n",
                                    encoding="utf-8")
    assert vf.best_recorded_round_641(d)["code_state"] == "ok"


def test_a_non_numeric_score_is_ignored(tmp_path):
    d = _ledger(tmp_path, [_r("x", "high"), _r("y", 0.10)])
    assert vf.best_recorded_round_641(d)["code_state"] == "y"


# --- the recommendation -----------------------------------------------------------------------

def test_it_reports_a_better_earlier_state(tmp_path):
    d = _ledger(tmp_path, [_r("good", 0.70)])
    out = vf.better_state_available_641(d, 0.30)
    assert out["code_state"] == "good" and out["delta"] == pytest.approx(0.40)


def test_it_stays_silent_when_now_is_best(tmp_path):
    d = _ledger(tmp_path, [_r("old", 0.30)])
    assert vf.better_state_available_641(d, 0.70) is None


def test_a_hairs_breadth_difference_is_noise(tmp_path):
    """The judge is not exactly repeatable; reverting on noise would churn the tree."""
    d = _ledger(tmp_path, [_r("old", 0.501)])
    assert vf.better_state_available_641(d, 0.50) is None


def test_the_margin_is_adjustable(tmp_path):
    d = _ledger(tmp_path, [_r("old", 0.53)])
    assert vf.better_state_available_641(d, 0.50, margin=0.10) is None
    assert vf.better_state_available_641(d, 0.50, margin=0.01)["code_state"] == "old"


def test_a_missing_current_score_reports_nothing(tmp_path):
    d = _ledger(tmp_path, [_r("good", 0.70)])
    assert vf.better_state_available_641(d, None) is None


# --- how it reaches the verdict ------------------------------------------------------------------

def _persist(root, sim):
    (root / "design" / "visual_gate").mkdir(parents=True, exist_ok=True)
    vf._persist_verdict(str(root), passed=False, min_similarity=0.65, summary="s", coverage={},
                        results=[{"name": "login", "route": "/login", "similarity": sim}])
    return json.loads((root / "design" / "visual_gate" / "verdict.json")
                      .read_text(encoding="utf-8"))


def test_the_first_round_has_nothing_to_compare_against(tmp_path):
    assert "better_state_available" not in _persist(tmp_path, 0.60)


def test_it_changes_no_decision(tmp_path):
    """A recommendation must not flip the gate."""
    _persist(tmp_path, 0.60)
    v = _persist(tmp_path, 0.10)
    assert v["passed"] is False
    assert v["blocking_average_live"] == pytest.approx(0.10)


def test_the_note_names_the_commit_and_the_gap(tmp_path):
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    i = src.index("#641: computed BEFORE this round joins the ledger")
    block = src[i:src.index('(vdir / "verdict.json").write_text', i)]
    assert "better_state_available" in block and "24 of 39 runs" in block


def test_the_comparison_excludes_the_round_being_written(tmp_path):
    """Computed before the append, so a round can never recommend itself."""
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    assert (src.index("better_state_available_641(vdir")
            < src.index("_append_round_record_640(vdir"))


def test_why_acting_on_it_still_waits_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(vf.better_state_available_641).split())
    assert "changes no decision here" in flat
    assert "24 of 39 runs" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
