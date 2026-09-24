"""orchestrator._dispatch_implementation_phase — the §5-entry / D4.3 dispatch.

Smoke #3 (2026-06-05): kickoff finalized + created 11 assigned tasks, but the
lanes never implemented — they wake on kickoff_complete (not a task_ready, so it
doesn't pass KickoffBootstrapGate) and burn their idle budget on kickoff replies,
getting LaneIdleCircuitBreaker-halted before any code is written. This dispatch
step makes finalize⟹work deterministic: reset the lanes' idle counters at the
kickoff→implement boundary + send each impl lane an orchestrator task_ready.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


class _FakeAgent:
    def __init__(self):
        # simulate a lane that burned its idle budget during kickoff
        self._consecutive_idle_steps = 9
        self._last_idle_tier = 2
        self._lane_idle_tier3_failed = False
        self._lane_idle_prev_owned = 3


class _FakeWorkHub:
    def __init__(self, tasks):
        self._tasks = tasks
    def list_tasks(self):
        return self._tasks


class _FakeHubs:
    def __init__(self, tasks):
        self.workhub = _FakeWorkHub(tasks)


class _FakeBus:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)
        return True


class _StubOrchestrator:
    def __init__(self, tasks):
        import logging
        self._agents = {
            "orchestrator": _FakeAgent(),
            "backend": _FakeAgent(),
            "frontend": _FakeAgent(),
            "verifier": _FakeAgent(),
        }
        self.hubs = _FakeHubs(tasks)
        self.message_bus = _FakeBus()
        self._logger = logging.getLogger("stub_dispatch")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _target_lanes(bus):
    return {m.header.target_agent_id for m in bus.sent}


class DispatchImplementationPhaseTests(unittest.TestCase):
    def _dispatch(self, tasks):
        from multi_agent.orchestrator import Orchestrator
        stub = _StubOrchestrator(tasks)
        dispatched = _run(Orchestrator._dispatch_implementation_phase(stub))
        return stub, dispatched

    def test_resets_idle_counters_for_every_lane(self):
        stub, _ = self._dispatch([{"owner": "backend"}, {"owner": "frontend"}])
        for lane_id, agent in stub._agents.items():
            self.assertEqual(agent._consecutive_idle_steps, 0, lane_id)
            self.assertEqual(agent._last_idle_tier, 0, lane_id)
            self.assertFalse(agent._lane_idle_tier3_failed, lane_id)
            self.assertIsNone(agent._lane_idle_prev_owned, lane_id)  # re-seed

    def test_dispatches_task_ready_to_impl_lanes_only(self):
        stub, dispatched = self._dispatch([{"owner": "backend"}, {"owner": "frontend"},
                                           {"owner": "verifier"}])
        self.assertEqual(set(dispatched), {"backend", "frontend"})
        self.assertEqual(_target_lanes(stub.message_bus), {"backend", "frontend"})
        # never the verifier (it self-triggers on impl-completion) or orchestrator
        self.assertNotIn("verifier", _target_lanes(stub.message_bus))
        self.assertNotIn("orchestrator", _target_lanes(stub.message_bus))

    def test_dispatched_messages_are_orchestrator_task_ready(self):
        stub, _ = self._dispatch([{"assignee": "backend"}])
        self.assertTrue(stub.message_bus.sent)
        for m in stub.message_bus.sent:
            self.assertEqual(m.header.source_agent_id, "orchestrator")
            self.assertEqual((m.metadata or {}).get("msg_type"), "task_ready")

    def test_robust_to_empty_task_list(self):
        # Even with no listable tasks, the impl lanes still get the start signal
        # (the contract is registered; they claim by assignee at wake).
        stub, dispatched = self._dispatch([])
        self.assertEqual(set(dispatched), {"backend", "frontend"})


if __name__ == "__main__":
    unittest.main()
