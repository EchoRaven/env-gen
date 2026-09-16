"""#1202po: a tool-less stage call reuses the previous request's tools with
tool_choice="none", so it shares the provider's cached prefix instead of paying full input
price for the whole history (measured: 5,632/6,411 cached vs 0 with tools removed)."""
import asyncio

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import tooling


class OpenAIClient:  # the class name is the provider signal
    pass


class OtherClient:
    pass


class _LLM:
    def __init__(self, client):
        self._client = client

    async def chat_messages(self, messages, **kw):
        return kw


class _Agent(tooling.AgentStepToolingMixin):
    agent_id = "backend"

    def __init__(self, client):
        self.llm = _LLM(client)
        self.sent = []

    async def call_with_retry(self, fn, *a, **kw):
        self.sent.append(kw)
        return await fn(*a, **kw)


TOOLS = [{"type": "function", "function": {"name": "read", "parameters": {}}}]


def _drive(agent):
    async def go():
        await agent._call_stage_llm([], "action", "act", TOOLS)
        await agent._call_stage_llm([], "planning", "plan", [])
    asyncio.run(go())
    return agent.sent


def test_a_tool_less_stage_keeps_the_previous_tools_with_none(monkeypatch):
    monkeypatch.delenv("ENVGEN_STAGE_TOOLS_CACHE", raising=False)
    sent = _drive(_Agent(OpenAIClient()))
    assert sent[1]["tools"] == TOOLS
    assert sent[1]["tool_choice"] == "none"
    assert "tool_choice" not in sent[0]


def test_the_first_call_has_nothing_to_reuse(monkeypatch):
    monkeypatch.delenv("ENVGEN_STAGE_TOOLS_CACHE", raising=False)
    agent = _Agent(OpenAIClient())
    asyncio.run(agent._call_stage_llm([], "planning", "plan", []))
    assert agent.sent[0]["tools"] == [] and "tool_choice" not in agent.sent[0]


def test_other_providers_and_the_switch_are_untouched(monkeypatch):
    monkeypatch.delenv("ENVGEN_STAGE_TOOLS_CACHE", raising=False)
    sent = _drive(_Agent(OtherClient()))
    assert sent[1]["tools"] == [] and "tool_choice" not in sent[1]
    monkeypatch.setenv("ENVGEN_STAGE_TOOLS_CACHE", "0")
    sent = _drive(_Agent(OpenAIClient()))
    assert sent[1]["tools"] == [] and "tool_choice" not in sent[1]
