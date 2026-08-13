r"""#639: pacing the idle spin — the deferral in #637 was wrong, and measurably so.

#637 measured that **952M of the orchestrator's 2.76B tokens (35%)** are spent on steps that
conclude "Idle." — a median of 63 per run — and then added only a counter, on the grounds that
the cost of pacing "is not measurable from any artifact on disk".

The artifacts carry timestamps. It is measurable, and it is one-sided:

    P(next step does real work)      after 1 idle 53% · after 2 40% · after 6+  8%
    tokens in the k>=6 idle bucket   199M
    transitions a backoff postpones  110 total = 1.8 per run
    median step gap (one tick)       10.3s        median run wall-clock 68 min
    => added latency                 0.3 min/run = 0.5% of the run

0.5% of the clock against 199M tokens, and nothing is ever dropped: work arriving during the wait
is picked up by the very next step. Third time this session that a "not computable" claim
dissolved on contact with the data — the same correction as #630, #615 and #638.
"""
import asyncio
import logging

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.step_runner import (
    _IDLE_BACKOFF_AFTER_639 as AFTER,
    _IDLE_BACKOFF_MAX_S_639 as CAP,
    _idle_backoff_639 as backoff,
)


class _Agent:
    agent_id = "orchestrator"
    _logger = logging.getLogger("test")

    def __init__(self, streak=0):
        self._idle_streak_637 = streak


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Assert on the requested delay, never actually wait."""
    slept = []

    async def fake(sec):
        slept.append(sec)

    monkeypatch.setattr(asyncio, "sleep", fake)
    return slept


def _run(agent):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(backoff(agent))


# --- when it engages ------------------------------------------------------------------------------

def test_a_busy_agent_never_waits():
    assert asyncio.run(backoff(_Agent(0))) == 0.0


@pytest.mark.parametrize("streak", [1, 2, 3, 4, 5])
def test_a_short_streak_never_waits(streak):
    """Below the threshold, P(next step does work) is 20-53% — pacing there would cost real
    responsiveness for little saving."""
    assert asyncio.run(backoff(_Agent(streak))) == 0.0


def test_it_engages_at_the_measured_threshold():
    """k>=6 is where P(work) collapses to 8% and where the 199M tokens sit."""
    assert AFTER == 6
    assert asyncio.run(backoff(_Agent(6))) > 0


def test_the_first_wait_is_about_one_tick():
    """The measured median step gap is 10.3s; the first backoff must be that order, not minutes."""
    assert asyncio.run(backoff(_Agent(6))) == pytest.approx(10.0)


# --- how it grows ---------------------------------------------------------------------------------

def test_it_doubles_as_the_streak_lengthens():
    a, b, c = (asyncio.run(backoff(_Agent(k))) for k in (6, 7, 8))
    assert b == 2 * a and c == 2 * b


def test_it_is_capped():
    assert asyncio.run(backoff(_Agent(50))) == CAP
    assert CAP <= 60.0


def test_the_cap_is_far_below_a_run():
    """68 min median run — a single wait must never be a meaningful fraction of it."""
    assert CAP / (68 * 60) < 0.02


# --- it must never break the loop -------------------------------------------------------------------

def test_a_missing_counter_is_treated_as_busy():
    class _Bare:
        pass
    assert asyncio.run(backoff(_Bare())) == 0.0


def test_a_bogus_counter_does_not_raise():
    a = _Agent(0)
    a._idle_streak_637 = "lots"
    assert asyncio.run(backoff(a)) == 0.0


def test_a_missing_logger_does_not_raise():
    class _NoLog:
        _idle_streak_637 = 9
    assert asyncio.run(backoff(_NoLog())) > 0


# --- wiring -------------------------------------------------------------------------------------

def test_it_runs_before_the_step_is_announced():
    """The wait belongs before the model call, not after the work is already assembled."""
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import step_runner
    src = inspect.getsource(step_runner)
    i = src.index("await _idle_backoff_639(self)")
    assert i < src.index('f"[{self.agent_id}] Step {step + 1}/{max_steps}', i)


def test_the_streak_is_reset_by_real_work():
    """Without this the backoff would keep growing after the agent resumed working."""
    from env_generator.llm_generator.multi_agent.agents.runtime.hub_pulse import note_finish_637
    a = _Agent(9)
    note_finish_637(a, "Dispatched 2 failing checks")
    assert a._idle_streak_637 == 0
    assert asyncio.run(backoff(a)) == 0.0


def test_the_counterfactual_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import step_runner
    flat = " ".join(inspect.getsource(step_runner._idle_backoff_639).split())
    assert "0.5% of wall clock" in flat
    assert "199M" in flat and "1.8 per run" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
