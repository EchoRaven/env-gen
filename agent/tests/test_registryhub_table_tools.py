import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_APIHUB_TABLE_TOOLS = {
    "registryhub_register_table",
    "registryhub_list_tables",
    "registryhub_register_table_consumer",
    "registryhub_get_table_breaking_changes",
}


def _run(coro):
    return asyncio.run(coro)


class RegistryHubTableToolsTests(unittest.TestCase):
    def setUp(self):
        asyncio.set_event_loop(asyncio.new_event_loop())

    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="database_worker", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_registryhub_table_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_APIHUB_TABLE_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_registryhub_register_table_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["registryhub_register_table"]
            result = _run(tool._run(name="users", schema={"id": "int", "email": "string"}))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["name"], "users")
            self.assertEqual(data["provider"], "database_worker")

    def test_registryhub_list_tables_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.schema_hub.register_table(name="users", schema={"id": "int"}, provider="database", agent="database_worker")
            tool = tool_by_name["registryhub_list_tables"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertIn("users", data["tables"])

    def test_registryhub_register_table_consumer_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.schema_hub.register_table(name="users", schema={"id": "int"}, provider="database", agent="database_worker")
            tool = tool_by_name["registryhub_register_table_consumer"]
            result = _run(tool._run(table_name="users", file_path="app/backend/users.py",
                                     metadata={"usage_type": "select"}))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["table_name"], "users")
            self.assertEqual(data["agent"], "database_worker")  # tool injects agent_id

    def test_registryhub_get_table_breaking_changes_returns_list(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.schema_hub.register_table(name="users", schema={"id": "int", "email": "string"},
                                         provider="database", agent="database_worker")
            hubs.schema_hub.update_table_schema("users", {"id": "int"}, agent="database_worker")  # removes email
            tool = tool_by_name["registryhub_get_table_breaking_changes"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(len(data["breaking_changes"]), 1)
            self.assertIn("email", data["breaking_changes"][0]["breaking"]["removed_columns"])


if __name__ == "__main__":
    unittest.main()
