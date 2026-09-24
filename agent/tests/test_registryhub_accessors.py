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


class RegistryHubAccessorsTests(unittest.TestCase):
    def _hub(self, td):
        return HubRegistry(Path(td)).registryhub

    def test_get_consumers_filters_by_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("GET", "/api/users", schema={}, provider="backend", agent="backend")
            hub.register_consumer("GET /api/feed", "app/frontend/Feed.jsx", "frontend")
            hub.register_consumer("GET /api/feed", "app/frontend/FeedDetail.jsx", "frontend")
            hub.register_consumer("GET /api/users", "app/frontend/Users.jsx", "frontend")

            feed_consumers = hub.get_consumers("GET /api/feed")
            self.assertEqual(len(feed_consumers), 2)
            self.assertEqual({c["file_path"] for c in feed_consumers},
                             {"app/frontend/Feed.jsx", "app/frontend/FeedDetail.jsx"})

    def test_get_consumers_empty_for_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertEqual(hub.get_consumers("GET /api/nope"), [])


    def test_get_dependencies_for_file_lists_endpoints_for_file(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("POST", "/api/posts", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("GET", "/api/users", schema={}, provider="backend", agent="backend")
            hub.register_consumer("GET /api/feed", "app/frontend/Feed.jsx", "frontend")
            hub.register_consumer("POST /api/posts", "app/frontend/Feed.jsx", "frontend")
            hub.register_consumer("GET /api/users", "app/frontend/Users.jsx", "frontend")

            deps = hub.get_dependencies_for_file("app/frontend/Feed.jsx")
            self.assertEqual({d["endpoint_id"] for d in deps},
                             {"GET /api/feed", "POST /api/posts"})

    def test_get_dependencies_for_file_empty_for_unknown_file(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertEqual(hub.get_dependencies_for_file("nope.jsx"), [])


    def test_get_breaking_changes_returns_recorded_changes_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed",
                                  schema={"response": {"posts": [], "total": 0}},
                                  provider="backend", agent="backend")
            # First breaking change (removes posts and total)
            hub.update_schema("GET /api/feed", response={"items": []}, agent="backend")
            # Second breaking change (type change on items)
            hub.update_schema("GET /api/feed", response={"items": [{"id": "int"}]}, agent="backend")
            # Non-breaking endpoint
            hub.register_endpoint("GET", "/api/users", schema={}, provider="backend", agent="backend")

            changes = hub.get_breaking_changes()
            self.assertGreaterEqual(len(changes), 1)
            timestamps = [c.get("created_at", 0) for c in changes]
            self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_get_breaking_changes_since_ts_filters_out_old(self):
        with tempfile.TemporaryDirectory() as td:
            import time
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed",
                                  schema={"response": {"posts": []}},
                                  provider="backend", agent="backend")
            hub.update_schema("GET /api/feed", response={"items": []}, agent="backend")
            cutoff = time.time() + 1.0
            changes = hub.get_breaking_changes(since_ts=cutoff)
            self.assertEqual(changes, [])


    def test_get_contract_test_results_filters_by_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            hub.register_endpoint("GET", "/api/users", schema={}, provider="backend", agent="backend")
            hub.record_api_test("GET /api/feed", {"passed": True}, evidence={"trace": "ok1"}, agent="verifier")
            # Event-store efficiency (#4): re-recording the SAME endpoint
            # upserts by endpoint_id (no longer appends a new row per call),
            # so the latest result wins and there is exactly ONE feed row.
            hub.record_api_test("GET /api/feed", {"passed": False}, evidence={"trace": "fail"}, agent="verifier")
            hub.record_api_test("GET /api/users", {"passed": True}, evidence={"trace": "ok2"}, agent="verifier")

            feed_tests = hub.get_contract_test_results("GET /api/feed")
            self.assertEqual(len(feed_tests), 1)
            self.assertEqual({t["endpoint_id"] for t in feed_tests}, {"GET /api/feed"})
            # Latest verdict wins (the upsert kept the most recent result).
            self.assertEqual(feed_tests[0]["verdict"], "fail")

    def test_get_contract_test_results_empty_for_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            self.assertEqual(hub.get_contract_test_results("GET /api/nope"), [])


    def test_submit_api_review_transitions_pending_to_approved(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            review = hub.request_api_review("GET /api/feed", reviewers=["frontend"],
                                            agent="backend", reason="schema confirmation")
            review_id = review["id"]
            submitted = hub.submit_api_review(review_id, reviewer="frontend",
                                              decision="approve", comments=["LGTM"])
            self.assertEqual(submitted["status"], "approve")
            stored = hub.snapshot()["api_reviews"][review_id]
            self.assertEqual(stored["status"], "approve")
            self.assertIn("frontend", stored["reviewed_by"])

    def test_submit_api_review_rejects_unknown_review_id(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            result = hub.submit_api_review("bogus_id", reviewer="frontend",
                                            decision="approve", comments=[])
            self.assertIn("error", result)

    def test_submit_api_review_request_changes_stays_open(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._hub(td)
            hub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            review = hub.request_api_review("GET /api/feed", reviewers=["frontend"], agent="backend")
            result = hub.submit_api_review(review["id"], reviewer="frontend",
                                            decision="request_changes",
                                            comments=["Please add pagination"])
            self.assertEqual(result["status"], "request_changes")
            self.assertEqual(result.get("comments"), ["Please add pagination"])


if __name__ == "__main__":
    unittest.main()
