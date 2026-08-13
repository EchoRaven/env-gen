r"""#659b: the plan-decision timeout went live with #658, and said nothing useful.

#658 fixed `BaseMessage(content=)`, which means a plan with more steps than
`_auto_approve_threshold` now gets past `submit_plan` for the first time. The submitting tool
then does:

    plan = await self._plan_decision.submit_plan(...)
    plan = await self._plan_decision.wait_for_decision(plan.id)      # timeout=300.0

so a code path that used to fail in milliseconds can now wait five minutes. That wait is not new
— it was always the design — but nothing had ever reached it, and on expiry it recorded only
"Rejected: decision timeout".

Checked before writing this: the loop IS closeable. `accept_plan` / `request_plan_changes` set
`_decision_events[plan_id]`, and the lead reaches a pending plan through the
`list_pending_plan_decisions` tool. What does NOT exist is a subscriber for the
`plan_decision_request` notification itself — grep the repo and the only hit is a test. So the
realistic failure is "the lead never polled", and the message now says exactly that, names the
two tools that would have resolved it, and gives the escape (re-submit under the threshold).

Same family as #634/#635/#636/#642/#657/#659: a five-minute stall that does not explain itself
costs the round twice.
"""
import asyncio

import pytest

from env_generator.llm_generator.multi_agent.team_runtime.models import PlanStatus
from env_generator.llm_generator.multi_agent.team_runtime.plan_decision import (
    PlanDecisionProtocol,
)


class _Bus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _proto():
    return PlanDecisionProtocol(_Bus(), lead_agent_id="orch")


def _submit(proto, steps=4):
    return asyncio.run(proto.submit_plan(agent_id="a", title="t", description="d",
                                         steps=[{"s": i} for i in range(steps)]))


def _timed_out(proto, plan):
    return asyncio.run(proto.wait_for_decision(plan.id, timeout=0.01))


# --- the timeout explains itself ------------------------------------------------------------

def test_the_plan_is_still_rejected_on_timeout():
    """Behaviour is unchanged — only the explanation is new."""
    p = _proto()
    out = _timed_out(p, _submit(p))
    assert out.status is PlanStatus.REJECTED


def test_it_names_the_two_calls_that_would_have_resolved_it():
    p = _proto()
    fb = _timed_out(p, _submit(p)).feedback
    assert "accept_plan" in fb and "request_plan_changes" in fb


def test_it_names_the_poll_the_lead_was_supposed_to_use():
    """The notification has no subscriber; polling is the only route that works."""
    p = _proto()
    assert "list_pending_plan_decisions" in _timed_out(p, _submit(p)).feedback


def test_it_names_the_lead_it_waited_on():
    p = _proto()
    assert "orch" in _timed_out(p, _submit(p)).feedback


def test_it_offers_the_escape_hatch_with_the_real_threshold():
    """A stuck agent needs a way forward, not just a diagnosis."""
    p = _proto()
    fb = _timed_out(p, _submit(p)).feedback
    assert f"<= {p._auto_approve_threshold} steps" in fb
    assert "auto-approve" in fb


def test_it_reports_how_long_it_waited():
    """Asserted on the format, not by actually waiting — a real 7s sleep in the suite is a cost
    with no extra signal (the 0.01s path above already proves the branch runs)."""
    import inspect
    src = inspect.getsource(PlanDecisionProtocol.wait_for_decision)
    assert "{timeout:.0f}s" in src
    p = _proto()
    assert "0s" in _timed_out(p, _submit(p)).feedback


# --- the happy path is untouched ------------------------------------------------------------

def test_accepting_still_unblocks_the_waiter():
    p = _proto()
    plan = _submit(p)
    p.accept_plan(plan.id, decision_maker_id="orch", feedback="ok")
    out = asyncio.run(p.wait_for_decision(plan.id, timeout=1))
    assert out.status is PlanStatus.APPROVED
    assert out.decision_maker_id == "orch"


def test_the_auto_approve_path_never_waits():
    p = _proto()
    plan = _submit(p, steps=p._auto_approve_threshold)
    out = asyncio.run(p.wait_for_decision(plan.id, timeout=0.01))
    assert out.status is PlanStatus.APPROVED


def test_an_unknown_plan_still_raises():
    p = _proto()
    with pytest.raises(ValueError):
        asyncio.run(p.wait_for_decision("nope", timeout=0.01))


# --- the premise, pinned ----------------------------------------------------------------------

def test_there_really_is_no_subscriber_for_the_notification():
    """If someone adds a handler, this message's advice becomes wrong and should be revisited."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    # scoped to source: `generated/` holds ~16k throwaway .py files and scanning them
    # dominated this file's runtime for no signal.
    hits = subprocess.run(
        ["grep", "-rIl", "--include=*.py", "plan_decision_request",
         str(root / "env_generator"), str(root / "utils")],
        capture_output=True, text=True).stdout.split()
    named = {Path(h).name for h in hits}
    named.discard("plan_decision.py")                       # the sender
    assert not named, f"a subscriber appeared: {named}"


def test_accept_plan_is_what_sets_the_event():
    import inspect
    src = inspect.getsource(PlanDecisionProtocol.accept_plan)
    assert "_decision_events" in src and ".set()" in src


def test_the_provenance_is_recorded():
    import inspect
    flat = " ".join(
        inspect.getsource(PlanDecisionProtocol.wait_for_decision).replace("#", " ").split())
    assert "went LIVE for the first time with  658" in flat or "658" in flat
    assert "list_pending_plan_decisions" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
