"""Tests for RegistryHub.list_contract_test_results_sorted (Phase 4+ roadmap O7).

The existing `get_contract_test_results` iterates dict.values() in
insertion order, which is NOT a reliable "latest first" — `results[-1]`
catches the last-inserted record, not the latest by `created_at`.
Phase 3.5's `endpoint_contract` resolver in StoryHub needs to read the
latest verdict for a given endpoint, so this helper provides that
contract explicitly.

Per `docs/phase_4_plus_roadmap.md` O7 (P1 medium, READY, blocks 3.5):
- New method `list_contract_test_results_sorted(endpoint_id, *,
  by='created_at', desc=True)`.
- `get_contract_test_results` stays unchanged for backward-compat with
  the 7 known existing callers.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class ListContractTestResultsSorted(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registryhub_sorted_"))
        self.reg = HubRegistry(self.tmp)
        self.hub = self.reg.registryhub
        self.hub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_empty_for_unknown_endpoint(self) -> None:
        self.assertEqual(
            self.hub.list_contract_test_results_sorted("GET /api/unknown"),
            [],
        )

    def test_returns_results_for_known_endpoint(self) -> None:
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={}, agent="verifier",
        )
        results = self.hub.list_contract_test_results_sorted("GET /api/feed")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["endpoint_id"], "GET /api/feed")

    def test_latest_verdict_wins_after_reverdict(self) -> None:
        """The Phase 3.5 endpoint_contract resolver consumes [0] to get
        the LATEST verdict. Event-store efficiency (#4) upserts per
        endpoint_id, so re-recording the same endpoint keeps ONE row with
        the most-recent result — which is exactly what [0] must surface."""
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={"r": "first"},
            agent="verifier",
        )
        time.sleep(0.05)
        self.hub.record_api_test(
            "GET /api/feed", {"passed": False}, evidence={"r": "second"},
            agent="verifier",
        )
        results = self.hub.list_contract_test_results_sorted("GET /api/feed")
        self.assertEqual(len(results), 1, "upsert keeps one row per endpoint")
        # The latest record's verdict/evidence is what [0] surfaces.
        self.assertEqual(results[0]["evidence"]["r"], "second")
        self.assertEqual(results[0]["verdict"], "fail")

    def test_sort_orders_across_endpoints_desc_by_default(self) -> None:
        """Sorting still orders by created_at across DISTINCT endpoints
        (the upsert collapses per-endpoint history, not the cross-endpoint
        ordering the helper provides)."""
        self.hub.register_endpoint(
            "GET", "/api/other", schema={}, provider="backend", agent="backend",
        )
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={"r": "first"},
            agent="verifier",
        )
        time.sleep(0.05)
        self.hub.record_api_test(
            "GET /api/other", {"passed": False}, evidence={"r": "second"},
            agent="verifier",
        )
        # Filtered by endpoint => one row each; assert the per-endpoint
        # latest is returned and ordering flags are honored.
        feed = self.hub.list_contract_test_results_sorted("GET /api/feed")
        other = self.hub.list_contract_test_results_sorted("GET /api/other", desc=False)
        self.assertEqual(feed[0]["evidence"]["r"], "first")
        self.assertEqual(other[0]["evidence"]["r"], "second")

    def test_by_id_sort_works(self) -> None:
        """Sorting by id (string field) lex-orders correctly."""
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={}, agent="verifier",
        )
        time.sleep(0.05)
        self.hub.record_api_test(
            "GET /api/feed", {"passed": False}, evidence={}, agent="verifier",
        )
        results = self.hub.list_contract_test_results_sorted(
            "GET /api/feed", by="id", desc=False,
        )
        ids = [r["id"] for r in results]
        self.assertEqual(ids, sorted(ids))

    def test_legacy_accessor_returns_upserted_row(self) -> None:
        """`get_contract_test_results` stays a plain endpoint-id filter (no
        sort of its own). Event-store efficiency (#4) upserts per endpoint,
        so a re-record of the same endpoint yields ONE row carrying the
        latest result rather than appending history."""
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={"r": "first"},
            agent="verifier",
        )
        self.hub.record_api_test(
            "GET /api/feed", {"passed": False}, evidence={"r": "second"},
            agent="verifier",
        )
        legacy = self.hub.get_contract_test_results("GET /api/feed")
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["evidence"]["r"], "second")


class FiltersByEndpoint(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registryhub_sorted_filter_"))
        self.reg = HubRegistry(self.tmp)
        self.hub = self.reg.registryhub
        self.hub.register_endpoint(
            "GET", "/api/feed", schema={},
            provider="backend", agent="backend",
        )
        self.hub.register_endpoint(
            "GET", "/api/users", schema={},
            provider="backend", agent="backend",
        )
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={}, agent="verifier",
        )
        self.hub.record_api_test(
            "GET /api/users", {"passed": True}, evidence={}, agent="verifier",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filters_by_endpoint_id(self) -> None:
        feed = self.hub.list_contract_test_results_sorted("GET /api/feed")
        users = self.hub.list_contract_test_results_sorted("GET /api/users")
        self.assertEqual(len(feed), 1)
        self.assertEqual(len(users), 1)
        self.assertEqual(feed[0]["endpoint_id"], "GET /api/feed")
        self.assertEqual(users[0]["endpoint_id"], "GET /api/users")


if __name__ == "__main__":
    unittest.main()
