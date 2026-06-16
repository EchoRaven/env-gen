"""Tests for CRDT deep binding — updated for Cutover 4.

sync_file_change / crdt_projection removed; agents now register directly via
registryhub.register_endpoint and registryhub.register_table.  These tests verify the
equivalent hub-level semantics.
"""
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


class CRDTDeepBindingTests(unittest.TestCase):
    def test_register_endpoint_visible_in_registryhub(self):
        """Agents register endpoints directly; they appear in registryhub."""
        with tempfile.TemporaryDirectory() as td:
            crdt = HubRegistry(Path(td))
            crdt.hubs.registryhub.register_endpoint(
                "GET", "/api/feed", schema={"response": {"posts": []}},
                provider="backend", agent="backend", status="defined"
            )
            endpoints = crdt.hubs.registryhub.get_endpoints()
            self.assertIn("GET /api/feed", endpoints)
            self.assertEqual(endpoints["GET /api/feed"]["status"], "defined")

    def test_register_table_visible_via_get_tables(self):
        """Agents register tables; they appear via get_tables (reads from RegistryHub)."""
        with tempfile.TemporaryDirectory() as td:
            crdt = HubRegistry(Path(td))
            crdt.hubs.schema_hub.register_table(
                "posts",
                schema={"columns": [{"name": "id", "type": "UUID"}, {"name": "body", "type": "TEXT"}]},
                provider="backend",
                agent="backend",
            )
            tables = crdt.get_tables()
            self.assertIn("posts", tables)
            cols = tables["posts"].get("columns") or tables["posts"].get("schema", {}).get("columns", [])
            self.assertEqual(len(cols), 2)

    def test_update_status_preserves_implemented(self):
        """An endpoint registered as implemented keeps that status when updated."""
        with tempfile.TemporaryDirectory() as td:
            crdt = HubRegistry(Path(td))
            crdt.hubs.registryhub.register_endpoint(
                "GET", "/api/feed", schema={}, provider="backend", agent="backend", status="implemented"
            )
            # A subsequent schema update should not downgrade status to 'defined'
            crdt.hubs.registryhub.update_schema(
                "GET /api/feed", response={"items": []}, agent="backend"
            )
            ep = crdt.hubs.registryhub.get_endpoints().get("GET /api/feed", {})
            self.assertEqual(ep.get("status"), "implemented")

    def test_deprecated_endpoint_via_hub(self):
        """Endpoints can be deprecated via hub directly."""
        with tempfile.TemporaryDirectory() as td:
            crdt = HubRegistry(Path(td))
            crdt.hubs.registryhub.register_endpoint(
                "POST", "/api/posts", schema={}, provider="backend", agent="backend", status="defined"
            )
            crdt.hubs.registryhub.register_endpoint(
                "POST", "/api/posts", schema={}, provider="backend", agent="backend", status="deprecated"
            )
            ep = crdt.hubs.registryhub.get_endpoints().get("POST /api/posts", {})
            self.assertEqual(ep.get("status"), "deprecated")


if __name__ == "__main__":
    unittest.main()
