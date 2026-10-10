r"""#1202z6: `mcp_connect` fails every time during generation, so it must say why.

`mcp_server/<env>/start.sh` opens with "Launch the FastMCP server (agentsuite-red pool runs
this as a subprocess)": the generated server is started by the DOWNSTREAM consumer, on
PORT 8890, not by the run that writes it.

MEASURED over the corpus: 115 runs author that file, ZERO add it to docker-compose, no MCP
container has ever existed, and `mcp_connect` succeeded 0 times against 9 failures across
the last four runs — `Connection refused`, or `404 .../mcp/tools` when the caller aims at
the backend's port instead. `mcp_list_tools` and `mcp_call` have never been called at all.

WHAT THE BARE ERROR COSTS. In r140 the MCP test-user spent 503 log lines grepping for
`8890` and `mcp_server`, and the debugger then filed a correctly-diagnosed bug — "MCP server
is not exposed/running in current topology" — against BACKEND, a lane that does not own the
topology. 8 of 180 runs carry such a task; the recent ones carry three or four.

★ THE FAILURE IS UNCHANGED. This adds no retry, no fallback and no new state — the call
still fails, with the same exception text. What changes is whether the reader learns the
failure is expected and who it is not a defect of. That distinction is the whole ticket:
a silent-but-correct failure that costs a step and an unactionable P-bug is the same shape
as #1202z0 and #1202z4, one tool over.

★ I GOT THE FRAMING WRONG TWICE before reading that start.sh comment — first "the framework
forgets to add it to compose", then "the framework forgets to start it". Both would have
produced advice telling someone to fix a thing that is working as designed. The rule the
tests below encode: name where the server IS started, not just that it is not up.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.mcp_client_tools as MC  # noqa: E402


def _connect(monkeypatch, exc=ConnectionRefusedError("[Errno 111] Connection refused")):
    def _boom(*a, **k):
        raise exc
    monkeypatch.setattr(MC, "get_mcp_client", _boom)
    tool = MC.MCPConnectTool() if hasattr(MC, "MCPConnectTool") else None
    assert tool is not None, "MCPConnectTool is gone"
    return tool.execute(server_url="http://localhost:8017")


def _msg(res):
    for attr in ("error", "message", "detail"):
        v = getattr(res, attr, None)
        if isinstance(v, str) and v:
            return v
    return str(getattr(res, "data", "") or res)


def test_the_underlying_error_is_still_reported(monkeypatch):
    """★ The exception text is the evidence; the explanation is additive. A hint that
    replaced the cause would trade one silence for another."""
    m = _msg(_connect(monkeypatch))
    assert "Connection refused" in m, m
    assert "Failed to connect" in m, m


def test_it_names_where_the_server_is_actually_started(monkeypatch):
    """Not merely "it is not running" — which is what the caller already knows."""
    m = _msg(_connect(monkeypatch))
    assert "start.sh" in m, m
    assert "downstream" in m.lower(), m


def test_it_names_no_fixed_port(monkeypatch):
    """★ #1203h5 corrected this file's own anchor. These tests used to assert `8890`
    was IN the hint — so they held the copy at a port the run does not control, which
    is the #1203fz family (r174 followed a hardcoded 8890 straight into `Port 8890 is
    already in use`). The port is per-run; the hint must say how to GET one."""
    m = _msg(_connect(monkeypatch))
    assert "8890" not in m, m
    assert "find_free_port" in m, m


def test_it_says_this_is_not_a_backend_defect(monkeypatch):
    """★ The measured cost: r140's debugger filed this against a lane that cannot fix it."""
    m = _msg(_connect(monkeypatch)).lower()
    assert "not a backend defect" in m or "not a backend" in m, m
    assert "do not file" in m, m


def test_it_offers_both_ways_forward(monkeypatch):
    """Start it yourself, or verify the wrapped endpoints and SAY the surface was not
    exercised — the second matters because saying nothing is how 2379 tools came to be
    marked `implemented` without one ever being invoked."""
    m = _msg(_connect(monkeypatch))
    assert "start.sh" in m and "127.0.0.1:<that port>" in m, m
    assert "not exercised" in m, m


def test_a_404_does_not_get_the_nothing_is_listening_excuse(monkeypatch):
    """★ #1203h5 REVERSED this test. It used to assert a 404 "gets the same
    explanation" — and that blanket excuse is what made r175's agent treat a live
    server's 404 as expected, then hand-edit the generated server into a REST shim to
    make the call pass. A 404 means something ANSWERED: that is a real defect, and the
    reader must be told so, not told to ignore it."""
    m = _msg(_connect(monkeypatch, exc=RuntimeError(
        "Client error '404 Not Found' for url 'http://localhost:8017/mcp/tools'")))
    assert "404" in m, m
    low = m.lower()
    assert "real defect" in low, m
    assert "is expected" not in low, m
    assert "do not file it as one" not in low, m
    assert "hand-edit" in low, m


def test_a_successful_connect_carries_no_hint(monkeypatch):
    """The hint belongs to the failure path only; a working connection must not be
    editorialised."""
    class _C:
        def list_tools_sync(self):
            return [{"name": "get_feed"}]
    monkeypatch.setattr(MC, "get_mcp_client", lambda **k: _C())
    res = MC.MCPConnectTool().execute(server_url="http://127.0.0.1:8890")
    blob = str(getattr(res, "data", "") or "")
    assert "8890" in blob or "get_feed" in blob
    assert "start.sh" not in blob, blob


def test_it_adds_no_retry_or_fallback():
    """★ The user's standing rule: a fallback that hides a failure is worse than none. This
    changes the message and nothing else — no retry loop, no alternate URL, no success
    returned from a failed connect."""
    import ast
    import inspect

    src = inspect.getsource(MC.MCPConnectTool.execute)
    tree = ast.parse(src.lstrip())
    handlers = [h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers, "the except clause is gone"
    for h in handlers:
        for node in ast.walk(h):
            assert not isinstance(node, (ast.For, ast.While)), "a retry loop appeared"
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
                assert name != "ok", "a failed connect must not return ok()"
