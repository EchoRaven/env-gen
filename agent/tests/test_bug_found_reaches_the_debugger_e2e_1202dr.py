r"""#1202dr end-to-end: publish a bug_found, prove a triage loop actually starts.

The unit tests beside this one stub the queue, so they prove the dispatch BRANCH exists.
They cannot prove the chain that was broken on r44 -- where every intermediate layer
reported success and the lane still never ran:

    bug_report -> eventhub.publish_event(recipients=['debugger'], priority='high')
               -> MessageBusBridge.deliver -> agent.receive_message
               -> PriorityQueue.put -> get_if_urgent() -> ??? -> dropped

This wires the REAL EventHub, the REAL MessageBusBridge, the REAL receive_message and the
REAL PriorityQueue, and stubs only the LLM turn. It is the closest thing to the r44
evidence that does not cost a run.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub
from env_generator.llm_generator.multi_agent.runtime.hubs.eventhub import MessageBusBridge
from env_generator.llm_generator.multi_agent.agents.priority_queue import PriorityMessageQueue
from env_generator.llm_generator.multi_agent.agents.runtime.messaging import AgentMessaging
from env_generator.llm_generator.multi_agent.agents.runtime.common import ProcessingState


class _Bus:
    def __init__(self):
        self._agents = {}

    def register_agent(self, agent):
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id):
        return self._agents.get(agent_id)


class _Debugger(AgentMessaging):
    """Real messaging mixin; only the LLM turn and the outbound ack are stubbed."""

    def __init__(self):
        self.agent_id = "debugger"
        _n = lambda *a, **k: None
        self._logger = SimpleNamespace(info=_n, warning=_n, error=_n, debug=_n)
        self._workflow_policies = []
        self._processing_state = ProcessingState.IDLE
        self._agentic_loop_depth = 0
        self._deferred_task_ready_messages = []
        self._upstream_ready_agents = set()
        self._interrupt_messages = []
        self._subscription_inbox = []
        self._message_tracker = None
        self._is_resident_lane = True
        self._priority_queue = PriorityMessageQueue()
        self.loops = []

    # --- stubs at the edges only -------------------------------------------------
    async def _enqueue_for_dispatch(self, message):
        return None

    async def _maybe_schedule_resident_message_wakeup(self, message, inbox_msg):
        return None

    async def _send_delivery_ack(self, message):
        return None

    async def _pickup_undelivered_inbox_events(self):
        return 0

    async def _drain_deferred_task_ready_messages(self):
        return None

    def _compose_system_prompt(self):
        return "SYSTEM"

    async def run_agentic_loop(self, system_prompt, initial_prompt, max_steps=30):
        self.loops.append(initial_prompt)


def _publish_and_drain(event_type: str, priority: str = "high"):
    """Publish through the real hub+bridge, then run one urgent drain."""

    async def _go():
        tmp = tempfile.mkdtemp()
        hub = EventHub(Path(tmp))
        bus = _Bus()
        lane = _Debugger()
        bus.register_agent(lane)
        hub.add_bridge(MessageBusBridge(bus, hub))

        hub.publish_event(
            source_hub="verifier",
            event_type=event_type,
            payload={"task_id": "task_x", "severity": "P0",
                     "title": "GET /api/titles/{id}/episodes returns 500"},
            recipients=["debugger"],
            priority=priority,
        )
        # the bridge is fired via ensure_future inside a running loop
        for _ in range(5):
            await asyncio.sleep(0)

        handled = await lane._check_and_handle_urgent()
        return lane, handled, hub

    return asyncio.run(_go())


# --- the chain that was broken ------------------------------------------------------

def test_a_published_bug_found_starts_a_triage_loop():
    lane, handled, _ = _publish_and_drain("bug_found")
    assert handled is True
    assert len(lane.loops) == 1, (
        "the whole r44 failure: delivered=True, queued, popped -- and no loop. "
        "This assertion is the one that was false in production.")


def test_the_message_really_travelled_through_the_priority_queue():
    """Guard against the test accidentally proving something easier than the real path."""
    lane, _, _ = _publish_and_drain("bug_found")
    assert lane._subscription_inbox, "receive_message never ran -- the bridge did not deliver"
    assert lane._priority_queue.empty(), "the urgent drain did not consume the message"


def test_run_failed_takes_the_same_path():
    lane, handled, _ = _publish_and_drain("run_failed")
    assert handled is True and len(lane.loops) == 1


def test_the_durable_inbox_still_records_it():
    """#628's addressing must keep working -- the wakeup fix must not replace it."""
    _, _, hub = _publish_and_drain("bug_found")
    items = hub.list_inbox("debugger", unread_only=False)
    assert len(items) == 1
    assert items[0]["event_type"] == "bug_found"
    assert items[0]["inbox"].get("delivered") is True, \
        "the bridge marks delivered only on the success path"


def test_an_unsubscribed_event_type_does_not_start_a_loop():
    """The fix must stay a branch, not a catch-all: a delivered-but-unhandled event is
    still dropped (that is correct for events the lane only needs at hub_pulse)."""
    lane, handled, _ = _publish_and_drain("run_completed", priority="high")
    assert handled is False
    assert lane.loops == []
