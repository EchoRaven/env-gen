r"""#1202tn: "idle" meant two different things, and tier-3 asserted the wrong one.

`LaneIdleCircuitBreakerPolicy` advances its counter on every `finish()` that wrote no files and
grew no hub. That is equally true of a lane that is STUCK and of a lane that has NOTHING
ASSIGNED — and the tier-3 text asserted the first for both:

    "Lane has been idle for N steps after two prior escalations. Escalate to human triage;
     the agent is unable to self-recover."

MEASURED across the corpus's 65 tier-3 halts:

    60 of 65   are the BACKEND lane (frontend 5, no other lane ever)
    31 of 65   have the lane's own finish message in the preceding lines saying it has no
               work — "no pending or in-progress backend tasks remain", "Backend wind-down
               complete … no pending or in-progress backend tasks were present"

A sampled instance reads end to end: the backend reviewed its inbox, reported "Validation
check-in complete: inbox reviewed, no pending backend WorkHub tasks", called `finish()` — and
two seconds later was told it could not self-recover. The counter was right; the diagnosis was
not. The backend finishes its implementation early and then has nothing to do while the run
waits on the gate, so it accrues idle steps by behaving correctly.

Telling the orchestrator to triage a lane whose queue is empty points it at the wrong thing.
The signal that separates the two cases was already computed next door by
`LaneWindDownPolicy` — claimed-in-progress tasks and unread directed messages — so this reads
it rather than inventing one.

WHAT IS UNCHANGED: the counter, the tiers, the deterministic tier-3 action, and the escalation
for a lane that DOES hold work. Only the sentence changes, and only when the lane provably has
nothing — which is the same call #1202tl and #1202tm made: fix what it says, not what it does.

The two counts also go into the event payload and the log line, because "idle" alone cannot be
read afterwards: a run's artifacts are all a later reader gets.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.workflow_policies import LaneIdleCircuitBreakerPolicy  # noqa: E402


class _EventHub:
    def __init__(self, unread):
        self.published = []
        self._inbox = [{"read": False, "metadata": {"msg_type": "send_message"}}] * unread

    def publish_event(self, **kw):
        self.published.append(kw)

    def list_inbox(self, *a, **k):
        return self._inbox


def _agent(claimed=0, unread=0, agent_id="backend"):
    tasks = {f"t{i}": {"claimed_by": agent_id, "status": "in_progress"}
             for i in range(claimed)}
    workhub = types.SimpleNamespace(
        stores=types.SimpleNamespace(tasks=types.SimpleNamespace(value=lambda: tasks)))
    hub = _EventHub(unread)
    return types.SimpleNamespace(
        agent_id=agent_id,
        _hubs=types.SimpleNamespace(workhub=workhub, eventhub=hub),
        _logger=logging.getLogger("test_1202tn"))


def _emit(agent, tier=3):
    pol = LaneIdleCircuitBreakerPolicy(halt_action="signal_only")
    pol._emit_escalation(agent, 10, tier)
    return agent._hubs.eventhub.published[0]["payload"]


def test_an_empty_queue_is_not_described_as_stuck():
    """The 31-of-65 case."""
    pl = _emit(_agent(claimed=0, unread=0))
    assert pl["has_work"] is False
    assert "nothing is assigned to it, not because it is stuck" in pl["suggestion"]
    assert "unable to self-recover" not in pl["suggestion"]


def test_it_points_at_the_run_rather_than_the_lane():
    """A suggestion that names the wrong subject costs the orchestrator a cycle."""
    pl = _emit(_agent(claimed=0, unread=0))
    assert "Do not triage the lane" in pl["suggestion"]
    assert "delivery gate" in pl["suggestion"]


@pytest.mark.parametrize("claimed,unread", [(2, 0), (0, 3), (1, 1)])
def test_a_lane_that_holds_work_still_escalates(claimed, unread):
    """Non-vacuity, and the property that must not regress: the breaker exists for this case."""
    pl = _emit(_agent(claimed=claimed, unread=unread))
    assert pl["has_work"] is True
    assert "unable to self-recover" in pl["suggestion"]


def test_the_evidence_travels_with_the_event():
    """"idle" alone cannot be read afterwards; a run's artifacts are all a later reader gets."""
    pl = _emit(_agent(claimed=2, unread=3))
    assert pl["claimed_in_progress"] == 2
    assert pl["unread_inbox"] == 3


def test_lower_tiers_keep_their_own_wording():
    """Only tier 3 asserted 'unable to self-recover'; 1 and 2 are nudges and stay as they are."""
    for tier in (1, 2):
        pl = _emit(_agent(claimed=0, unread=0), tier=tier)
        assert "nothing is assigned" not in pl["suggestion"]


class _BrokenInbox(_EventHub):
    def list_inbox(self, *a, **k):
        raise RuntimeError("hub unreadable")


@pytest.mark.parametrize("break_what", ["workhub", "inbox"])
def test_an_unreadable_hub_is_unknown_not_empty(break_what):
    """★ THE TRAP IN MY OWN FIX, caught before it shipped.

    Both helpers are deliberately tolerant — `_collect_in_progress_claimed` documents "[] on
    error so a misconfigured hub can't itself block finish", and `_unread_inbox` returns 0 the
    same way. So an UNREADABLE hub and an EMPTY queue arrive as the same 0, and trusting it
    would re-create, one level down, the exact conflation this item is about: a blind guard
    answering as though it had looked.

    The counts must read -1 (unknown) and the lane must keep the ORIGINAL escalation."""
    agent = _agent()
    if break_what == "workhub":
        agent._hubs = types.SimpleNamespace(workhub=None, eventhub=agent._hubs.eventhub)
    else:
        agent._hubs = types.SimpleNamespace(workhub=agent._hubs.workhub,
                                            eventhub=_BrokenInbox(0))
    pol = LaneIdleCircuitBreakerPolicy(halt_action="signal_only")
    pol._emit_escalation(agent, 10, 3)
    pl = agent._hubs.eventhub.published[0]["payload"]
    assert pl["claimed_in_progress"] == -1 and pl["unread_inbox"] == -1
    assert pl["has_work"] is True, "unknown must not read as 'has nothing'"
    assert "nothing is assigned" not in pl["suggestion"]
    assert "unable to self-recover" in pl["suggestion"]
