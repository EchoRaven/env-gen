r"""#870: the only unbounded await on the path, and everything the run needs was behind it.

`plan_milestones` ends in a bare `await client.chat(...)` — no `wait_for`, no timeout — and the
caller's `try/except` catches **exceptions, not hangs**. Behind that await sit `set_roadmap`
(#864's readback), the per-milestone loop, and `start_kickoff` **inside** that loop.

★ The kickoff receipts a few hundred lines below **are** bounded (`asyncio.wait_for` at
orchestrator.py:1710, 1751, 1909). This call runs first and was not — so a hang here means even
those timeouts never get the chance to run. Seven `asyncio.wait_for` uses in the tree; the one
await that gates the entire run was the omission.

**It fits the 7 dead runs point for point** (r19, r35, r38, r42, r44, r136, r140):

| observed | explained by a hang at this line |
|---|---|
| no `milestones.json` | the write is *after* it |
| a `.lock` in 5 of 7 | an earlier `list_milestones()` read created the lock and found nothing |
| design_analyst logging 104–789s **after** the orchestrator's last entry | a separate task, unaffected |
| the orchestrator lane idling on *"kickoff still in flight"* | it is, forever |
| **no `phase_error`** | a hang raises nothing |
| 3–4 minute runs with references, no DDL, no frontend | design prep completed; nothing after it started |

★ **This is the best-supported candidate of the whole chain, and it is still a candidate.** After
item 198's correction I am not calling it the cause: a hang leaves no artifact, so the corpus can
show the fit and not the fact. What run 152 decides is which of the two it is — and either way the
timeout is right, because an unbounded await in front of the entire pipeline is a defect
independent of whether it has fired.

On timeout it falls into the **existing** `_planned = None` path, which #865 made a real
single-milestone fallback rather than a log line. The two compose: **#865 made the fallback real,
#870 makes it reachable.**
"""
import asyncio
import inspect
import os
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _span():
    """The planning block, anchored between its own marker and the roadmap seed that follows."""
    src = inspect.getsource(orch)
    start = src.index("#870: BOUND this await")
    end = src.index("set_roadmap(milestones", start)
    return src[start:end]


def test_the_planning_site_is_findable():
    """Non-vacuity: every case below reads this span."""
    src = inspect.getsource(orch)
    assert "#870: BOUND this await" in src
    assert "plan_milestones(" in src


def test_the_await_is_bounded():
    span = _span()
    assert "asyncio.wait_for(" in span
    assert "plan_milestones(" in span
    assert "_MILESTONE_PLAN_TIMEOUT_S_870" in span


def test_a_timeout_falls_back_rather_than_propagating():
    """★ A raise here would trade a hang for an aborted run — strictly worse, because the single
    milestone is a perfectly good outcome and #865 now actually produces it."""
    span = _span()
    assert "except asyncio.TimeoutError:" in span
    assert "_planned = None" in span


def test_the_timeout_is_reported_as_an_error():
    """Silent degradation is this pipeline's dominant class; a fallback nobody sees is how a
    multi-milestone run quietly becomes a single-milestone one."""
    span = _span()
    assert "_logger.error" in span
    assert "TIMED OUT" in span


def test_the_constant_is_finite_generous_and_overridable():
    t = orch._MILESTONE_PLAN_TIMEOUT_S_870
    assert 30.0 <= t <= 1800.0, t
    src = inspect.getsource(orch)
    assert "ENVGEN_MILESTONE_PLAN_TIMEOUT_S" in src


def test_the_floor_survives_a_hostile_env(monkeypatch):
    """`=0` must not mean 'time out instantly and never plan'. The `max(30.0, …)` is the guard, and
    the env parse must be a number rather than a truthiness test (#562's trap)."""
    src = inspect.getsource(orch)
    m = re.search(r"_MILESTONE_PLAN_TIMEOUT_S_870 = max\(\s*30\.0,\s*float\(", src)
    assert m, "the floor or the numeric parse changed"


@pytest.mark.parametrize("delay,expect_timeout", [(0.0, False), (5.0, True)])
def test_wait_for_semantics_hold_for_this_shape(delay, expect_timeout):
    """★ Not a mock of the orchestrator — a check that the construct actually bounds a coroutine
    that never returns, which is the whole claim. A hang leaves no artifact, so the mechanism has
    to be demonstrated somewhere."""
    async def _hang():
        await asyncio.sleep(delay)
        return ["planned"]

    async def _run():
        try:
            return await asyncio.wait_for(_hang(), timeout=0.05)
        except asyncio.TimeoutError:
            return None

    got = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run())
    assert (got is None) is expect_timeout, got


def test_the_neighbouring_awaits_are_still_bounded():
    """Non-vacuity for the premise that this was the OUTLIER: if the kickoff receipts lose their
    timeouts, the argument changes from 'one omission' to 'a pattern', and the note should be
    re-read."""
    src = inspect.getsource(orch)
    assert src.count("asyncio.wait_for(") >= 4
    assert "KICKOFF_TIMEOUT_SEC + 600" in src


def test_the_fallback_it_lands_in_is_the_real_one():
    """★ #870 is only safe because #865 exists. Timing out into a branch that assigns nothing
    would reproduce #864's empty roadmap — the exact total loss this is meant to prevent."""
    src = inspect.getsource(orch)
    assert "#865: HONOUR the fallback" in src
    assert "if not milestones:" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
