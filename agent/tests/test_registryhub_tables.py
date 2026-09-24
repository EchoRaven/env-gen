"""
Tests for RegistryHub.register_table, list_tables, get_table, update_table_schema (Task 19).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _hub(td: str):
    # PR 5: table surface retired from RegistryHub to SchemaHub.
    return HubRegistry(Path(td)).schema_hub


class TestRegistryHubTables(unittest.TestCase):
    def test_register_table_persists(self):
        """register_table stores a table retrievable via get_table and list_tables."""
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            result = hub.register_table(
                name="users",
                schema={"columns": [{"name": "id", "type": "integer"}, {"name": "email", "type": "varchar"}]},
                provider="backend",
                agent="backend",
                status="defined",
            )
            self.assertEqual(result["name"], "users")
            self.assertEqual(result["status"], "defined")
            self.assertEqual(result["provider"], "backend")
            # Persists across call
            fetched = hub.get_table("users")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched["name"], "users")
            all_tables = hub.list_tables()
            self.assertIn("users", all_tables)

    def test_list_tables_filters_by_provider(self):
        """list_tables(provider=...) returns only tables from that provider."""
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            hub.register_table("users", provider="backend", agent="backend")
            hub.register_table("sessions", provider="backend", agent="backend")
            hub.register_table("posts", provider="content_service", agent="backend")
            backend_tables = hub.list_tables(provider="backend")
            self.assertEqual(set(backend_tables.keys()), {"users", "sessions"})
            content_tables = hub.list_tables(provider="content_service")
            self.assertEqual(set(content_tables.keys()), {"posts"})

    def test_get_table_returns_by_name(self):
        """get_table(name) returns the exact table or None for unknown names."""
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            hub.register_table("orders", provider="order_service", agent="backend", status="implemented")
            t = hub.get_table("orders")
            self.assertIsNotNone(t)
            self.assertEqual(t["status"], "implemented")
            self.assertIsNone(hub.get_table("nonexistent_table"))

    def test_update_table_schema_modifies_existing(self):
        """update_table_schema updates the schema on an existing table."""
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            hub.register_table(
                "products",
                schema={"columns": [{"name": "id", "type": "integer"}]},
                provider="catalog",
                agent="backend",
            )
            new_schema = {"columns": [{"name": "id", "type": "integer"}, {"name": "price", "type": "decimal"}]}
            updated = hub.update_table_schema("products", schema=new_schema, agent="backend")
            self.assertEqual(updated["schema"], new_schema)
            self.assertEqual(updated["provider"], "catalog")
            # Error for unknown table
            err = hub.update_table_schema("nonexistent", schema={}, agent="backend")
            self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
