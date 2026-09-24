"""#1202cs — a snapshot must preserve the visual gate's ledger.

Snapshots existed to stop work being lost, but captured only `shared/hubs`, `.checkpoint`
and the design artifacts. `design/visual_gate/` was absent — and it is the ONLY record of
what a run has already WON: #500's best-ever-per-screen merge reads `verdict.json` back
off disk, and gate_state.json carries deferred_since / total_judgments / plateau_rounds.
Restoring without it resurrects a run that has forgotten every screen score it earned,
with the escape timer and plateau detection at zero — re-creating the "two rounds spent
re-winning points already won" failure inside the mechanism meant to prevent lost work.

The second half is the cost side: capturing the directory WHOLE was measured at 107MB
against 8.9MB for the rest, 97MB of it re-takeable PNGs. Disk is this project's binding
constraint and _KEEP multiplies every snapshot, so the images must stay out.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.run_snapshot import (
    take_snapshot,
    restore_snapshot,
)


def _make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "design/visual_gate/captures").mkdir(parents=True)
    (run / "design/visual_gate/history").mkdir(parents=True)
    (run / "shared/hubs").mkdir(parents=True)
    (run / "design/visual_gate/gate_state.json").write_text(json.dumps(
        {"total_judgments": 7, "plateau_rounds": 2, "released": False,
         "deferred_since": 1234.5}))
    (run / "design/visual_gate/verdict.json").write_text(json.dumps(
        {"screens": [{"name": "home", "similarity": 0.81}]}))
    (run / "design/visual_gate/rounds.jsonl").write_text('{"round": 1}\n')
    (run / "design/visual_gate/captures/home.png").write_bytes(b"\x89PNG" + b"x" * 5000)
    (run / "design/visual_gate/history/1_home.png").write_bytes(b"\x89PNG" + b"y" * 5000)
    (run / "design/visual_gate/home.png").write_bytes(b"\x89PNG" + b"z" * 5000)
    (run / "shared/hubs/workhub_tasks.json").write_text('{"t1": {"status": "completed"}}')
    (run / "run_budget.json").write_text('{"llm": {"usd": 1.0}, "usage": {}}')
    return run


def test_a_restored_run_remembers_the_scores_it_had_won(tmp_path):
    """The whole point: judgments, plateau state and the escape clock survive a restore."""
    run = _make_run(tmp_path)
    snap = Path(str(take_snapshot(run, kind="manual", label="rt")))

    import shutil
    shutil.rmtree(run / "design/visual_gate")

    restore_snapshot(run, snap.name)

    gate = json.loads((run / "design/visual_gate/gate_state.json").read_text())
    assert gate["total_judgments"] == 7
    assert gate["plateau_rounds"] == 2
    assert gate["deferred_since"] == 1234.5
    verdict = json.loads((run / "design/visual_gate/verdict.json").read_text())
    assert verdict["screens"][0]["similarity"] == 0.81


def test_the_images_are_left_out(tmp_path):
    """97MB of the 107MB was PNGs a resumed run re-takes. Capturing them would trade a
    lost-work bug for a full disk."""
    run = _make_run(tmp_path)
    snap = Path(str(take_snapshot(run, kind="manual", label="sz")))

    assert not list(snap.rglob("*.png"))
    captured = {p.name for p in (snap / "design/visual_gate").rglob("*") if p.is_file()}
    assert captured == {"gate_state.json", "verdict.json", "rounds.jsonl"}


def test_the_hub_ledger_is_still_captured_whole(tmp_path):
    """The json-only rule must apply to the gate directory ONLY — shared/hubs has no
    re-derivable half and narrowing it would silently drop coordination state."""
    run = _make_run(tmp_path)
    (run / "shared/hubs/blob.bin").write_bytes(b"\x00" * 16)
    snap = Path(str(take_snapshot(run, kind="manual", label="hub")))
    assert (snap / "shared/hubs/workhub_tasks.json").exists()
    assert (snap / "shared/hubs/blob.bin").exists()


def test_the_gate_directory_is_declared_json_only_not_wholesale(tmp_path):
    """Anchored on the declaration so adding it back to _STATE_DIRS — the obvious edit —
    fails here rather than in a 107MB snapshot nobody measures."""
    from env_generator.llm_generator.multi_agent.runtime import run_snapshot as rs

    def _covered_by(rules):
        # #1202ey widened the JSON-only rule from `design/visual_gate` to `design`, so the
        # literal no longer appears. The PROPERTY this guards is unchanged and is what is
        # asserted now: whatever rule reaches the gate directory must be a JSON-only one,
        # and no wholesale rule may reach it. Anchoring on the literal would have made a
        # correct generalisation look like the 107MB regression it exists to prevent.
        return any(p == "design/visual_gate" or "design/visual_gate".startswith(p + "/")
                   for p in rules)

    assert _covered_by(rs._STATE_DIRS_JSON_ONLY_1202CS)
    assert not _covered_by(rs._STATE_DIRS)
    assert set(rs._JSON_SUFFIXES_1202CS) == {".json", ".jsonl"}
