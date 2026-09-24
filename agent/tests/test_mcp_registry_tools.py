"""Tests for MCP registry LLM tools (Cutover 22)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class MCPRegistryToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_server_tool(self) -> None:
        from tools.mcp_registry_tools import RegisterMCPServerTool
        tool = RegisterMCPServerTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend"))
        self.assertTrue(result.success)
        self.assertEqual(result.data["server"]["name"], "filesystem")

    def test_register_tool_requires_server(self) -> None:
        from tools.mcp_registry_tools import RegisterMCPToolTool
        tool = RegisterMCPToolTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            server_name="missing", tool_name="x",
            schema={}, provider="backend"))
        self.assertFalse(result.success)

    def test_register_consumer_full_flow(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, RegisterMCPToolTool, RegisterMCPConsumerTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend"))
        result = _run_async(RegisterMCPConsumerTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts"))
        self.assertTrue(result.success)

    def test_list_servers_tool(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, ListMCPServersTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="fs", transport="stdio", endpoint="./fs", provider="backend"))
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend"))
        result = _run_async(ListMCPServersTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["servers"]), 2)

    def test_list_tools_tool(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, RegisterMCPToolTool, ListMCPToolsTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="write_file",
            schema={}, provider="backend"))
        result = _run_async(ListMCPToolsTool(hub_registry=self.reg).execute(
            server_name="filesystem"))
        self.assertEqual(len(result.data["tools"]), 2)


if __name__ == "__main__":
    unittest.main()
