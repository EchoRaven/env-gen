"""#1202bw — restore points for a long run.

A run's state is already durable but is rewritten IN PLACE, so the only state a wedged run
has is the wedged state. These snapshots let an operator rewind to a tick that was still
making progress. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import run_snapshot as rs  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ENVGEN_SNAPSHOT_EVERY_MIN", "ENVGEN_SNAPSHOT_ON_MILESTONE",
              "ENVGEN_SNAPSHOT_KEEP"):
        monkeypatch.delenv(k, raising=False)
    rs._last_snapshot_ts.clear()
    yield
    rs._last_snapshot_ts.clear()


def _run_dir(tmp_path, tasks="original"):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "workhub_tasks.json").write_text(json.dumps({"t1": tasks}), encoding="utf-8")
    (hubs / "eventhub_events.json").write_text(json.dumps({"e1": "x"}), encoding="utf-8")
    (hubs / "workhub_tasks.json.lock").write_text("", encoding="utf-8")
    (hubs / "eventhub_events.json.4242.tmp").write_text("half", encoding="utf-8")
    (tmp_path / ".checkpoint").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (tmp_path / "run_budget.json").write_text(json.dumps({"llm": {"usd": 12.5}}), encoding="utf-8")
    return tmp_path


def test_snapshot_captures_the_hub_ledger_and_the_run_files(tmp_path):
    d = rs.take_snapshot(_run_dir(tmp_path), "manual")
    assert d is not None
    assert (d / "shared" / "hubs" / "workhub_tasks.json").is_file()
    assert (d / "shared" / "hubs" / "eventhub_events.json").is_file()
    assert (d / ".checkpoint").is_file()
    assert (d / "run_budget.json").is_file()


def test_locks_and_half_written_temps_are_never_captured(tmp_path):
    """#1202ap orphans are not state; a restored `.lock` would reinstate a stale sentinel."""
    d = rs.take_snapshot(_run_dir(tmp_path), "manual")
    names = {p.name for p in d.rglob("*") if p.is_file()}
    assert not any(n.endswith(".lock") for n in names)
    assert not any(n.endswith(".tmp") for n in names)


def test_manifest_records_what_was_captured(tmp_path):
    d = rs.take_snapshot(_run_dir(tmp_path), "milestone", "m2")
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["kind"] == "milestone" and m["label"] == "m2"
    assert m["files"] >= 4 and m["bytes"] > 0 and m["failed"] == []


def test_an_empty_run_dir_yields_no_snapshot(tmp_path):
    """An empty ledger is not a restore point; leaving a husk directory would make the
    listing lie about what can be rewound to."""
    assert rs.take_snapshot(tmp_path, "manual") is None
    assert not (rs.snapshots_root(tmp_path) / "x").exists()


def test_two_snapshots_in_one_second_do_not_merge(tmp_path):
    r = _run_dir(tmp_path)
    a = rs.take_snapshot(r, "manual")
    b = rs.take_snapshot(r, "manual")
    assert a is not None and b is not None and a != b


def test_interval_first_call_starts_the_clock_rather_than_snapshotting(tmp_path):
    r = _run_dir(tmp_path)
    assert rs.maybe_snapshot(r, "interval", "t1") is None
    assert rs.list_snapshots(r) == []


def test_interval_fires_once_due(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SNAPSHOT_EVERY_MIN", "20")
    r = _run_dir(tmp_path)
    assert rs.maybe_snapshot(r, "interval", "t1") is None
    rs._last_snapshot_ts[str(r)] = time.time() - 21 * 60
    assert rs.maybe_snapshot(r, "interval", "t2") is not None


def test_interval_zero_disables_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SNAPSHOT_EVERY_MIN", "0")
    r = _run_dir(tmp_path)
    rs._last_snapshot_ts[str(r)] = time.time() - 999 * 60
    assert rs.maybe_snapshot(r, "interval", "t9") is None


def test_milestone_snapshots_ignore_the_interval_clock(tmp_path):
    """A milestone boundary is a restore point regardless of when the last one was."""
    r = _run_dir(tmp_path)
    assert rs.maybe_snapshot(r, "milestone", "m1") is not None
    assert rs.maybe_snapshot(r, "milestone", "m2") is not None


def test_milestone_snapshots_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SNAPSHOT_ON_MILESTONE", "0")
    assert rs.maybe_snapshot(_run_dir(tmp_path), "milestone", "m1") is None


def test_retention_is_per_kind_so_interval_churn_cannot_evict_a_milestone(tmp_path,
                                                                         monkeypatch):
    """The design claim worth guarding: the last milestone boundary is usually the most
    valuable restore point, and under one global budget a long tail of interval snapshots
    would evict exactly that one."""
    monkeypatch.setenv("ENVGEN_SNAPSHOT_KEEP", "2")
    r = _run_dir(tmp_path)
    rs.take_snapshot(r, "milestone", "m1")
    for i in range(6):
        rs.take_snapshot(r, "interval", f"t{i}")
    kinds = [s["kind"] for s in rs.list_snapshots(r)]
    assert kinds.count("milestone") == 1, "the milestone restore point was evicted"
    assert kinds.count("interval") == 2


def test_retention_keeps_the_newest(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SNAPSHOT_KEEP", "2")
    r = _run_dir(tmp_path)
    for i in range(5):
        rs.take_snapshot(r, "interval", f"t{i}")
    labels = [s["label"] for s in rs.list_snapshots(r)]
    assert labels == ["t3", "t4"]


def test_keep_zero_retains_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_SNAPSHOT_KEEP", "0")
    r = _run_dir(tmp_path)
    for i in range(4):
        rs.take_snapshot(r, "interval", f"t{i}")
    assert len(rs.list_snapshots(r)) == 4


def test_restore_rewinds_the_ledger(tmp_path):
    r = _run_dir(tmp_path, tasks="original")
    snap = rs.take_snapshot(r, "milestone", "m1")
    live = r / "shared" / "hubs" / "workhub_tasks.json"
    live.write_text(json.dumps({"t1": "wedged"}), encoding="utf-8")

    res = rs.restore_snapshot(r, snap.name)
    assert res["ok"] is True
    assert json.loads(live.read_text(encoding="utf-8"))["t1"] == "original"


def test_restore_keeps_the_state_it_overwrote(tmp_path):
    """Rewinding to the wrong point must be undoable — restore is the one destructive
    operation here."""
    r = _run_dir(tmp_path, tasks="original")
    snap = rs.take_snapshot(r, "milestone", "m1")
    live = r / "shared" / "hubs" / "workhub_tasks.json"
    live.write_text(json.dumps({"t1": "wedged"}), encoding="utf-8")

    res = rs.restore_snapshot(r, snap.name)
    saved = Path(res["backup"]) / "shared" / "hubs" / "workhub_tasks.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["t1"] == "wedged"


def test_restore_does_not_copy_the_manifest_into_the_run(tmp_path):
    r = _run_dir(tmp_path)
    snap = rs.take_snapshot(r, "manual")
    rs.restore_snapshot(r, snap.name)
    assert not (r / "manifest.json").exists()


def test_restoring_an_unknown_snapshot_reports_instead_of_raising(tmp_path):
    res = rs.restore_snapshot(_run_dir(tmp_path), "nope")
    assert res["ok"] is False and "no such snapshot" in res["error"]


def test_listing_is_oldest_first_and_carries_the_kind(tmp_path):
    r = _run_dir(tmp_path)
    rs.take_snapshot(r, "milestone", "m1")
    rs.take_snapshot(r, "interval", "t1")
    got = rs.list_snapshots(r)
    assert [s["kind"] for s in got] == ["milestone", "interval"]


def test_pre_restore_backups_are_not_listed_as_restore_points(tmp_path):
    """They are dotted on purpose: offering one as a rewind target would hand the operator
    back the very state they just rewound away from."""
    r = _run_dir(tmp_path)
    snap = rs.take_snapshot(r, "manual")
    rs.restore_snapshot(r, snap.name)
    assert all(not s["name"].startswith(".") for s in rs.list_snapshots(r))


def test_orchestrator_snapshots_at_both_boundaries():
    """#943: landmark anchors. Both hooks must survive, and both must be exception-guarded —
    a safety net that can abort the run is worse than none."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    for anchor in ('_snap1202bw(self.output_dir, "milestone"',
                   '_snap1202bw2(self.output_dir, "interval"'):
        i = src.index(anchor)
        # Landmarks, not a byte window (#943): the call must sit between the `try:` that
        # opens its guard and the next `except Exception:` that closes it.
        assert src.rindex("try:", 0, i) < i < src.index("except Exception:", i)


def test_cli_handles_snapshots_before_the_fresh_reset():
    """--fresh wipes the output dir; if these were handled after it, --list-snapshots would
    delete the snapshots it was asked to print."""
    src = (LLM / "main.py").read_text(encoding="utf-8")
    assert src.index("args.list_snapshots or args.restore_snapshot") < \
           src.index("reset_output_dir(output_dir)")
