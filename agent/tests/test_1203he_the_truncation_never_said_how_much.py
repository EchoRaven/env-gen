r"""#1203he: a truncated log line said `...` and never how much it dropped.

```python
        def truncate(s: str, max_len: int = 150) -> str:
            s = str(s)
            return s[:max_len] + "..." if len(s) > max_len else s
```

A bare `...` makes a cut record indistinguishable from a complete one, and this log line
is the ONLY copy of a failing tool call an operator ever reads: the agent itself gets
`result.error_message` whole (`Message.tool(f"Error: {result.error_message}")`, with no
cap on that path). So this is DIAGNOSABILITY, not pipeline behaviour — the agent's
information is unchanged either way.

MEASURED over the last 20 runs: 308 of 345 `Interactable elements on this page:` lists
end in a bare `...`, in every one of the 20 runs. #362/#688/#1202uk built that list
precisely so a failed selector teaches the model about the page, and the operator's copy
of it stops at `{type='submit', te...` on a login page — inside the submit button's own
text, which is the thing a reader most needs.

★ IT COST REAL WORK TWICE IN ONE DAY. #1203h2 was diagnosed from a record truncated by a
monitor AND capped by a ledger, and had to be withdrawn in full. And 24 corpus records
ending at the literal `Error respo` sent me an hour up an upstream-truncation path that
does not exist — the cut was downstream all along. `[+412 chars]` tells a reader to go
read the artifact; `...` does not say there is one.

★ TWO COPIES. This helper is defined TWICE in `tooling.py` — in `_log_tool_details`
(default 200) and in `_log_tool_result` (default 150) — with byte-identical bodies. The
308 measurements come from the SECOND, so patching the first alone would have shipped a
fix whose evidence came from a call site it never touched. I had the one-copy script
written before noticing. `test_no_copy_of_the_helper_prints_a_bare_ellipsis` is the guard
against a third appearing.
"""
import ast
import os
import re
import sys
import types
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402
from utils.tool import ToolResult  # noqa: E402

_SRC = Path(os.path.join(
    _AGENT, "env_generator/llm_generator/multi_agent/agents/runtime/tooling.py"))


class _Logger:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)


def _emit(error_message):
    """Drive the real `_log_tool_result` failure branch with a stand-in self."""
    log = _Logger()
    me = types.SimpleNamespace(
        _logger=log, agent_id="browser_test_user",
        _record_tool_ms_1202wl=lambda *a, **k: None)
    AgentTooling._log_tool_result(
        me, "browser_fill",
        ToolResult(success=False, error_message=error_message), 8808)
    return "\n".join(log.lines)


# --------------------------------------------------------- the operator's copy
def test_a_short_message_is_untouched():
    """★ The no-op guarantee: the overwhelming majority of failures are short."""
    out = _emit("Fill failed: no such element")
    assert "Fill failed: no such element" in out
    assert "chars]" not in out, out


def test_a_long_message_says_how_much_was_dropped():
    """★ THE defect, measured 308 times in 20 runs."""
    msg = "Fill failed: Locator.fill: Timeout 5000ms exceeded. " + "x" * 600
    out = _emit(msg)
    assert "chars]" in out, out
    dropped = int(re.search(r"\[\+(\d+) chars\]", out).group(1))
    assert dropped == len(msg) - 300, (dropped, len(msg))


def test_the_count_is_what_is_missing_not_the_total():
    """"+N chars" has to mean N MORE, or a reader cannot tell how far to go."""
    msg = "y" * 500
    out = _emit(msg)
    assert "[+200 chars]" in out, out


def test_a_message_exactly_at_the_cap_is_not_annotated():
    """Off-by-one in the direction that matters: annotating a complete record is the
    same lie as not annotating a cut one."""
    out = _emit("z" * 300)
    assert "chars]" not in out, out


def test_no_bare_ellipsis_survives_in_the_operators_copy():
    """The whole point: a reader must never see a cut they cannot measure."""
    out = _emit("Fill failed: " + "q" * 900)
    assert not re.search(r"\.\.\.\s*$", out), out


def test_the_candidate_list_shortfall_is_now_countable():
    """The shape this was found on, verbatim from r175 at 12:17:54."""
    msg = ('Fill failed: Locator.fill: Timeout 5000ms exceeded.\nCall log:\n'
           '  - waiting for get_by_label("Email").first\n'
           ". Interactable elements on this page: "
           + "; ".join("{name='f%d', id='f%d', type='text'}" % (i, i) for i in range(30)))
    out = _emit(msg)
    assert "get_by_label" in out, out
    assert "chars]" in out, out


# ------------------------------------------------------------- both copies, and no third
def _truncate_bodies():
    """Every nested `def truncate` in the module, as source."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "truncate":
            out.append(ast.get_source_segment(_SRC.read_text(encoding="utf-8"), node) or "")
    return out


def test_both_copies_of_the_helper_exist_and_are_patched():
    """★ Two definitions, `_log_tool_details` (200) and `_log_tool_result` (150). Both
    had byte-identical bodies and both had to change."""
    bodies = _truncate_bodies()
    assert len(bodies) == 2, f"expected 2 copies, found {len(bodies)}"
    for b in bodies:
        assert "chars]" in b, b


def test_no_copy_of_the_helper_prints_a_bare_ellipsis():
    """★ The guard against a third copy, and against either of these two regressing.
    A literal `+ "..."` is the exact expression this ticket removed."""
    for b in _truncate_bodies():
        assert '+ "..."' not in b, b
        assert "+ '...'" not in b, b


def test_the_failure_log_still_caps_at_three_hundred():
    """★ SCOPE. This ticket changes the ANNOTATION, not the budget: run logs carry ~674
    tool calls, and widening every failure line is a different decision with a different
    cost. If the cap moves, that was not this patch."""
    src = _SRC.read_text(encoding="utf-8")
    assert "truncate(result.error_message or '', 300)" in src, "the failure cap moved"


def test_the_agent_still_receives_the_message_whole():
    """★ THE CLAIM THAT MAKES THIS LOG-ONLY. If the agent-facing path ever starts
    truncating, this stops being diagnosability and becomes a defect — and the 308
    measurements would have to be re-read as agent-visible."""
    step = Path(os.path.join(
        _AGENT,
        "env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py"
    )).read_text(encoding="utf-8")
    assert 'f"Error: {result.error_message}"' in step, (
        "the agent-facing message is no longer handed over whole")
