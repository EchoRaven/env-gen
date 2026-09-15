"""#1202nr: the request log names where a prompt stopped matching the previous one.

tiktok-r125's orchestrator paid ~18k uncached input tokens per call against ~3k for the lanes;
inside one loop consecutive calls kept the same cached count (23,168) while the prompt grew to
72k. The log carried counts only, so where the prefix changed could not be recovered.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import llm as L  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read"}}]


def _msgs(*contents):
    roles = ["system", "user"] + ["assistant", "tool"] * 10
    return [{"role": r, "content": c} for r, c in zip(roles, contents)]


def _at(trace):
    return trace.split("diverge_at=")[1].split("/")[0]


def setup_function(_):
    L._PREFIX_LAST_1202NR.clear()


def test_an_appended_conversation_matches_up_to_its_previous_length():
    assert _at(L._prefix_trace_1202nr(TOOLS, _msgs("sys", "task", "a1"))) == "new"
    assert _at(L._prefix_trace_1202nr(TOOLS, _msgs("sys", "task", "a1", "t1", "a2"))) == "3"


def test_a_rewritten_earlier_message_is_named():
    L._prefix_trace_1202nr(TOOLS, _msgs("sys", "task", "a1", "big result", "a2"))
    trace = L._prefix_trace_1202nr(TOOLS, _msgs("sys", "task", "a1", "[truncated]", "a2", "t2"))
    assert _at(trace) == "3", trace


def test_a_changed_tool_list_is_named():
    L._prefix_trace_1202nr(TOOLS, _msgs("sys", "task", "a1"))
    trace = L._prefix_trace_1202nr(TOOLS + [{"type": "function", "function": {"name": "edit"}}],
                                   _msgs("sys", "task", "a1", "t1"))
    assert _at(trace) == "tools", trace


def test_it_never_raises():
    assert L._prefix_trace_1202nr(object(), [object()]) is not None
