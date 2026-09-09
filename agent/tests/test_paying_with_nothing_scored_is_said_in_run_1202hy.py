r"""#1202hy: "nothing scored" was only ever said after the run was over.

#1202di put "⚠ NOTHING SCORED" in the snapshot listing — read when someone is choosing
what to rewind to, which is after the money is gone. Across seven runs on this corpus,
$814 accumulated in states where the visual gate had never judged a single screen.

Validated against the run that DELIVERED before being believed, because "no screens yet"
could simply be what the first minutes of any run look like:

    r97 (delivered)   first snapshot ALREADY judged=1 at $43; no zero-judgment snapshot
    r106              judged=0 through $165 before the first score
    r102              judged=0 at EVERY snapshot — it never scored anything

Replayed against r106's own snapshots, the warning fires at $96 and $165 and stays
silent at $48 (under the floor) and at $49-after-scoring — and silent on all of r97.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import run_snapshot as RS


@pytest.fixture(autouse=True)
def _unlatched(monkeypatch):
    RS._NOTHING_SCORED_WARNED_1202HY.clear()
    monkeypatch.delenv("ENVGEN_NOTHING_SCORED_WARN_USD", raising=False)
    yield
    RS._NOTHING_SCORED_WARNED_1202HY.clear()


def _run(tmp: Path, usd=None, judged=None) -> Path:
    if usd is not None:
        (tmp / "run_budget.json").write_text(json.dumps({"llm": {"usd": usd}}))
    if judged is not None:
        g = tmp / "design" / "visual_gate"
        g.mkdir(parents=True, exist_ok=True)
        (g / "gate_state.json").write_text(json.dumps({"total_judgments": judged}))
    return tmp


def test_it_warns_when_money_went_and_nothing_was_judged(tmp_path):
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=96.0, judged=0))


def test_it_is_silent_once_a_screen_has_been_judged(tmp_path):
    """r97 judged by $43 and must never be nagged."""
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=430.0, judged=1)) is None


def test_it_is_silent_below_the_floor(tmp_path):
    """r106's $48 snapshot is under it; a run legitimately builds before it can be shot."""
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=48.0, judged=0)) is None


def test_a_gate_that_has_not_run_is_not_reported_as_stalled(tmp_path):
    """NOT MEASURED is not 'judged nothing' — the #1202di rule.

    Two distinct shapes, and only the second reaches the `judged is None` branch: a
    MISSING gate file returns earlier via the read guard, so a test that only covers
    that one passes even with the branch deleted. The counter-proof caught exactly that.
    """
    # (a) no gate file at all
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=500.0)) is None


def test_a_gate_file_without_a_verdict_is_not_reported_as_stalled(tmp_path):
    """(b) the file exists but carries no total_judgments — measured NOTHING, not zero."""
    RS._NOTHING_SCORED_WARNED_1202HY.clear()
    (tmp_path / "run_budget.json").write_text(json.dumps({"llm": {"usd": 500.0}}))
    g = tmp_path / "design" / "visual_gate"
    g.mkdir(parents=True)
    g.joinpath("gate_state.json").write_text(json.dumps({"attempts": 2}))
    assert RS._warn_if_nothing_scored_1202hy(tmp_path) is None, (
        "a gate with no verdict must not be reported as a run that judged nothing")


def test_a_missing_ledger_is_silent(tmp_path):
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, judged=0)) is None


def test_it_warns_once_per_run(tmp_path):
    d = _run(tmp_path, usd=200.0, judged=0)
    assert RS._warn_if_nothing_scored_1202hy(d)
    for _ in range(4):
        assert RS._warn_if_nothing_scored_1202hy(d) is None


def test_two_runs_each_get_their_own_warning(tmp_path):
    a = _run(tmp_path / "a", usd=200.0, judged=0) if (tmp_path / "a").mkdir() or True else None
    b = _run(tmp_path / "b", usd=200.0, judged=0) if (tmp_path / "b").mkdir() or True else None
    assert RS._warn_if_nothing_scored_1202hy(a)
    assert RS._warn_if_nothing_scored_1202hy(b), "the latch must be per run, not global"


def test_the_floor_is_tunable_and_zero_silences(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "0")
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=900.0, judged=0)) is None


def test_a_junk_floor_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "nope")
    assert RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=96.0, judged=0))


def test_corrupt_files_never_raise(tmp_path):
    (tmp_path / "run_budget.json").write_text("{oops")
    assert RS._warn_if_nothing_scored_1202hy(tmp_path) is None


def test_the_message_says_what_to_check_and_that_it_is_only_a_warning(tmp_path):
    m = RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=165.0, judged=0))
    assert "backend_health" in m, "name the usual cause, not just the symptom"
    assert "Warning only" in m
    assert "ENVGEN_NOTHING_SCORED_WARN_USD" in m


def test_it_goes_through_a_logger_when_given_one(tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        RS._warn_if_nothing_scored_1202hy(_run(tmp_path, usd=96.0, judged=0), RS._LOG_1202HY)
    assert any("#1202hy" in r.getMessage() for r in caplog.records)


# --- reachability: both snapshot cadences must call it -------------------------------

def test_both_maybe_snapshot_paths_call_it():
    """A warner nothing calls is the defect it was written to fix."""
    import ast, inspect
    src = inspect.getsource(RS.maybe_snapshot)
    calls = [n for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_warn_if_nothing_scored_1202hy"]
    assert len(calls) == 2, (
        "milestone and interval are separate returns; a call on only one leaves the "
        f"other cadence silent (found {len(calls)})")
