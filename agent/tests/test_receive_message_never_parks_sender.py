"""#150 — receive_message must never park the SENDER on a full dispatch queue.

run-77 live (USR2 task dump, 09:56): SEVEN tasks parked at messaging.py:96
`await self._message_queue.put(message)` — the bounded asyncio.Queue(100) of a lane
whose _main_loop was itself stuck inside _dispatch_message. The backend posted FINISH
at 09:44:26 and its notification flush (bus.send → target.receive_message → queue.put)
parked forever → its unwind never ran → state stuck PROCESSING_TASK for 12min = the
run-71 REAL-wedge class, root-caused. The watchdog (#147/#149, poller context) rescued
it — this fixes the cause.

By line 96 the message has ALREADY reached _subscription_inbox, the priority queue
(line 95, drop-when-full by design), and the interrupt channel for urgent types — the
bounded _message_queue only feeds _main_loop's ordinary dispatch. On QueueFull we now
drop THAT delivery loudly instead of parking the sender (the inbox + priority-queue
copies survive; a 100-deep dispatch backlog means ordinary dispatch is already dead).
LOCAL-ONLY (agent/tests/ gitignored).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402


class _Lane(AgentMessaging):
    def __init__(self, qsize=1):
        self.agent_id = "verifier"
        self.warnings = []
        self._logger = SimpleNamespace(
            info=lambda *a, **k: None, debug=lambda *a, **k: None,
            error=lambda *a, **k: None,
            warning=lambda *a, **k: self.warnings.append(a[0] if a else ""))
        self._message_queue = asyncio.Queue(maxsize=qsize)


def test_full_dispatch_queue_drops_loudly_instead_of_parking():
    async def run():
        lane = _Lane(qsize=1)
        lane._message_queue.put_nowait("existing")  # queue is FULL
        # must return promptly instead of awaiting a consumer that never comes
        await asyncio.wait_for(
            asyncio.ensure_future(_call(lane, "m2")), timeout=2.0)
        assert lane._message_queue.qsize() == 1, "full queue → dispatch copy dropped"
        assert lane.warnings, "the drop must be LOUD (warning with the queue state)"
        assert any("dispatch" in w or "full" in w for w in lane.warnings)
    asyncio.run(run())


def test_normal_path_still_enqueues():
    async def run():
        lane = _Lane(qsize=4)
        await _call(lane, "m1")
        assert lane._message_queue.qsize() == 1
        assert not lane.warnings
    asyncio.run(run())


async def _call(lane, msg):
    await lane._enqueue_for_dispatch(msg)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
