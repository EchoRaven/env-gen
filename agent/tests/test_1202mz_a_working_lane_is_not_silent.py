"""#1202mz: stall escalation must not re-drive a lane that is working.

`nudge_silent_resident_lanes` judged liveness from `agent_status` heartbeats alone, and a lane can
work for many minutes without emitting one. Across the run logs, 2950 of 3216 stall re-drives
(92%, in 106 runs) went to a lane that had logged a tool call within the previous 150 seconds.
tiktok-r125: "re-driving never-woke lane verifier (last activity none since finalize)" 104 seconds
after the verifier's last tool call, in the middle of a validation pass — and 72 task_ready
messages queued in that verifier while it was busy, each replayed later as a full work loop.

The agent object already carries the liveness the #147 wedge watchdog trusts:
`_last_step_activity`, stamped at loop entry, every action round and after every stage LLM call.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_orchestrator_stall_escalation import (  # noqa: E402
    _StubOrchestrator, _nudge_method, _run)


class _WorkHub:
    """Every lane holds work, so only liveness decides whether it is nudged."""

    def list_tasks(self, assignee=None, status=None):
        return [{"id": f"t-{assignee}-{status}"}]


def _stub(**stamps):
    stub = _StubOrchestrator(statuses={})
    stub.hubs.workhub = _WorkHub()
    for lane, stamp in stamps.items():
        stub._agents[lane]._last_step_activity = stamp
    return stub


def test_a_lane_that_stepped_recently_is_not_re_driven():
    now = time.time()
    stub = _stub(verifier=now - 104.0)          # r125: 104s after its last tool call
    nudged = _run(_nudge_method()(stub, now - 3000.0))
    assert "verifier" not in nudged, nudged


def test_a_lane_whose_loop_stopped_stamping_is_still_re_driven():
    now = time.time()
    stub = _stub(verifier=now - 900.0)
    nudged = _run(_nudge_method()(stub, now - 3000.0))
    assert "verifier" in nudged, nudged


def test_a_lane_without_a_stamp_is_judged_as_before():
    now = time.time()
    stub = _stub()
    nudged = _run(_nudge_method()(stub, now - 3000.0))
    assert "verifier" in nudged and "backend" in nudged, nudged


def test_a_working_lanes_nudge_counter_resets():
    """Like a fresh heartbeat: a new stall episode starts clean."""
    now = time.time()
    stub = _stub(verifier=now - 10.0)
    stub._silent_lane_nudges["verifier"] = 3
    _run(_nudge_method()(stub, now - 3000.0))
    assert "verifier" not in stub._silent_lane_nudges


def test_the_stall_window_is_the_same_one_heartbeats_use(monkeypatch):
    now = time.time()
    monkeypatch.setenv("ENVGEN_LANE_STALL_SEC", "30")
    stub = _stub(verifier=now - 60.0)
    nudged = _run(_nudge_method()(stub, now - 3000.0))
    assert "verifier" in nudged, nudged
