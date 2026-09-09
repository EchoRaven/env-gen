r"""#1202hx: many restore points, and nothing said which one was the good state.

#1202bw stores them and #1202di says whether each had judged anything — which separates
a snapshot of a run that could not boot from one that could, and stops there. Choosing
between the ones that DID score was done by reading timestamps, and the newest is not
the best: r106's last interval held 1 of 9 screens at a 0.34 median while blocked on two
framework checks, against a milestone minutes earlier holding the same screens blocked
on one.

Both numbers were already inside every snapshot (#1202cs put design/ there). Nothing new
is captured; the listing stops throwing the answer away.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import run_snapshot as RS


def _snap(root: Path, name: str, *, scores=None, fwval=None, stuck=None) -> Path:
    d = root / name
    (d / "design" / "visual_gate").mkdir(parents=True, exist_ok=True)
    if scores is not None:
        (d / "design" / "visual_gate" / "gate_state.json").write_text(json.dumps(
            {"_best_by_screen": {f"s{i}": v for i, v in enumerate(scores)}}))
    if fwval is not None or stuck is not None:
        payload = {}
        if fwval is not None:
            payload["_fwval_failure_set"] = fwval
        if stuck is not None:
            payload["_fwdeliver_stuck_count"] = stuck
        (d / "design" / "milestone_gates.json").write_text(json.dumps(payload))
    return d


# --- reading quality out of a snapshot --------------------------------------------

def test_it_counts_screens_over_the_threshold(tmp_path):
    q = RS._snapshot_quality_1202hx(_snap(tmp_path, "a", scores=[0.9, 0.7, 0.64, 0.2]))
    assert q["screens_total"] == 4
    assert q["screens_pass"] == 2          # 0.9, 0.7 — 0.64 is under 0.65
    # Upper median on an even count, the convention the rest of this corpus reports with.
    assert q["visual_med"] == 0.7


def test_a_dict_shaped_score_is_read_too(tmp_path):
    """_best_by_screen carries bare floats in some runs and {score: x} in others."""
    d = _snap(tmp_path, "b")
    (d / "design" / "visual_gate" / "gate_state.json").write_text(json.dumps(
        {"_best_by_screen": {"x": {"score": 0.8}, "y": {"score": 0.5}}}))
    q = RS._snapshot_quality_1202hx(d)
    assert q["screens_pass"] == 1 and q["screens_total"] == 2


def test_not_measured_is_none_never_zero(tmp_path):
    """A snapshot older than the gate dir has NO verdict — different from 'scored 0'."""
    q = RS._snapshot_quality_1202hx(_snap(tmp_path, "c"))
    assert q["screens_pass"] is None and q["visual_med"] is None
    assert q["fwval_failed"] is None


def test_an_empty_failure_set_is_distinguished_from_unmeasured(tmp_path):
    q = RS._snapshot_quality_1202hx(_snap(tmp_path, "d", scores=[0.7], fwval=[]))
    assert q["fwval_failed"] == [], "no blocking checks is a FACT, not a missing one"


def test_it_reads_the_blocking_checks(tmp_path):
    q = RS._snapshot_quality_1202hx(
        _snap(tmp_path, "e", scores=[0.7], fwval=["business_chain", "backend_health"],
              stuck=3))
    assert q["fwval_failed"] == ["business_chain", "backend_health"]
    assert q["deliver_stuck"] == 3


def test_junk_files_never_raise(tmp_path):
    d = tmp_path / "f"
    (d / "design" / "visual_gate").mkdir(parents=True)
    (d / "design" / "visual_gate" / "gate_state.json").write_text("{not json")
    (d / "design" / "milestone_gates.json").write_text("[]")
    q = RS._snapshot_quality_1202hx(d)
    assert q["screens_pass"] is None and q["fwval_failed"] is None


# --- picking the best ---------------------------------------------------------------

def _rec(name, *, judgments=1, sp=None, med=None, fw=None, epoch=0.0):
    return {"name": name, "judgments": judgments, "screens_pass": sp,
            "visual_med": med, "fwval_failed": fw, "epoch": epoch}


def test_more_passing_screens_wins():
    best = RS.best_snapshot_1202hx([_rec("a", sp=1, med=0.9), _rec("b", sp=3, med=0.4)])
    assert best == "b"


def test_the_median_breaks_a_tie_on_count():
    """A run can hold its count while every screen improves."""
    best = RS.best_snapshot_1202hx([_rec("a", sp=2, med=0.40), _rec("b", sp=2, med=0.55)])
    assert best == "b"


def test_fewer_blocking_checks_breaks_a_tie_on_score():
    """r106's real case: same 1/9 at 0.34, one blocked on two checks and one on one."""
    best = RS.best_snapshot_1202hx([
        _rec("later", sp=1, med=0.34, fw=["auth_enforced_401", "business_chain"], epoch=2),
        _rec("earlier", sp=1, med=0.34, fw=["backend_health"], epoch=1)])
    assert best == "earlier", "the NEWEST is not the best; that is the whole point"


def test_a_snapshot_that_scored_nothing_is_never_best():
    """Restoring it resumes a run with no visual evidence at all (the #1202di trap)."""
    assert RS.best_snapshot_1202hx(
        [_rec("dead", judgments=0, sp=0, med=0.0)]) is None


def test_unmeasured_snapshots_are_not_ranked():
    assert RS.best_snapshot_1202hx([_rec("old", sp=None, med=None)]) is None


def test_no_snapshots_is_none():
    assert RS.best_snapshot_1202hx([]) is None


# --- reachability: the listing must actually SHOW it --------------------------------

def test_list_snapshots_merges_the_quality(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    _snap(root, "20260101-000000-interval-t1", scores=[0.9, 0.2], fwval=["x"])
    recs = RS.list_snapshots(tmp_path)
    assert recs and recs[0]["screens_pass"] == 1
    assert recs[0]["fwval_failed"] == ["x"]


def test_the_cli_prints_it_and_names_the_best():
    """A field nothing prints is a field nobody has."""
    src = (Path(RS.__file__).parents[2] / "main.py").read_text()
    assert "best_snapshot_1202hx" in src, "the picker is not imported by the CLI"
    i = src.index("if args.list_snapshots:")
    seg = src[i:src.index("res = restore_snapshot(", i)]
    assert "screens" in seg and "blocked on" in seg
    assert "BEST STATE TO RESUME FROM" in seg
    assert "--restore-snapshot" in seg, "it must say how to act on the answer"
