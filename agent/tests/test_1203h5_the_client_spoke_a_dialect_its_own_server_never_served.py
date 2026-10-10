r"""#1203h5: `mcp_connect` spoke a REST dialect the framework's own server never served.

`mcp_server/<env>/main.py` — which this framework writes — ends in
`mcp.run(transport="http")`. That is FastMCP streamable-HTTP: ONE endpoint at
`<base>/mcp` taking JSON-RPC over POST and replying in SSE frames. The client in
`tools/mcp_client_tools.py` did `GET <base>/mcp/tools`.

MEASURED over the whole corpus: `mcp_connect` succeeded 0 times in 170 attempts.
101 were `Connection refused` (nothing listening — since fixed by #1203gs/#1203h3,
which let the squad start the server itself), and every one of the remaining 69
REACHED A LIVE SERVER AND STILL FAILED: 55x HTTP 4xx, 8x "Server disconnected
without sending a response", 6x "Expecting value: line 1 column 1" (SSE read as
JSON). 19 of the 4xx carried a doubled path, `/mcp/mcp/tools`, because the caller
passed the base URL WITH `/mcp` — which the tool schema never told it not to —
and the client appended a second copy.

PROBED against fastmcp 2.13.0.2 and against a real generated server
(`generated/instagram-core-r174/mcp_server/app`, DISABLE_OAUTH=1):
    GET  /mcp/tools  -> 404
    POST /mcp  + `Accept: application/json, text/event-stream`
         -> 200, an `mcp-session-id` header, and an SSE `data:` frame.
After this patch that same generated server answers `tools_count: 5` and
`mcp_connect success = True` — the first success in the project's history.

★ WHY IT WENT UNSEEN FOR 170 ATTEMPTS. #1202z6 added a hint saying the failure
"is expected and is NOT a backend defect: do not file it as one". That was true
while nothing was listening. Once the squad started the server itself, the same
blanket excuse covered a LIVE server's 404 — a fallback masking a failure. In
r175 the agent, measured on making the call pass, HAND-EDITED
`mcp_server/app/main.py` — whose first line reads "do NOT hand-edit" — into a
FastAPI shim serving `/mcp/tools` AND `/mcp/mcp/tools`, defaulted ON via
`MCP_COMPAT_HTTP`, which makes `mcp.run(transport="http")` dead code and ships a
surface speaking no MCP at all to the downstream pool. It reached the delivery
tree root, not just a worktree. So the hint now splits on whether anything
answered, and says so.

★ THE DIALECT IS THE POINT. A unit test with a fake transport can only confirm
the client sends what the client was written to send. The last test here drives
the REAL FastMCP app, which is the only kind that fails when the two sides
disagree.
"""
import ast
import inspect
import json
import os
import socket
import subprocess
import sys
import textwrap
import time

import httpx
import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.mcp_client_tools as MC  # noqa: E402


# --------------------------------------------------------------- the endpoint
@pytest.mark.parametrize("given", [
    "http://127.0.0.1:8052",
    "http://127.0.0.1:8052/",
    "http://127.0.0.1:8052/mcp",
    "http://127.0.0.1:8052/mcp/",
])
def test_every_spelling_of_the_base_lands_on_one_endpoint(given):
    """★ The measured bug: 19 attempts produced `/mcp/mcp/tools`. The schema asks for
    "the address this run actually published" and never says whether to include the
    path, so both spellings must land on the same place."""
    assert MC.mcp_endpoint_1203h5(given) == "http://127.0.0.1:8052/mcp"


def test_an_sse_base_is_not_doubled_either():
    """One corpus attempt aimed at `/sse`, FastMCP's other transport mount."""
    assert MC.mcp_endpoint_1203h5("http://h:1/sse") == "http://h:1/mcp"


def test_the_endpoint_never_contains_the_segment_twice():
    """A property, not three examples: whatever the caller held, `/mcp` appears once."""
    for given in ("http://h:1", "http://h:1/mcp", "http://h:1/mcp/", "http://h:1/sse"):
        assert MC.mcp_endpoint_1203h5(given).count("/mcp") == 1, given


# ------------------------------------------------------------- the SSE unwrap
def test_an_sse_framed_reply_is_unwrapped():
    body = ('event: message\n'
            'data: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_feed"}]}}\n\n')
    got = MC.parse_rpc_payload_1203h5("text/event-stream", body)
    assert got["result"]["tools"][0]["name"] == "get_feed"


def test_a_bare_json_reply_is_accepted_too():
    """The spec lets the server answer `application/json`; both are legal."""
    got = MC.parse_rpc_payload_1203h5("application/json", '{"result":{"tools":[]}}')
    assert got["result"]["tools"] == []


def test_a_jsonrpc_error_raises_instead_of_reading_as_an_empty_tool_list():
    """★ 6 corpus failures were "Expecting value: line 1 column 1" — the old client read
    an SSE body as JSON. The dual hazard is worse: a protocol-level refusal that parses
    must not become `tools: []`, which reads as "the server has no tools"."""
    body = 'data: {"jsonrpc":"2.0","id":2,"error":{"code":-32602,"message":"no session"}}\n'
    with pytest.raises(RuntimeError) as ei:
        MC.parse_rpc_payload_1203h5("text/event-stream", body)
    assert "no session" in str(ei.value)


def test_an_sse_body_with_no_data_frame_raises():
    """Silence is not an empty result."""
    with pytest.raises(ValueError):
        MC.parse_rpc_payload_1203h5("text/event-stream", "event: ping\n\n")


def test_a_notification_carries_no_id():
    """`notifications/initialized` is a notification; an `id` makes the server wait to
    answer a request nobody will read."""
    assert "id" not in MC.rpc_body_1203h5("notifications/initialized")
    assert MC.rpc_body_1203h5("tools/list", {}, 2)["id"] == 2


# ------------------------------------------------- the dialect is gone (AST)
def test_no_call_site_builds_the_rest_dialect_any_more():
    """★ Structural, because the bug was six copies of one f-string and a seventh in a
    tool that hand-rolled its own URL. A comment may still quote the old path; code may
    not build it."""
    path = inspect.getsourcefile(MC)
    tree = ast.parse(open(path, encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant)
                and isinstance(v.value, str))
            if "/mcp/tools" in literal or "/mcp/resources" in literal:
                bad.append((node.lineno, literal))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(("/mcp/tools", "/mcp/resources")):
                bad.append((node.lineno, node.value))
    assert not bad, f"the REST dialect is still being built: {bad}"


def test_the_resource_tool_goes_through_the_client():
    """★ "Fixing one reader is worse than none": MCPGetResourceTool used to build its own
    URL, so a path fix would land on five callers and not the sixth."""
    src = inspect.getsource(MC.MCPGetResourceTool.execute)
    assert "read_resource_sync" in src, src
    assert "httpx" not in src, src


# ------------------------------------------- the request sequence (fake wire)
class _FakeResponse:
    def __init__(self, payload, session_id=None, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": "text/event-stream"}
        if session_id:
            self.headers["mcp-session-id"] = session_id

    @property
    def text(self):
        return f"event: message\ndata: {json.dumps(self._payload)}\n\n"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeClient:
    """Records the wire. Hands out a session id on `initialize`, as FastMCP does."""

    def __init__(self, tools=(("get_feed", ),)):
        self.calls = []
        self._tools = [{"name": n[0]} for n in tools]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append({"url": url, "headers": dict(headers or {}),
                           "body": json})
        method = (json or {}).get("method")
        if method == "initialize":
            return _FakeResponse({"result": {"protocolVersion": "2025-06-18"}},
                                 session_id="sess-1")
        if method == "notifications/initialized":
            return _FakeResponse({}, status=202)
        if method == "tools/list":
            return _FakeResponse({"result": {"tools": self._tools}})
        if method == "tools/call":
            return _FakeResponse(
                {"result": {"content": [{"type": "text", "text": "called"}]}})
        raise AssertionError(f"unexpected method {method!r}")


def _drive(monkeypatch, fn, *a, **kw):
    fake = _FakeClient()
    monkeypatch.setattr(MC.httpx, "Client", lambda *x, **y: fake)
    return fn(*a, **kw), fake


def test_listing_tools_performs_the_handshake_in_order(monkeypatch):
    client = MC.MCPClient(server_url="http://h:1")
    tools, fake = _drive(monkeypatch, client.list_tools_sync)
    assert [c["body"]["method"] for c in fake.calls] == [
        "initialize", "notifications/initialized", "tools/list"]
    assert [t["name"] for t in tools] == ["get_feed"]


def test_every_request_declares_it_can_read_sse(monkeypatch):
    """★ Without this header FastMCP answers 406, which is how 8 corpus attempts became
    "Server disconnected without sending a response"."""
    client = MC.MCPClient(server_url="http://h:1")
    _tools, fake = _drive(monkeypatch, client.list_tools_sync)
    for call in fake.calls:
        accept = call["headers"].get("Accept", "")
        assert "text/event-stream" in accept, call


def test_the_session_id_is_carried_after_initialize(monkeypatch):
    """The server hands it out in a header and then requires it; dropping it is the
    `-32602 no session` refusal."""
    client = MC.MCPClient(server_url="http://h:1")
    _tools, fake = _drive(monkeypatch, client.list_tools_sync)
    assert "mcp-session-id" not in fake.calls[0]["headers"]
    for call in fake.calls[1:]:
        assert call["headers"].get("mcp-session-id") == "sess-1", call


def test_every_request_goes_to_the_one_endpoint(monkeypatch):
    client = MC.MCPClient(server_url="http://h:1/mcp")
    _tools, fake = _drive(monkeypatch, client.list_tools_sync)
    assert {c["url"] for c in fake.calls} == {"http://h:1/mcp"}


def test_calling_a_tool_names_it_in_params_not_in_the_path(monkeypatch):
    """The old client put the tool name in the URL (`/mcp/tools/<name>`); MCP puts it in
    `params.name` of a `tools/call`."""
    client = MC.MCPClient(server_url="http://h:1")
    res, fake = _drive(monkeypatch, client.call_tool_sync, "get_feed", {"x": 1})
    last = fake.calls[-1]
    assert last["body"]["method"] == "tools/call"
    assert last["body"]["params"] == {"name": "get_feed", "arguments": {"x": 1}}
    assert "get_feed" not in last["url"]
    assert res["content"][0]["text"] == "called"


# ------------------------------------------------- against the REAL protocol
_SERVER = """
import os
from fastmcp import FastMCP
mcp = FastMCP("Probe MCP")

@mcp.tool
def get_post(post_id: str) -> str:
    "Return one post."
    return f"post-{post_id}"

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=int(os.environ["PORT"]))
"""


@pytest.fixture
def real_fastmcp_server(tmp_path):
    """A server started the way the framework's own generated `main.py` starts one.

    Skips rather than fails where fastmcp is absent, so the suite stays runnable; the
    process is stopped through the Popen handle alone — never a pattern match over
    /proc, which is how #1203h3's mutation killed a live run.
    """
    pytest.importorskip("fastmcp")
    script = tmp_path / "srv.py"
    script.write_text(textwrap.dedent(_SERVER))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen([sys.executable, str(script)], env=env,
                            cwd=str(tmp_path),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 45
        while time.time() < deadline:
            if proc.poll() is not None:
                out = (proc.stdout.read() or b"").decode("utf-8", "replace")
                pytest.skip(f"fastmcp server would not start: {out[-400:]}")
            try:
                httpx.post(base + "/mcp", timeout=2, headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "p", "version": "1"}}})
                break
            except Exception:
                time.sleep(0.4)
        else:
            pytest.skip("fastmcp server did not answer in 45s")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_the_old_dialect_really_is_404_on_a_real_server(real_fastmcp_server):
    """★ THE NEGATIVE CONTROL, and the reason 170 attempts failed. Without this the
    tests above only prove the client sends what it was written to send."""
    assert httpx.get(real_fastmcp_server + "/mcp/tools", timeout=10).status_code == 404


@pytest.mark.parametrize("suffix", ["", "/mcp"])
def test_the_client_lists_and_calls_tools_on_a_real_server(real_fastmcp_server, suffix):
    """Both spellings of the base, discovery and invocation, against a server started by
    `mcp.run(transport="http")` — the exact line the framework projects."""
    client = MC.MCPClient(server_url=real_fastmcp_server + suffix)
    assert [t["name"] for t in client.list_tools_sync()] == ["get_post"]
    out = client.call_tool_sync("get_post", {"post_id": "42"})
    blob = json.dumps(out)
    assert "post-42" in blob, blob


def test_mcp_connect_reports_success_on_a_real_server(real_fastmcp_server):
    """End to end through the tool the agent actually calls. Before this patch this
    returned `Failed to connect` with a 404 for every run in the corpus."""
    MC._mcp_client = None
    res = MC.MCPConnectTool().execute(server_url=real_fastmcp_server)
    assert res.success, getattr(res, "error", res)
    assert res.data["tools_count"] == 1
    assert res.data["tools"] == ["get_post"]
