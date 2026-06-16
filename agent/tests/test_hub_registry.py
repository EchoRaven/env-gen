"""
Tests for multi_agent.runtime.hubs.HubRegistry — the CRDTWorkspace replacement.
"""

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


class TestHubRegistryBasic(unittest.TestCase):
    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))

    def test_store_dir_created(self):
        store_dir = Path(self._td) / "shared" / "hubs"
        self.assertTrue(store_dir.is_dir())

    def test_all_hubs_available(self):
        self.assertIsNotNone(self.hubs.registryhub)
        self.assertIsNotNone(self.hubs.codehub)
        self.assertIsNotNone(self.hubs.eventhub)
        self.assertIsNotNone(self.hubs.workhub)

    def test_get_versions_returns_dict(self):
        versions = self.hubs.get_versions()
        self.assertIsInstance(versions, dict)

    def test_snapshot_has_all_hubs(self):
        snap = self.hubs.snapshot()
        self.assertIn("codehub", snap)
        self.assertIn("workhub", snap)
        self.assertIn("registryhub", snap)
        self.assertIn("eventhub", snap)


class TestHubRegistryCodeHub(unittest.TestCase):
    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))

    def test_codehub_ensure_repo(self):
        self.hubs.codehub.ensure_repo()
        self.assertTrue((Path(self._td) / ".git").is_dir())

    def test_codehub_register_worktree(self):
        self.hubs.codehub.ensure_repo()
        wt = self.hubs.codehub.register_agent_worktree("backend")
        self.assertIsNotNone(wt)


class TestHubRegistryRegistryHub(unittest.TestCase):
    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))

    def test_register_and_get_endpoint(self):
        # agent="backend" admits past the Phase 2 ownership gate
        # (was "design" pre-gate; switched to the allowed lane to
        # preserve test intent — persistence + listing semantics —
        # at all phase thresholds).
        self.hubs.registryhub.register_endpoint(
            "GET", "/api/items",
            schema={"response": {"items": []}},
            provider="backend",
            agent="backend",
        )
        endpoints = self.hubs.registryhub.get_endpoints()
        self.assertIn("GET /api/items", endpoints)

    def test_register_and_list_table(self):
        # agent="backend" admits past the Phase 1 ownership gate
        # ({backend, database_worker}). Was "design" pre-gate.
        self.hubs.schema_hub.register_table(
            name="products",
            schema={"columns": [{"name": "id", "type": "UUID"}]},
            provider="database",
            agent="backend",
        )
        tables = self.hubs.schema_hub.list_tables()
        self.assertIn("products", tables)


class TestHubRegistryEventHub(unittest.TestCase):
    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))

    def test_record_and_get_agent_status(self):
        self.hubs.eventhub.record_agent_status("backend", {"status": "working", "step": 1})
        statuses = self.hubs.eventhub.get_all_agent_statuses()
        self.assertIn("backend", statuses)
        self.assertEqual(statuses["backend"]["status"], "working")


class TestHubRegistryWithMessageBus(unittest.TestCase):
    def test_message_bus_bridge_attached(self):
        from utils.communication import MessageBus
        from multi_agent.runtime.hub_registry import HubRegistry

        async def run():
            with tempfile.TemporaryDirectory() as td:
                bus = MessageBus()
                await bus.start()
                hubs = HubRegistry(Path(td), message_bus=bus)
                self.assertIsNotNone(hubs.bridge)
                await bus.stop()

        asyncio.get_event_loop().run_until_complete(run())


if __name__ == "__main__":
    unittest.main()
