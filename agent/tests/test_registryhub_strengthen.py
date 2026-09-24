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


class RegistryHubStrengthenTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).registryhub

    def test_update_schema_merges_request_and_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint(
                "POST", "/api/posts",
                schema={"request": {"title": "string"}, "response": {"id": "int"}},
                provider="backend", agent="backend",
            )
            updated = hub.update_schema(
                "POST /api/posts",
                response={"id": "int", "created_at": "string"},
                agent="backend",
            )
            self.assertEqual(updated["schema"]["request"], {"title": "string"})
            self.assertEqual(updated["schema"]["response"], {"id": "int", "created_at": "string"})

    def test_update_schema_returns_error_for_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.update_schema("GET /api/nope", request={"q": "string"}, agent="backend")
            self.assertIn("error", result)

    def test_add_mock_stores_mock_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            mock = hub.add_mock(
                "GET /api/feed",
                {"posts": [{"id": 1, "title": "hello"}], "total": 1},
                agent="backend",
            )
            self.assertEqual(mock["endpoint_id"], "GET /api/feed")
            stored = hub.snapshot()["mocks"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(list(stored.values())[0]["response"]["total"], 1)

    def test_add_example_stores_request_and_response_pair(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("POST", "/api/posts", schema={}, provider="backend", agent="backend")
            example = hub.add_example(
                "POST /api/posts",
                request_example={"title": "hello"},
                response_example={"id": 42, "title": "hello"},
                agent="backend",
            )
            self.assertEqual(example["request"], {"title": "hello"})
            self.assertEqual(example["response"], {"id": 42, "title": "hello"})

    def test_deprecate_endpoint_marks_status_and_records_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/posts/v1", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("GET", "/api/posts/v2", schema={}, provider="backend", agent="backend")
            result = hub.deprecate_endpoint(
                "GET /api/posts/v1",
                replacement_id="GET /api/posts/v2",
                agent="backend",
            )
            self.assertEqual(result["status"], "deprecated")
            self.assertEqual(result["replacement_id"], "GET /api/posts/v2")
            # status persisted in main endpoints store
            current = hub.get_endpoints()["GET /api/posts/v1"]
            self.assertEqual(current["status"], "deprecated")
            self.assertEqual(current.get("replacement_id"), "GET /api/posts/v2")


    def test_breaking_change_detects_type_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response": {"id": "int", "name": "string"}}
            new = {"response": {"id": "string", "name": "string"}}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("id", result.get("type_changed_fields", []))

    def test_breaking_change_detects_required_added_in_request(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"request": {"title": "string"}}
            new = {"request": {"title": "string", "author_id": "int (required)"}}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertIn("author_id", result.get("required_added_in_request", []))

    def test_breaking_change_detects_path_method_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"method": "GET", "path": "/api/feed"}
            new = {"method": "POST", "path": "/api/feed"}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("method_changed"))

    def test_breaking_change_detects_response_key_change(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response_key": "posts"}
            new = {"response_key": "items"}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("response_key_changed"))

    def test_breaking_change_detects_auth_added(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"auth_required": False}
            new = {"auth_required": True}
            result = hub.detect_breaking_change(old, new)
            self.assertTrue(result["is_breaking"])
            self.assertTrue(result.get("auth_added"))

    def test_breaking_change_returns_not_breaking_for_additive_response(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            old = {"response": {"id": "int"}}
            new = {"response": {"id": "int", "created_at": "string"}}
            result = hub.detect_breaking_change(old, new)
            self.assertFalse(result["is_breaking"])


if __name__ == "__main__":
    unittest.main()
