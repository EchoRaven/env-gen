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
from multi_agent.runtime.registryhub import _schema_subset_check  # noqa: E402  # ``_schema_subset_check`` stays available on RegistryHub; SchemaHub has its own copy for table consumer validation.


class SchemaSubsetCheckTests(unittest.TestCase):
    def test_expected_subset_of_actual_returns_none(self):
        actual = {"id": "int", "name": "string", "extra": "string"}
        expected = {"id": "int", "name": "string"}
        self.assertIsNone(_schema_subset_check(expected, actual))

    def test_missing_field_reports_missing(self):
        actual = {"id": "int"}
        expected = {"id": "int", "name": "string"}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertIn("name", result["missing"])
        self.assertEqual(result["type_mismatches"], [])

    def test_type_mismatch_reports_it(self):
        actual = {"id": "string"}
        expected = {"id": "int"}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertEqual(result["missing"], [])
        self.assertIn("id", result["type_mismatches"])

    def test_empty_expected_always_subset(self):
        self.assertIsNone(_schema_subset_check({}, {"id": "int"}))
        self.assertIsNone(_schema_subset_check({}, {}))

    def test_nested_dict_recursive_check(self):
        actual = {"response": {"data": {"id": "int", "name": "string"}}}
        expected = {"response": {"data": {"id": "int"}}}
        self.assertIsNone(_schema_subset_check(expected, actual))

    def test_nested_dict_missing_reports_dotted_path(self):
        actual = {"response": {"data": {"id": "int"}}}
        expected = {"response": {"data": {"id": "int", "name": "string"}}}
        result = _schema_subset_check(expected, actual)
        self.assertIsNotNone(result)
        self.assertIn("response.data.name", result["missing"])


class RegisterConsumerWriteTimeGateTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).registryhub

    def test_register_consumer_unknown_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_consumer(
                "GET /api/nope", "src/Feed.jsx", "frontend", metadata={})
            self.assertEqual(result.get("error"), "endpoint_not_registered")

    def test_register_consumer_deprecated_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/old", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("GET", "/api/new", schema={}, provider="backend", agent="backend")
            hub.deprecate_endpoint("GET /api/old", replacement_id="GET /api/new", agent="backend")
            result = hub.register_consumer("GET /api/old", "src/Feed.jsx", "frontend")
            self.assertEqual(result.get("error"), "endpoint_deprecated")
            self.assertEqual(result.get("replacement_id"), "GET /api/new")

    def test_register_consumer_expected_schema_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend",
            )
            # Frontend expects a field the endpoint doesn't have
            result = hub.register_consumer(
                "GET /api/feed", "src/Feed.jsx", "frontend",
                metadata={"expected_schema": {"response": {"posts": [], "missing_field": 0}}},
            )
            self.assertEqual(result.get("error"), "schema_mismatch")
            self.assertIn("response.missing_field", result.get("missing_fields", []))

    def test_register_consumer_expected_schema_match_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend",
            )
            # Frontend expects subset of what endpoint provides
            result = hub.register_consumer(
                "GET /api/feed", "src/Feed.jsx", "frontend",
                metadata={"expected_schema": {"response": {"posts": []}}},
            )
            self.assertNotIn("error", result)
            self.assertEqual(result["file_path"], "src/Feed.jsx")

    def test_register_consumer_no_expected_schema_still_works(self):
        # Backward compat: existing callers don't pass expected_schema
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            result = hub.register_consumer("GET /api/feed", "src/Feed.jsx", "frontend")
            self.assertNotIn("error", result)


class RegisterTableConsumerWriteTimeGateTests(unittest.TestCase):
    # PR 5: ``register_table_consumer`` retired from RegistryHub to SchemaHub.
    def _hub(self, td):
        return HubRegistry(Path(td)).schema_hub

    def test_register_table_consumer_unknown_table_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.register_table_consumer(
                "missing_table", "src/users.py", "backend")
            self.assertIn("error", result)

    def test_register_table_consumer_expected_columns_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users",
                               schema={"id": "int", "email": "string"},
                               provider="database", agent="backend")
            result = hub.register_table_consumer(
                "users", "src/users.py", "backend",
                metadata={"expected_columns": {"id": "int", "phone": "string"}},
            )
            self.assertEqual(result.get("error"), "schema_mismatch")
            self.assertIn("phone", result.get("missing_fields", []))

    def test_register_table_consumer_expected_columns_match_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_table(name="users",
                               schema={"id": "int", "email": "string"},
                               provider="database", agent="backend")
            result = hub.register_table_consumer(
                "users", "src/users.py", "backend",
                metadata={"expected_columns": {"id": "int"}},
            )
            self.assertNotIn("error", result)
            self.assertEqual(result["table_name"], "users")


if __name__ == "__main__":
    unittest.main()
