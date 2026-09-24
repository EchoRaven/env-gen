"""#259 — a tool exchange cannot be replayed to a request that declares NO tools.

Root cause of the `unexpected tool_use_id` 400 that has blocked every Anthropic-backed
provider for this pipeline. Bisected live against the gateway with one message list sent
twice:

    same 8 messages + "tools": [...]   -> 200
    same 8 messages, no "tools" key    -> 400 messages.4.content.0: unexpected
                                          `tool_use_id` ... must have a corresponding
                                          `tool_use` block in the previous message

With no tool declarations there is nothing for the assistant's `tool_use` block to refer
to, so it is dropped in translation and the following `tool_result` is orphaned. It was
never a pairing bug — r46/r48/r53 WIRE-SHAPE dumps all showed the pairing adjacent and
correct — and it is not the gateway's fault either: we were sending an unrepresentable
history. The framework issues plenty of tool-less calls (planning, summarisation,
condensation) over histories that contain tool exchanges; r53 logged `tools=0` on exactly
the calls that 400'd, and each one degraded the run ("action round planning skipped").

The repair is information-preserving: keep the tool call and its result as TEXT, so the
model still sees what was called and what came back.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.llm import _prepare_messages_for_request  # noqa: E402

TID = "toolu_vrtx_01TCzGfB8fWmVufnQx8bpR6x"
MODEL = "claude-4-7-opus-vertex-genai"
TOOLS = [{"type": "function", "function": {"name": "check_inbox", "parameters": {}}}]


def _history():
    return [
        {"role": "system", "content": "You coordinate the team."},
        {"role": "user", "content": "kickoff"},
        {"role": "assistant", "content": "planning"},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "checking",
         "tool_calls": [{"id": TID, "type": "function",
                         "function": {"name": "check_inbox",
                                      "arguments": '{"limit": 20}'}}]},
        {"role": "tool", "tool_call_id": TID, "content": '{"count": 2}'},
        {"role": "assistant", "content": "got it"},
        {"role": "user", "content": "next step"},
    ]


def _has_tool_protocol(wire):
    return any(m.get("tool_calls") or m.get("role") == "tool" or m.get("tool_call_id")
               for m in wire)


def test_toolless_request_carries_no_tool_protocol():
    """The regression: this exact payload 400s against a live Anthropic-backed model."""
    wire = _prepare_messages_for_request(_history(), MODEL, tools=None)
    assert not _has_tool_protocol(wire)


def test_toolless_request_keeps_the_information():
    """Flatten, do not delete — the model must still see the call and its result."""
    text = " ".join(str(m.get("content") or "") for m in
                    _prepare_messages_for_request(_history(), MODEL, tools=None))
    assert "check_inbox" in text
    assert '"count": 2' in text or '{"count": 2}' in text


def test_request_WITH_tools_is_untouched():
    """The working path must not change shape at all."""
    wire = _prepare_messages_for_request(_history(), MODEL, tools=TOOLS)
    assert _has_tool_protocol(wire)
    assert any(m.get("role") == "tool" for m in wire)


def test_empty_tool_list_counts_as_toolless():
    wire = _prepare_messages_for_request(_history(), MODEL, tools=[])
    assert not _has_tool_protocol(wire)


def test_applies_to_every_provider_not_just_anthropic():
    """A history that cannot be represented is wrong everywhere; Gemini merely tolerated
    it. Keeping the rule provider-independent avoids a second silent divergence."""
    wire = _prepare_messages_for_request(_history(), "gemini-3.1-pro-preview-customtools",
                                         tools=None)
    assert not _has_tool_protocol(wire)


def test_plain_history_keeps_its_content_and_closes_the_turn():
    """#265b: Claude rejects a conversation ending on an assistant turn ("does not support
    assistant message prefill"), so the normaliser closes it. Content is untouched."""
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=None)
    assert [m["role"] for m in wire][:3] == ["system", "user", "assistant"]
    assert wire[-1]["role"] == "user"
    assert [m["content"] for m in wire][:3] == ["s", "u", "a"]


def test_non_anthropic_history_is_byte_identical():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}]
    wire = _prepare_messages_for_request(msgs, "gpt-5.5", tools=None)
    assert [m["role"] for m in wire] == ["system", "user", "assistant"]


def test_orphan_result_without_its_call_is_still_dropped():
    """#249's guarantee must survive the flattening."""
    msgs = [{"role": "user", "content": "u"},
            {"role": "tool", "tool_call_id": "gone", "content": "orphan"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert not any(m.get("role") == "tool" for m in wire)


def test_default_call_without_the_tools_kwarg_still_works():
    """Back-compat: three of the four call sites pass no tools kwarg yet."""
    wire = _prepare_messages_for_request(_history(), MODEL)
    assert isinstance(wire, list) and wire
