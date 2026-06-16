"""Tests for bug_triage owning-agent resolution helpers (Cutover 10)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.bug_triage import (  # noqa: E402
    find_owning_agent_for_endpoint,
    find_owning_agent_for_table,
    find_owning_agent_for_file,
    resolve_owning_agent,
)


class OwningAgentResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="bt_resolver_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_endpoint_resolves_to_registered_provider(self) -> None:
        self.reg.registryhub.register_endpoint("POST", "/api/feed",
                                          schema={}, provider="backend", agent="backend")
        self.assertEqual(
            find_owning_agent_for_endpoint(self.reg, "POST", "/api/feed"),
            "backend",
        )

    def test_endpoint_unknown_returns_none(self) -> None:
        self.assertIsNone(find_owning_agent_for_endpoint(self.reg, "POST", "/missing"))

    def test_table_resolves_to_registered_provider(self) -> None:
        self.reg.schema_hub.register_table("users", schema={"columns": []},
                                       provider="database", agent="database_worker")
        self.assertEqual(find_owning_agent_for_table(self.reg, "users"), "database")

    def test_file_path_under_backend_dir_resolves_to_backend(self) -> None:
        self.assertEqual(find_owning_agent_for_file("backend/routes/feed.py"), "backend")

    def test_file_path_under_frontend_dir_resolves_to_frontend(self) -> None:
        self.assertEqual(find_owning_agent_for_file("frontend/components/Feed.tsx"), "frontend")

    def test_file_path_under_database_or_migrations_resolves_to_database(self) -> None:
        self.assertEqual(find_owning_agent_for_file("database/migrations/001.sql"), "database")
        self.assertEqual(find_owning_agent_for_file("migrations/002_add_users.sql"), "database")

    def test_file_path_unknown_returns_none(self) -> None:
        self.assertIsNone(find_owning_agent_for_file("README.md"))

    def test_resolve_owning_agent_prefers_endpoint_over_file(self) -> None:
        self.reg.registryhub.register_endpoint("GET", "/api/x", schema={},
                                          provider="backend", agent="backend")
        artifacts = {
            "affected_endpoint": "GET /api/x",
            "affected_files": ["frontend/foo.tsx"],
        }
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "backend")

    def test_resolve_owning_agent_falls_back_to_file_when_endpoint_unknown(self) -> None:
        artifacts = {"affected_files": ["frontend/components/X.tsx"]}
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "frontend")

    def test_resolve_owning_agent_table_path(self) -> None:
        self.reg.schema_hub.register_table("orders", schema={"columns": []},
                                       provider="database", agent="database_worker")
        artifacts = {"affected_table": "orders"}
        self.assertEqual(resolve_owning_agent(self.reg, artifacts), "database")

    def test_resolve_owning_agent_returns_none_when_nothing_matches(self) -> None:
        artifacts = {"affected_files": ["README.md"]}
        self.assertIsNone(resolve_owning_agent(self.reg, artifacts))


if __name__ == "__main__":
    unittest.main()
