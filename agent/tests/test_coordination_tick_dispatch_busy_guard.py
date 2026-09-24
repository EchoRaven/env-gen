"""PROPOSAL #17 — coordination-tick dispatch busy-guard + tunable timeout.

The run() coordination loop awaited the resident LLM tick with a hard-coded
timeout=900.0, and (Defect B) re-dispatched a fresh tick on the wall-clock stuck
path even while the prior tick was still in flight. The orchestrator lane is a
SERIAL queue-consumer, so piling a tick onto a busy/wedged lane floods its queue
→ send_task blocks → the run() loop (and its deterministic drivers) stalls 900s
per cycle → runs can't converge (youtube run 2026-06-18, 3× 900s stalls).

Fix: dispatch ONLY when the lane is FREE (done-event set) + bound the dispatch
await to a tunable ENVGEN_COORD_TICK_DISPATCH_TIMEOUT_S (default 180s).

This pins the fix structurally (run() isn't unit-testable in isolation) + the
busy-guard DECISION semantics via the real coordination_tick_due predicate.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.coordination import coordination_tick_due  # noqa: E402

ORCH = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "orchestrator.py").read_text()


class StructuralPin(unittest.TestCase):
    def test_busy_guard_present(self):
        self.assertIn("_lane_free = orchestrator_task_done_event.is_set()", ORCH)
        self.assertIn("_lane_free and self._coordination_tick_due(", ORCH)

    def test_dispatch_timeout_is_tunable_not_hardcoded_900(self):
        self.assertIn("timeout=coordination_tick_dispatch_timeout_s", ORCH)
        self.assertIn('ENVGEN_COORD_TICK_DISPATCH_TIMEOUT_S', ORCH)
        self.assertIn('"180"', ORCH.split("ENVGEN_COORD_TICK_DISPATCH_TIMEOUT_S")[1][:40])
        self.assertNotIn("timeout=900.0", ORCH)  # the hard-coded value is gone


class BusyGuardDecision(unittest.TestCase):
    """The inline dispatch condition is `_lane_free and coordination_tick_due(event_set=_lane_free, ...)`.
    Replicate it to pin the decision: a BUSY lane is never re-dispatched (the
    Defect-B stuck-path pile-up that caused the 900s flood is gone); a FREE lane
    dispatches per the normal cadence."""

    @staticmethod
    def _would_dispatch(lane_free, now, last_tick_at, loop_start, stuck_sec):
        return bool(lane_free and coordination_tick_due(
            event_set=lane_free, now=now, last_tick_at=last_tick_at,
            loop_start=loop_start, stuck_sec=stuck_sec))

    def test_busy_lane_never_dispatched_even_when_long_wedged(self):
        # lane busy (done-event NOT set) + 10000s since last tick (way past stuck) →
        # the OLD Defect-B stuck path would re-dispatch (pile-up); the fix must NOT.
        self.assertFalse(self._would_dispatch(
            lane_free=False, now=10_000, last_tick_at=0, loop_start=0, stuck_sec=300))

    def test_free_lane_dispatches(self):
        # lane free → dispatch (event_set short-circuits coordination_tick_due True)
        self.assertTrue(self._would_dispatch(
            lane_free=True, now=10, last_tick_at=0, loop_start=0, stuck_sec=300))


if __name__ == "__main__":
    unittest.main()
