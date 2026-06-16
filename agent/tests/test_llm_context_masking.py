"""Context-size control: _mask_old_observations bounds per-call LLM input.

Cost root cause (youtube run, 2026-06-15): the per-call message history grew
unbounded (median ~95K, max ~768K chars) and input tokens dominate the bill.
_mask_old_observations truncates the bulky text of STALE messages while keeping
the system prompt, the task (first non-system message), every role, and
tool_call pairing intact — so cost drops without breaking the agent loop.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from utils.llm import _mask_old_observations, Message  # noqa: E402


def _history(n_tool, size=1000):
    msgs = [Message.system("SYSTEM PROMPT " + "s" * size),
            Message.user("THE TASK " + "t" * size)]
    for i in range(n_tool):
        msgs.append(Message.tool("OUTPUT %d " % i + "y" * size, tool_call_id="tc%d" % i))
    return msgs


def test_short_history_returned_untouched(monkeypatch):
    monkeypatch.setenv("ENVGEN_CTX_MASK", "1")
    monkeypatch.setenv("ENVGEN_CTX_KEEP_RECENT", "8")
    monkeypatch.setenv("ENVGEN_CTX_MAX_OLD_CHARS", "100")
    m = _history(3)  # 5 messages <= keep_recent
    assert _mask_old_observations(m) is m


def test_old_truncated_recent_and_anchors_preserved(monkeypatch):
    monkeypatch.setenv("ENVGEN_CTX_MASK", "1")
    monkeypatch.setenv("ENVGEN_CTX_KEEP_RECENT", "2")
    monkeypatch.setenv("ENVGEN_CTX_MAX_OLD_CHARS", "100")
    m = _history(10, size=1000)         # system + task + 10 tool = 12
    out = _mask_old_observations(m)
    assert len(out) == len(m)           # count preserved => tool_call pairing intact
    assert out[0].content == m[0].content   # system prompt preserved full
    assert out[1].content == m[1].content   # task (first non-system) preserved full
    assert out[-1].content == m[-1].content and out[-2].content == m[-2].content  # recent full
    # a stale bulky tool message is truncated but keeps its role + tool_call_id
    old = out[5]
    assert "older output truncated" in old.content and len(old.content) < 1000
    assert old.role == "tool" and old.tool_call_id is not None


def test_disabled_via_env_returns_original(monkeypatch):
    monkeypatch.setenv("ENVGEN_CTX_MASK", "0")
    m = _history(20, size=2000)
    assert _mask_old_observations(m) is m


def test_multimodal_content_never_truncated(monkeypatch):
    monkeypatch.setenv("ENVGEN_CTX_MASK", "1")
    monkeypatch.setenv("ENVGEN_CTX_KEEP_RECENT", "1")
    monkeypatch.setenv("ENVGEN_CTX_MAX_OLD_CHARS", "100")
    img = Message.user_with_image("look", "A" * 500)
    m = [Message.system("s")] + [img] + [Message.tool("z" * 800, "tc%d" % i) for i in range(5)]
    out = _mask_old_observations(m)
    assert out[1].content == img.content  # list/multimodal content left intact
