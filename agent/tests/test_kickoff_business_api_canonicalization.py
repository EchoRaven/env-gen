"""PROPOSAL #43: kickoff canonicalizes bare business endpoint paths to the framework
``/api`` convention, using the pre-registered fixed surface (kind-tagged) as the
control-plane oracle — NOT a hardcoded path blocklist.

Regression target: smoke-notes run (2026-06-19) where the kickoff LLM authored
``GET /notes`` / ``POST /notes`` (status=defined), the frontend called ``/api/notes``,
and the two never reconciled → ``/notes`` orphaned forever and
``business_endpoints_implemented`` could never pass.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (
    _canonicalize_business_endpoint_paths,
    _ensure_business_api_prefix,
    _control_plane_keys,
    _reconcile_dangling_frontend_calls,
)


# The fixed surface registered BEFORE synthesis (spine/auth/control, kind-tagged).
FIXED_SURFACE = [
    {"method": "POST", "path": "/auth/register"},
    {"method": "POST", "path": "/auth/login"},
    {"method": "GET", "path": "/oauth/authorize"},
    {"method": "GET", "path": "/health"},
    {"method": "GET", "path": "/api/v1/tenants"},
]


class EnsurePrefixTests(unittest.TestCase):
    def setUp(self):
        self.cp = _control_plane_keys(FIXED_SURFACE)

    def test_bare_business_path_gets_api_prefix(self):
        self.assertEqual(_ensure_business_api_prefix("GET", "/notes", self.cp), "/api/notes")
        self.assertEqual(_ensure_business_api_prefix("POST", "/notes", self.cp), "/api/notes")

    def test_already_api_path_unchanged_no_double_prefix(self):
        self.assertEqual(_ensure_business_api_prefix("GET", "/api/notes", self.cp), "/api/notes")
        self.assertEqual(_ensure_business_api_prefix("GET", "/api/v1/tenants", self.cp), "/api/v1/tenants")

    def test_control_plane_left_verbatim_via_registered_oracle(self):
        # matched against the fixed surface — owned elsewhere, NOT prefixed.
        self.assertEqual(_ensure_business_api_prefix("POST", "/auth/login", self.cp), "/auth/login")
        self.assertEqual(_ensure_business_api_prefix("GET", "/health", self.cp), "/health")
        self.assertEqual(_ensure_business_api_prefix("GET", "/oauth/authorize", self.cp), "/oauth/authorize")

    def test_business_resource_named_like_control_plane_is_NOT_falsely_exempt(self):
        # The reviewer's decisive case: a doc-management app's /docs, a fitness app's
        # /health/{id} — these are LLM-authored business endpoints (not in the fixed
        # surface) and MUST be prefixed. A path blocklist would wrongly exempt them.
        self.assertEqual(_ensure_business_api_prefix("GET", "/docs", self.cp), "/api/docs")
        self.assertEqual(_ensure_business_api_prefix("GET", "/health/{id}", self.cp), "/api/health/{id}")
        self.assertEqual(_ensure_business_api_prefix("GET", "/metrics", self.cp), "/api/metrics")

    def test_unparseable_left_alone(self):
        self.assertEqual(_ensure_business_api_prefix("GET", "relative/x", self.cp), "relative/x")
        self.assertEqual(_ensure_business_api_prefix("GET", "", self.cp), "")


class CanonicalizeDraftsTests(unittest.TestCase):
    def test_backend_draft_paths_rewritten(self):
        drafts = {"backend": {"endpoints": [
            {"method": "GET", "path": "/notes", "response_key": "items"},
            {"method": "POST", "path": "/notes", "response_key": "item"},
            {"method": "GET", "path": "/api/feed", "response_key": "items"},
        ]}}
        out = _canonicalize_business_endpoint_paths(drafts, FIXED_SURFACE)
        paths = [(e["method"], e["path"]) for e in out["backend"]["endpoints"]]
        self.assertIn(("GET", "/api/notes"), paths)
        self.assertIn(("POST", "/api/notes"), paths)
        self.assertIn(("GET", "/api/feed"), paths)  # already /api → unchanged
        # other draft fields preserved
        self.assertEqual(out["backend"]["endpoints"][0]["response_key"], "items")

    def test_api_endpoints_key_variant(self):
        drafts = {"backend": {"api_endpoints": [{"method": "GET", "path": "/widgets"}]}}
        out = _canonicalize_business_endpoint_paths(drafts, FIXED_SURFACE)
        self.assertEqual(out["backend"]["api_endpoints"][0]["path"], "/api/widgets")

    def test_idempotent_and_noop_returns_same_object(self):
        drafts = {"backend": {"endpoints": [{"method": "GET", "path": "/api/notes"}]}}
        out = _canonicalize_business_endpoint_paths(drafts, FIXED_SURFACE)
        self.assertIs(out, drafts)  # nothing moved → same object


class ReconcilerNoLongerDuplicatesTests(unittest.TestCase):
    """After canonicalization, the frontend's /api/notes call matches the canonical
    backend endpoint, so the reconciler must NOT auto-register a duplicate."""

    def test_no_duplicate_when_frontend_matches_canonical_backend(self):
        drafts = {
            "backend": {"endpoints": [{"method": "GET", "path": "/notes"}]},
            "frontend": {"screens": [
                {"api_calls": [{"method": "GET", "path": "/api/notes"}]}
            ]},
        }
        canon = _canonicalize_business_endpoint_paths(drafts, FIXED_SURFACE)
        _reconciled, added = _reconcile_dangling_frontend_calls(canon, registered_endpoints=FIXED_SURFACE)
        self.assertEqual(added, [], f"reconciler duplicated despite canonical match: {added}")

    def test_genuinely_new_frontend_business_call_added_under_api(self):
        drafts = {
            "backend": {"endpoints": [{"method": "GET", "path": "/notes"}]},
            "frontend": {"screens": [
                {"api_calls": [{"method": "GET", "path": "/widgets"}]}  # bare, not declared
            ]},
        }
        canon = _canonicalize_business_endpoint_paths(drafts, FIXED_SURFACE)
        _reconciled, added = _reconcile_dangling_frontend_calls(canon, registered_endpoints=FIXED_SURFACE)
        self.assertEqual(added, ["GET /api/widgets"], f"expected /api-prefixed add, got {added}")


if __name__ == "__main__":
    unittest.main()
