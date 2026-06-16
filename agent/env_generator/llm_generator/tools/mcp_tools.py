"""
MCP Tools - Tools to help MCP Agent generate MCP services

Instead of auto-generating, these tools provide:
1. Reference patterns and examples
2. API spec retrieval
3. Code validation
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult


logger = logging.getLogger("mcp_tools")


# Reference code patterns for MCP Agent
MCP_PATTERNS = {
    "server_main": '''"""
MCP Server for {service_name}
"""
import asyncio
import json
import os
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, Resource, TextContent

from config import Config
from auth import AuthHandler

# Initialize
config = Config()
server = Server(config.service_name)
auth = AuthHandler(config)

# Import and register tools
from tools import register_all_tools
from resources import register_all_resources

register_all_tools(server, config, auth)
register_all_resources(server, config)

async def main():
    """Run MCP server."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    
    if transport == "stdio":
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    elif transport == "http":
        from mcp.server.sse import SseServerTransport
        from aiohttp import web
        
        sse = SseServerTransport("/mcp")
        app = web.Application()
        sse.setup(app)
        print(f"MCP HTTP server starting on port {config.port}")
        web.run_app(app, host="0.0.0.0", port=config.port)

if __name__ == "__main__":
    asyncio.run(main())
''',
    
    "config": '''"""
Configuration for MCP service.
"""
import os
from dataclasses import dataclass

@dataclass
class Config:
    """MCP service configuration from environment."""
    
    # Service
    service_name: str = os.getenv("MCP_SERVICE_NAME", "{service_name}")
    api_base: str = os.getenv("API_BASE_URL", "http://localhost:3000")
    port: int = int(os.getenv("MCP_PORT", "8080"))
    
    # Authentication
    auth_type: str = os.getenv("AUTH_TYPE", "bearer")  # bearer, api_key, none
    api_key_header: str = os.getenv("API_KEY_HEADER", "X-API-Key")
    
    # Retry
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "30.0"))
    
    # Cache
    enable_cache: bool = os.getenv("ENABLE_CACHE", "true").lower() == "true"
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))
''',

    "auth": '''"""
Authentication handler for MCP tools.
"""
import httpx
from typing import Dict, Optional

class AuthHandler:
    """Manage authentication state."""
    
    def __init__(self, config):
        self.config = config
        self._token: Optional[str] = None
        self._user: Optional[Dict] = None
        self._api_key: Optional[str] = None
    
    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        if self.config.auth_type == "bearer":
            return self._token is not None
        elif self.config.auth_type == "api_key":
            return self._api_key is not None
        return True
    
    def get_headers(self) -> Dict[str, str]:
        """Get HTTP headers with authentication."""
        headers = {"Content-Type": "application/json"}
        
        if self.config.auth_type == "bearer" and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif self.config.auth_type == "api_key" and self._api_key:
            headers[self.config.api_key_header] = self._api_key
            
        return headers
    
    async def login(self, email: str, password: str) -> Dict:
        """Login and store token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.api_base}/api/auth/login",
                json={"email": email, "password": password},
                timeout=self.config.request_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                self._token = data.get("token")
                self._user = data.get("user")
                return {"success": True, "user": self._user}
            else:
                return {"success": False, "error": response.text}
    
    def set_api_key(self, api_key: str):
        """Set API key for authentication."""
        self._api_key = api_key
    
    def logout(self):
        """Clear authentication state."""
        self._token = None
        self._user = None
    
    def get_current_user(self) -> Optional[Dict]:
        """Get current authenticated user."""
        return self._user
''',

    "tool_get": '''@server.tool()
async def get_{entity}(id: str) -> List[TextContent]:
    """
    Get a specific {entity} by ID.
    
    Args:
        id: The unique {entity} identifier
        
    Returns:
        {entity_cap} object with all fields
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{{config.api_base}}/api/{entities}/{{id}}",
                headers=auth.get_headers(),
                timeout=config.request_timeout
            )
            
            if response.status_code == 404:
                return [TextContent(type="text", text=json.dumps({{
                    "error": "not_found",
                    "message": f"{entity_cap} '{{id}}' not found"
                }}))]
            
            response.raise_for_status()
            data = response.json()
            if "{response_key}" not in data:
                raise KeyError("Expected response key '{response_key}' was not found")
            result = data["{response_key}"]
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
    except httpx.TimeoutException:
        return [TextContent(type="text", text=json.dumps({{
            "error": "timeout", "message": "Request timed out"
        }}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{
            "error": "internal", "message": str(e)
        }}))]
''',

    "tool_list": '''@server.tool()
async def list_{entities}(
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    {filter_params}
) -> List[TextContent]:
    """
    List {entities} with pagination and filtering.
    
    Args:
        page: Page number (1-indexed)
        limit: Items per page (max 100)
        sort_by: Field to sort by
        {filter_docs}
        
    Returns:
        List of {entity} objects with pagination info
    """
    try:
        params = {{"page": page, "limit": min(limit, 100), "sort": sort_by}}
        {filter_logic}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{{config.api_base}}/api/{entities}",
                headers=auth.get_headers(),
                params=params,
                timeout=config.request_timeout
            )
            response.raise_for_status()
            data = response.json()
            if "{response_key}" not in data:
                raise KeyError("Expected response key '{response_key}' was not found")
            items = data["{response_key}"]
            total = data.get("total", len(items))
            
            return [TextContent(type="text", text=json.dumps({{
                "{entities}": items,
                "total": total,
                "page": page,
                "limit": limit
            }}, indent=2))]
            
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{
            "error": "internal", "message": str(e)
        }}))]
''',

    "tool_create": '''@server.tool()
async def create_{entity}({params}) -> List[TextContent]:
    """
    Create a new {entity}.
    
    Args:
        {param_docs}
        
    Returns:
        Created {entity} object with ID
        
    Requires:
        Authentication
    """
    if not auth.is_authenticated():
        return [TextContent(type="text", text=json.dumps({{
            "error": "unauthorized",
            "message": "Authentication required"
        }}))]
    
    try:
        body = {body_dict}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{{config.api_base}}/api/{entities}",
                headers=auth.get_headers(),
                json=body,
                timeout=config.request_timeout
            )
            
            if response.status_code == 400:
                return [TextContent(type="text", text=json.dumps({{
                    "error": "validation",
                    "message": response.json().get("message", "Validation failed")
                }}))]
            
            response.raise_for_status()
            data = response.json()
            if "{response_key}" not in data:
                raise KeyError("Expected response key '{response_key}' was not found")
            result = data["{response_key}"]
            
            return [TextContent(type="text", text=json.dumps({{
                "success": True,
                "{entity}": result
            }}, indent=2))]
            
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{
            "error": "internal", "message": str(e)
        }}))]
''',

    "tool_update": '''@server.tool()
async def update_{entity}(id: str, {params}) -> List[TextContent]:
    """
    Update an existing {entity}.
    
    Args:
        id: {entity_cap} ID to update
        {param_docs}
        
    Returns:
        Updated {entity} object
        
    Requires:
        Authentication
    """
    if not auth.is_authenticated():
        return [TextContent(type="text", text=json.dumps({{
            "error": "unauthorized",
            "message": "Authentication required"
        }}))]
    
    try:
        body = {{k: v for k, v in {body_dict}.items() if v is not None}}
        
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{{config.api_base}}/api/{entities}/{{id}}",
                headers=auth.get_headers(),
                json=body,
                timeout=config.request_timeout
            )
            
            if response.status_code == 404:
                return [TextContent(type="text", text=json.dumps({{
                    "error": "not_found",
                    "message": f"{entity_cap} '{{id}}' not found"
                }}))]
            
            response.raise_for_status()
            data = response.json()
            if "{response_key}" not in data:
                raise KeyError("Expected response key '{response_key}' was not found")
            result = data["{response_key}"]
            
            return [TextContent(type="text", text=json.dumps({{
                "success": True,
                "{entity}": result
            }}, indent=2))]
            
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{
            "error": "internal", "message": str(e)
        }}))]
''',

    "tool_delete": '''@server.tool()
async def delete_{entity}(id: str) -> List[TextContent]:
    """
    Delete a {entity}.
    
    Args:
        id: {entity_cap} ID to delete
        
    Returns:
        Confirmation of deletion
        
    Requires:
        Authentication
    """
    if not auth.is_authenticated():
        return [TextContent(type="text", text=json.dumps({{
            "error": "unauthorized",
            "message": "Authentication required"
        }}))]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{{config.api_base}}/api/{entities}/{{id}}",
                headers=auth.get_headers(),
                timeout=config.request_timeout
            )
            
            if response.status_code == 404:
                return [TextContent(type="text", text=json.dumps({{
                    "error": "not_found",
                    "message": f"{entity_cap} '{{id}}' not found"
                }}))]
            
            response.raise_for_status()
            
            return [TextContent(type="text", text=json.dumps({{
                "success": True,
                "message": f"{entity_cap} '{{id}}' deleted"
            }}))]
            
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{
            "error": "internal", "message": str(e)
        }}))]
''',

    "resource_schema": '''@server.resource("schema://database")
async def get_database_schema() -> Resource:
    """
    Get database schema information.
    
    Useful for RL agents to understand data structure.
    """
    schema = {schema_content}
    
    return Resource(
        uri="schema://database",
        name="Database Schema",
        description="Database tables, columns, and relationships",
        mimeType="application/json",
        text=json.dumps(schema, indent=2)
    )
''',

    "resource_status": '''@server.resource("status://api")
async def get_api_status() -> Resource:
    """
    Get current API health status.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config.api_base}/api/health",
                timeout=5.0
            )
            status = "healthy" if response.status_code == 200 else "degraded"
    except:
        status = "unreachable"
    
    return Resource(
        uri="status://api",
        name="API Status",
        description="Current API health status",
        mimeType="application/json",
        text=json.dumps({"status": status, "api_base": config.api_base})
    )
''',

    "requirements": '''# MCP Server Dependencies
mcp>=0.1.0
httpx>=0.24.0
aiohttp>=3.8.0  # For HTTP transport
python-dotenv>=1.0.0
''',
}


class GetMCPReferenceTool(BaseTool):
    """Get MCP code patterns and examples."""
    
    NAME = "get_mcp_reference"
    DESCRIPTION = """Get MCP code patterns and examples for generating MCP service.

Available patterns:
- server_main: Main MCP server entry point
- config: Configuration class
- auth: Authentication handler
- tool_get: GET single item pattern
- tool_list: LIST items with pagination pattern
- tool_create: CREATE item pattern
- tool_update: UPDATE item pattern
- tool_delete: DELETE item pattern
- resource_schema: Database schema resource
- resource_status: API status resource
- requirements: Python dependencies

Example:
```python
get_mcp_reference(pattern="server_main")  # Get main server template
get_mcp_reference(pattern="all")  # Get all patterns
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
                        "pattern": {
                            "type": "string",
                            "description": "Pattern name (server_main, config, auth, tool_*, resource_*, requirements, or 'all')"
                        }
                    },
                    "required": ["pattern"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, pattern: str = "all") -> ToolResult:
        """Get MCP reference patterns."""
        if pattern == "all":
            return ToolResult.ok(
                f"Available patterns: {', '.join(MCP_PATTERNS.keys())}\n\nUse get_mcp_reference(pattern='<name>') to get specific pattern code."
            )
        
        if pattern in MCP_PATTERNS:
            return ToolResult.ok(
                f"Pattern: {pattern}\n\n```python\n{MCP_PATTERNS[pattern]}\n```"
            )
        
        # Try partial match
        matches = [k for k in MCP_PATTERNS.keys() if pattern in k]
        if matches:
            result = "\n\n---\n\n".join([
                f"## {m}\n```python\n{MCP_PATTERNS[m]}\n```"
                for m in matches
            ])
            return ToolResult.ok(result)
        
        return ToolResult.fail(
            f"Pattern '{pattern}' not found. Available: {', '.join(MCP_PATTERNS.keys())}"
        )


class ListMCPToolsTool(BaseTool):
    """List MCP tools that should be generated from API spec."""
    
    NAME = "list_mcp_tools_to_generate"
    DESCRIPTION = """Analyze API endpoints and suggest MCP tools to generate.

Returns a list of recommended MCP tools based on the API specification.
"""
    
    def __init__(self, workspace_path: Path = None, hubs=None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.workspace_path = workspace_path
        self._hubs = hubs
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self) -> ToolResult:
        """List recommended MCP tools."""
        endpoints = []
        
        # Get from HubRegistry (RegistryHub)
        if self._hubs:
            endpoint_data = self._hubs.registryhub.get_endpoints()
            for path, info in endpoint_data.items():
                endpoints.append({
                    "path": path,
                    "method": info.get("method", "GET"),
                    "description": info.get("description", ""),
                    "response_key": info.get("response_key"),
                    "auth_required": info.get("auth_required", False),
                })

        if not endpoints:
            return ToolResult.ok(
                "No API endpoints found in RegistryHub. Wait for backend API to be defined."
            )
        
        # Group by entity
        entities = {}
        for ep in endpoints:
            path = ep["path"]
            # Extract entity from path like /api/games/:id -> games
            parts = path.replace("/api/", "").split("/")
            entity = parts[0] if parts else "unknown"
            
            if entity not in entities:
                entities[entity] = []
            entities[entity].append(ep)
        
        # Generate recommendations
        lines = ["# Recommended MCP Tools to Generate\n"]
        
        for entity, eps in entities.items():
            lines.append(f"\n## Entity: {entity}")
            lines.append(f"File: `mcp/tools/{entity}_tools.py`\n")
            
            for ep in eps:
                method = ep["method"]
                path = ep["path"]
                
                # Suggest tool name
                if method == "GET" and ":" not in path:
                    tool_name = f"list_{entity}"
                elif method == "GET":
                    tool_name = f"get_{entity}"
                elif method == "POST":
                    tool_name = f"create_{entity.rstrip('s')}"
                elif method == "PUT" or method == "PATCH":
                    tool_name = f"update_{entity.rstrip('s')}"
                elif method == "DELETE":
                    tool_name = f"delete_{entity.rstrip('s')}"
                else:
                    tool_name = f"{method.lower()}_{entity}"
                
                auth = " [AUTH]" if ep.get("auth_required") else ""
                resp_key = f" -> {ep['response_key']}" if ep.get("response_key") else ""
                
                lines.append(f"- `{tool_name}`: {method} {path}{auth}{resp_key}")
        
        lines.append("\n\n## Also Generate:")
        lines.append("- `mcp/resources/schema.py` - Database schema resource")
        lines.append("- `mcp/resources/status.py` - API status resource")
        lines.append("- `mcp/auth.py` - Authentication handler")
        lines.append("- `mcp/config.py` - Configuration")
        
        return ToolResult.ok("\n".join(lines))


class ValidateMCPCodeTool(BaseTool):
    """Validate MCP server code."""
    
    NAME = "validate_mcp_code"
    DESCRIPTION = """Validate MCP server code for common issues.

Checks:
- Required imports
- Tool decorator usage
- Return type consistency
- Authentication handling
- Error handling patterns
"""
    
    def __init__(self, workspace_path: Path = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.workspace_path = workspace_path
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to MCP Python file to validate"
                        }
                    },
                    "required": ["file_path"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, file_path: str) -> ToolResult:
        """Validate MCP code."""
        try:
            if self.workspace_path:
                full_path = self.workspace_path / file_path
            else:
                full_path = Path(file_path)
            
            if not full_path.exists():
                return ToolResult.fail(f"File not found: {file_path}")
            
            content = full_path.read_text()
            issues = []
            suggestions = []
            
            # Check imports
            required_imports = [
                ("from mcp.server import Server", "MCP Server import"),
                ("from mcp.types import", "MCP types import"),
                ("import httpx", "HTTP client import"),
                ("import json", "JSON import"),
            ]
            
            for imp, desc in required_imports:
                if imp not in content:
                    issues.append(f"Missing: {desc} ({imp})")
            
            # Check tool decorators
            if "@server.tool()" not in content and "server.tool" not in content:
                suggestions.append("No @server.tool() decorators found - add tools")
            
            # Check async
            if "async def" not in content:
                issues.append("No async functions - MCP tools should be async")
            
            # Check return type
            if "List[TextContent]" not in content and "TextContent" not in content:
                suggestions.append("Consider returning List[TextContent] from tools")
            
            # Check error handling
            if "try:" not in content or "except" not in content:
                suggestions.append("Add try/except error handling to tools")
            
            # Check auth
            if "auth" not in content.lower():
                suggestions.append("Consider adding authentication support")
            
            # Compile result
            if issues:
                return ToolResult.fail(
                    f"Validation issues:\n" + "\n".join(f"- {i}" for i in issues) +
                    ("\n\nSuggestions:\n" + "\n".join(f"- {s}" for s in suggestions) if suggestions else "")
                )
            
            result = "✓ MCP code looks good!"
            if suggestions:
                result += "\n\nSuggestions:\n" + "\n".join(f"- {s}" for s in suggestions)
            
            return ToolResult.ok(result)
            
        except Exception as e:
            return ToolResult.fail(f"Validation error: {e}")


def create_mcp_tools(workspace_path: Path = None, hubs=None) -> List[BaseTool]:
    """Create MCP helper tools."""
    return [
        GetMCPReferenceTool(),
        ListMCPToolsTool(workspace_path, hubs),
        ValidateMCPCodeTool(workspace_path),
    ]


__all__ = [
    "GetMCPReferenceTool",
    "ListMCPToolsTool",
    "ValidateMCPCodeTool",
    "create_mcp_tools",
    "MCP_PATTERNS",
]
