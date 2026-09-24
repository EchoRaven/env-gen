r"""#1202di: `--list-snapshots` shows size, not whether the snapshot is worth restoring.

The listing prints name, kind, file count and megabytes. None of that answers the only
question an operator actually has at the moment of choosing: *was this run healthy here?*

netflix-r43 (2026-09-04) is the case. A port clash meant the visual gate could not boot the
app for the whole run, so all four of its snapshots were taken inside a poisoned window —
every one of them `total_judgments: 0`. Restoring any of them continues a run that has
never scored a screen, and nothing in the listing said so. The same shape repeated the next
day with a full disk: r43's second attempt snapshotted twice, both at `total_judgments: 0`.

The data is already in the snapshot. #1202cs put `design/visual_gate` (JSON only) inside it
and `run_budget.json` was always there. This only reads what is on disk and shows it.

The distinction that matters, and the one this codebase keeps having to relearn: a snapshot
with NO gate state has not been measured, and must not report `0`. "Not measured" reading as
"zero" is how #1039's dead audit looked clean, and it is what `live_row_counts_1039`'s own
docstring warns about — "an empty result must mean 'not measured' and is never interpreted
as 'every table is empty'".
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.run_snapshot import list_snapshots


def _snap(root: Path, name: str, *, gate: dict | None = None, budget: dict | None = None):
    d = root / "snapshots" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"files": 3, "bytes": 1234}), encoding="utf-8")
    if gate is not None:
        g = d / "design" / "visual_gate"
        g.mkdir(parents=True, exist_ok=True)
        (g / "gate_state.json").write_text(json.dumps(gate), encoding="utf-8")
    if budget is not None:
        (d / "run_budget.json").write_text(json.dumps(budget), encoding="utf-8")
    return d


def test_a_poisoned_snapshot_is_visible_as_such(tmp_path):
    """r43's snapshots: taken during the outage, zero screens ever judged."""
    _snap(tmp_path, "20260905-110203-interval-t6",
          gate={"total_judgments": 0, "plateau_rounds": 7, "passed": False},
          budget={"usage": {"ticks": 6}, "llm": {"usd": 84.34}})
    (rec,) = list_snapshots(tmp_path)
    assert rec["judgments"] == 0
    assert rec["plateau"] == 7
    assert rec["ticks"] == 6
    assert rec["usd"] == pytest.approx(84.34)


def test_a_healthy_snapshot_reports_its_judgments(tmp_path):
    _snap(tmp_path, "20260905-120000-interval-t20",
          gate={"total_judgments": 4, "plateau_rounds": 0, "passed": False},
          budget={"usage": {"ticks": 20}, "llm": {"usd": 210.5}})
    (rec,) = list_snapshots(tmp_path)
    assert rec["judgments"] == 4
    assert rec["plateau"] == 0


def test_no_gate_state_is_unknown_not_zero(tmp_path):
    """The #1039 lesson: 'not measured' must never render as 'measured zero'."""
    _snap(tmp_path, "20260905-104543-milestone-m1", gate=None,
          budget={"usage": {"ticks": 0}, "llm": {"usd": 8.3}})
    (rec,) = list_snapshots(tmp_path)
    assert rec["judgments"] is None, (
        "a snapshot taken before the gate existed reported 0 judgments, which reads as "
        "'this run judged nothing' rather than 'this was not measured'")
    assert rec["plateau"] is None


def test_a_missing_budget_degrades_without_raising(tmp_path):
    _snap(tmp_path, "20260905-104543-milestone-m1", gate={"total_judgments": 2})
    (rec,) = list_snapshots(tmp_path)
    assert rec["judgments"] == 2
    assert rec["usd"] is None and rec["ticks"] is None


def test_corrupt_json_does_not_break_the_listing(tmp_path):
    d = _snap(tmp_path, "20260905-130000-interval-t9", gate={"total_judgments": 1})
    (d / "run_budget.json").write_text("{not json", encoding="utf-8")
    (rec,) = list_snapshots(tmp_path)
    assert rec["judgments"] == 1
    assert rec["usd"] is None


def test_the_existing_fields_are_untouched(tmp_path):
    _snap(tmp_path, "20260905-140000-interval-t3", gate={"total_judgments": 3})
    (rec,) = list_snapshots(tmp_path)
    assert rec["name"] == "20260905-140000-interval-t3"
    assert rec["files"] == 3 and rec["bytes"] == 1234
    assert rec["kind"]
