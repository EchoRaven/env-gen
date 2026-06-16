"""MCP registry LLM tools (Cutover 22)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param


class _MCPToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterMCPServerTool(_MCPToolBase):
    NAME = "mcp_registry_register_server"
    DESCRIPTION = ("Register an MCP server (backend agent uses this). "
                    "transport: stdio | http | sse | websocket. "
                    "endpoint: binary path for stdio, URL for http/sse.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "transport": {"type": "string",
                                    "enum": ["stdio", "http", "sse", "websocket"]},
                    "endpoint": {"type": "string"},
                    "provider": {"type": "string", "default": "backend"},
                },
                "required": ["name", "transport", "endpoint"],
            }, required=["name", "transport", "endpoint"])

    async def execute(self, *, name: str, transport: str, endpoint: str,
                       provider: str = "backend", **_kw) -> ToolResult:
        record = self.hub_registry.mcp_registry.register_mcp_server(
            name=name, transport=transport, endpoint=endpoint,
            provider=provider,
            agent=getattr(self, "_agent_id", None) or provider)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"server": record})


class RegisterMCPToolTool(_MCPToolBase):
    NAME = "mcp_registry_register_tool"
    DESCRIPTION = ("Register an MCP tool exposed by a server. Backend agent "
                    "calls this for each tool the MCP server provides.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "schema": {"type": "object",
                                "description": "input/output schema"},
                    "provider": {"type": "string", "default": "backend"},
                },
                "required": ["server_name", "tool_name", "schema"],
            }, required=["server_name", "tool_name", "schema"])

    async def execute(self, *, server_name: str, tool_name: str,
                       schema: dict, provider: str = "backend", **_kw) -> ToolResult:
        record = self.hub_registry.mcp_registry.register_mcp_tool(
            server_name=server_name, tool_name=tool_name,
            schema=schema, provider=provider,
            agent=getattr(self, "_agent_id", None) or provider)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"tool": record})


class RegisterMCPConsumerTool(_MCPToolBase):
    NAME = "mcp_registry_register_consumer"
    DESCRIPTION = ("Register that a file consumes an MCP tool. Consumer agents "
                    "(typically frontend) call this per-usage.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "file_path": {"type": "string"},
                },
                "required": ["server_name", "tool_name", "file_path"],
            }, required=["server_name", "tool_name", "file_path"])

    async def execute(self, *, server_name: str, tool_name: str,
                       file_path: str, **_kw) -> ToolResult:
        agent = getattr(self, "_agent_id", "")
        record = self.hub_registry.mcp_registry.register_mcp_consumer(
            server_name=server_name, tool_name=tool_name,
            file_path=file_path, agent=agent)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"consumer": record})


class ListMCPServersTool(_MCPToolBase):
    NAME = "mcp_registry_list_servers"
    DESCRIPTION = "List all registered MCP servers."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        servers = list((self.hub_registry.mcp_registry.get_mcp_servers() or {}).values())
        return ToolResult.ok(data={"servers": servers})


class ListMCPToolsTool(_MCPToolBase):
    NAME = "mcp_registry_list_tools"
    DESCRIPTION = "List MCP tools, optionally filtered by server name."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {"server_name": {"type": "string"}},
            }, required=[])

    async def execute(self, *, server_name: str = None, **_kw) -> ToolResult:
        tools = list(
            (self.hub_registry.mcp_registry.get_mcp_tools(server_name=server_name) or {}).values()
        )
        return ToolResult.ok(data={"tools": tools})


_MCP_TOOLS = [RegisterMCPServerTool, RegisterMCPToolTool, RegisterMCPConsumerTool,
               ListMCPServersTool, ListMCPToolsTool]


def create_mcp_registry_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _MCP_TOOLS]


__all__ = [
    "RegisterMCPServerTool", "RegisterMCPToolTool", "RegisterMCPConsumerTool",
    "ListMCPServersTool", "ListMCPToolsTool",
    "create_mcp_registry_tools",
]
