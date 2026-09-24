"""Closed-by-construction guard: the agent LLM call sites resolve + pass reasoning_effort.

The agentic mini-loop is too heavy to drive in a unit test, so we pin the wiring by
source inspection (the repo uses this pattern elsewhere) + confirm the chain imports.
Resolution logic is tested in test_reasoning_effort.py and the gpt-5 gate in
test_llm_reasoning_effort.py.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"


def test_base_chat_passes_resolved_reasoning_effort():
    txt = (SRC / "multi_agent/agents/base.py").read_text()
    assert "from ..runtime.reasoning_effort import resolve_effort" in txt
    assert "reasoning_effort=_effort" in txt


def test_messaging_chat_passes_resolved_reasoning_effort():
    txt = (SRC / "multi_agent/agents/runtime/messaging.py").read_text()
    assert "from ...runtime.reasoning_effort import resolve_effort" in txt
    assert "reasoning_effort=_effort" in txt
