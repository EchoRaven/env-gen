"""Tests for RegistryHub seed registration helpers (Cutover 21)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_SAMPLE_USERS = [
    {"id": 1, "name": "Alex Chen", "email": "alex.chen@example.com", "is_active": True},
    {"id": 2, "name": "Maria Rodriguez", "email": "maria.r@example.com", "is_active": False},
    {"id": 3, "name": "Yuki Tanaka", "email": "yuki@example.com", "is_active": True},
]


class RegistryHubSeedRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_seed_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_seed_data_stores_record(self) -> None:
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database_worker")
        record = self.reg.schema_hub.register_seed_data(
            "users", row_count=42, sample_excerpt=_SAMPLE_USERS,
            agent="database_worker")
        self.assertEqual(record["table_name"], "users")
        self.assertEqual(record["row_count"], 42)
        self.assertEqual(len(record["sample_excerpt"]), 3)
        self.assertEqual(record["registered_by"], "database_worker")

    def test_register_unregistered_table_fails(self) -> None:
        result = self.reg.schema_hub.register_seed_data(
            "missing_table", row_count=10, sample_excerpt=[],
            agent="database_worker")
        self.assertIn("error", result)
        self.assertIn("not registered", result["error"].lower())

    def test_negative_row_count_rejected(self) -> None:
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database_worker")
        result = self.reg.schema_hub.register_seed_data(
            "users", row_count=-1, sample_excerpt=_SAMPLE_USERS,
            agent="database_worker")
        self.assertIn("error", result)

    def test_get_seed_data_returns_record(self) -> None:
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database_worker")
        self.reg.schema_hub.register_seed_data(
            "users", row_count=42, sample_excerpt=_SAMPLE_USERS,
            agent="database_worker")
        got = self.reg.schema_hub.get_seed_data("users")
        self.assertIsNotNone(got)
        self.assertEqual(got["row_count"], 42)

    def test_get_seed_data_returns_none_for_unregistered(self) -> None:
        self.assertIsNone(self.reg.schema_hub.get_seed_data("nonexistent"))

    def test_list_seed_registrations_returns_all(self) -> None:
        for name in ("users", "posts", "comments"):
            self.reg.schema_hub.register_table(name, schema={"columns": []},
                                            provider="database", agent="database_worker")
            self.reg.schema_hub.register_seed_data(
                name, row_count=10, sample_excerpt=[{"id": 1}],
                agent="database_worker")
        regs = self.reg.schema_hub.list_seed_registrations()
        self.assertEqual(set(regs.keys()), {"users", "posts", "comments"})

    def test_register_updates_existing(self) -> None:
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database_worker")
        self.reg.schema_hub.register_seed_data(
            "users", row_count=5, sample_excerpt=[{"id": 1}], agent="database_worker")
        # Re-register with higher count
        self.reg.schema_hub.register_seed_data(
            "users", row_count=50, sample_excerpt=_SAMPLE_USERS, agent="database_worker")
        got = self.reg.schema_hub.get_seed_data("users")
        self.assertEqual(got["row_count"], 50)
        self.assertEqual(len(got["sample_excerpt"]), 3)

    def test_min_seed_rows_metadata_round_trips(self) -> None:
        # Database agent can declare a table needs more than the default 5 rows
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database_worker",
                                        min_seed_rows=20)
        table = self.reg.schema_hub.get_table("users")
        self.assertEqual((table.get("metadata") or {}).get("min_seed_rows"), 20)


if __name__ == "__main__":
    unittest.main()
