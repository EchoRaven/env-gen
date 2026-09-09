r"""#1202ia: a restore point is only worth something if the run can still reach a gate.

#1202hx ranks restore points by how good the run LOOKED, which is a different question
from whether resuming can pay off. The no-convergence abort spends a budget
(ENVGEN_NO_DELIVER_ABORT_S, lane time since the contract was built) that is cumulative
across every process over the output dir and is carried, correctly, into each snapshot's
own ledger. tiktok-r106's every restore point — the best one included — was taken with
79.6 of its 90 minutes already gone; restoring the best and resuming cost $70.27 and died
21 minutes later without reaching one gate evaluation.

★ It is a NUMBER, deliberately not a verdict. The first draft printed "DO NOT RESUME"
  when the budget was gone. Validating that against the run that DELIVERED killed it:
  tiktok-r97 cut release 1.0.0 with its budget already ~52 minutes NEGATIVE and ran on to
  -110 without ever aborting, because the abort needs BOTH an exhausted budget AND a
  declined delivery, and r97's deliveries were progressing (4/9 -> 5/9 screens).

  One death and one survival is not a calibration. These tests hold that line.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import run_snapshot as RS


def _snap(root: Path, name: str, alive_before=None, elapsed=None,
          alive_total=None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if alive_before is not None or elapsed is not None or alive_total is not None:
        cum = {}
        if alive_before is not None:
            cum["alive_before_this_run"] = alive_before
        if alive_total is not None:
            cum["alive_total"] = alive_total
        (d / "run_budget.json").write_text(json.dumps(
            {"cumulative_1202cg": cum,
             "usage": {} if elapsed is None else {"elapsed_sec": elapsed}}))
    return d


def test_it_reports_the_budget_that_is_left(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "5400")
    q = RS._snapshot_budget_1202ia(_snap(tmp_path, "a", alive_total=4773.2))
    assert q["budget_cap_s"] == 5400.0
    assert q["budget_left_s"] == pytest.approx(626.8, abs=0.1)   # r106: 10.4 min


def test_an_exhausted_budget_reports_negative_not_zero(tmp_path, monkeypatch):
    """r97 ran 110 minutes past it and delivered; clamping would hide how far past."""
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "5400")
    q = RS._snapshot_budget_1202ia(_snap(tmp_path, "b", alive_total=12042.0))
    assert q["budget_left_s"] < 0


def test_a_snapshot_without_a_ledger_is_unmeasured(tmp_path):
    q = RS._snapshot_budget_1202ia(_snap(tmp_path, "c"))
    assert q["budget_left_s"] is None and q["budget_cap_s"] is None


def test_a_corrupt_ledger_never_raises(tmp_path):
    d = _snap(tmp_path, "d")
    (d / "run_budget.json").write_text("{broken")
    assert RS._snapshot_budget_1202ia(d)["budget_left_s"] is None


def test_the_cap_follows_the_env_the_orchestrator_reads(monkeypatch):
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "1200")
    assert RS._abort_budget_s_1202ia() == 1200.0
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "junk")
    assert RS._abort_budget_s_1202ia() == 4500.0


def test_the_listing_carries_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "5400")
    root = tmp_path / "snapshots"
    _snap(root, "20260101-000000-interval-t1", alive_total=600.0)
    recs = RS.list_snapshots(tmp_path)
    assert recs and recs[0]["budget_left_s"] == pytest.approx(4800.0)


# --- the line that must not be crossed ---------------------------------------------

def test_there_is_no_futility_verdict():
    """r97 delivered with the budget 52 minutes gone. Any 'do not resume' built on this
    number alone would have talked its operator out of the only run that ever shipped."""
    assert not hasattr(RS, "resume_is_futile_1202ia"), (
        "a verdict on this number was tried and refuted by r97; keep it a number")


def test_the_cli_prints_the_number_and_no_verdict():
    src = (Path(RS.__file__).parents[2] / "main.py").read_text()
    i = src.index("if args.list_snapshots:")
    seg = src[i:src.index("res = restore_snapshot(", i)]
    assert "budget" in seg and "min left" in seg
    assert "DO NOT RESUME" not in seg


def test_the_counterexample_is_recorded_next_to_the_code():
    """The reason there is no verdict must survive the next person's good idea."""
    src = Path(RS.__file__).read_text()
    i = src.index("#1202ia:")
    seg = src[i:src.index("def best_snapshot_1202hx", i)]
    assert "r97" in seg and "NEGATIVE" in seg
    assert "not a calibration" in seg


# --- the bug the framework's own warning caught -------------------------------------

def test_a_never_resumed_run_is_not_reported_as_untouched(tmp_path, monkeypatch):
    """#1202ig: the first cut read `alive_before_this_run`, which is the time PREVIOUS
    processes spent and is 0 for a run that has never been resumed.

    Every one of tiktok-r107's snapshots was reported "budget 90min left" while the run
    had been alive 124 minutes, and the framework said so itself the moment a resume
    started: "#1202fw this run has ALREADY spent 124 min of lane time ... past the 90
    min". A tool built to stop a doomed resume was recommending one.
    """
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "5400")
    d = _snap(tmp_path, "r107", alive_before=0.0, elapsed=7471.0, alive_total=7470.6)
    q = RS._snapshot_budget_1202ia(d)
    assert q["budget_left_s"] < 0, "a run 35 minutes past its cap must not read as fresh"


def test_it_falls_back_to_before_plus_elapsed(tmp_path, monkeypatch):
    """Ledgers written before `alive_total` existed still have both halves."""
    monkeypatch.setenv("ENVGEN_NO_DELIVER_ABORT_S", "5400")
    q = RS._snapshot_budget_1202ia(
        _snap(tmp_path, "old", alive_before=1200.0, elapsed=1200.0))
    assert q["budget_left_s"] == pytest.approx(3000.0)


def test_it_matches_what_the_abort_bounds_by():
    """`_lane_time_1202fk` bounds lane time by alive_total; reading anything else here
    guarantees the listing and the abort disagree."""
    import inspect
    src = inspect.getsource(RS._snapshot_budget_1202ia)
    i = src.index("spent = ")
    assert 'cum.get("alive_total")' in src[i:i + 60]
