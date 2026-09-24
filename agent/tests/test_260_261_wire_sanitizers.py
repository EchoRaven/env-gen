"""#260/#261 — two more shapes an Anthropic-backed provider rejects outright.

r54 (first real opus-4.7 run) logged 1350 x 400 and aborted having built almost nothing
(no_successful_run / dead_artifacts / frontend_build_not_recorded). Two causes, both ours,
both confirmed by probing the live gateway:

  #260  800x "messages: text content blocks must contain non-whitespace text"
        An empty / whitespace-only / None text block is rejected. Verified: content=""
        -> "must be non-empty", content="   " -> "must contain non-whitespace text",
        content=None -> "Unsupported message content type". NOTE content=None is fine
        when the message carries tool_calls (the content array then holds the tool_use
        block), so the rule is specifically about an empty TEXT block.

  #261  220x "messages.N.content.0.tool_use.id: String should match '^[a-zA-Z0-9_-]+$'"
        Verified rejected: "", "a.b", "a:b", "a b". Accepted: "call_1", a plain uuid.
        The rewrite has to stay consistent across the assistant's tool_calls and the
        matching tool message's tool_call_id, or #249 sees an orphan and drops the result.

OpenAI and Gemini tolerate both, which is why neither surfaced until the first Claude run.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.llm import _prepare_messages_for_request  # noqa: E402

MODEL = "claude-4-7-opus-vertex-genai"
TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {}}}]


def _call(tid, content="x"):
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": tid, "type": "function",
                            "function": {"name": "f", "arguments": "{}"}}]}


def _texts(wire):
    return [m.get("content") for m in wire]


# ------------------------------------------------------------------ #260
def test_empty_and_whitespace_text_turns_are_removed():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "   "},
            {"role": "assistant", "content": None},
            {"role": "user", "content": "go"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    for c in _texts(wire):
        assert c is None or (isinstance(c, str) and c.strip()), wire


def test_a_message_with_tool_calls_keeps_its_place_even_with_empty_text():
    """content=None + tool_calls is LEGAL — the content array holds the tool_use block —
    so this message must never be dropped: dropping it would orphan its result."""
    msgs = [{"role": "user", "content": "hi"}, _call("call_1", ""),
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert any(m.get("tool_calls") for m in wire)
    assert any(m.get("role") == "tool" for m in wire)


def test_tool_results_with_empty_bodies_survive_with_a_placeholder():
    """A tool that returned nothing is INFORMATION (it ran, it was empty) and dropping the
    result would orphan the call."""
    msgs = [{"role": "user", "content": "hi"}, _call("call_1"),
            {"role": "tool", "tool_call_id": "call_1", "content": ""}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    tool = [m for m in wire if m.get("role") == "tool"]
    assert tool and isinstance(tool[0]["content"], str) and tool[0]["content"].strip()


def test_non_string_content_is_left_alone():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "img"}]}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    assert isinstance(wire[0]["content"], list)


# ------------------------------------------------------------------ #261
def _ids(wire):
    out = []
    for m in wire:
        for c in m.get("tool_calls") or []:
            out.append(c.get("id"))
        if m.get("role") == "tool":
            out.append(m.get("tool_call_id"))
    return out


def test_illegal_id_characters_are_rewritten():
    import re
    for bad in ("a.b", "a:b", "a b", "call/42", "x@y"):
        msgs = [{"role": "user", "content": "hi"}, _call(bad),
                {"role": "tool", "tool_call_id": bad, "content": "ok"}]
        wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
        for got in _ids(wire):
            assert re.fullmatch(r"[a-zA-Z0-9_-]+", got or ""), (bad, got)


def test_empty_id_gets_a_real_one():
    import re
    msgs = [{"role": "user", "content": "hi"}, _call(""),
            {"role": "tool", "tool_call_id": "", "content": "ok"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    got = _ids(wire)
    assert got and all(re.fullmatch(r"[a-zA-Z0-9_-]+", g or "") for g in got), got


def test_rewrite_keeps_call_and_result_paired():
    """If the two sides diverge, #249 drops the result as an orphan — silently."""
    msgs = [{"role": "user", "content": "hi"}, _call("a.b"),
            {"role": "tool", "tool_call_id": "a.b", "content": "ok"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    call_id = [c["id"] for m in wire for c in (m.get("tool_calls") or [])]
    res_id = [m["tool_call_id"] for m in wire if m.get("role") == "tool"]
    assert call_id and res_id and call_id[0] == res_id[0]


def test_distinct_bad_ids_do_not_collide():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "x", "tool_calls": [
                {"id": "a.b", "type": "function", "function": {"name": "f", "arguments": "{}"}},
                {"id": "a:b", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a.b", "content": "1"},
            {"role": "tool", "tool_call_id": "a:b", "content": "2"}]
    wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
    ids = [c["id"] for m in wire for c in (m.get("tool_calls") or [])]
    assert len(set(ids)) == 2, ids


def test_legal_ids_are_untouched():
    for good in ("call_1", "toolu_vrtx_01TCzGfB8fWm", "01d393e7-de51-4ce2-9f85-5b67f8d064f0"):
        msgs = [{"role": "user", "content": "hi"}, _call(good),
                {"role": "tool", "tool_call_id": good, "content": "ok"}]
        wire = _prepare_messages_for_request(msgs, MODEL, tools=TOOLS)
        assert all(i == good for i in _ids(wire)), good
