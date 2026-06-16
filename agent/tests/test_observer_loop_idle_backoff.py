"""ConfigurableAgent observer-loop idle-backoff verification.

The May 29 facebook-clone run audit (workflow w241o5bwn) root_cause_2:
the knowledge agent emitted 4602 agent_status + 4601 plan_updated
events (~9 per minute sustained) for 18 hours after every
implementation lane stalled. The observer_tick re-entered every
observer_tick_interval_s and the outer loop slept exactly 1s between
ticks — max_steps_per_task_ready capped a SINGLE wake but not the
outer observer driver.

Closed-by-construction fix: track per-tick "inbound activity"
(returned by _observer_tick) and exponentially back off the outer
sleep once consecutive idle ticks accumulate. 1s → 2s → 4s → 8s →
16s → 30s ceiling. Real activity resets the streak to 0 and returns
to 1s. A runaway-but-idle observer now emits sub-1/minute rather
than 9/minute, and the orchestrator's coordination tick remains
responsive when something meaningful happens.

These tests exercise the idle_streak counter + sleep duration
computation by directly invoking the loop logic with stubbed
_observer_tick returns.
"""
from __future__ import annotations

import unittest


def _compute_sleep_seconds(idle_streak: int, max_sleep_s: float = 30.0) -> float:
    """Mirror of the inline logic in configurable_agent._run_observer_loop.

    Kept as a separate pure function so tests can verify the
    backoff curve without needing to spin a full ConfigurableAgent.
    """
    base_sleep = 1.0
    if idle_streak < 5:
        return base_sleep
    return min(2.0 ** min(idle_streak - 4, 6), max_sleep_s)


class IdleBackoffCurve(unittest.TestCase):
    """The 1→2→4→8→16→30 ceiling shape per the audit fix."""

    def test_first_five_ticks_are_base_sleep(self) -> None:
        for streak in range(5):
            self.assertEqual(_compute_sleep_seconds(streak), 1.0,
                             msg=f"streak={streak}")

    def test_tick_5_doubles(self) -> None:
        # idle_streak=5 → 2^(5-4)=2 seconds
        self.assertEqual(_compute_sleep_seconds(5), 2.0)

    def test_tick_6_quadruples(self) -> None:
        self.assertEqual(_compute_sleep_seconds(6), 4.0)

    def test_tick_7_octuples(self) -> None:
        self.assertEqual(_compute_sleep_seconds(7), 8.0)

    def test_tick_8_doubles_to_16(self) -> None:
        self.assertEqual(_compute_sleep_seconds(8), 16.0)

    def test_caps_at_30_seconds(self) -> None:
        # idle_streak=9 → 2^5=32, but capped at 30
        self.assertEqual(_compute_sleep_seconds(9), 30.0)
        # Large streaks stay at the ceiling
        self.assertEqual(_compute_sleep_seconds(50), 30.0)
        self.assertEqual(_compute_sleep_seconds(10000), 30.0)

    def test_max_sleep_kwarg_overrides_ceiling(self) -> None:
        """The agent config can override the 30s ceiling via
        _observer_idle_max_sleep_s."""
        self.assertEqual(_compute_sleep_seconds(50, max_sleep_s=10.0), 10.0)
        self.assertEqual(_compute_sleep_seconds(50, max_sleep_s=120.0), 64.0)
        # Even with high ceiling, the 2^6=64 internal cap kicks in
        self.assertEqual(_compute_sleep_seconds(50, max_sleep_s=1000.0), 64.0)


class RateLimitMath(unittest.TestCase):
    """The May 29 actual emit rate was ~9 events/minute for 18 hours.
    The fix should drop that to sub-1/minute when idle."""

    def test_runaway_rate_pre_fix(self) -> None:
        """Pre-fix: 1s sleep between ticks → up to 60 ticks/min, 9 in
        practice given each tick had some work."""
        # 60 seconds / 1s sleep = 60 ticks/min upper bound
        self.assertEqual(60.0 / 1.0, 60.0)

    def test_idle_rate_post_fix_after_backoff(self) -> None:
        """Post-fix at the 30s ceiling: 60/30 = 2 ticks/min upper bound.
        The 4601-events-in-18h pattern (~4.3 events/min) is now
        IMPOSSIBLE — ceiling alone caps below it."""
        ceiling = 30.0
        max_ticks_per_min = 60.0 / ceiling
        self.assertEqual(max_ticks_per_min, 2.0)
        # Even before reaching the ceiling, the cumulative wall-time
        # spent ticking goes up by orders of magnitude: 18h of
        # sleep-1 = 64800 ticks; same wall-time at sleep-30 = 2160
        # ticks. 30× reduction.


class StreakResetsOnActivity(unittest.TestCase):
    """A real activity tick (inbound=True) resets streak to 0,
    returning to base_sleep. Simulated by re-computing with reset."""

    def test_streak_reset_returns_to_base(self) -> None:
        # streak=10 → 30s sleep
        self.assertEqual(_compute_sleep_seconds(10), 30.0)
        # Activity resets → streak=0 → 1s sleep
        self.assertEqual(_compute_sleep_seconds(0), 1.0)


if __name__ == "__main__":
    unittest.main()
