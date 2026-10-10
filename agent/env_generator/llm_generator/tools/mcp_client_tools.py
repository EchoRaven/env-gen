"""
MCP Client Tools - Tools for User Agent to connect and call MCP services

These tools allow User Agent to:
1. Connect to MCP server
2. List available MCP tools
3. Call MCP tools
4. Handle authentication
"""

import json
import logging
import httpx
from typing import Any, Dict, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult


logger = logging.getLogger("mcp_client")


# --- #1203h5: speak the protocol our OWN generated server serves -------------
# `mcp_server/<env>/main.py` ends in `mcp.run(transport="http")` -- FastMCP
# streamable-HTTP: ONE endpoint at `<base>/mcp` that takes JSON-RPC over POST
# and replies in SSE frames. This client used to GET `<base>/mcp/tools`, a REST
# dialect NOTHING the framework generates serves (1 of 145 generated servers,
# and that one was hand-written by an agent working around this very bug).
# Measured over the whole corpus: `mcp_connect` succeeded 0 times in 170
# attempts -- 101 refused (nothing listening, since fixed by #1203gs/#1203h3)
# and every one of the other 69 reached a LIVE server and still failed: 55x
# 4xx, 8x "Server disconnected", 6x non-JSON. Probed against fastmcp 2.13.0.2:
# `GET /mcp/tools` -> 404; `POST /mcp` with `Accept: application/json,
# text/event-stream` -> 200 + an `mcp-session-id` header.
MCP_PROTOCOL_VERSION_1203H5 = "2025-06-18"


def mcp_endpoint_1203h5(server_url: str) -> str:
    """The single URL a FastMCP ``transport="http"`` server serves.

    Accepts both spellings a caller may hold, because the tool schema asks for
    "the address this run actually published" and never says whether to include
    the path. Appending blindly produced `/mcp/mcp/tools` in 19 corpus attempts.
    """
    base = (server_url or "").rstrip("/")
    for served in ("/mcp", "/sse"):
        if base.endswith(served):
            base = base[: -len(served)]
            break
    return f"{base}/mcp"


def parse_rpc_payload_1203h5(content_type: str, text: str) -> Dict[str, Any]:
    """Unwrap one JSON-RPC reply, SSE-framed or bare.

    Raises on a JSON-RPC ``error`` rather than returning a result-shaped dict,
    so a protocol-level refusal can never read as an empty tool list.
    """
    body = text or ""
    if "text/event-stream" in (content_type or "").lower():
        frames = [
            line[len("data:"):].strip()
            for line in body.splitlines()
            if line.startswith("data:")
        ]
        if not frames:
            raise ValueError(
                f"MCP reply carried no `data:` frame: {body[:200]!r}")
        body = frames[-1]
    payload = json.loads(body)
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        raise RuntimeError(
            "MCP server refused the call: "
            f"{err.get('message') if isinstance(err, dict) else err}")
    return payload if isinstance(payload, dict) else {}


def rpc_body_1203h5(method: str, params=None, rpc_id=None) -> Dict[str, Any]:
    """One JSON-RPC envelope; no ``id`` means a notification."""
    body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if rpc_id is not None:
        body["id"] = rpc_id
    if params is not None:
        body["params"] = params
    return body


class MCPClient:
    """
    MCP Client for connecting to MCP servers.
    
    Supports:
    - HTTP transport (REST-like)
    - Tool discovery
    - Tool invocation
    - Authentication
    """
    
    def __init__(
        self,
        server_url: str = "http://localhost:8080",
        auth_token: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.server_url = server_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self._tools_cache = None
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers including auth."""
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
    
    def _rpc_headers(self, session_id: Optional[str] = None) -> Dict[str, str]:
        """Auth headers plus the two things streamable-HTTP requires."""
        headers = self._get_headers()
        headers["Accept"] = "application/json, text/event-stream"
        if session_id:
            headers["mcp-session-id"] = session_id
        return headers

    def _init_params_1203h5(self) -> Dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION_1203H5,
            "capabilities": {},
            "clientInfo": {"name": "envgen-mcp-client", "version": "1"},
        }

    def _rpc_sync(self, client, method, params=None, *, session_id=None,
                  rpc_id=1):
        response = client.post(
            mcp_endpoint_1203h5(self.server_url),
            headers=self._rpc_headers(session_id),
            json=rpc_body_1203h5(method, params, rpc_id),
        )
        response.raise_for_status()
        payload = parse_rpc_payload_1203h5(
            response.headers.get("content-type", ""), response.text)
        return payload, (response.headers.get("mcp-session-id") or session_id)

    def _open_session_sync(self, client) -> Optional[str]:
        """``initialize`` then ``notifications/initialized``."""
        _payload, session_id = self._rpc_sync(
            client, "initialize", self._init_params_1203h5())
        ack = client.post(
            mcp_endpoint_1203h5(self.server_url),
            headers=self._rpc_headers(session_id),
            json=rpc_body_1203h5("notifications/initialized"),
        )
        ack.raise_for_status()
        return session_id

    async def _rpc_async(self, client, method, params=None, *, session_id=None,
                         rpc_id=1):
        response = await client.post(
            mcp_endpoint_1203h5(self.server_url),
            headers=self._rpc_headers(session_id),
            json=rpc_body_1203h5(method, params, rpc_id),
        )
        response.raise_for_status()
        payload = parse_rpc_payload_1203h5(
            response.headers.get("content-type", ""), response.text)
        return payload, (response.headers.get("mcp-session-id") or session_id)

    async def _open_session_async(self, client) -> Optional[str]:
        _payload, session_id = await self._rpc_async(
            client, "initialize", self._init_params_1203h5())
        ack = await client.post(
            mcp_endpoint_1203h5(self.server_url),
            headers=self._rpc_headers(session_id),
            json=rpc_body_1203h5("notifications/initialized"),
        )
        ack.raise_for_status()
        return session_id

    async def list_tools(self) -> List[Dict]:
        """
        List available MCP tools.
        
        Returns:
            List of tool definitions with name, description, parameters
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout,
                                         follow_redirects=True) as client:
                session_id = await self._open_session_async(client)
                payload, _ = await self._rpc_async(
                    client, "tools/list", session_id=session_id, rpc_id=2)
                self._tools_cache = (payload.get("result") or {}).get("tools", [])
                return self._tools_cache
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> Dict:
        """
        Call an MCP tool.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool execution result
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout,
                                         follow_redirects=True) as client:
                session_id = await self._open_session_async(client)
                payload, _ = await self._rpc_async(
                    client, "tools/call",
                    {"name": tool_name, "arguments": arguments or {}},
                    session_id=session_id, rpc_id=2)
                return payload.get("result") or {}
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP tool call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"MCP tool call error: {e}")
            raise
    
    def read_resource_sync(self, uri: str) -> Dict:
        """Synchronous ``resources/read``.

        #1203h5: exists so MCPGetResourceTool stops hand-rolling its own URL --
        that second spelling is how a path fix lands on one caller and not the
        other (#1202lh / "fixing one reader is worse than none").
        """
        try:
            with httpx.Client(timeout=self.timeout,
                              follow_redirects=True) as client:
                session_id = self._open_session_sync(client)
                payload, _ = self._rpc_sync(
                    client, "resources/read", {"uri": uri},
                    session_id=session_id, rpc_id=2)
                return payload.get("result") or {}
        except Exception as e:
            logger.error(f"Failed to read MCP resource: {e}")
            raise

    async def get_resources(self) -> List[Dict]:
        """List available MCP resources."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout,
                                         follow_redirects=True) as client:
                session_id = await self._open_session_async(client)
                payload, _ = await self._rpc_async(
                    client, "resources/list", session_id=session_id, rpc_id=2)
                return (payload.get("result") or {}).get("resources", [])
        except Exception as e:
            logger.error(f"Failed to list MCP resources: {e}")
            raise
    
    async def read_resource(self, uri: str) -> Dict:
        """Read an MCP resource."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout,
                                         follow_redirects=True) as client:
                session_id = await self._open_session_async(client)
                payload, _ = await self._rpc_async(
                    client, "resources/read", {"uri": uri},
                    session_id=session_id, rpc_id=2)
                return payload.get("result") or {}
        except Exception as e:
            logger.error(f"Failed to read MCP resource: {e}")
            raise
    
    def list_tools_sync(self) -> List[Dict]:
        """Synchronous version of list_tools."""
        try:
            with httpx.Client(timeout=self.timeout,
                              follow_redirects=True) as client:
                session_id = self._open_session_sync(client)
                payload, _ = self._rpc_sync(
                    client, "tools/list", session_id=session_id, rpc_id=2)
                self._tools_cache = (payload.get("result") or {}).get("tools", [])
                return self._tools_cache
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise
    
    def call_tool_sync(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> Dict:
        """Synchronous version of call_tool."""
        try:
            with httpx.Client(timeout=self.timeout,
                              follow_redirects=True) as client:
                session_id = self._open_session_sync(client)
                payload, _ = self._rpc_sync(
                    client, "tools/call",
                    {"name": tool_name, "arguments": arguments or {}},
                    session_id=session_id, rpc_id=2)
                return payload.get("result") or {}
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP tool call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"MCP tool call error: {e}")
            raise


# Global client instance
_mcp_client: Optional[MCPClient] = None


def get_mcp_client(
    server_url: Optional[str] = None,
    auth_token: Optional[str] = None
) -> MCPClient:
    """Get or create MCP client."""
    global _mcp_client
    
    if server_url:
        _mcp_client = MCPClient(server_url=server_url, auth_token=auth_token)
    elif _mcp_client is None:
        _mcp_client = MCPClient()
    
    return _mcp_client


# ==================== MCP Tools for User Agent ====================

class MCPConnectTool(BaseTool):
    """Connect to an MCP server"""
    
    NAME = "mcp_connect"
    DESCRIPTION = """Connect to an MCP server.

Call this before using mcp_call() to set up the connection.

Example:
```python
mcp_connect(
    server_url="http://localhost:8080",
    auth_token="optional_token"
)
```

Returns list of available tools on success.
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server_url": {
                            "type": "string",
                            "description": "MCP server URL. Use the address this run "
                                           "actually published — ports are per-run and the "
                                           "example's :8080 has long hosted an unrelated "
                                           "demo on the gen host (#207/#1202lq)."
                        },
                        "auth_token": {
                            "type": "string",
                            "description": "Optional authentication token"
                        }
                    },
                    "required": ["server_url"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        server_url: str,
        auth_token: Optional[str] = None
    ) -> ToolResult:
        """Connect to MCP server and list tools."""
        try:
            client = get_mcp_client(server_url=server_url, auth_token=auth_token)
            tools = client.list_tools_sync()
            
            tool_names = [t.get("name") for t in tools]
            
            return ToolResult.ok({
                "connected": True,
                "server_url": server_url,
                "tools_count": len(tools),
                "tools": tool_names,
                "message": f"Connected to MCP server with {len(tools)} tools"
            })
        except Exception as e:
            # #1202z6: say WHY this fails, because it fails EVERY time and the caller then
            # spends the step hunting for a server that is not meant to be up.
            #
            # `mcp_server/<env>/start.sh` opens with "Launch the FastMCP server
            # (agentsuite-red pool runs this as a subprocess)" -- so the generated server is
            # started by the DOWNSTREAM consumer, on PORT 8890, not by the run that writes
            # it. Measured over the corpus: 115 runs author that file, ZERO add it to
            # docker-compose, no MCP container has ever existed, and `mcp_connect` succeeded
            # 0 times against 9 failures in the last four runs -- `Connection refused`, or
            # `404 .../mcp/tools` when the caller aims at the backend's port instead.
            #
            # Without this, r140's MCP test-user spent 503 log lines grepping for `8890` and
            # `mcp_server`, then the debugger filed a correctly-diagnosed bug ("MCP server is
            # not exposed/running in current topology") against BACKEND -- a lane that does
            # not own the topology. 8 of 180 runs carry such a task. The failure is the same
            # either way; what changes is whether the reader learns it is expected.
            #
            # #1203h5: that blanket "this failure is expected" became a fallback
            # that MASKS a failure once #1203gs/#1203h3 let the squad start the
            # server itself: the server IS up, and the 404 is this framework's
            # own client speaking a REST dialect FastMCP does not serve. In
            # r175 the agent answered the masked 404 by HAND-EDITING
            # `mcp_server/app/main.py` -- whose first line reads "do NOT
            # hand-edit" -- into a FastAPI shim serving `/mcp/tools` AND
            # `/mcp/mcp/tools`, defaulted ON (`MCP_COMPAT_HTTP`), which makes
            # `mcp.run(transport="http")` dead code and ships a surface that
            # speaks no MCP at all to the downstream pool. So the hint now
            # splits on what actually happened, and says the port is per-run
            # instead of naming 8890 (#1203fz: never name a fixed port the run
            # does not control).
            # The split is "did any HTTP response come back", not the exception
            # class: httpx.ConnectError is a TransportError and NOT an OSError,
            # while a bare socket failure IS one (ConnectionRefusedError <-
            # ConnectionError <- OSError), so both spellings must be listed.
            # Anything else -- an HTTP status, "Server disconnected", non-JSON,
            # a JSON-RPC error -- means something ANSWERED, which is the real
            # defect branch.
            _refused_1203h5 = isinstance(
                e, (httpx.ConnectError, httpx.ConnectTimeout, OSError))
            if _refused_1203h5:
                _hint_1202z6 = (
                    " — NOTE: nothing is listening there. The generated MCP server "
                    "(`mcp_server/<env>/main.py`) is launched by the DOWNSTREAM agent "
                    "pool, not by the generation run, so during generation this is "
                    "expected and is NOT a backend defect: do not file it as one. To "
                    "exercise the surface here, start it yourself — get a port with "
                    "`find_free_port`, then `run_background` with "
                    "`API_BASE_URL=<the API base> PORT=<that port> sh start.sh` in "
                    "`mcp_server/<env>`, and connect to http://127.0.0.1:<that port> "
                    "— otherwise verify the endpoints the tools wrap and say the MCP "
                    "surface was not exercised."
                )
            else:
                _hint_1202z6 = (
                    " — NOTE: something IS listening there and it refused the MCP "
                    "handshake, so this is a REAL defect, not the expected "
                    "nothing-is-running case: report it with this message against "
                    "whoever owns that surface. Do NOT hand-edit "
                    "`mcp_server/<env>/main.py` to make this call pass — its first "
                    "line says do NOT hand-edit, and a REST shim there replaces the "
                    "real FastMCP server for the downstream pool, which is a worse "
                    "deliverable than an unexercised MCP surface."
                )
            return ToolResult.fail(f"Failed to connect: {str(e)}{_hint_1202z6}")


class MCPListToolsTool(BaseTool):
    """List available MCP tools"""
    
    NAME = "mcp_list_tools"
    DESCRIPTION = """List all available tools on the connected MCP server.

Example:
```python
tools = mcp_list_tools()
# Returns: {tools: [{name, description, parameters}, ...]}
```
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {"type": "object", "properties": {}}
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self) -> ToolResult:
        """List MCP tools."""
        try:
            client = get_mcp_client()
            tools = client.list_tools_sync()
            
            return ToolResult.ok({
                "count": len(tools),
                "tools": tools
            })
        except Exception as e:
            return ToolResult.fail(f"Failed to list tools: {str(e)}")


class MCPCallTool(BaseTool):
    """Call an MCP tool"""
    
    NAME = "mcp_call"
    DESCRIPTION = """Call a tool on the MCP server.

Use this to execute actions through MCP instead of browser.

Example:
```python
# Login via MCP
result = mcp_call(
    tool_name="login",
    arguments={"email": "user@test.com", "password": "pass123"}
)

# List games via MCP
result = mcp_call(
    tool_name="list_games",
    arguments={"genre": "rpg", "limit": 10}
)

# Add to cart via MCP
result = mcp_call(
    tool_name="add_to_cart",
    arguments={"game_id": "123", "quantity": 1}
)
```

Returns the tool execution result.
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Name of the MCP tool to call"
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments to pass to the tool"
                        }
                    },
                    "required": ["tool_name"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        """Call MCP tool."""
        try:
            client = get_mcp_client()
            result = client.call_tool_sync(tool_name, arguments or {})
            
            return ToolResult.ok({
                "tool": tool_name,
                "arguments": arguments,
                "result": result
            })
        except Exception as e:
            return ToolResult.fail(f"MCP call failed: {str(e)}")


class MCPGetResourceTool(BaseTool):
    """Get an MCP resource"""
    
    NAME = "mcp_get_resource"
    DESCRIPTION = """Get a resource from the MCP server.

Resources are read-only data like schemas, configurations, etc.

Example:
```python
resource = mcp_get_resource(uri="games/schema")
```
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "Resource URI"
                        }
                    },
                    "required": ["uri"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, uri: str) -> ToolResult:
        """Get MCP resource."""
        try:
            client = get_mcp_client()
            return ToolResult.ok(client.read_resource_sync(uri))
        except Exception as e:
            return ToolResult.fail(f"Failed to get resource: {str(e)}")


def create_mcp_client_tools() -> List[BaseTool]:
    """Create MCP client tools for User Agent."""
    return [
        MCPConnectTool(),
        MCPListToolsTool(),
        MCPCallTool(),
        MCPGetResourceTool(),
    ]


__all__ = [
    "MCPClient",
    "get_mcp_client",
    "MCPConnectTool",
    "MCPListToolsTool",
    "MCPCallTool",
    "MCPGetResourceTool",
    "create_mcp_client_tools",
]

