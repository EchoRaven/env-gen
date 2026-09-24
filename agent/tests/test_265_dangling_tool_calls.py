"""#265 — the mirror of #249: a tool_call with no result is as fatal as a result with no call.

r56 (opus-4.7), live:

    400 messages.142: `tool_use` ids were found without `tool_result` blocks immediately
        after

#249 prunes orphan RESULTS (a tool_result whose tool_use was masked away). Nothing pruned
the other direction, so an assistant turn whose tool_calls were never answered — the last
turn of a step that ended at its round budget, or a result dropped by condensation — goes
out with dangling tool_use blocks and the request is rejected outright.

Anthropic requires the pairing in BOTH directions and immediately adjacent. The repair is
the same shape as #259's: keep the call as text so the model still sees what was attempted,
and drop only the protocol structure that cannot be satisfied.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.llm import _prepare_messages_for_request  # noqa: E402

MODEL = "claude-4-7-opus-vertex-genai"
TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {}}}]


def _call(tid, content="working"):
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": tid, "type": "function",
                            "function": {"name": "f", "arguments": '{"x": 1}'}}]}


def _result(tid, body="ok"):
    return {"role": "tool", "tool_call_id": tid, "content": body}


def _dangling(wire):
    """tool_call ids not answered by the immediately following message."""
    out = []
    for i, m in enumerate(wire):
        for c in m.get("tool_calls") or []:
            nxt = wire[i + 1] if i + 1 < len(wire) else None
            if not (nxt and nxt.get("role") == "tool"
                    and nxt.get("tool_call_id") == c.get("id")):
                out.append(c.get("id"))
    return out


def test_r56_regression_trailing_unanswered_call_is_not_sent_as_protocol():
    msgs = [{"role": "user", "content": "go"}, _call("call_1")]
    assert _dangling(_prepare_messages_for_request(msgs, MODEL, tools=TOOLS)) == []


def test_the_attempted_call_survives_as_text():
    """Information-preserving: the model must still see what it tried to invoke."""
    msgs = [{"role": "user", "content": "go"}, _call("call_1")]
    text = " ".join(str(m.get("content") or "")
                    for m in _prepare_messages_for_request(msgs, MODEL, tools=TOOLS))
    assert "f" in text and "working" in text


def test_answered_calls_are_left_alone():
    msgs = [{"role": "user", "content": "go"}, _call("call_1"), _result("call_1")]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert _dangling(wire) == []
    assert any(m.get("tool_calls") for m in wire)
    assert any(m.get("role") == "tool" for m in wire)


def test_mid_history_unanswered_call_is_repaired_too():
    """Not just the tail — a dropped result anywhere breaks the same way."""
    msgs = [{"role": "user", "content": "go"}, _call("call_1"),
            {"role": "assistant", "content": "moved on"},
            _call("call_2"), _result("call_2")]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert _dangling(wire) == []


def test_multi_call_turn_with_only_some_answers():
    """A turn with two calls and one result cannot be represented either way."""
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "two", "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "f", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
            _result("a")]
    assert _dangling(_prepare_messages_for_request(msgs, MODEL, tools=TOOLS)) == []


def test_249_orphan_results_still_pruned():
    """The other direction must keep working."""
    msgs = [{"role": "user", "content": "go"}, _result("vanished")]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert not any(m.get("role") == "tool" for m in wire)


def test_no_tool_traffic_keeps_every_turn():
    """No tool protocol to repair — content survives verbatim; #265b only appends the
    closing user turn Claude requires."""
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert [m["content"] for m in wire][:3] == ["s", "u", "a"]
    assert wire[-1]["role"] == "user"


def test_holds_for_every_provider():
    """An unrepresentable history is wrong everywhere; only Claude rejects it loudly."""
    msgs = [{"role": "user", "content": "go"}, _call("call_1")]
    for model in (MODEL, "gemini-3.1-pro-preview-customtools", "gpt-5.5"):
        assert _dangling(_prepare_messages_for_request(msgs, model, tools=TOOLS)) == [], model
