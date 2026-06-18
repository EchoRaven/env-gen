"""Gemini pairs function_call<->function_response BY NAME (not by id like
OpenAI/Anthropic). Our Message tool results only carry `tool_call_id`, never
`.name`, so the Google converter must resolve each result back to its
originating call's REAL function name. The prior bug sent every response named
"tool", causing MALFORMED_FUNCTION_CALL and the model echoing literal tokens
like `tool_error`/`get_skill` as tool names (youtube run).

This locks in: each emitted function_response Part carries the real function
name of the call it answers, derived from the assistant tool_calls by
tool_call_id.
"""

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.config import LLMConfig, LLMProvider  # noqa: E402
from utils.llm import GoogleClient, Message  # noqa: E402

# The converter imports the google-genai SDK; skip cleanly if unavailable.
pytest.importorskip("google.genai")


def _client() -> GoogleClient:
    return GoogleClient(LLMConfig(provider=LLMProvider.GOOGLE, model_name="gemini-3.1-preview"))


def _assistant_with_two_calls() -> Message:
    return Message.assistant(
        content="working on it",
        tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "registryhub_list_tables", "arguments": "{}"}},
            {"id": "call_2", "type": "function",
             "function": {"name": "edit_code", "arguments": "{}"}},
        ],
    )


def _function_response_names(contents):
    """Collect the .name of every function_response Part in converted contents."""
    names = []
    for content in contents:
        for part in (content.parts or []):
            fr = getattr(part, "function_response", None)
            if fr is not None and fr.name is not None:
                names.append(fr.name)
    return names


def test_tool_results_paired_with_real_function_names(monkeypatch):
    # Disable old-observation masking so message ordering/content is untouched.
    monkeypatch.setenv("ENVGEN_CTX_MASK", "0")
    messages = [
        Message.system("system"),
        Message.user("do the thing"),
        _assistant_with_two_calls(),
        Message.tool("table list output", tool_call_id="call_1"),
        Message.tool("edit applied", tool_call_id="call_2"),
    ]

    _, contents = _client()._convert_messages_to_google(messages)
    names = _function_response_names(contents)

    # Two results -> two function_response parts, each with the REAL name.
    assert names == ["registryhub_list_tables", "edit_code"], names
    # The bug regression: nothing must be named the generic "tool".
    assert "tool" not in names


def test_unknown_tool_call_id_falls_back_to_tool(monkeypatch):
    # A result whose id has no matching call still emits (named "tool"),
    # rather than crashing — graceful fallback only when truly unknown.
    monkeypatch.setenv("ENVGEN_CTX_MASK", "0")
    messages = [
        Message.user("hi"),
        Message.tool("orphan output", tool_call_id="missing"),
    ]
    _, contents = _client()._convert_messages_to_google(messages)
    assert _function_response_names(contents) == ["tool"]
