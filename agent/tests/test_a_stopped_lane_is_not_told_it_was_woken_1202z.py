r"""#1202z: a wakeup is not "scheduled" onto a queue nobody is reading.

`stop()` sets `_running = False` and cancels the worker tasks, so anything put on
`_message_queue` afterwards is never consumed. `_enqueue_resident_wakeup_966` did not check,
put the task on anyway, and logged "scheduled resident wakeup" as if it had been delivered.

r32 ended on exactly that:

    00:31:38  Stopping agent: Frontend Engineer Agent
    00:31:40  [frontend] scheduled resident wakeup for endpoint_schema_changed from registryhub
    ...       Stall escalation (elapsed=5560s ... 5778s) ... silent resident lanes ['frontend']
    Status: FAIL — cannot complete task

The orchestrator spent 95 minutes dispatching urgent task_ready to a lane that could not
answer, and the run aborted having delivered one milestone instead of three.

This is the #1178 shape a third time: a delivery that reports success into a void, and a
run that then waits on it. The fix does not restart the lane — that is the orchestrator's
decision, not this method's — it just stops claiming the message was scheduled, so "could
not deliver" becomes a fact someone can act on.
"""

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402


class _Lane(AgentMessaging):
    """The two attributes the enqueue path touches, and a queue that records puts."""

    def __init__(self, running):
        self.agent_id = "frontend"
        self.is_running = running
        self._resident_wakeup_task_pending = True
        self._logger = logging.getLogger("lane_1202z")
        self.puts = []

        class _Q:
            def __init__(self, sink): self.sink = sink
            async def put(self, m): self.sink.append(m)

        self._message_queue = _Q(self.puts)


def _enqueue(lane):
    asyncio.run(lane._enqueue_resident_wakeup_966(
        source="registryhub", msg_type="endpoint_schema_changed", message_id="m1"))


def test_a_running_lane_still_gets_its_wakeup():
    lane = _Lane(running=True)
    _enqueue(lane)
    assert len(lane.puts) == 1
    assert lane.puts[0].task_name == "resident_message_wakeup"


def test_a_stopped_lane_is_not_queued(caplog):
    lane = _Lane(running=False)
    with caplog.at_level(logging.WARNING, logger="lane_1202z"):
        _enqueue(lane)
    assert lane.puts == []
    assert "NOT scheduled" in caplog.text
    assert "no consumer" in caplog.text


def test_the_pending_flag_is_cleared_so_a_later_wakeup_can_arm(caplog):
    """Leaving it set would suppress the wakeup even after the lane comes back."""
    lane = _Lane(running=False)
    with caplog.at_level(logging.WARNING, logger="lane_1202z"):
        _enqueue(lane)
    assert lane._resident_wakeup_task_pending is False


def test_a_lane_without_the_attribute_is_treated_as_running():
    """Unknown state must not silence a lane that is fine — the default is to deliver."""
    lane = _Lane(running=True)
    del lane.is_running
    _enqueue(lane)
    assert len(lane.puts) == 1
