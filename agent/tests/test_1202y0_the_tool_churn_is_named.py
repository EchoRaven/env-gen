r"""#1202y0: when the tool blob changes, say WHICH tools — the hash cannot.

A provider cache bills the longest common PREFIX and the tools sit at its head, so any
change to them throws the whole prefix away, system prompt included. Measured on r138
(delivered M1, $280.16): 1,118 of 5,200 calls (21%) diverge on `tools`, and those cache at
83.3% against 96.3% for calls that diverge only in their messages — 5.1M tokens, ~$25 of
the run. 40 of the 48 conversations hold ONE tool hash for the whole run; the churn is
entirely inside the five long-lived lane conversations, which cycle 6 to 12 tool sets each
(48 distinct hashes overall, against roughly 25 lane x phase combinations).

Whether that is worth changing turns on a distinction `prefix_fp=tools:<hash>` cannot make:

  * a DIFFERENT SET  -- per-phase tool scoping, a real trade-off against tool isolation
  * the SAME set rendered differently -- ordering or schema churn, free to fix

`#1202nr` named where the MESSAGES diverge for exactly this reason ("the log carried counts
only, so the position could not be recovered"); the tools half stopped at "tools". This is
that half.

LOCAL-ONLY (gitignored).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from utils.llm import (  # noqa: E402
    _prefix_trace_1202nr, _tool_delta_1202y0, _tool_names_1202y0, _PREFIX_LAST_1202NR)


def _tool(name, desc="d"):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object"}}}


_MSGS = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]


def _fresh():
    _PREFIX_LAST_1202NR.clear()


def test_names_are_read_from_either_shape():
    class _F:
        name = "beta"

    class _T:
        function = _F()
    assert _tool_names_1202y0([_tool("gamma"), _tool("alpha"), _T()]) == (
        "alpha", "beta", "gamma")
    assert _tool_names_1202y0(None) == ()


def test_the_same_set_in_a_different_order_is_named_as_such():
    """★ The free case: the prefix was thrown away and no tool was actually added or
    removed. A hash alone reports this identically to a real scoping change."""
    _fresh()
    _prefix_trace_1202nr([_tool("a"), _tool("b")], _MSGS)
    out = _prefix_trace_1202nr([_tool("b"), _tool("a")], _MSGS)
    assert "diverge_at=tools/" in out, out
    assert "tools_delta=same-set" in out, out


def test_a_changed_schema_with_the_same_names_is_also_same_set():
    _fresh()
    _prefix_trace_1202nr([_tool("a", "one")], _MSGS)
    out = _prefix_trace_1202nr([_tool("a", "two")], _MSGS)
    assert "tools_delta=same-set" in out, out


def test_an_added_and_a_removed_tool_are_both_named():
    _fresh()
    _prefix_trace_1202nr([_tool("a"), _tool("b")], _MSGS)
    out = _prefix_trace_1202nr([_tool("b"), _tool("c")], _MSGS)
    assert "tools_delta=+c/-a" in out, out


def test_a_long_delta_says_how_many_it_cut():
    """#1034: a cut list has to say it was cut."""
    _fresh()
    _prefix_trace_1202nr([], _MSGS)
    out = _prefix_trace_1202nr([_tool("t%d" % i) for i in range(9)], _MSGS)
    assert "+t0,t1,t2,t3+5" in out, out


def test_no_delta_when_the_tools_did_not_move():
    """The message-divergence line must read exactly as it did before."""
    _fresh()
    tools = [_tool("a")]
    _prefix_trace_1202nr(tools, _MSGS)
    out = _prefix_trace_1202nr(tools, _MSGS + [{"role": "user", "content": "V"}])
    assert "tools_delta" not in out, out
    assert "diverge_at=2/3" in out, out


def test_a_new_conversation_carries_no_delta():
    _fresh()
    out = _prefix_trace_1202nr([_tool("a")], _MSGS)
    assert "diverge_at=new/" in out and "tools_delta" not in out, out


def test_the_trace_never_raises_on_a_hostile_tool_list():
    _fresh()
    for bad in ([{"function": None}], [object()], [{"name": None}], "not-a-list"):
        assert isinstance(_prefix_trace_1202nr(bad, _MSGS), str)
