r"""#1203hh: #674 built the mechanism and nothing on the agent path called it.

`ToolResult.__str__` renders a FAILURE as `Error: <error_message>\n<data>`, bounded at
`_FAILED_DATA_CHARS_674` = 8000 — written by #674 precisely so a failed tool's payload
reaches the agent ("on FAILURE this returned the error line ALONE and dropped `data` on
the floor — and `data` is where tools put what actually went wrong").

Every agent-facing site read `result.error_message` instead, which is that same string
MINUS the data. So `__str__` was never on the path: there is no caller of it in the
agents package.

    step_pipeline/tooling.py:696  Message.tool(f"Error: {result.error_message}", ...)
    step_pipeline/tooling.py:772  Message.tool(f"Error: {result.error_message}", ...)
    step_pipeline/tooling.py:875  result_str = result.data if result.success
                                               else f"Error: {result.error_message}"

OBSERVED on r176 at 15:41:53, with #1203ha already landed:
`❌ docker_validate FAILED (18ms): Docker compose validation failed: Found 1 issue(s) in
docker-compose.yml` — character for character what r175 said BEFORE ha. And the verifier
quoted it straight back ("failed with: \"...Found 1 issue(s)...\""), which is harder
evidence than the log: the agent really did receive only the count. #1203ha moved the
payload into `.data` correctly and the reader still looked somewhere else.

★ WHY #674 LOOKED LIKE IT WORKED. `test_api` APPENDS to `error_message`
(`error_message=f"HTTP Error: {e.code}{hint}"`), which is why its body and auth hints do
reach the agent and why bare `HTTP Error: N` is 0 in the corpus today. One producer routed
around the gap; the mechanism itself was never connected. A producer's self-rescue is not
the mechanism working — ask who ELSE depends on it.

★ MY OWN TEST ASSERTED THE WRONG CONSUMER. `#1203ha`'s
`test_the_agent_facing_text_carries_the_payload` asserted `str(res)` — and no agent path
calls it. The test NAME claimed a path I had never checked. The tests below assert the
expression the agent path actually uses.

SCOPE: `:856` feeds `memory.record_tool_call`, a different consumer with its own size
budget, and is deliberately left reading `error_message`.
"""
import ast
import os
import pathlib
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from utils.tool import ToolResult  # noqa: E402

_TOOLING = pathlib.Path(os.path.join(
    _AGENT, "env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py"))


def _src():
    return _TOOLING.read_text(encoding="utf-8")


# ------------------------------------------------- what the agent path now hands over
def test_a_failure_with_a_payload_renders_both():
    """★ The behaviour the agent path now gets: the error line AND what went wrong."""
    r = ToolResult.fail("Docker compose validation failed: Found 1 issue(s)",
                        data={"issues": ["backend: build context 'app/backend' not found"]})
    out = str(r)
    assert "Found 1 issue(s)" in out, out
    assert "build context 'app/backend' not found" in out, out


def test_a_failure_without_a_payload_is_byte_identical_to_before():
    """★ THE NO-OP GUARANTEE, and the reason this is safe to apply to every tool: with no
    `.data`, `str(result)` is exactly the string the old expression built."""
    r = ToolResult.fail("plain failure")
    assert str(r) == f"Error: {r.error_message}"


def test_an_empty_payload_is_treated_as_none():
    """`{}` and `[]` must not append a line that says nothing — #674 already decided this
    and the agent path inherits it."""
    for empty in ({}, [], None):
        r = ToolResult.fail("plain failure", data=empty)
        assert str(r) == f"Error: {r.error_message}", (empty, str(r))


def test_a_huge_payload_is_bounded_and_says_so():
    """The 8000-char bound is #674's, reused rather than re-chosen; and a truncation that
    does not declare itself is #1034's defect."""
    r = ToolResult.fail("boom", data={"blob": "x" * 20000})
    out = str(r)
    assert len(out) < 9000, len(out)
    assert "chars total" in out, out[-80:]


# --------------------------------------------- the agent-facing sites are actually wired
def _tool_message_exprs():
    """Every `Message.tool(...)` first argument in this module, as source."""
    tree = ast.parse(_src())
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tool"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "Message"
                and node.args):
            out.append(ast.get_source_segment(_src(), node.args[0]) or "")
    return out


def test_no_agent_message_is_built_from_error_message_alone():
    """★ THE GUARD, and the exact expression this ticket removed. If it comes back, the
    payload stops reaching the agent again and no behavioural test here would notice —
    which is how #1203ha shipped half-done."""
    for expr in _tool_message_exprs():
        assert 'result.error_message' not in expr, expr


def test_the_failure_branches_hand_over_the_whole_result():
    """Both `Message.tool` failure sites, by count, so losing one is caught."""
    assert _src().count("Message.tool(str(result), tool_call_id)") == 2, _src().count(
        "Message.tool(str(result), tool_call_id)")


def test_the_result_str_branch_is_symmetric():
    """★ `:875` handed over `.data` on SUCCESS and dropped it on FAILURE — the asymmetry
    #674 was written about. Both branches now carry the payload."""
    assert "result_str = result.data if result.success else str(result)" in _src()


def test_the_memory_record_is_deliberately_left_alone():
    """★ SCOPE, pinned. `memory.record_tool_call` is a different consumer with its own size
    budget; widening it is a separate decision and must not be attributed to this ticket."""
    assert "result=result.data if result.success else result.error_message," in _src()


def test_str_is_what_the_agent_path_calls_now():
    """★ The claim #1203ha's test should have made. Asserting a rendering function proves
    nothing unless the path under discussion calls it — so assert that it does."""
    src = _src()
    assert "str(result)" in src, src[:200]
    # and the old form is gone from the LLM-facing expressions
    assert 'Message.tool(f"Error: {result.error_message}"' not in src
