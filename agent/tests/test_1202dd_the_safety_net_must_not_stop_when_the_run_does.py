"""#1202dd — snapshot cadence must not depend on the tick loop it protects.

#1202bw's interval snapshot sits inside the orchestrator's tick loop, so it is only ASKED
once per tick even though `maybe_snapshot` decides on wall-clock. netflix-r43 spent its
last 82 minutes inside two ticks — the visual gate retrying docker_up against a host port
it could never bind — and took ZERO snapshots in that window against a 15-minute cadence.
Its final restore point is t20 at 00:15 for a run that died at 01:37.

The rhythm of the safety net was coupled to the thing it exists to survive: the slower a
run gets, the fewer restore points it keeps, and a wedged run keeps none.

A judged round is the other place a long milestone reliably passes through — r43 reached
7 of them in that same window. `maybe_snapshot` stays the single cadence authority, so an
extra caller cannot snapshot more often than ENVGEN_SNAPSHOT_EVERY_MIN allows.
"""
import time
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import run_snapshot as rs

SRC = Path("env_generator/llm_generator/multi_agent/runtime/visual_fidelity.py").read_text()


def _judge_round_body() -> str:
    i = SRC.index("self.attempts = self.attempts + 1")
    return SRC[i:SRC.index("Per-component MODEL config", i)]


def test_a_judged_round_also_asks_for_a_snapshot():
    """The one place a stalled run still passes through repeatedly."""
    body = _judge_round_body()
    assert "maybe_snapshot" in body
    assert "orch.output_dir" in body


def test_it_cannot_break_the_gate():
    """This runs inside the judging path; an exception here would cost the round, which
    is far worse than a missing restore point."""
    body = _judge_round_body()
    assert "except Exception:" in body


def test_maybe_snapshot_remains_the_only_cadence_authority(tmp_path, monkeypatch):
    """Adding a caller must not raise the snapshot rate — the gate itself decides. A
    second caller that bypassed the clock would fill the disk on a busy run."""
    monkeypatch.setenv("ENVGEN_SNAPSHOT_EVERY_MIN", "15")
    out = tmp_path / "run"
    (out / "shared" / "hubs").mkdir(parents=True)
    (out / "shared" / "hubs" / "x.json").write_text("{}")

    rs._last_snapshot_ts.pop(str(out), None)
    assert rs.maybe_snapshot(out, "interval", "a") is None      # first call starts the clock
    assert rs.maybe_snapshot(out, "interval", "b") is None      # not due
    assert rs.maybe_snapshot(out, "interval", "c") is None      # still not due

    rs._last_snapshot_ts[str(out)] = time.time() - 16 * 60      # now due
    assert rs.maybe_snapshot(out, "interval", "d") is not None
    assert rs.maybe_snapshot(out, "interval", "e") is None      # and immediately not again


def test_the_tick_loop_call_site_is_still_there():
    """This adds a caller, it does not move one — a milestone-free stretch with slow
    judging still needs the tick cadence."""
    orch = Path("env_generator/llm_generator/multi_agent/orchestrator.py").read_text()
    assert orch.count("maybe_snapshot") >= 2
    assert "_snap1202bw2" in orch
