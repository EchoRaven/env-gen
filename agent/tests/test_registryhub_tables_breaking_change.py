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


class RegistryHubTableBreakingChangeTests(unittest.TestCase):
    """PR 5 of the hub-responsibility-split plan retired the table
    surface from RegistryHub into SchemaHub; this suite migrated from
    ``hub = HubRegistry(...).registryhub`` to ``hub = HubRegistry(...).schema_hub``
    in the same PR. The on-disk stores stay owned by RegistryHub so
    snapshot semantics are unchanged."""

    def _hub(self, td):
        return HubRegistry(Path(td)).schema_hub

    def test_register_table_consumer_persists(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "email": "string"},
                                provider="database", agent="database_worker")
            result = hub.register_table_consumer(
                table_name="users",
                file_path="app/backend/users.py",
                agent="backend",
                metadata={"usage_type": "select"},
            )
            self.assertEqual(result["table_name"], "users")
            self.assertEqual(result["file_path"], "app/backend/users.py")
            self.assertEqual(result["agent"], "backend")

    def test_register_table_consumer_unknown_table_returns_error(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_table_consumer(
                table_name="nonexistent", file_path="x.py", agent="backend",
            )
            self.assertIn("error", result)

    def test_detect_table_breaking_change_removed_column(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int", "name": "string", "email": "string"}
            new = {"id": "int", "name": "string"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("email", result["removed_columns"])

    def test_detect_table_breaking_change_type_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int"}
            new = {"id": "string"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("id", result["type_changed_columns"])

    def test_detect_table_breaking_change_additive_is_not_breaking(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"id": "int"}
            new = {"id": "int", "created_at": "timestamp"}
            result = hub.detect_table_breaking_change(old, new)
            self.assertFalse(result["is_breaking"])

    def test_update_table_schema_records_breaking_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "email": "string"},
                                provider="database", agent="database_worker")
            hub.update_table_schema("users", {"id": "int"}, agent="database_worker")  # removes email
            changes = hub.get_table_breaking_changes()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["table_name"], "users")
            self.assertIn("email", changes[0]["breaking"]["removed_columns"])

    def test_get_table_breaking_changes_filters_by_since_ts(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users", schema={"id": "int", "x": "string"},
                                provider="database", agent="database_worker")
            hub.update_table_schema("users", {"id": "int"}, agent="database_worker")
            future = time.time() + 1.0
            self.assertEqual(hub.get_table_breaking_changes(since_ts=future), [])


if __name__ == "__main__":
    unittest.main()
