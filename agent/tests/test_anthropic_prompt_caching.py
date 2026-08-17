"""Prompt-caching breakpoint injection for the native Anthropic client (opus cost).

The engine sends a large CONSTANT system prompt per role every turn. Attaching an
ephemeral cache_control breakpoint to `system` turns the tools+system prefix into a
cache_read (~10% of fresh input) after the first call. ANTHROPIC-NATIVE only — the
OpenAI-compat wrapper drops cache_control for opus (proven inert), which is why the
engine talks the messages API directly.

Live-verified on claude-opus-4-7 (Vertex gateway): call1 cache_creation=34303/read=0,
call2 read=34303. These tests pin the request-shaping the client applies before the call.
"""
import os
import importlib

from utils.llm import AnthropicClient

_apply = AnthropicClient._apply_prompt_caching


def _clear_env():
    os.environ.pop("ENVGEN_ANTHROPIC_CACHE", None)


def test_string_system_becomes_cached_block():
    _clear_env()
    p = {"system": "big stable system prompt", "messages": []}
    _apply(p)
    assert p["system"] == [{
        "type": "text",
        "text": "big stable system prompt",
        "cache_control": {"type": "ephemeral"},
    }]


def test_empty_system_untouched():
    _clear_env()
    p = {"system": "   ", "messages": []}
    _apply(p)
    assert p["system"] == "   "  # no cacheable content -> left alone


def test_no_system_key_is_noop():
    _clear_env()
    p = {"messages": []}
    _apply(p)
    assert "system" not in p


def test_block_form_marks_last_text_block():
    _clear_env()
    p = {"system": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    _apply(p)
    assert "cache_control" not in p["system"][0]
    assert p["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_existing_breakpoint_not_doubled():
    _clear_env()
    marked = [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}]
    p = {"system": list(marked)}
    _apply(p)
    assert p["system"] == marked  # already has a breakpoint -> unchanged


def test_disabled_via_env():
    os.environ["ENVGEN_ANTHROPIC_CACHE"] = "0"
    try:
        p = {"system": "big stable system prompt"}
        _apply(p)
        assert p["system"] == "big stable system prompt"  # opt-out honored
    finally:
        _clear_env()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
