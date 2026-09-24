"""PROPOSAL #50: register_endpoint enforces the canonical response envelope key
(item/items) for BUSINESS endpoints on EVERY registration — #46 only canonicalized at
kickoff, so a backend impl-time registration (e.g. /api/dummy_trigger response_key=
'triggered') bypassed it and hard-blocked delivery on business_response_key_noncanonical
(smoke-notes 2026-06-19: the FINAL check before the first create_release). LOCAL-ONLY."""
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


class CanonicalResponseKeyAtRegistryTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.rh = RegistryHub(Path(self._d.name))

    def tearDown(self):
        self._d.cleanup()

    def _rk(self, method, path):
        e = self.rh._endpoints.get(self.rh.endpoint_id(method, path))
        return (e.get("metadata") or {}).get("response_key")

    def _schema_rk(self, method, path):
        e = self.rh._endpoints.get(self.rh.endpoint_id(method, path))
        return (e.get("schema") or {}).get("response_key")

    def test_business_noncanonical_collection_get_becomes_items(self):
        self.rh.register_endpoint("GET", "/api/dummy_trigger", provider="backend",
                                  agent="backend", status="implemented", response_key="triggered")
        self.assertEqual(self._rk("GET", "/api/dummy_trigger"), "items")

    def test_business_noncanonical_param_get_becomes_item(self):
        self.rh.register_endpoint("GET", "/api/notes/{id}", provider="backend",
                                  agent="backend", status="implemented", response_key="notes")
        self.assertEqual(self._rk("GET", "/api/notes/{id}"), "item")

    def test_control_plane_kind_preserves_declared_key(self):
        # kind-exempt (gate exempts it) → clobbering would cause false contract-drift.
        self.rh.register_endpoint("POST", "/api/v1/tenants", provider="backend",
                                  agent="backend", status="defined", response_key="tenant", kind="infra")
        self.assertEqual(self._rk("POST", "/api/v1/tenants"), "tenant")

    def test_already_canonical_unchanged(self):
        self.rh.register_endpoint("GET", "/api/feed", provider="backend",
                                  agent="backend", status="defined", response_key="items")
        self.assertEqual(self._rk("GET", "/api/feed"), "items")

    def test_absent_key_stays_absent(self):
        # the gate EXEMPTS an absent response_key, so don't force one.
        self.rh.register_endpoint("GET", "/api/widgets", provider="backend",
                                  agent="backend", status="defined")
        self.assertIsNone(self._rk("GET", "/api/widgets"))

    def test_non_api_path_left_alone(self):
        self.rh.register_endpoint("POST", "/auth/login", provider="backend",
                                  agent="backend", status="defined", response_key="access_token")
        self.assertEqual(self._rk("POST", "/auth/login"), "access_token")

    def test_schema_only_noncanonical_key_canonicalized(self):
        # youtube run #18: GET /api/v1/health registered with schema.response_key=
        # 'status' and NO metadata key → the metadata-only rewrite missed it but the
        # gate (reads metadata OR schema) hard-blocked delivery. Now the EFFECTIVE
        # key is canonicalized in BOTH places.
        self.rh.register_endpoint("GET", "/api/v1/health", provider="backend",
                                  agent="backend", status="implemented",
                                  schema={"response_key": "status"})
        self.assertEqual(self._rk("GET", "/api/v1/health"), "items")
        self.assertEqual(self._schema_rk("GET", "/api/v1/health"), "items")

    def test_schema_only_param_get_becomes_item(self):
        self.rh.register_endpoint("GET", "/api/orders/{id}", provider="backend",
                                  agent="backend", status="implemented",
                                  schema={"response_key": "order"})
        self.assertEqual(self._rk("GET", "/api/orders/{id}"), "item")
        self.assertEqual(self._schema_rk("GET", "/api/orders/{id}"), "item")

    def test_canonical_metadata_leaves_schema_untouched(self):
        # metadata already canonical (gate reads it first + passes) → don't touch
        # schema (mirrors today's DELETE-action behavior, no needless churn).
        self.rh.register_endpoint("DELETE", "/api/videos/{id}", provider="backend",
                                  agent="backend", status="implemented",
                                  response_key="item", schema={"response_key": "message"})
        self.assertEqual(self._rk("DELETE", "/api/videos/{id}"), "item")
        self.assertEqual(self._schema_rk("DELETE", "/api/videos/{id}"), "message")


if __name__ == "__main__":
    unittest.main()
