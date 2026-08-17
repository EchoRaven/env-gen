"""#480 — NEW infra regression (r53: 59 LLM failures; r51/r52: 0). design_prep._chat_ladder
forced the screen-enrichment tool with tool_choice="required" (a STRING); the now-stricter
vertex proxy rejects it with BadRequestError 400 ('tool_choice: Input should be a valid
dictionary'). The ladder only caught TypeError, so the 400 PROPAGATED and failed the whole
per-screen enrichment (degraded design → lower fidelity) instead of degrading to JSON-mode.
FIX: send the Anthropic force-tool DICT ({"type":"tool","name":...}) AND degrade on ANY
forced-function failure (the ladder's stated intent) so JSON-mode still yields the screen.
Generalizable to every run's design phase; robust to future provider/proxy changes."""
import asyncio
from env_generator.llm_generator.multi_agent.runtime.design_prep import _chat_ladder


def _run(coro):
    """Run a coroutine in an isolated loop, then restore a FRESH open loop — avoids
    asyncio.run()'s side-effect of leaving a closed loop that breaks later async tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Client:
    def __init__(self, forced_exc=True):
        self.forced_exc = forced_exc
        self.calls = []

    async def chat(self, msgs, **kw):
        self.calls.append(kw)
        if "tool_choice" in kw:
            if self.forced_exc:
                raise Exception("BadRequestError 400 - tool_choice: Input should be a valid dictionary")
            return _Resp(tool_calls=[{"function": {"arguments": '{"name":"forced"}'}}])
        if kw.get("response_mime_type"):
            return _Resp(content='{"name":"s1","regions":[]}')
        return _Resp(content='plain {"name":"s1"}')


def test_forced_function_400_degrades_to_json_mode():
    c = _Client(forced_exc=True)
    out = _run(_chat_ladder(c, [], max_tokens=100))
    assert out == {"name": "s1", "regions": []}, \
        "#480: a forced-function 400 must DEGRADE to JSON-mode (no propagation), still yielding the screen"
    assert isinstance(c.calls[0].get("tool_choice"), dict), \
        "#480: tool_choice sent as an Anthropic DICT, not a bare string"
    assert c.calls[0]["tool_choice"].get("type") == "tool", "#480: {type: tool, name: submit_screen_enrichment}"


def test_forced_function_success_returns_tool_args():
    c = _Client(forced_exc=False)
    out = _run(_chat_ladder(c, [], max_tokens=100))
    assert out == {"name": "forced"}, "#480: a working forced-function returns its tool args (preferred rung)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
