r"""#1199c: the trimming gate measures what the request actually carries.

`_mask_old_observations` skips masking entirely when the history fits the model's working
window — its docstring says *"If the FULL message history fits the model's recommended working
window, do NOT mask at all"*. The code summed only `m.content`. An assistant message that CALLS
a tool carries its arguments in `tool_calls` and leaves `content` empty, so every file body a
lane wrote was invisible to the check that decides whether trimming is needed at all.

Measured on the frontend lane's own log: tool-call arguments are ~20% of its history (write
0.26MB + apply_patch 0.15MB + edit 0.06MB against 1.2MB of results), so the gate ran at a fifth
again the intended budget.

This changes behaviour — masking now engages where it previously did not — in the direction the
docstring already promised. The same accounting backs the `[LLM Request] content_chars=` log
line, so the two cannot drift; they already had.
"""

import sys
import types
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from utils.llm import _payload_chars_1199  # noqa: E402


def _tool_call(args: str):
    return {"function": {"arguments": args}}


def _msg(role, content=None, tool_calls=None):
    return types.SimpleNamespace(role=role, content=content, tool_calls=tool_calls)


def test_a_tool_calls_arguments_are_counted():
    """The whole point: a write whose body is 5000 chars is not zero."""
    body = "x" * 5000
    msgs = [_msg("assistant", None, [_tool_call('{"content": "%s"}' % body)])]
    assert _payload_chars_1199(msgs) >= 5000


def test_content_is_still_counted():
    assert _payload_chars_1199([_msg("user", "hello")]) == 5


def test_both_are_counted_together():
    msgs = [_msg("user", "abc"), _msg("assistant", None, [_tool_call("1234567890")])]
    assert _payload_chars_1199(msgs) == 3 + 10


def test_dict_messages_work_too():
    """The provider paths hand this ordinary objects or dicts depending on the call."""
    msgs = [{"role": "assistant", "content": "hi",
             "tool_calls": [{"function": {"arguments": "abcd"}}]}]
    assert _payload_chars_1199(msgs) == 2 + 4


def test_a_measurement_never_raises():
    """It runs on every request; a formatting slip must not be able to break a call."""
    class _Hostile:
        @property
        def content(self):
            raise RuntimeError("no")

    assert _payload_chars_1199([_Hostile(), None, 17]) >= 0


def test_the_masking_gate_uses_the_same_accounting(monkeypatch):
    """A history that fits only because its tool-call arguments were ignored must now mask."""
    from multi_agent.agents.runtime import step_runner as sr

    budget = 4000
    monkeypatch.setattr("utils.model_limits.resolve_ctx_working_chars", lambda _m: budget)

    big_args = "y" * 3500
    msgs = [_msg("user", "z" * 1000)]
    msgs += [_msg("assistant", None, [_tool_call(big_args)])]
    for i in range(12):
        msgs.append(_msg("tool", "R" * 900))

    out = sr._mask_old_observations(list(msgs), model="some-model", keep_last=2)
    masked = [m for m in out if isinstance(getattr(m, "content", None), str)
              and m.content.endswith("[masked]")]
    assert masked, "history exceeds the budget once tool-call arguments count; it must mask"
