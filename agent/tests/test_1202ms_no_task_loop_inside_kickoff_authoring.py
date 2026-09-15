"""#1202ms: no task loop may start inside an open kickoff authoring loop.

tiktok-r124's resume, M1 kickoff (23:32:13 -> 23:47, about 15 minutes):

  backend   23:32:53  kickoff authoring loop enters (max_steps=12)
            23:35:20  step 2/12; an urgent `info` is handled mid-step
            23:36:03  "Starting work - triggered by orchestrator: Re-drive P0 ..." — the info
                      handler's finally drained a queued task_ready into a 2000-step loop
            23:43:32  step 3/12 — the kickoff sat behind it for 448s
  frontend  23:32:22 / 23:32:23  two authoring loops for the SAME meeting, depth 2 then 3

Every busy guard read `_processing_state`, which an inner handler's unwind resets to IDLE while
the kickoff loop is still open. V30 added a depth check to the task_ready path; the drain never
got one, and `kickoff_request` is dispatched with no guard at all.

Corpus (every gm_*.log except googlemaps-r16; detector validated on the r124 case first — its
first version keyed on depth and missed it, because the unwind had lowered depth too): 52 task
loops nested inside kickoff authoring across 31 runs, pausing it for a median 108s, p90 844s,
max 1568s.

The guard keys on an explicit authoring marker, not on state or depth: the orchestrator nests
loops at depth 2 routinely (21 times in the same log), and that must keep working.
"""
import ast
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]
LLM_DIR = AGENT / "env_generator" / "llm_generator"
sys.path.insert(0, str(LLM_DIR))

from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402
from multi_agent.agents.runtime.common import ProcessingState  # noqa: E402
from utils.message import BaseMessage, MessageHeader  # noqa: E402

MESSAGING = LLM_DIR / "multi_agent" / "agents" / "runtime" / "messaging.py"


class _Queue:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    async def get_if_urgent(self):
        return self._msgs.pop(0) if self._msgs else None


class _Lane(AgentMessaging):
    def __init__(self, msgs=()):
        self.agent_id = "backend"
        _n = lambda *a, **k: None
        self._logger = SimpleNamespace(info=_n, warning=_n, error=_n, debug=_n)
        self._workflow_policies = []
        self._processing_state = ProcessingState.IDLE
        self._agentic_loop_depth = 0
        self._deferred_task_ready_messages = []
        self._deferred_kickoff_messages = []
        self._upstream_ready_agents = set()
        self._priority_queue = _Queue(msgs)
        self.handled = []

    async def _pickup_undelivered_inbox_events(self):
        return 0

    async def _handle_task_ready(self, message):
        self.handled.append(message.header.message_id)


def _task_ready(mid="redrive"):
    return BaseMessage(
        header=MessageHeader(message_id=mid, source_agent_id="orchestrator",
                             target_agent_id="backend"),
        payload="Re-drive P0 task_45282db33d remains pending/unclaimed.",
        metadata={"msg_type": "task_ready"})


# ── the urgent path ────────────────────────────────────────────────────────────────────────

def test_task_ready_is_queued_while_authoring_even_when_state_reads_idle():
    lane = _Lane([_task_ready()])
    lane._kickoff_authoring_1202ms = "doc_2d07232f52"   # state IDLE, depth 0: the r124 window
    asyncio.run(lane._check_and_handle_urgent(from_loop=True))
    assert lane.handled == []
    assert [m.header.message_id for m in lane._deferred_task_ready_messages] == ["redrive"]


def test_the_wedge_rescue_does_not_fire_into_an_authoring_loop():
    lane = _Lane([_task_ready()])
    lane._processing_state = ProcessingState.PROCESSING_TASK
    lane._agentic_loop_depth = 1
    lane._last_step_activity = time.time() - 3600
    lane._kickoff_authoring_1202ms = "doc_x"
    asyncio.run(lane._check_and_handle_urgent())
    assert lane.handled == []


def test_an_idle_lane_that_is_not_authoring_still_starts_at_once():
    lane = _Lane([_task_ready()])
    asyncio.run(lane._check_and_handle_urgent(from_loop=True))
    assert lane.handled == ["redrive"]


# ── the drain ──────────────────────────────────────────────────────────────────────────────

def test_the_drain_leaves_the_queue_alone_while_authoring():
    lane = _Lane()
    lane._deferred_task_ready_messages = [_task_ready()]
    lane._kickoff_authoring_1202ms = "doc_x"
    asyncio.run(lane._drain_deferred_task_ready_messages())
    assert lane.handled == []
    assert len(lane._deferred_task_ready_messages) == 1


def test_the_drain_runs_the_queue_once_authoring_has_closed():
    lane = _Lane()
    lane._deferred_task_ready_messages = [_task_ready()]
    lane._kickoff_authoring_1202ms = None
    asyncio.run(lane._drain_deferred_task_ready_messages())
    assert lane.handled == ["redrive"]


# ── the r124 sequence through the real kickoff handler ────────────────────────────────────

def _kickoff_request(meeting="doc_2d07232f52"):
    return BaseMessage(
        header=MessageHeader(message_id="k-" + meeting, source_agent_id="orchestrator",
                             target_agent_id="backend"),
        payload={"meeting_id": meeting, "milestone_index": 1, "requirements": ["M1"]},
        metadata={"msg_type": "kickoff_request"})


class _KickoffLane(_Lane):
    """Runs the real `_handle_kickoff_request`; its agentic loop replays r124's step 2."""

    def __init__(self):
        super().__init__()
        self._prompt_cfg = {}
        self.loops = []
        self.order = []

    def _compose_system_prompt(self):
        return "system"

    def _contract_already_complete_1202er(self, **_kw):
        return True

    def _ensure_initial_section_decision(self, **_kw):
        self.order.append("section")

    async def _handle_task_ready(self, message):
        self.order.append("task:" + message.header.message_id)
        self.handled.append(message.header.message_id)

    async def run_agentic_loop(self, **kw):
        self.loops.append(kw.get("max_steps"))
        # step 2: a task_ready was queued earlier, and an urgent handler finishes inside the
        # loop — resetting the shared state and draining, exactly as r124's `info` did
        self._deferred_task_ready_messages = [_task_ready()]
        self._processing_state = ProcessingState.IDLE
        await self._drain_deferred_task_ready_messages()
        self.order.append("kickoff-step-3")
        return {}


def test_r124s_kickoff_is_not_paused_by_the_queued_task():
    lane = _KickoffLane()
    asyncio.run(lane._handle_kickoff_request(_kickoff_request()))
    assert "kickoff-step-3" in lane.order and "task:redrive" in lane.order, lane.order
    assert lane.order.index("kickoff-step-3") < lane.order.index("task:redrive"), lane.order
    assert lane._kickoff_authoring_1202ms is None


def test_a_second_request_for_the_meeting_being_authored_runs_no_second_loop():
    lane = _KickoffLane()
    lane._kickoff_authoring_1202ms = "doc_2d07232f52"
    asyncio.run(lane._handle_kickoff_request(_kickoff_request("doc_2d07232f52")))
    assert lane.loops == []


def test_the_marker_is_cleared_before_the_section_guarantee_and_the_drain():
    """Call-site order in the finally, read from the AST (#1202fd: order checks must look at
    where things are CALLED, not defined)."""
    tree = ast.parse(MESSAGING.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_kickoff_request")
    final = next(t for t in ast.walk(fn) if isinstance(t, ast.Try) and t.finalbody).finalbody
    events = []
    for stmt in final:
        for n in ast.walk(stmt):
            if (isinstance(n, ast.Assign) and any(
                    getattr(t, "attr", None) == "_kickoff_authoring_1202ms" for t in n.targets)):
                events.append((n.lineno, "clear"))
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in (
                    "_ensure_initial_section_decision", "_drain_deferred_task_ready_messages"):
                events.append((n.lineno, n.func.attr))
    names = [e for _l, e in sorted(events)]
    assert names[0] == "clear", names
