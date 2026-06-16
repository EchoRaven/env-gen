"""Tests for RegistryHub MCP registry helpers (Cutover 22)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class RegistryHubMCPServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_server_stores_record(self) -> None:
        record = self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend", agent="backend")
        self.assertEqual(record["name"], "filesystem")
        self.assertEqual(record["transport"], "stdio")
        self.assertEqual(record["provider"], "backend")

    def test_register_mcp_server_rejects_unknown_transport(self) -> None:
        result = self.reg.mcp_registry.register_mcp_server(
            name="x", transport="carrier_pigeon",
            endpoint="x", provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_register_mcp_server_rejects_empty_name(self) -> None:
        result = self.reg.mcp_registry.register_mcp_server(
            name="", transport="stdio",
            endpoint="x", provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_get_mcp_servers_returns_all(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="fs", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_server(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend", agent="backend")
        servers = self.reg.mcp_registry.get_mcp_servers()
        self.assertEqual(set(servers.keys()), {"fs", "git"})


class RegistryHubMCPToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_tool_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_tool_stores_record(self) -> None:
        record = self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={"input": {"path": "string"}, "output": {"content": "string"}},
            provider="backend", agent="backend")
        self.assertEqual(record["server_name"], "filesystem")
        self.assertEqual(record["tool_name"], "read_file")

    def test_register_mcp_tool_requires_server_to_exist(self) -> None:
        result = self.reg.mcp_registry.register_mcp_tool(
            server_name="nonexistent", tool_name="x",
            schema={}, provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_get_mcp_tools_filters_by_server(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="git", transport="stdio", endpoint="./git",
            provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_tool(
            server_name="git", tool_name="status",
            schema={}, provider="backend", agent="backend")
        fs_tools = self.reg.mcp_registry.get_mcp_tools(server_name="filesystem")
        self.assertEqual(len(fs_tools), 1)
        self.assertEqual(list(fs_tools.values())[0]["tool_name"], "read_file")

    def test_get_mcp_tools_no_filter_returns_all(self) -> None:
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="write_file",
            schema={}, provider="backend", agent="backend")
        all_tools = self.reg.mcp_registry.get_mcp_tools()
        self.assertEqual(len(all_tools), 2)


class RegistryHubMCPConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_cons_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_consumer_stores_record(self) -> None:
        record = self.reg.mcp_registry.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts", agent="frontend")
        self.assertEqual(record["server_name"], "filesystem")
        self.assertEqual(record["tool_name"], "read_file")
        self.assertEqual(record["file_path"], "frontend/src/api/fs.ts")

    def test_register_consumer_requires_tool_to_exist(self) -> None:
        result = self.reg.mcp_registry.register_mcp_consumer(
            server_name="filesystem", tool_name="nonexistent",
            file_path="x.ts", agent="frontend")
        self.assertIn("error", result)

    def test_get_mcp_consumers_filters_by_server_and_tool(self) -> None:
        self.reg.mcp_registry.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="a.ts", agent="frontend")
        self.reg.mcp_registry.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="b.ts", agent="frontend")
        consumers = self.reg.mcp_registry.get_mcp_consumers(
            server_name="filesystem", tool_name="read_file")
        self.assertEqual(len(consumers), 2)


if __name__ == "__main__":
    unittest.main()
