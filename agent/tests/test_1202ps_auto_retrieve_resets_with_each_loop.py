"""#1202ps: the auto-retrieve throttle must reset when a new agentic loop restarts `step`,
otherwise every wake after the first pays the NEED_RETRIEVAL decision call."""
import asyncio

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline.stages import (
    AgentStepStageMixin,
)


class _A(AgentStepStageMixin):
    TEAM_TOOL_NAMES = ()

    def __init__(self):
        self.decisions = 0
        self.fetches = 0

    def _agent_has_knowledge_to_fetch(self):
        return True

    def _stage_tool_names(self, *a, **k):
        return set()

    async def _decide_stage_boolean(self, **k):
        self.decisions += 1
        return False

    async def _run_stage_tool_call_phase(self, **k):
        self.fetches += 1
        return None


def _stage(agent, step):
    return asyncio.run(agent._run_retrieve_context_stage(
        enabled=True, tool_schema_map={}, knowledge_fetch_names={"read_memory_bank"},
        knowledge_store_names=set(), hub_sync_tool_names=set(), initial_prompt="p",
        hub_pulse_prompt=None, runtime_team_status_prompt=None, retrieved_action_names={},
        messages=[], files_created=[], files_modified=[], step=step, max_calls_cfg={},
        step_trace={}, step_traces=[], loop_time=lambda: 0.0, mark_stage=lambda *a, **k: None))


def test_a_new_loop_auto_retrieves_without_a_decision_call():
    agent = _A()
    for step in (1, 2, 3, 4, 5):       # first wake runs five steps
        _stage(agent, step)
    decisions_after_first_wake = agent.decisions
    _stage(agent, 1)                   # next wake: step restarts
    assert agent.decisions == decisions_after_first_wake
    assert agent.fetches == 3          # step 1, step 4, and the new loop's step 1


def test_the_throttle_still_applies_within_a_loop():
    agent = _A()
    for step in (1, 2, 3):
        _stage(agent, step)
    assert agent.fetches == 1 and agent.decisions == 2
