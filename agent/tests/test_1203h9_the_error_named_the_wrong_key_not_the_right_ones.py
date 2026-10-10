r"""#1203h9: a wrong parameter name came back as a raw Python TypeError.

`_finalize_hub_tools._default_execute` returned `str(e)` for every exception, so a
call with the wrong key reached the agent as

    RegistryHubRegisterEndpointTool._run() got an unexpected keyword argument 'provider_id'

which names the wrong key and never the right ones. The agent guesses again.

MEASURED over the corpus: 212 such results across 55 logs and 22 tool classes --
175 `got an unexpected keyword argument` and 37 `missing N required positional
argument`. By tool class: RegistryHubRegisterEndpointTool 64, CodeHubGetFileContentTool
26, WorkHubUpdatePageTool 17, RegistryHubRegisterTableTool 16, WorkHubCommentTool 15,
CodeHubGetDiffTool 14, CodeHubRecordCheckTool 12, WorkHubGetTaskTool 10. Registration
tools dominate, which is where a wasted step costs most: per #257 a run's cost is the
prompt, re-sent every step.

★ ADDITIVE, NOT A FALLBACK. The call still fails and the original exception text is kept
verbatim -- #1202z6's rule, "the exception text is the evidence; the explanation is
additive". No retry, no coercion to success.

★ ONE CHOKEPOINT. `_default_execute` is the single place every HubTool subclass that
defines only `_run` is dispatched through, so one edit covers all 82 of them -- and the
next tool to be added gets it for free.
"""
import ast
import asyncio
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.hub_tools as HT  # noqa: E402
from utils.tool import ToolResult  # noqa: E402


# ----------------------------------------------------------------- real tools
def test_a_wrong_key_is_answered_with_the_accepted_ones():
    """★ The corpus's second-biggest offender, verbatim: `branch` for `pr_id`."""
    res = asyncio.run(HT.CodeHubGetFileContentTool().execute(branch="main", path="a.py"))
    assert res.success is False
    msg = res.error_message
    assert "unexpected keyword argument 'branch'" in msg, msg
    assert "`pr_id` (required)" in msg, msg
    assert "`path` (required)" in msg, msg


def test_a_missing_key_is_answered_the_same_way():
    """The 37 `missing N required positional argument` results."""
    res = asyncio.run(HT.RegistryHubRegisterEndpointTool().execute(method="GET"))
    assert res.success is False
    msg = res.error_message
    assert "missing 1 required positional argument" in msg, msg
    assert "`path` (required)" in msg, msg


def test_the_optional_parameters_are_listed_without_the_required_mark():
    """The biggest offender takes five, two required. An agent that cannot tell them
    apart either omits a required one or invents a key for an optional one."""
    res = asyncio.run(HT.RegistryHubRegisterEndpointTool().execute(method="GET"))
    msg = res.error_message
    assert "`schema`" in msg and "`schema` (required)" not in msg, msg
    assert "`provider`" in msg and "`provider` (required)" not in msg, msg


def test_the_tool_is_named_by_the_name_the_agent_calls():
    """Not `CodeHubGetFileContentTool` -- the agent has never seen that string."""
    res = asyncio.run(HT.CodeHubGetFileContentTool().execute(branch="main", path="a.py"))
    assert "codehub_get_file_content takes" in res.error_message, res.error_message


# --------------------------------------------------------------- the scope guard
class _Boom(HT.HubTool):
    NAME = "boom_tool"
    DESCRIPTION = "raises from inside"
    PARAMETERS = {"type": "object", "properties": {"x": {"type": "string"}},
                  "required": ["x"]}

    async def _run(self, x: str) -> ToolResult:
        # A TypeError from the BODY, not from the call shape.
        return ToolResult(data={"n": x + 1})


class _LooksLikeACallerMistake(HT.HubTool):
    """Its body re-invokes its own `_run` badly, so the TypeError reads
    `_LooksLikeACallerMistake._run() missing 1 required positional argument: 'x'`
    -- character for character what the CALLER passing wrong keys produces."""

    NAME = "looks_like_tool"
    DESCRIPTION = "an in-body TypeError wearing the caller's message"
    PARAMETERS = {"type": "object", "properties": {"x": {"type": "string"}},
                  "required": ["x"]}

    async def _run(self, x: str) -> ToolResult:
        return await self._run()


class _Other(HT.HubTool):
    NAME = "other_tool"
    DESCRIPTION = "raises ValueError"
    PARAMETERS = {"type": "object", "properties": {"x": {"type": "string"}}}

    async def _run(self, x: str = "") -> ToolResult:
        raise ValueError("a domain failure")


HT._finalize_hub_tools([_Boom, _LooksLikeACallerMistake, _Other])


def test_a_typeerror_from_inside_the_tool_keeps_its_text_unadorned():
    """★ THE SCOPE GUARD. A real bug in a tool must not be dressed up as the caller's
    mistake -- that would send whoever reads it to fix the wrong thing."""
    res = asyncio.run(_Boom().execute(x="a"))
    assert res.success is False
    assert "takes exactly these parameters" not in res.error_message, res.error_message


def test_an_in_body_error_wearing_the_callers_message_is_still_not_adorned():
    """★ THE TEST THE FIRST DRAFT COULD NOT EXPRESS. That draft decided from `str(exc)`,
    and mutation testing showed both of its text guards were untested -- every fixture
    that reached one failed the other. This input defeats text matching outright: the
    message names this tool's own `_run()` AND carries `missing 1 required positional
    argument`. Only asking whether THIS call's kwargs bind can tell the two apart, which
    is why the predicate is now a binding and not a string."""
    res = asyncio.run(_LooksLikeACallerMistake().execute(x="a"))
    assert res.success is False
    assert "missing 1 required positional argument" in res.error_message, res.error_message
    assert "takes exactly these parameters" not in res.error_message, res.error_message


def test_a_non_typeerror_keeps_its_text_unadorned():
    res = asyncio.run(_Other().execute(x="a"))
    assert "a domain failure" in res.error_message
    assert "takes exactly these parameters" not in res.error_message, res.error_message


def test_a_tool_with_no_declared_parameters_says_nothing_extra():
    """Better silence than "takes exactly these parameters: ." """
    class _Bare(HT.HubTool):
        NAME = "bare_tool"
        DESCRIPTION = "no params"
        PARAMETERS = {"type": "object", "properties": {}}

        async def _run(self) -> ToolResult:
            return ToolResult(data={})

    HT._finalize_hub_tools([_Bare])
    res = asyncio.run(_Bare().execute(nope=1))
    assert res.success is False
    assert "takes exactly these parameters" not in res.error_message, res.error_message


def test_the_helper_never_raises():
    """It runs ON the failure path, where raising replaces a diagnosis with a traceback
    about the diagnosis."""
    assert HT._signature_help_1203h9(None, None) == ""
    assert HT._signature_help_1203h9(object(), TypeError("whatever")) == ""


def test_only_a_typeerror_can_be_a_call_shape_failure():
    """★ The second guard, isolated. Reached only by a direct call -- in the dispatcher a
    non-TypeError implies the arguments already bound -- but the contract is worth pinning
    so the branch cannot be deleted as dead."""
    tool = HT.CodeHubGetFileContentTool()
    # kwargs that do NOT bind, paired with a non-TypeError: still no help.
    assert HT._signature_help_1203h9(tool, ValueError("x"), {"branch": "main"}) == ""
    # the same non-binding kwargs with a TypeError DO get help.
    assert "takes exactly these parameters" in HT._signature_help_1203h9(
        tool, TypeError("x"), {"branch": "main"})


# ------------------------------------------------------------ shape of the fix
def test_the_original_exception_text_is_still_first():
    """The evidence leads; the explanation follows. A help string that REPLACED the
    exception would trade one silence for another."""
    res = asyncio.run(HT.CodeHubGetFileContentTool().execute(branch="main", path="a.py"))
    msg = res.error_message
    assert msg.index("unexpected keyword argument") < msg.index("takes exactly"), msg


def test_the_dispatcher_adds_no_retry():
    """★ The user's standing rule: a fallback that hides a failure is worse than none.
    This changes the message and nothing else."""
    src = inspect.getsource(HT._finalize_hub_tools)
    tree = ast.parse(src.lstrip())
    handlers = [h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers, "the except clause is gone"
    for h in handlers:
        for node in ast.walk(h):
            assert not isinstance(node, (ast.For, ast.While)), "a retry loop appeared"


def test_the_dispatcher_still_calls_the_helper_with_the_raw_error():
    src = inspect.getsource(HT._finalize_hub_tools)
    assert "str(e) + _signature_help_1203h9(tool, e, kwargs)" in src, src
