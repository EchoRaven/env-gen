"""#1202qi: an issue sent to the orchestrator is routed to the owning lane in a short loop; a
code lane still gets the fix-in-your-code loop."""
import asyncio
import logging
from types import SimpleNamespace

from env_generator.llm_generator.multi_agent.agents.runtime import messaging as M


class _Agent(M.AgentMessaging):
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self._logger = logging.getLogger("t")
        self._processing_state = None
        self._external_bus = None
        self.loops = []

    def _real_author_985(self, message, from_agent):
        return from_agent

    async def _send_runtime_status_update(self, **k):
        return None

    def _compose_system_prompt(self):
        return "sys"

    async def run_agentic_loop(self, system_prompt, initial_prompt, max_steps):
        self.loops.append((initial_prompt, max_steps))

    async def _drain_deferred_task_ready_messages(self):
        return None


def _issue():
    return SimpleNamespace(header=SimpleNamespace(source_agent_id="debugger"),
                           payload="POST /api/videos returns 500", metadata={"context": {}})


def test_the_orchestrator_routes_in_a_short_loop():
    a = _Agent("orchestrator")
    asyncio.run(a._handle_issue(_issue()))
    prompt, steps = a.loops[0]
    assert steps <= 8
    assert "do not edit code" in prompt and "Fix this issue in your code" not in prompt


def test_a_code_lane_keeps_the_fix_loop():
    a = _Agent("backend")
    asyncio.run(a._handle_issue(_issue()))
    prompt, steps = a.loops[0]
    assert steps == 30 and "Fix this issue in your code" in prompt
