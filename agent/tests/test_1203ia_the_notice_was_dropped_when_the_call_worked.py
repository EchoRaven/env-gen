"""#1203ia: a framework notice on a SUCCEEDING tool call never reached the agent.

`ToolResult._with_notices_1116` exists for one stated reason -- "Append framework notices
so the CALLER sees them, not only a log reader" -- and it is reachable only through
`ToolResult.__str__`. #1203hh put the FAILURE branch of the step pipeline on `str(result)`
for exactly that reason ("#674 BUILT THE MECHANISM AND NOTHING CALLED IT"). The success
branch kept reading `.data`, so `__str__` was never on its path and any notice attached to
a call that WORKED was dropped on the floor.

Three producers can fire on success, each written to change the agent's next move:
  * `foreign_target_notice_1134(url, answered=True)` -- "Whatever answered is a DIFFERENT
    service on this host ... do not file it as a defect."
  * `hub_tools` document name-resolution -- "%r is a name, not an id", returned as
    `ToolResult(data=_doc)`, i.e. success.
  * `dropped_args_message_1116` -- the agent is otherwise left assuming its argument landed.

Not landed on volume: `dropped unaccepted argument` is 11 occurrences corpus-wide and 0 in
the last six runs. Landed because the channel is designed to reach the agent, half of it
silently did not, and every notice added later would inherit that.
"""
import ast
import json
import os
import pathlib
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from utils.tool import ToolResult  # noqa: E402


def _render(result, tool_name="test_api"):
    """The step pipeline's own serialisation, in the order it performs it."""
    result_str = result.data if result.success else str(result)
    if isinstance(result_str, dict):
        result_str = json.dumps(result_str, indent=2)
    result_str = str(result_str)
    if not result_str.strip() or result_str.strip() == "{}":
        result_str = "Your command ran successfully and did not produce any output."
    elif result_str.strip() == "None":
        result_str = f"Tool {tool_name} completed successfully (no output)."
    if result.success:
        try:
            result_str = result._with_notices_1116(result_str)
        except Exception:
            pass
    return result_str


NOTICE = ("#1134 WRONG TARGET: this run's app publishes :3001 on localhost, and you probed "
          ":8082. Whatever answered is a DIFFERENT service on this host — do not file it as "
          "a defect.")


def test_a_notice_on_a_successful_call_reaches_the_agent():
    r = ToolResult(success=True, data={"status": 200, "response": "{}"})
    r.notices.append(NOTICE)
    out = _render(r)
    assert "WRONG TARGET" in out, "the notice was dropped on a succeeding call"
    assert "do not file it as a defect" in out


def test_the_payload_is_still_pretty_printed_json():
    """The reason this appends to the finished string instead of switching to
    `str(result)`: `.data` is rendered with `json.dumps(indent=2)`, and `str(result)` would
    hand the model a Python repr of the same dict. Fixing a notice must not reshape every
    successful tool result."""
    r = ToolResult(success=True, data={"status": 200, "items": [1, 2]})
    r.notices.append(NOTICE)
    out = _render(r)
    assert '"status": 200' in out, "the dict stopped being JSON (Python repr leaked in)"
    assert "'status': 200" not in out


def test_a_successful_call_with_no_notice_is_byte_identical():
    """Zero regression for the overwhelmingly common case."""
    r = ToolResult(success=True, data={"a": 1})
    assert _render(r) == json.dumps({"a": 1}, indent=2)


def test_the_failure_branch_still_carries_its_notice():
    """#1203hh's half, kept as a control: if this broke, the test above could be passing
    for the wrong reason (a renderer that appends notices unconditionally)."""
    r = ToolResult(success=False, error_message="Connection refused")
    r.notices.append(NOTICE)
    out = _render(r)
    assert "WRONG TARGET" in out
    assert "Connection refused" in out


def test_an_empty_result_with_a_notice_still_shows_it():
    """The `{}` and `None` normalisations rewrite `result_str` wholesale. A notice attached
    to such a call must survive that rewrite -- it is the only content there is."""
    r = ToolResult(success=True, data={})
    r.notices.append(NOTICE)
    out = _render(r)
    assert "did not produce any output" in out
    assert "WRONG TARGET" in out, "the empty-result rewrite discarded the notice"


# ------------------------------------------------- pinned against the real source
#
# `_render` above is a TRANSCRIPTION of the pipeline, and #1203hh's own docstring records
# what that costs: "MY OWN TEST ASSERTED THE WRONG CONSUMER ... The test NAME claimed a
# path I had never checked." So the behaviour above is not the evidence on its own -- the
# checks below pin the real function, following the AST technique that ticket established
# for this same file.
_TOOLING = pathlib.Path(os.path.join(
    _AGENT, "env_generator/llm_generator/multi_agent/agents/runtime/step_pipeline/tooling.py"))


def _src():
    return _TOOLING.read_text(encoding="utf-8")


def _success_branch_body():
    """The source of the `if result.success:` block that guards the notice append, located
    by walking the tree rather than by line number (#943: no fixed source windows)."""
    tree = ast.parse(_src())
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.get_source_segment(_src(), node.test) or ""
        if test.strip() != "result.success":
            continue
        body = "\n".join(
            (ast.get_source_segment(_src(), st) or "") for st in node.body)
        if "_with_notices_1116" in body:
            return body
    return ""


def test_the_real_pipeline_appends_notices_on_success():
    """★ THE GUARD. If this append is removed the notice silently stops arriving and every
    behavioural test above -- which exercises a transcription -- keeps passing."""
    assert _success_branch_body(), (
        "no `if result.success:` block in the step pipeline appends notices; the success "
        "branch has gone back to dropping them")


def test_the_append_is_guarded_by_success_not_unconditional():
    """The failure branch already reaches `_with_notices_1116` through `__str__`
    (#1203hh). Appending unconditionally would print the notice twice."""
    assert _src().count("_with_notices_1116(result_str)") == 1, (
        "more than one append site — the failure branch would double its notice")


def test_the_append_runs_after_the_empty_result_rewrite():
    """Placement is load-bearing: the `{}`/`None` normalisations REPLACE `result_str`
    wholesale, so a notice appended before them is thrown away. That is the one case where
    the notice is the only content the call has."""
    s = _src()
    i_rewrite = s.index('"Your command ran successfully and did not produce any output."')
    i_notice = s.index("_with_notices_1116(result_str)")
    assert i_notice > i_rewrite, (
        "the notice is appended before the empty-result rewrite, which discards it")
