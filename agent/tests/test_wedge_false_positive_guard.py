"""#149 — the #147 busy-wedge watchdog must not false-positive on a healthy long step.

run-73 forensics (4-reader investigation, all 4 declarations refuted): the liveness
stamp `_last_step_activity` moved only at loop-enter + step top, but one healthy step
runs up to 15 action rounds × 4 internal LLM stages (~60 LLM calls, 600-800s routine),
so a legitimately-busy lane exceeded ENVGEN_LANE_WEDGE_S mid-step and was force-reset —
spawning a CONCURRENT loop (frontend 00:11:45/00:11:53 double ENTER depth=1) whose state
the undead old loop's finally later stomped back to IDLE. Smoking gun: the backend loop
declared WEDGED at 00:32:29 completed its task NORMALLY at 00:43:16 (1398.68s).

Fix (three independent guards):
1. fine-grained stamps — `_stamp_step_activity()` at every action-round top + after every
   stage-LLM return (loop-owned paths only; the resident poller never stamps);
2. firing-context guard — the two IN-LOOP drain sites pass from_loop=True; a drain the
   loop itself executes proves the loop is alive, so the wedge branch may not fire there
   (the resident poller keeps its declaration right → run-71's real-wedge class stays covered);
3. generation guard — a watchdog force-reset bumps `_loop_generation`; a stale loop's
   finally skips the state/depth reset so it cannot stomp the replacement loop.
LOCAL-ONLY (agent/tests/ gitignored).
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402
from multi_agent.agents.runtime.common import ProcessingState  # noqa: E402
from utils.message import BaseMessage, MessageHeader  # noqa: E402

MA = AGENT / "env_generator" / "llm_generator" / "multi_agent"


class _Queue:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    async def get_if_urgent(self):
        return self._msgs.pop(0) if self._msgs else None


class _Lane(AgentMessaging):
    def __init__(self, msg):
        self.agent_id = "backend"
        _n = lambda *a, **k: None
        self._logger = SimpleNamespace(info=_n, warning=_n, error=_n, debug=_n)
        self._workflow_policies = []
        self._processing_state = ProcessingState.PROCESSING_TASK
        self._agentic_loop_depth = 1
        self._deferred_task_ready_messages = []
        self._upstream_ready_agents = set()
        self._priority_queue = _Queue([msg])
        self.handled = []

    async def _pickup_undelivered_inbox_events(self):
        return 0

    async def _handle_task_ready(self, message):
        self.handled.append(message)


def _task_ready(mid="m1"):
    return BaseMessage(
        header=MessageHeader(message_id=mid, source_agent_id="orchestrator",
                             target_agent_id="backend"),
        payload="URGENT: delivery is blocked on `business_chain_failing`.",
        metadata={"msg_type": "task_ready", "tags": ["remediation"],
                  "validation_phase": True})


def test_inloop_drain_never_declares_wedge():
    """A drain executed BY the running loop proves the loop is alive — even a
    600s+ stale stamp must defer normally, never force-reset (all 4 run-73/72
    false positives fired on healthy in-step lanes)."""
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time() - 3600
    asyncio.run(lane._check_and_handle_urgent(from_loop=True))
    assert not lane.handled, "in-loop drain must NOT start a concurrent nested loop"
    assert lane._processing_state == ProcessingState.PROCESSING_TASK
    assert lane._agentic_loop_depth == 1
    assert len(lane._deferred_task_ready_messages) == 1, "must defer like ordinary busy"
    assert getattr(lane, "_loop_generation", 0) == 0, "no reset → no generation bump"


def test_poller_drain_still_declares_wedge():
    """#147's real-wedge coverage (run-71: loop parked on a dead await, resident
    poller still drains) is preserved: default context fires as before."""
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time() - 3600
    asyncio.run(lane._check_and_handle_urgent())
    assert lane.handled, "resident-poller context must still rescue a real wedge"
    assert lane._deferred_task_ready_messages == []


def test_wedge_reset_bumps_generation():
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time() - 3600
    asyncio.run(lane._check_and_handle_urgent())
    assert lane.handled
    assert getattr(lane, "_loop_generation", 0) == 1, \
        "a force-reset must invalidate the in-flight loop's unwind"


def test_stale_loop_unwind_skips_state_reset():
    """The undead loop's finally must not stomp the replacement loop's state
    (run-73 frontend: old finally set IDLE + depth 0 under the new loop,
    blinding the V30 re-entrancy guard)."""
    from multi_agent.agents.runtime.step_runner import AgentStepRunner
    lane = SimpleNamespace(
        _processing_state=ProcessingState.PROCESSING_TASK,
        _agentic_loop_depth=1, _loop_generation=1,
        _logger=SimpleNamespace(info=lambda *a, **k: None,
                                warning=lambda *a, **k: None),
        agent_id="backend")
    # entered at generation 0; the watchdog bumped to 1 while it was in flight
    AgentStepRunner._unwind_agentic_loop(lane, entry_generation=0)
    assert lane._processing_state == ProcessingState.PROCESSING_TASK, \
        "stale unwind must not reset state owned by the replacement loop"
    assert lane._agentic_loop_depth == 1

    # current-generation unwind resets normally
    AgentStepRunner._unwind_agentic_loop(lane, entry_generation=1)
    assert lane._processing_state == ProcessingState.IDLE
    assert lane._agentic_loop_depth == 0


def test_stamp_helper_updates_timestamp():
    from multi_agent.agents.runtime.step_runner import AgentStepRunner
    lane = SimpleNamespace(_last_step_activity=0.0)
    AgentStepRunner._stamp_step_activity(lane)
    assert time.time() - lane._last_step_activity < 5


def test_fine_grained_stamp_sites_present():
    """Source invariant: the action stage stamps at round top + after each
    stage-LLM return, and both in-loop drains pass from_loop=True — a healthy
    long step keeps its stamp fresh and cannot be declared wedged."""
    action_src = (MA / "agents" / "runtime" / "step_pipeline" / "action.py").read_text()
    runner_src = (MA / "agents" / "runtime" / "step_runner.py").read_text()
    assert action_src.count("_stamp_step_activity()") >= 3, \
        "round top + round-plan LLM return + internal-stage LLM return"
    assert "self._check_and_handle_urgent(from_loop=True)" in action_src
    assert "self._check_and_handle_urgent(from_loop=True)" in runner_src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
