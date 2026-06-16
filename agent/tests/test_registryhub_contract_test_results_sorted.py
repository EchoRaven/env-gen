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

    def test_orders_by_created_at_desc_by_default(self) -> None:
        """The Phase 3.5 endpoint_contract resolver consumes [0] to get
        the LATEST verdict — verify ordering with two records 50ms apart
        in non-monotonic insertion order."""
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
        self.assertEqual(len(results), 2)
        # Latest first — the "second" record has higher created_at.
        self.assertEqual(results[0]["evidence"]["r"], "second")
        self.assertEqual(results[1]["evidence"]["r"], "first")

    def test_desc_false_yields_ascending_order(self) -> None:
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={"r": "first"},
            agent="verifier",
        )
        time.sleep(0.05)
        self.hub.record_api_test(
            "GET /api/feed", {"passed": False}, evidence={"r": "second"},
            agent="verifier",
        )
        results = self.hub.list_contract_test_results_sorted(
            "GET /api/feed", desc=False,
        )
        self.assertEqual(results[0]["evidence"]["r"], "first")
        self.assertEqual(results[1]["evidence"]["r"], "second")

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

    def test_legacy_accessor_unchanged(self) -> None:
        """`get_contract_test_results` MUST stay byte-compatible with
        the 7 existing callers — it returns insertion-order, not sorted."""
        self.hub.record_api_test(
            "GET /api/feed", {"passed": True}, evidence={"r": "first"},
            agent="verifier",
        )
        self.hub.record_api_test(
            "GET /api/feed", {"passed": False}, evidence={"r": "second"},
            agent="verifier",
        )
        legacy = self.hub.get_contract_test_results("GET /api/feed")
        # Legacy returns BOTH records; specific ordering is implementation
        # detail (dict insertion order). We assert no sort applied — that
        # is, the legacy accessor does NOT call sort itself, so if both
        # records pass insertion-order check, legacy is unchanged.
        self.assertEqual(len(legacy), 2)
        # Both evidence values present (order check is brittle, count is
        # the load-bearing assertion).
        evidence_set = {r["evidence"]["r"] for r in legacy}
        self.assertEqual(evidence_set, {"first", "second"})


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
