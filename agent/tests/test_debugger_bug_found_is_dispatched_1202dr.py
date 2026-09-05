r"""#1202dr: the debugger lane could not be reached, so 17 bug reports per run died.

Same defect class Round-8c fixed for `kickoff_request` ("received and logged but no
msg_type branch dispatched into an LLM turn, so the 4 attendees just sat idle"). It was
still open for `bug_found` / `run_failed` — which are the debugger's ONLY work triggers
in DEFAULT_SUBSCRIPTIONS.

Measured on netflix r44, original run AND its resume:

    17 of 18 `bug_found` events carry recipients=['debugger']   (#628 addressing works)
    all 38 debugger inbox items are delivered=True, read=False  (the bridge pushed them)
    "[debugger] Ready to accept tasks" logged in both runs      (the resident drain ran)
    run_agentic_loop ENTER: backend 58, orchestrator 55, frontend 25, verifier 12,
                            debugger 0                          (over 3.2 hours)
    grep -c bug_found messaging.py -> 0                          (the whole cause)

Every layer reported success. The message was popped by `get_if_urgent()` (priority
"high" = rank 1, inside the <=1 drain), matched no `msg_type ==` branch, and fell to the
bare `return False` at the end of the dispatch table — consumed and discarded.

What died with it: task_a40620a46a "Docker compose startup fails: backend container
missing during startup", assignee=debugger, claimed_by=None, status=cancelled. A release
blocker routed to a lane that could not be woken.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]

from env_generator.llm_generator.multi_agent.agents.runtime.messaging import AgentMessaging
from env_generator.llm_generator.multi_agent.agents.runtime.common import ProcessingState
from utils.message import BaseMessage, MessageHeader

MSG_SRC = (AGENT / "env_generator" / "llm_generator" / "multi_agent"
           / "agents" / "runtime" / "messaging.py").read_text()


class _Queue:
    def __init__(self, msgs):
        self._msgs = list(msgs)

    async def get_if_urgent(self):
        return self._msgs.pop(0) if self._msgs else None


class _Debugger(AgentMessaging):
    def __init__(self, msg, state=ProcessingState.IDLE):
        self.agent_id = "debugger"
        _n = lambda *a, **k: None
        self._logger = SimpleNamespace(info=_n, warning=_n, error=_n, debug=_n)
        self._workflow_policies = []
        self._processing_state = state
        self._agentic_loop_depth = 0 if state == ProcessingState.IDLE else 1
        self._deferred_task_ready_messages = []
        self._upstream_ready_agents = set()
        self._priority_queue = _Queue([msg])
        self.loops = []
        self.drained = 0

    async def _pickup_undelivered_inbox_events(self):
        return 0

    def _compose_system_prompt(self):
        return "SYSTEM"

    async def run_agentic_loop(self, system_prompt, initial_prompt, max_steps=30):
        self.loops.append(initial_prompt)
        # a real loop is not IDLE while it runs
        assert self._processing_state != ProcessingState.IDLE
        return None

    async def _drain_deferred_task_ready_messages(self):
        self.drained += 1


def _event(msg_type="bug_found", mid="e1"):
    return BaseMessage(
        header=MessageHeader(message_id=mid, source_agent_id="verifier",
                             target_agent_id="debugger"),
        payload="P0: GET /api/titles/{id}/episodes returns 500 (FK to titles)",
        metadata={"msg_type": msg_type})


def _dispatch_table() -> str:
    """The urgent dispatch table, landmark-anchored (no byte windows)."""
    start = MSG_SRC.index("async def _check_and_handle_urgent")
    return MSG_SRC[start:MSG_SRC.index("def _should_start_from_task_ready", start)]


def _dead_debugger_triggers(table: str):
    """Live (wakeup-carrying) debugger subscriptions with no branch in `table`."""
    import re

    subs = (AGENT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
            / "agent_subscriptions.py").read_text()

    def _block(name):
        m = re.search(rf"^{name}[^=]*=\s*\{{", subs, re.M)
        assert m, f"{name} moved -- this tripwire went blind"
        return subs[m.start():subs.index("\n}", m.start())]

    def _lane(src, lane):
        m = re.search(rf'"{lane}"\s*:\s*\[(.*?)\n    \]', src, re.S)
        return re.findall(r'\(\s*"[^"]*"\s*,\s*"([a-z_]+)"\s*,\s*"[a-z]+"\s*\)',
                          m.group(1)) if m else []

    triggers = _lane(_block("DEFAULT_SUBSCRIPTIONS"), "debugger")
    assert triggers, "the debugger subscription block moved -- this tripwire went blind"
    inbox_only = set(_lane(_block("INBOX_ONLY_SUBSCRIPTIONS"), "debugger"))

    # Two live subs are informational by their own source comments ("Kickoff_complete is
    # informational"; the stated wake set is "bug_found + runhub failures"). They are NOT
    # moved to inbox_only here: test_agent_subscriptions and test_kickoff_orchestrator_wire
    # both assert their membership in DEFAULT_SUBSCRIPTIONS, and flipping a contract two
    # tests encode is not a change to make from a static reading. They cost a popped-and-
    # dropped message each (r44: run_completed 4, kickoff_complete 1) against bug_found 22
    # and run_failed 13. Listed explicitly so a NEW debugger subscription still trips this.
    informational = {"run_completed", "kickoff_complete"}

    # Match the DISPATCH CONSTRUCT, not the word. A substring test reports "handled" for
    # any event merely NAMED in a comment -- and the #1202dr comment names bug_found six
    # times, which silently disarmed the vacuity check on the first attempt. Same class as
    # every other detector that matched "the word appears" instead of "the thing happens".
    handled = set(re.findall(r'msg_type\s*==\s*"([a-z_]+)"', table))
    handled |= set(re.findall(r'event_type\s*==\s*"([a-z_]+)"', table))
    for grp in re.findall(r"msg_type\s+in\s*\(([^)]*)\)", table, re.S):
        handled |= set(re.findall(r'"([a-z_]+)"', grp))

    return [t for t in triggers
            if t not in inbox_only and t not in informational and t not in handled]

# --- the wakeup that never happened --------------------------------------------------

def test_bug_found_wakes_an_idle_debugger():
    lane = _Debugger(_event("bug_found"))
    assert asyncio.run(lane._check_and_handle_urgent()) is True
    assert len(lane.loops) == 1, "bug_found must dispatch into an LLM turn, not fall through"


def test_run_failed_wakes_an_idle_debugger():
    """The debugger's other subscribed trigger — same dead path."""
    lane = _Debugger(_event("run_failed"))
    assert asyncio.run(lane._check_and_handle_urgent()) is True
    assert len(lane.loops) == 1


def test_an_unknown_event_type_still_falls_through():
    """The fix must not turn the dispatch table into a catch-all."""
    lane = _Debugger(_event("some_unrelated_event"))
    assert asyncio.run(lane._check_and_handle_urgent()) is False
    assert lane.loops == []


# --- busy => skip, not defer, not nest ------------------------------------------------

def test_bug_found_while_busy_does_not_start_a_nested_loop():
    lane = _Debugger(_event("bug_found"), state=ProcessingState.PROCESSING_TASK)
    assert asyncio.run(lane._check_and_handle_urgent()) is True
    assert lane.loops == [], "a nested triage loop would trip the V30 re-entrancy guard"


def test_a_skipped_wakeup_is_not_queued():
    """Deferring would rebuild the livelock the kickoff comment records; the WorkHub bug
    task is the source of truth, so the dropped wakeup costs nothing."""
    lane = _Debugger(_event("bug_found"), state=ProcessingState.PROCESSING_TASK)
    asyncio.run(lane._check_and_handle_urgent())
    assert lane._deferred_task_ready_messages == []


def test_a_busy_lane_keeps_its_state():
    lane = _Debugger(_event("bug_found"), state=ProcessingState.PROCESSING_TASK)
    asyncio.run(lane._check_and_handle_urgent())
    assert lane._processing_state == ProcessingState.PROCESSING_TASK
    assert lane._agentic_loop_depth == 1


# --- the triage loop is batch-shaped --------------------------------------------------

def test_the_prompt_opens_on_the_open_set_not_this_one_event():
    """A burst of N events must cost ONE loop and still see the bugs whose wakeups the
    busy-skip dropped -- that is only true if triage starts from bug_list_open."""
    lane = _Debugger(_event("bug_found"))
    asyncio.run(lane._check_and_handle_urgent())
    prompt = lane.loops[0]
    assert "bug_list_open" in prompt
    assert "Do NOT act on that single event" in prompt


def test_the_prompt_keeps_the_debugger_in_the_triage_role():
    lane = _Debugger(_event("bug_found"))
    asyncio.run(lane._check_and_handle_urgent())
    prompt = lane.loops[0]
    assert "do not fix it yourself" in prompt.lower()
    assert "Run ONCE" in prompt, "an unbounded triage loop would poll the assignees"


def test_state_is_restored_after_the_triage_loop():
    lane = _Debugger(_event("bug_found"))
    asyncio.run(lane._check_and_handle_urgent())
    assert lane._processing_state == ProcessingState.IDLE
    assert lane.drained == 1, "the finally must still drain deferred task_ready"


def test_a_raising_triage_loop_still_restores_state():
    lane = _Debugger(_event("bug_found"))

    async def _boom(**kw):
        raise RuntimeError("provider down")

    lane.run_agentic_loop = _boom
    assert asyncio.run(lane._check_and_handle_urgent()) is True
    assert lane._processing_state == ProcessingState.IDLE, \
        "a failed triage must not leave the lane permanently busy"


# --- the detector that found it, kept as a tripwire ------------------------------------

def test_every_debugger_trigger_has_a_dispatch_branch():
    """`grep -c bug_found messaging.py` was 0 -- that single number was the whole bug.

    Derived from DEFAULT_SUBSCRIPTIONS rather than hardcoding the two names, so a
    subscription added to the debugger later cannot silently become another dead trigger.

    Scoped to the debugger on purpose. A missing branch is FATAL only for a lane with no
    other activation path. Measured on r44: every other lane drains its inbox from its own
    continuous loop -- orchestrator 559/559 read, frontend 420/420, verifier 111/111,
    backend 206/209 -- so their 24 branch-less subscriptions cost wakeup LATENCY, not
    information. The debugger read 0 of 41 (0%) and ran 0 agentic loops in 3.2 hours,
    because it can only learn it has work by being woken.

    Block extraction is anchored at LINE START (#1202dr): `subs.index("INBOX_ONLY_
    SUBSCRIPTIONS")` matches a COMMENT inside DEFAULT_SUBSCRIPTIONS ("moved to
    INBOX_ONLY_SUBSCRIPTIONS below") and swallows the rest of that dict, which classifies
    every remaining event as inbox_only and makes this whole test pass vacuously. It did.
    `test_the_tripwire_is_not_vacuous` below is what caught that.
    """
    missing = _dead_debugger_triggers(_dispatch_table())
    assert not missing, (
        f"live debugger subscriptions with NO dispatch branch: {missing} -- they will be "
        "popped by get_if_urgent() and dropped, and the debugger has no other way to learn "
        "it has work (r44: 0 of 41 inbox items read, 0 agentic loops)")


def test_the_tripwire_is_not_vacuous():
    """Validate the detector on a known answer before trusting a green run.

    Delete the branch the defect was about; the check above must go red. Without this the
    first version of that test passed while asserting nothing at all.
    """
    broken = _dispatch_table().replace(
        'if msg_type in ("bug_found", "run_failed"):', 'if msg_type in ("run_failed",):')
    assert _dead_debugger_triggers(broken) == ["bug_found"], \
        "the tripwire does not fire on the very defect it was written for"


def test_the_dispatch_table_still_ends_in_a_fallthrough():
    """The fix adds a branch; it must not remove the explicit fallthrough."""
    start = MSG_SRC.index("async def _check_and_handle_urgent")
    end = MSG_SRC.index("def _should_start_from_task_ready", start)
    assert MSG_SRC[start:end].rstrip().endswith("return False")
