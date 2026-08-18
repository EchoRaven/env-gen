"""#966: a wake-eligible message that lands while a wakeup is in flight must not be lost.

``_maybe_schedule_resident_message_wakeup`` dedups on ``_resident_wakeup_task_pending``.
The in-flight wakeup drains the inbox ONCE; anything arriving after that read is never
seen again, because ``process_task``'s completion path cleared the flag without
re-checking. The orchestrator's ``finish_continue`` policy currently hides this (that
lane never sleeps, so it re-reads the inbox on its next step) — every other resident
lane is already exposed, and it is the documented instagram M1/M2 shape: a lane goes
idle holding an unread request and kickoff hangs to its 1200s timeout.

Removing ``finish_continue`` (the real spin fix) makes the race reachable for the
orchestrator too, so this lands FIRST and stands on its own.
"""

import ast
import asyncio
import inspect
import logging
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.messaging import AgentMessaging


class _Lane(AgentMessaging):
    """Minimal host carrying only what the wakeup path touches."""

    def __init__(self):
        self.agent_id = "frontend"
        self._is_resident_lane = True
        self._workflow_policies = []
        self._kickoff_bootstrapped = True
        self._resident_wakeup_task_pending = False
        self._message_queue = asyncio.Queue()
        self._logger = logging.getLogger("test.wakeup966")
        self._hubs = None


def _inbox(msg_type="question", frm="verifier"):
    return {"type": msg_type, "from": frm, "id": "m-1", "tags": []}


class _PlainMessage:
    """Not a TaskMessage — the wakeup path only skips TaskMessage."""

    payload = {}


def test_a_message_arriving_mid_wakeup_is_remembered():
    lane = _Lane()
    lane._resident_wakeup_task_pending = True  # a wakeup is already in flight

    asyncio.run(lane._maybe_schedule_resident_message_wakeup(_PlainMessage(), _inbox()))

    deferred = getattr(lane, "_wakeup_deferred_966", None)
    assert deferred, (
        "the message passed every eligibility gate and was dropped purely by the dedup "
        "guard — with nothing recorded, completion has no way to know it must re-arm")
    assert deferred["msg_type"] == "question"
    assert deferred["source"] == "verifier"


def test_a_non_waking_message_is_not_remembered():
    """'info' is narration and must stay non-waking — the re-arm must not resurrect it."""
    lane = _Lane()
    lane._resident_wakeup_task_pending = True

    asyncio.run(lane._maybe_schedule_resident_message_wakeup(
        _PlainMessage(), _inbox(msg_type="info")))

    assert getattr(lane, "_wakeup_deferred_966", None) is None, (
        "recording a suppressed type would re-arm a wake the 'info' exclusion exists to "
        "prevent, turning the fix into the wake-storm it must not cause")


def test_the_rearm_enqueues_through_the_same_path():
    lane = _Lane()

    async def _go():
        await lane._enqueue_resident_wakeup_966(
            source="verifier", msg_type="question", message_id="m-1")
        return lane._message_queue.get_nowait()

    task_msg = asyncio.run(_go())
    assert task_msg.task_name == "resident_message_wakeup"
    assert task_msg.payload["message_type"] == "question"
    assert task_msg.payload["source_agent"] == "verifier"


def test_process_task_rearms_on_completion():
    """The completion path in ``process_task`` must consume the deferred record and
    schedule another wakeup. Asserted on the real source, anchored to the #966 marker,
    because reaching that ``finally`` needs a fully booted lane."""
    from env_generator.llm_generator.multi_agent.agents import base

    src = inspect.getsource(base.EnvGenAgent.process_task)
    assert "_wakeup_deferred_966" in src, (
        "process_task still clears the pending flag without consulting the deferred "
        "record — the message stays stranded and the fix is inert")

    tree = ast.parse(src.strip())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "_enqueue_resident_wakeup_966" in names, (
        "the re-arm must go through the shared enqueue helper, not a second inline copy")


def test_the_control_loses_the_message():
    """Planted control: the PRE-FIX shape — dedup guard with no record — must fail the
    first test's assertion. Proven on a synthetic function so fixing the real code can
    never turn this red."""

    class _PreFix:
        def __init__(self):
            self._resident_wakeup_task_pending = True

        def maybe_schedule(self, inbox_msg):
            if self._resident_wakeup_task_pending:
                return  # the whole defect, in one line

    lane = _PreFix()
    lane.maybe_schedule(_inbox())
    assert getattr(lane, "_wakeup_deferred_966", None) is None, (
        "the control was supposed to lose the message; if it did not, the assertion in "
        "the main test does not discriminate")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
