"""#1116: an argument the framework throws away must be reported to the CALLER.

#360 strips arguments a tool's signature cannot take, so one bad key does not lose the
whole call, and logs a WARNING. That WARNING reaches a log file and no agent. The caller
gets a normal-looking result and proceeds believing its argument took effect.

Corpus: 52418 introspectable tool calls across 85 runs, 60 carrying an argument the tool
does not declare, spread over 25 runs. Most-dropped key: `uses` on
registryhub_register_endpoint — agents declaring which tables an endpoint reads. That
parameter does not exist, the key is discarded, and #1023b separately reports that
registryhub_register_table_consumer (the tool that would record it) was called in 0 of
172 runs.

Worst observed consequence, from the smoke-notes run: the orchestrator called
deliver_project(force_deliver=True), had the argument dropped, then reported "Delivery
gate refuses force_deliver" — a refusal that never happened — and escalated it.
"""
import sys

from utils.tool import ToolResult
from env_generator.llm_generator.multi_agent.agents.runtime.tooling import (
    drop_unaccepted_kwargs,
    dropped_args_message_1116,
)


class _FakeEndpointTool:
    """Shaped like registryhub_register_endpoint, which has no `uses` parameter."""

    NAME = "registryhub_register_endpoint"
    PARAMETERS = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "description": "HTTP verb"},
            "path": {"type": "string", "description": "registered path"},
            "schema": {"type": "object", "description": "request/response shape"},
            "provider": {"type": "string"},
            "status": {"type": "string", "description": "planned|implemented"},
        },
    }

    def _run(self, method, path, schema=None, provider=None, status=None):
        return ToolResult(success=True, data={"registered": f"{method} {path}"})


def test_a_notice_reaches_the_text_the_agent_reads():
    r = ToolResult(success=True, data={"registered": "GET /api/notes"})
    assert "ignored" not in str(r)

    r.notices.append("[framework] ignored argument(s) uses")
    rendered = str(r)
    assert "{'registered': 'GET /api/notes'}" in rendered, "the tool's own data was lost"
    assert "ignored argument(s) uses" in rendered, (
        "the notice never reached the caller — same blind spot #1116 exists to close"
    )


def test_a_notice_reaches_the_caller_on_failure_too():
    r = ToolResult(success=False, error_message="boom", data={"detail": "why"})
    r.notices.append("[framework] ignored argument(s) branch")
    rendered = str(r)
    assert "Error: boom" in rendered
    assert "why" in rendered           # #674's data-on-failure must survive
    assert "ignored argument(s) branch" in rendered


def test_no_notices_changes_nothing():
    """A result with no notices must render byte-identically to before #1116."""
    assert str(ToolResult(success=True, data={"a": 1})) == "{'a': 1}"
    assert str(ToolResult(success=True)) == "OK"
    assert str(ToolResult(success=False, error_message="nope")) == "Error: nope"
    assert str(ToolResult(success=True, data={"a": 1}, notices=[])) == "{'a': 1}"
    assert str(ToolResult(success=True, data={"a": 1}, notices=["", "  "])) == "{'a': 1}"


def test_the_message_names_the_dropped_key_and_what_the_tool_accepts():
    tool = _FakeEndpointTool()
    kept, dropped = drop_unaccepted_kwargs(
        tool._run, {"method": "GET", "path": "/api/notes", "uses": ["notes", "users"]})

    assert dropped == ["uses"], "the corpus's most-dropped key stopped being detected"
    assert "uses" not in kept and kept["method"] == "GET"

    msg = dropped_args_message_1116(tool.NAME, dropped, tool)
    assert "uses" in msg
    assert "did not happen" in msg, "the message must say the effect was NOT applied"
    # it must quote the tool's real schema back, so the agent can self-correct
    for real in ("method", "path", "schema", "provider", "status"):
        assert real in msg, "accepted parameter %r missing from the message" % real
    assert "planned|implemented" in msg, "the published descriptions were not quoted back"


def test_a_tool_with_no_schema_still_produces_a_usable_message():
    class _Bare:
        NAME = "bare_tool"

        def _run(self, a):
            return None

    msg = dropped_args_message_1116("bare_tool", ["b"], _Bare())
    assert "bare_tool" in msg and "b" in msg
    assert "no parameter schema" in msg


def test_kwargs_tools_still_drop_nothing():
    """#360's exemption is untouched: a **kwargs signature accepts everything."""
    def _run(self=None, **kw):
        return None

    kept, dropped = drop_unaccepted_kwargs(_run, {"anything": 1, "at": "all"})
    assert dropped == []
    assert kept == {"anything": 1, "at": "all"}
