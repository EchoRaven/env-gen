"""Guard: the coordination-tick re-dispatch fires on a wall-clock cadence even
when the done-event is stuck (Defect B, YOUTUBE_RUN_STALL_REVIEW).

The old gate was SOLELY `orchestrator_task_done_event.is_set()`, which stays
False forever when the resident orchestrator's tick LLM-loops without finishing
→ tick #2 never dispatched → run idle-wedges to budget. The pure
`_coordination_tick_due` adds the wall-clock fallback (smoke #19 did this for the
nudge but missed the tick).
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.orchestrator import Orchestrator as _Orch  # noqa: E402
_due = _Orch._coordination_tick_due


class CoordinationTickDueTests(unittest.TestCase):
    def test_event_set_fires_immediately(self):
        # clean tick finish → fire regardless of timing
        self.assertTrue(_due(event_set=True, now=100.0, last_tick_at=100.0, loop_start=100.0, stuck_sec=300.0))

    def test_stuck_event_fires_after_window(self):
        # event never set; >= stuck_sec since last tick → fire (the decouple)
        self.assertTrue(_due(event_set=False, now=500.0, last_tick_at=100.0, loop_start=0.0, stuck_sec=300.0))

    def test_stuck_event_holds_within_window(self):
        # event not set and within the stuck window → don't fire (no flood)
        self.assertFalse(_due(event_set=False, now=250.0, last_tick_at=100.0, loop_start=0.0, stuck_sec=300.0))

    def test_first_tick_fires_within_window_of_loop_start(self):
        # no tick yet (last_tick_at=0) → measured from loop_start; fires after stuck_sec
        self.assertFalse(_due(event_set=False, now=200.0, last_tick_at=0.0, loop_start=0.0, stuck_sec=300.0))
        self.assertTrue(_due(event_set=False, now=300.0, last_tick_at=0.0, loop_start=0.0, stuck_sec=300.0))

    def test_old_behavior_preserved_when_not_stuck(self):
        # before the window elapses, behaves exactly like the old event-only gate
        self.assertFalse(_due(event_set=False, now=50.0, last_tick_at=0.0, loop_start=0.0, stuck_sec=300.0))


if __name__ == "__main__":
    unittest.main()
