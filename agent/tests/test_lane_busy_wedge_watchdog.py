"""FIX #147 — busy-wedge watchdog: a lane with no step activity is wedged, not busy.

run-71 M2 live: the verifier's last real activity was 19:53:01 (finish
posted, the in-flight agentic loop never returned); from 19:53 to the 20:06
abort it stayed non-IDLE, so all 5 gate-check remediation task_ready wakes
(correctly flagged validation_phase=True) hit the busy branch and were
deferred "for later" — but the deferred queue only drains in a handler's
finally, which never ran. 7-cycle no-convergence abort. Same family as
run-59's orchestrator silent-stall (2nd occurrence → fix).

Watchdog: when a task_ready arrives while the lane claims busy AND
_last_step_activity (stamped at loop enter + every step, step_runner) is
older than ENVGEN_LANE_WEDGE_S (default 600s, 0 disables), the loop is
declared WEDGED: force-reset to IDLE and handle the task_ready immediately
in the urgent-drain context (which demonstrably still runs while wedged).
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


class _Queue:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    async def get_if_urgent(self):
        return self._msgs.pop(0) if self._msgs else None


class _Lane(AgentMessaging):
    def __init__(self, msg):
        self.agent_id = "verifier"
        _n = lambda *a, **k: None
        self._logger = SimpleNamespace(info=_n, warning=_n, error=_n, debug=_n)
        self._workflow_policies = []          # policy admits everything
        self._processing_state = ProcessingState.PROCESSING_TASK  # claims busy
        self._agentic_loop_depth = 1
        self._deferred_task_ready_messages = []
        self._upstream_ready_agents = set()
        self._priority_queue = _Queue([msg])
        self.handled = []

    async def _pickup_undelivered_inbox_events(self):
        return 0

    async def _handle_task_ready(self, message):
        self.handled.append(message)


def _task_ready():
    return BaseMessage(
        header=MessageHeader(message_id="m1", source_agent_id="orchestrator",
                             target_agent_id="verifier"),
        payload="URGENT: delivery is blocked on `verification_checklist_not_ready`.",
        metadata={"msg_type": "task_ready", "tags": ["remediation"],
                  "validation_phase": True})


def test_stale_activity_forces_wedge_recovery():
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time() - 3600  # 1h stale
    asyncio.run(lane._check_and_handle_urgent())
    assert lane.handled, "wedged lane must handle the task_ready immediately"
    assert lane._deferred_task_ready_messages == []


def test_fresh_activity_defers_normally():
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time()  # loop genuinely active
    asyncio.run(lane._check_and_handle_urgent())
    assert not lane.handled, "an actively-working lane must not be reset"
    assert len(lane._deferred_task_ready_messages) == 1


def test_no_stamp_defers_normally():
    lane = _Lane(_task_ready())  # lane never ran a loop → conservative defer
    asyncio.run(lane._check_and_handle_urgent())
    assert not lane.handled
    assert len(lane._deferred_task_ready_messages) == 1


def test_watchdog_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ENVGEN_LANE_WEDGE_S", "0")
    lane = _Lane(_task_ready())
    lane._last_step_activity = time.time() - 3600
    asyncio.run(lane._check_and_handle_urgent())
    assert not lane.handled
    assert len(lane._deferred_task_ready_messages) == 1


def test_idle_lane_handles_directly():
    lane = _Lane(_task_ready())
    lane._processing_state = ProcessingState.IDLE
    lane._agentic_loop_depth = 0
    asyncio.run(lane._check_and_handle_urgent())
    assert lane.handled and not lane._deferred_task_ready_messages
