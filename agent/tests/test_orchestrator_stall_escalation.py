"""Round 8h Patch B — closed-by-construction pin for
``Orchestrator._nudge_silent_resident_lanes``.

Smoke #18 surfaced that the coordination loop at
``orchestrator.py:621-750`` was textually instructing the orchestrator
lane to "escalate" after ``idle_tick_count >= 3``, but the actual peer
lanes (Frontend, Verifier, Debugger, Knowledge) never woke at all —
zero ``agent_status`` events emitted in 5 hours. Reading a textual
instruction cannot wake a peer.

This test fixes that by construction:

  * `_nudge_silent_resident_lanes(kickoff_finalized_at)` reads
    ``EventHub.get_all_agent_statuses`` and dispatches an urgent
    ``task_ready`` to every resident lane that has produced ZERO
    agent_status events since finalize.
  * Liveness evidence (any agent_status with ``_event_created_at >
    kickoff_finalized_at``) suppresses the nudge AND resets the
    per-lane nudge counter.
  * The orchestrator lane is never nudged (it's the polling lane).
  * Repeated calls increment a per-lane nudge counter so a future
    iteration can detect "still silent after N nudges".
"""

from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _FakeAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class _FakeEventHub:
    def __init__(self, statuses: Dict[str, Dict[str, Any]]):
        self._statuses = statuses

    def get_all_agent_statuses(self) -> dict:
        # Return a fresh copy each call (production semantics).
        return {k: dict(v) for k, v in self._statuses.items()}


class _FakeHubs:
    def __init__(self, eventhub: _FakeEventHub):
        self.eventhub = eventhub


class _StubOrchestrator:
    """A minimal bind target for the unbound method we're testing —
    avoids booting the full Orchestrator (MessageBus, agents, hubs,
    checkpoint manager, etc.)."""

    def __init__(self, statuses: Dict[str, Dict[str, Any]]):
        self.hubs = _FakeHubs(_FakeEventHub(statuses))
        self._agents = {
            "orchestrator": _FakeAgent("orchestrator"),
            "backend": _FakeAgent("backend"),
            "frontend": _FakeAgent("frontend"),
            "verifier": _FakeAgent("verifier"),
            "debugger": _FakeAgent("debugger"),
            "knowledge": _FakeAgent("knowledge"),
        }
        self.message_bus = MagicMock()
        self.message_bus.send = AsyncMock(return_value=True)
        self._silent_lane_nudges: Dict[str, int] = {}
        self._logger = logging.getLogger("stub_orchestrator")


def _nudge_method():
    """Pull the unbound coroutine off the real Orchestrator class."""
    from multi_agent.orchestrator import Orchestrator
    return Orchestrator._nudge_silent_resident_lanes


class NudgeSilentResidentLanesTests(unittest.TestCase):

    def test_silent_lanes_get_urgent_task_ready(self):
        """When NO lanes have emitted post-finalize agent_status, all
        non-orchestrator lanes get an urgent task_ready."""
        kickoff_finalized_at = 1000.0
        stub = _StubOrchestrator(statuses={})
        nudged = _run(_nudge_method()(stub, kickoff_finalized_at))

        self.assertEqual(
            sorted(nudged),
            ["backend", "debugger", "frontend", "knowledge", "verifier"],
        )
        # Orchestrator itself is never nudged.
        self.assertNotIn("orchestrator", nudged)
        # bus.send called once per nudged lane.
        self.assertEqual(stub.message_bus.send.await_count, 5)
        # Verify each call carried msg_type=task_ready + URGENT.
        for call in stub.message_bus.send.await_args_list:
            (message,) = call.args
            self.assertEqual(message.metadata.get("msg_type"), "task_ready")
            self.assertEqual(message.header.priority.name, "URGENT")
            self.assertIn(
                message.header.target_agent_id,
                {"backend", "frontend", "verifier", "debugger", "knowledge"},
            )

    def test_lane_with_post_finalize_status_not_nudged(self):
        """A lane that emitted agent_status AFTER kickoff_finalized_at
        is provably alive and MUST NOT be nudged."""
        kickoff_finalized_at = 1000.0
        statuses = {
            "backend": {"_event_created_at": 1100.0, "status": "active"},
            "frontend": {"_event_created_at": 1050.0, "status": "active"},
        }
        stub = _StubOrchestrator(statuses=statuses)
        nudged = _run(_nudge_method()(stub, kickoff_finalized_at))

        self.assertNotIn("backend", nudged)
        self.assertNotIn("frontend", nudged)
        # Verifier / Debugger / Knowledge still silent → nudged.
        self.assertEqual(
            sorted(nudged), ["debugger", "knowledge", "verifier"],
        )

    def test_lane_with_pre_finalize_status_still_nudged(self):
        """An agent_status whose timestamp predates kickoff_finalized
        does NOT count as liveness — it's stale from a prior session."""
        kickoff_finalized_at = 1000.0
        statuses = {
            "backend": {"_event_created_at": 500.0, "status": "stale"},
        }
        stub = _StubOrchestrator(statuses=statuses)
        nudged = _run(_nudge_method()(stub, kickoff_finalized_at))

        self.assertIn("backend", nudged)

    def test_nudge_counter_increments_on_repeated_silence(self):
        """Each call to the nudge helper while a lane remains silent
        increments that lane's per-lane nudge counter — lets a future
        iteration detect 'still silent after N nudges' and escalate."""
        kickoff_finalized_at = 1000.0
        stub = _StubOrchestrator(statuses={})
        _run(_nudge_method()(stub, kickoff_finalized_at))
        _run(_nudge_method()(stub, kickoff_finalized_at))
        _run(_nudge_method()(stub, kickoff_finalized_at))

        self.assertEqual(stub._silent_lane_nudges["backend"], 3)
        self.assertEqual(stub._silent_lane_nudges["frontend"], 3)

    def test_liveness_resets_nudge_counter(self):
        """Once a previously-silent lane emits a post-finalize
        agent_status, its nudge counter resets (next stall episode
        starts clean instead of accumulating against a now-alive lane)."""
        kickoff_finalized_at = 1000.0
        stub = _StubOrchestrator(statuses={})
        _run(_nudge_method()(stub, kickoff_finalized_at))
        _run(_nudge_method()(stub, kickoff_finalized_at))
        self.assertEqual(stub._silent_lane_nudges.get("backend"), 2)

        # Backend wakes and emits a post-finalize status.
        stub.hubs.eventhub._statuses["backend"] = {
            "_event_created_at": 1500.0, "status": "active",
        }
        _run(_nudge_method()(stub, kickoff_finalized_at))
        self.assertNotIn("backend", stub._silent_lane_nudges)

    def test_eventhub_failure_returns_empty_and_logs(self):
        """If the EventHub read raises, the nudge helper logs and
        returns [] (no nudge) — it never crashes the coordination loop
        on a hub-side bug."""
        kickoff_finalized_at = 1000.0
        stub = _StubOrchestrator(statuses={})

        def boom():
            raise RuntimeError("eventhub corrupted")
        stub.hubs.eventhub.get_all_agent_statuses = boom

        nudged = _run(_nudge_method()(stub, kickoff_finalized_at))
        self.assertEqual(nudged, [])
        # No bus.send calls were made.
        self.assertEqual(stub.message_bus.send.await_count, 0)

    def test_bus_send_returning_false_does_not_count_as_nudged(self):
        """If bus.send returns False (target not registered with bus —
        a structural wiring bug), the lane is NOT recorded as nudged
        and its counter does not increment. A loud ERROR is logged
        so the bug surfaces."""
        kickoff_finalized_at = 1000.0
        stub = _StubOrchestrator(statuses={})
        stub.message_bus.send = AsyncMock(return_value=False)

        nudged = _run(_nudge_method()(stub, kickoff_finalized_at))
        self.assertEqual(nudged, [])
        self.assertEqual(stub._silent_lane_nudges, {})


class ShouldAttemptSilentLaneNudgeTests(unittest.TestCase):
    """Round 8h Patch B v2 — pure wall-clock cadence helper. Smoke #19
    surfaced that the v1 wiring nested the nudge inside
    ``if orchestrator_task_done_event.is_set()`` so when the
    orchestrator lane LLM-looped without finishing tick #1 the nudge
    never fired. v2 extracts the gating decision into this pure
    helper and calls it on every ``wait_for`` timeout iteration
    INDEPENDENT of the tick boundary.
    """

    def _decide(self, **kw):
        from multi_agent.orchestrator import Orchestrator
        defaults = {
            "now": 1300.0,
            "kickoff_finalized_at": 1000.0,
            "last_nudge_attempt_at": 0.0,
            "grace_sec": 120.0,
            "interval_sec": 60.0,
        }
        defaults.update(kw)
        return Orchestrator._should_attempt_silent_lane_nudge(**defaults)

    def test_inside_grace_period_returns_false(self):
        """Within the grace period after finalize, no nudge —
        kickoff_complete subscribers get a fair shot to wake first."""
        # 60s post-finalize, grace=120s → too early.
        self.assertFalse(self._decide(now=1060.0, kickoff_finalized_at=1000.0))

    def test_first_nudge_after_grace_period(self):
        """Past the grace period and no previous nudge → fire."""
        self.assertTrue(self._decide(
            now=1130.0, kickoff_finalized_at=1000.0,
            last_nudge_attempt_at=0.0,
        ))

    def test_nudge_interval_throttle(self):
        """Within the inter-nudge interval, even if grace cleared,
        the helper says no — prevents bus spam."""
        # 200s after finalize (past 120s grace) BUT only 30s after
        # previous nudge (interval=60s) → wait.
        self.assertFalse(self._decide(
            now=1200.0, kickoff_finalized_at=1000.0,
            last_nudge_attempt_at=1170.0,
        ))

    def test_nudge_again_after_interval(self):
        """Past both grace and inter-nudge interval → fire again."""
        self.assertTrue(self._decide(
            now=1230.0, kickoff_finalized_at=1000.0,
            last_nudge_attempt_at=1170.0,
        ))

    def test_grace_period_takes_priority_over_interval(self):
        """Even if last_nudge_attempt is ancient, we still wait for
        the grace period to clear (the grace is post-finalize, not
        relative to nudges)."""
        # Last nudge was a long time ago, but kickoff just finalized.
        self.assertFalse(self._decide(
            now=1010.0, kickoff_finalized_at=1000.0,
            last_nudge_attempt_at=0.0,
            grace_sec=120.0,
        ))

    def test_zero_grace_zero_interval_always_fires(self):
        """Operationally tunable: env vars set both to 0 → every
        wait_for-timeout iteration fires a nudge attempt."""
        self.assertTrue(self._decide(
            now=1001.0, kickoff_finalized_at=1000.0,
            last_nudge_attempt_at=999.0,
            grace_sec=0.0, interval_sec=0.0,
        ))


if __name__ == "__main__":
    unittest.main()
