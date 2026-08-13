r"""#640: the per-round score was never written, so "ship the best commit" stayed undecidable.

I deferred that selection three times, most recently saying its counterfactual "is not computable
— `code_state` exists in 0 of the 40 kept verdict.json files". Having just written the rule that
*"no artifact can settle this" is itself a claim, and cheaper to test than to defend*, I tested
it. The claim was half wrong, and the half that was right had a different cause:

  * `round -> commit` IS recoverable for past runs. Captures are written as
    `design/visual_gate/history/HHMMSS_<screen>.png`, and codehub records every commit with
    `created_at`. That join was never the missing piece.
  * `round -> score` is recorded NOWHERE. `verdict.json` is ONE file, overwritten every round,
    holding the #500 best-of merge rather than this capture. The history holds images. The run
    log prints coverage and milestone scope, and no similarity at all — grepping 45 logs for a
    per-round score returns nothing.

So `code_state` alone could not have made the decision possible on the next run either: the score
to compare it against would still be gone by the time the run ended. #618's finding — **24 of 39
runs ship a state worse than their own best**, by up to +0.44 — stays unactionable until the pair
is persisted. This writes it.
"""
import json
import os
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _persist(root, sim, name="login"):
    (root / "design" / "visual_gate").mkdir(parents=True, exist_ok=True)
    vf._persist_verdict(str(root), passed=False, min_similarity=0.65, summary="s", coverage={},
                        results=[{"name": name, "route": "/login", "similarity": sim}])


def _rows(root):
    p = root / "design" / "visual_gate" / "rounds.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# --- one line per round ---------------------------------------------------------------------------

def test_a_round_is_recorded(tmp_path):
    _persist(tmp_path, 0.42)
    assert len(_rows(tmp_path)) == 1


def test_every_round_appends_rather_than_overwriting(tmp_path):
    """verdict.json is overwritten each round — that is exactly why the series was lost."""
    for s in (0.30, 0.55, 0.41):
        _persist(tmp_path, s)
    assert [r["blocking_average_live"] for r in _rows(tmp_path)] == [0.30, 0.55, 0.41]


def test_it_records_THIS_capture_not_the_best_of_merge(tmp_path):
    """#500 keeps the max per screen in verdict.json; the round record must not inherit that."""
    _persist(tmp_path, 0.80)
    _persist(tmp_path, 0.20)
    last = _rows(tmp_path)[-1]
    assert last["blocking_average_live"] == pytest.approx(0.20)
    assert last["blocking_average"] == pytest.approx(0.80)   # the merge, for contrast


def test_the_commit_is_on_the_same_line_as_the_score(tmp_path):
    """The whole point: a score with no tree, or a tree with no score, decides nothing."""
    _persist(tmp_path, 0.42)
    row = _rows(tmp_path)[0]
    assert "code_state" in row and "blocking_average_live" in row


def test_per_screen_live_scores_are_kept(tmp_path):
    _persist(tmp_path, 0.42, name="browse")
    assert _rows(tmp_path)[0]["live"] == {"browse": 0.42}


def test_the_round_is_timestamped(tmp_path):
    _persist(tmp_path, 0.42)
    assert isinstance(_rows(tmp_path)[0]["at"], (int, float))


def test_the_bar_is_recorded_so_pass_fail_can_be_recomputed(tmp_path):
    _persist(tmp_path, 0.42)
    row = _rows(tmp_path)[0]
    assert row["min_similarity"] == 0.65 and row["passed"] is False


# --- it must never endanger the gate ----------------------------------------------------------------

def test_an_unwritable_history_does_not_fail_the_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(vf, "_append_round_record_640",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    _persist(tmp_path, 0.42)
    assert (tmp_path / "design" / "visual_gate" / "verdict.json").is_file()


def test_it_is_written_AFTER_the_verdict(tmp_path):
    """The verdict is the product; the record is bookkeeping and must never precede it."""
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    assert (src.index('(vdir / "verdict.json").write_text')
            < src.index("_append_round_record_640(vdir"))


def test_a_bad_results_list_is_tolerated(tmp_path):
    (tmp_path / "design" / "visual_gate").mkdir(parents=True)
    vf._append_round_record_640(tmp_path / "design" / "visual_gate", {}, None)
    vf._append_round_record_640(tmp_path / "design" / "visual_gate", {}, [None, "x"])
    assert len(_rows(tmp_path)) == 2


# --- why it exists ------------------------------------------------------------------------------

def test_the_tested_claim_is_recorded():
    """Both halves — what WAS recoverable and what genuinely was not."""
    import inspect
    flat = " ".join(inspect.getsource(vf._append_round_record_640).split())
    assert "That join was never the missing piece" in flat
    assert "recorded NOWHERE" in flat
    assert "24 of 39 runs ship a state worse than their own best" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
