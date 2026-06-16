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
        auth_token: str = None,
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
    
    async def list_tools(self) -> List[Dict]:
        """
        List available MCP tools.
        
        Returns:
            List of tool definitions with name, description, parameters
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.server_url}/mcp/tools",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
                self._tools_cache = data.get("tools", [])
                return self._tools_cache
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any] = None
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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.server_url}/mcp/tools/{tool_name}",
                    headers=self._get_headers(),
                    json={"arguments": arguments or {}}
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP tool call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"MCP tool call error: {e}")
            raise
    
    async def get_resources(self) -> List[Dict]:
        """List available MCP resources."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.server_url}/mcp/resources",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json().get("resources", [])
        except Exception as e:
            logger.error(f"Failed to list MCP resources: {e}")
            raise
    
    async def read_resource(self, uri: str) -> Dict:
        """Read an MCP resource."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.server_url}/mcp/resources/{uri}",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to read MCP resource: {e}")
            raise
    
    def list_tools_sync(self) -> List[Dict]:
        """Synchronous version of list_tools."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.server_url}/mcp/tools",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                data = response.json()
                self._tools_cache = data.get("tools", [])
                return self._tools_cache
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            raise
    
    def call_tool_sync(
        self,
        tool_name: str,
        arguments: Dict[str, Any] = None
    ) -> Dict:
        """Synchronous version of call_tool."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.server_url}/mcp/tools/{tool_name}",
                    headers=self._get_headers(),
                    json={"arguments": arguments or {}}
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP tool call failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"MCP tool call error: {e}")
            raise


# Global client instance
_mcp_client: Optional[MCPClient] = None


def get_mcp_client(
    server_url: str = None,
    auth_token: str = None
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
                            "description": "MCP server URL (e.g., http://localhost:8080)"
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
        auth_token: str = None
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
            return ToolResult.fail(f"Failed to connect: {str(e)}")


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
        arguments: Dict[str, Any] = None
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
            with httpx.Client(timeout=30) as http_client:
                response = http_client.get(
                    f"{client.server_url}/mcp/resources/{uri}",
                    headers=client._get_headers()
                )
                response.raise_for_status()
                return ToolResult.ok(response.json())
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

