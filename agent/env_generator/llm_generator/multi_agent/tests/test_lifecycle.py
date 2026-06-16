"""Phase B1 — artifact lifecycle vocabulary + state queries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.lifecycle import (  # noqa: E402
    is_valid_transition, is_business, endpoint_kind,
    business_endpoints, endpoints_by_state, all_business_endpoints_implemented,
)


def _ep(method, path, status="defined", kind=None):
    rec = {"id": f"{method} {path}", "method": method, "path": path, "status": status}
    if kind:
        rec["metadata"] = {"kind": kind}
    return rec


class TransitionTests(unittest.TestCase):
    def test_endpoint_happy_path(self):
        self.assertTrue(is_valid_transition("endpoint", "defined", "implementing"))
        self.assertTrue(is_valid_transition("endpoint", "implementing", "implemented"))
        self.assertTrue(is_valid_transition("endpoint", "implemented", "revising"))
        self.assertTrue(is_valid_transition("endpoint", "revising", "implemented"))

    def test_illegal_transitions_rejected(self):
        self.assertFalse(is_valid_transition("endpoint", "defined", "revising"))      # skip impl
        self.assertFalse(is_valid_transition("endpoint", "implemented", "defined"))   # no regress
        self.assertFalse(is_valid_transition("endpoint", "deprecated", "implemented"))

    def test_idempotent_reassert_allowed(self):
        self.assertTrue(is_valid_transition("endpoint", "implemented", "implemented"))

    def test_predicate_lifecycle(self):
        self.assertTrue(is_valid_transition("predicate", "defined", "covered"))
        self.assertTrue(is_valid_transition("predicate", "covered", "passing"))
        self.assertTrue(is_valid_transition("predicate", "passing", "failing"))
        self.assertFalse(is_valid_transition("predicate", "defined", "passing"))  # must be covered first

    def test_unknown_artifact_is_false(self):
        self.assertFalse(is_valid_transition("widget", "a", "b"))


class KindTests(unittest.TestCase):
    def test_business_vs_fixed(self):
        self.assertTrue(is_business(_ep("GET", "/api/notes")))
        self.assertFalse(is_business(_ep("POST", "/auth/login", kind="auth")))
        self.assertFalse(is_business(_ep("GET", "/health", kind="infra")))
        self.assertEqual(endpoint_kind(_ep("GET", "/health", kind="infra")), "infra")

    def test_top_level_kind_also_read(self):
        self.assertFalse(is_business({"method": "GET", "path": "/x", "kind": "spine"}))


class QueryTests(unittest.TestCase):
    def _contract(self):
        return {
            "GET /api/notes": _ep("GET", "/api/notes", "implemented"),
            "POST /api/notes": _ep("POST", "/api/notes", "implementing"),
            "POST /auth/login": _ep("POST", "/auth/login", "implemented", kind="auth"),
            "GET /health": _ep("GET", "/health", "implemented", kind="infra"),
        }

    def test_business_endpoints_excludes_fixed_and_deprecated(self):
        eps = self._contract()
        eps["GET /api/old"] = _ep("GET", "/api/old", "deprecated")
        biz = {e["path"] for e in business_endpoints(eps)}
        self.assertEqual(biz, {"/api/notes", "/api/notes"})  # set dedups path; both business
        self.assertNotIn("/auth/login", biz)
        self.assertNotIn("/health", biz)
        self.assertNotIn("/api/old", biz)

    def test_endpoints_by_state(self):
        by = endpoints_by_state(self._contract())
        self.assertEqual(len(by["implemented"]), 3)   # notes(GET) + auth + health
        self.assertEqual(len(by["implementing"]), 1)  # notes(POST)

    def test_all_business_implemented_false_when_one_implementing(self):
        # POST /api/notes is still implementing → not complete
        self.assertFalse(all_business_endpoints_implemented(self._contract()))

    def test_all_business_implemented_true_when_all_business_done(self):
        eps = self._contract()
        eps["POST /api/notes"]["status"] = "implemented"
        self.assertTrue(all_business_endpoints_implemented(eps))

    def test_all_business_implemented_ignores_fixed_surface_state(self):
        # Even if a fixed endpoint were somehow not 'implemented', business
        # completeness ignores it (it's not business).
        eps = self._contract()
        eps["POST /api/notes"]["status"] = "implemented"
        eps["POST /auth/login"]["status"] = "defined"   # fixed, not business
        self.assertTrue(all_business_endpoints_implemented(eps))

    def test_empty_business_contract_is_not_complete(self):
        self.assertFalse(all_business_endpoints_implemented({}))
        self.assertFalse(all_business_endpoints_implemented(
            {"GET /health": _ep("GET", "/health", "implemented", kind="infra")}))


if __name__ == "__main__":
    unittest.main()
