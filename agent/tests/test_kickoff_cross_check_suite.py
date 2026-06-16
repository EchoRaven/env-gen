"""Regression tests for runtime.kickoff.cross_check_suite.

Closed-by-construction: every test pins exactly one invariant the
module promises in its docstring. No exhaustive matrix — one happy
path + one obvious failure + one empty edge per check, plus the
dispatcher's no-raise discipline.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.kickoff.cross_check_suite import (  # noqa: E402
    api_vs_data_model,
    api_vs_frontend,
    run_cross_checks,
    test_strategy_coverage,
    # Round 8e.1: ui_pages_vs_user_flows removed (design merged into
    # frontend; both fields intra-section now).
)
from multi_agent.runtime.kickoff.contract import (  # noqa: E402
    REQUIRED_ENDPOINT_KEYS,
    endpoint_id,
    validate_kickoff_endpoint,
)


class ApiVsFrontendTests(unittest.TestCase):
    def test_endpoint_and_screen_aligned_passes(self):
        api = [{"method": "GET", "path": "/api/posts"}]
        screens = [{"id": "feed", "api_calls": [{"method": "get", "path": "/api/posts"}]}]
        out = api_vs_frontend(api, screens)
        self.assertEqual(out["status"], "pass")
        self.assertEqual(out["severity"], "info")

    def test_ui_call_to_undefined_endpoint_fails(self):
        api = [{"method": "GET", "path": "/api/posts"}]
        screens = [{"id": "feed", "api_calls": [{"method": "POST", "path": "/api/comments"}]}]
        out = api_vs_frontend(api, screens)
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["severity"], "error")
        self.assertIn("api_calls", out["offending_field"])
        self.assertIn("POST /api/comments", out["detail"])

    def test_dead_endpoint_fails(self):
        # Default severity is now "info" (MCP-tool endpoints have no UI
        # consumer by design); the error path remains available explicitly.
        api = [{"method": "GET", "path": "/api/posts"}]
        screens = [{"id": "feed", "api_calls": []}]
        out = api_vs_frontend(api, screens, dead_endpoint_severity="error")
        self.assertEqual(out["status"], "fail")
        self.assertIn("no UI consumer", out["detail"])
        # new default: pass (unconsumed endpoint is not kickoff-fatal)
        self.assertEqual(api_vs_frontend(api, screens)["status"], "pass")

    def test_frontend_call_to_registered_fixed_surface_resolves(self):
        # §4 D4.2: a login screen calls POST /auth/login. The backend section is
        # business-only (doesn't define it), but /auth/login is REGISTERED
        # (kind=auth) before the meeting → the call resolves, no "undefined".
        api = [{"method": "GET", "path": "/api/notes"}]
        screens = [
            {"id": "login", "api_calls": [{"method": "POST", "path": "/auth/login"}]},
            {"id": "notes", "api_calls": [{"method": "get", "path": "/api/notes"}]},
        ]
        registered = [
            {"method": "POST", "path": "/auth/login", "metadata": {"kind": "auth"}},
            {"method": "GET", "path": "/health", "metadata": {"kind": "infra"}},
        ]
        out = api_vs_frontend(api, screens, registered)
        self.assertEqual(out["status"], "pass", out.get("detail"))

    def test_section_declared_fixed_surface_exempt_by_registered_kind(self):
        # A lane slips GET /health into its section. It's registered kind=infra,
        # so it is exempt from "needs a UI consumer" BY KIND — not by a path list.
        api = [{"method": "GET", "path": "/api/notes"}, {"method": "GET", "path": "/health"}]
        screens = [{"id": "notes", "api_calls": [{"method": "get", "path": "/api/notes"}]}]
        registered = [{"method": "GET", "path": "/health", "kind": "infra"}]
        out = api_vs_frontend(api, screens, registered)
        self.assertEqual(out["status"], "pass", out.get("detail"))

    def test_dead_business_endpoint_still_fails_even_with_registry(self):
        # The exemption is kind-driven: a genuinely dead BUSINESS endpoint (not
        # registered as fixed) must still fail.
        api = [{"method": "GET", "path": "/api/orphans"}]
        screens = [{"id": "x", "api_calls": []}]
        registered = [{"method": "GET", "path": "/health", "kind": "infra"}]
        out = api_vs_frontend(api, screens, registered,
                              dead_endpoint_severity="error")
        self.assertEqual(out["status"], "fail")
        self.assertIn("/api/orphans", out["detail"])

    def test_unregistered_undefined_call_still_fails(self):
        # A UI call to something neither in the section NOR registered → undefined.
        api = [{"method": "GET", "path": "/api/notes"}]
        screens = [{"id": "x", "api_calls": [{"method": "POST", "path": "/api/widgets"}]}]
        out = api_vs_frontend(api, screens, registered_endpoints=[])
        self.assertEqual(out["status"], "fail")
        self.assertIn("/api/widgets", out["detail"])

    def test_run_cross_checks_threads_registered_endpoints(self):
        from multi_agent.runtime.kickoff.cross_check_suite import run_cross_checks
        drafts = {
            "backend": {"endpoints": [{"method": "GET", "path": "/api/notes",
                                       "response_key": "items", "response": {"tables": ["notes"]}}],
                        "data_model": {"tables": [{"name": "notes", "columns": [{"name": "id", "type": "int"}]}]}},
            "frontend": {"screens": [
                {"id": "login", "api_calls": [{"method": "POST", "path": "/auth/login"}]},
                {"id": "notes", "user_flow": "f1", "api_calls": [{"method": "GET", "path": "/api/notes"}]},
            ], "user_flows": [{"id": "f1", "critical": False}]},
            "verifier": {"predicates": []},
        }
        registered = [{"method": "POST", "path": "/auth/login", "metadata": {"kind": "auth"}}]
        out = run_cross_checks(drafts, registered_endpoints=registered)
        af = [i for i in out["items"] if i["id"] == "api_vs_frontend"][0]
        self.assertEqual(af["status"], "pass", af)

    def test_param_notation_difference_is_not_a_conflict(self):
        # smoke #4 (2026-06-05): frontend declared GET /api/notes/:noteId, backend
        # declared GET /api/notes/{note_id} — SAME endpoint at runtime (param
        # notation, not drift). Must NOT flag "undefined endpoint" or "no consumer".
        api = [
            {"method": "GET", "path": "/api/notes"},
            {"method": "GET", "path": "/api/notes/{note_id}"},
            {"method": "POST", "path": "/api/notes"},
        ]
        screens = [
            {"id": "list", "api_calls": [{"method": "GET", "path": "/api/notes"}]},
            {"id": "detail", "api_calls": [{"method": "GET", "path": "/api/notes/:noteId"}]},
            {"id": "new", "api_calls": [{"method": "POST", "path": "/api/notes"}]},
        ]
        out = api_vs_frontend(api, screens)
        self.assertEqual(out["status"], "pass", out.get("detail"))

    def test_template_literal_param_also_matches(self):
        api = [{"method": "GET", "path": "/api/notes/{id}"}]
        screens = [{"id": "d", "api_calls": [{"method": "GET", "path": "/api/notes/${noteId}"}]}]
        out = api_vs_frontend(api, screens)
        self.assertEqual(out["status"], "pass", out.get("detail"))

    def test_empty_inputs_pass_vacuously(self):
        self.assertEqual(api_vs_frontend([], [])["status"], "pass")


class ApiVsDataModelTests(unittest.TestCase):
    def test_response_tables_subset_passes(self):
        api = [{
            "method": "GET", "path": "/api/posts",
            "response": {"tables": ["posts"]},
        }]
        dm = {"tables": [{"name": "posts"}, {"name": "users"}]}
        self.assertEqual(api_vs_data_model(api, dm)["status"], "pass")

    def test_undeclared_table_fails(self):
        api = [{
            "method": "GET", "path": "/api/posts",
            "response": {"tables": ["unicorns"]},
        }]
        dm = {"tables": [{"name": "posts"}]}
        out = api_vs_data_model(api, dm)
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["severity"], "error")
        self.assertIn("unicorns", out["detail"])
        self.assertIn("api_endpoints[0].response.tables", out["offending_field"])

    def test_endpoints_without_response_skipped(self):
        api = [{"method": "GET", "path": "/api/health"}]
        dm = {"tables": []}
        self.assertEqual(api_vs_data_model(api, dm)["status"], "pass")

    def test_empty_inputs_pass(self):
        self.assertEqual(api_vs_data_model([], {"tables": []})["status"], "pass")


# Round 8e.1: UiPagesVsUserFlowsTests deleted — the
# ui_pages_vs_user_flows check was retired with the design→frontend
# merge. Both fields now live in frontend's section, so cross-section
# arbitration is unnecessary; intra-section coherence is the LLM's
# responsibility (not the suite's). See test_kickoff_run_kickoff.py
# for the merge-related fixture changes.


class TestStrategyCoverageTests(unittest.TestCase):
    def test_critical_flow_with_predicate_passes(self):
        preds = [{"id": "p1", "flow": "checkout"}]
        flows = [{"id": "checkout", "critical": True, "pages": []}]
        self.assertEqual(test_strategy_coverage(preds, flows)["status"], "pass")

    def test_critical_flow_without_predicate_fails(self):
        preds = []
        flows = [{"id": "checkout", "critical": True, "pages": []}]
        out = test_strategy_coverage(preds, flows)
        self.assertEqual(out["status"], "fail")
        self.assertIn("checkout", out["detail"])
        self.assertIn("acceptance predicate", out["detail"])

    def test_non_critical_flow_without_predicate_passes(self):
        preds = []
        flows = [{"id": "settings", "critical": False, "pages": []}]
        self.assertEqual(test_strategy_coverage(preds, flows)["status"], "pass")

    def test_empty_inputs_pass(self):
        self.assertEqual(test_strategy_coverage([], [])["status"], "pass")


class RunCrossChecksDispatcherTests(unittest.TestCase):
    def test_full_consistent_drafts_pass(self):
        drafts = {
            "backend": {
                "api_endpoints": [{
                    "method": "GET", "path": "/api/posts",
                    "response": {"tables": ["posts"]},
                }],
                "data_model": {"tables": [{"name": "posts"}]},
            },
            "frontend": {
                # Round 8e.1: frontend absorbed design's user_flows.
                "screens": [{
                    "id": "feed",
                    "api_calls": [{"method": "GET", "path": "/api/posts"}],
                }],
                "ui_pages": [{"id": "feed"}],
                "user_flows": [{
                    "id": "browse", "critical": True,
                    "pages": ["feed"],
                }],
            },
            "verifier": {
                "predicates": [{"id": "p1", "flow": "browse"}],
            },
        }
        out = run_cross_checks(drafts)
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["items"]), 3)  # Round 8e.1: 4 checks → 3 (ui_pages_vs_user_flows dropped)
        self.assertTrue(all(i["status"] == "pass" for i in out["items"]))

    def test_drift_flips_ok_false_and_blocker_carries_check_id(self):
        drafts = {
            "backend": {
                "api_endpoints": [{"method": "GET", "path": "/api/posts"}],
                "data_model": {"tables": []},
            },
            "frontend": {
                # Round 8e.1: frontend absorbed design's user_flows.
                "screens": [{
                    "id": "feed",
                    "api_calls": [{"method": "POST", "path": "/api/zzz"}],
                }],
                "ui_pages": [{"id": "feed"}],
                "user_flows": [{"id": "browse", "pages": ["feed"]}],
            },
            "verifier": {"predicates": []},
        }
        out = run_cross_checks(drafts)
        self.assertFalse(out["ok"])
        failing = [i for i in out["items"] if i["status"] != "pass"]
        self.assertGreaterEqual(len(failing), 1)
        # api_vs_frontend should be in the failing set with a blocker
        # string that names the check id.
        avf = next(i for i in out["items"] if i["id"] == "api_vs_frontend")
        self.assertEqual(avf["status"], "fail")
        self.assertTrue(any("api_vs_frontend" in b for b in avf["blockers"]))

    def test_empty_drafts_pass_vacuously(self):
        # Mirrors story_hub's "empty in -> ok=True" semantics: nothing
        # to misalign yet.
        out = run_cross_checks({})
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["items"]), 3)  # Round 8e.1: 4 checks → 3 (ui_pages_vs_user_flows dropped)

    def test_check_exceptions_coerce_to_evidence_pending(self):
        # Closed-by-construction guard: per the module docstring, an
        # individual check raising MUST NOT bubble out of the
        # dispatcher — it must be coerced to status='evidence_pending'.
        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated check fault")

        def _extract_any(_drafts):
            return ()

        custom = {"boom_check": (_extract_any, _boom)}
        out = run_cross_checks({}, checks=custom)
        self.assertFalse(out["ok"])
        self.assertEqual(out["items"][0]["status"], "evidence_pending")
        self.assertEqual(out["items"][0]["id"], "boom_check")
        self.assertTrue(out["items"][0]["blockers"])
        self.assertIn("simulated check fault",
                      out["items"][0]["blockers"][0])

    def test_non_mapping_drafts_raises(self):
        # Charter no-phantom-defaults: an obviously-wrong input must
        # raise rather than silently pass.
        with self.assertRaises(ValueError):
            run_cross_checks("not a dict")  # type: ignore[arg-type]


class CanonicalKickoffShapeRegressionTests(unittest.TestCase):
    """Pin cross_check_suite to the canonical ``KickoffEndpoint`` shape.

    These cases double-bolt the cross-checks to the **contract.py**
    source-of-truth shape (top-level ``method/path/response_key/auth_required``
    + ``response.tables`` sub-mapping) so a future PR that reverts
    ``cross_check_suite`` to expect a different shape (e.g. nested under
    ``metadata`` per the round-7 reviewer's contract-drift concern)
    would break these tests, not slip through unnoticed.

    Discipline: each fixture is first validated via
    ``validate_kickoff_endpoint`` (zero findings ⇒ canonical shape),
    then fed into the check to assert the documented failure mode.
    """

    def _canonical_endpoint(
        self,
        *,
        method: str,
        path: str,
        response_tables=None,
    ):
        """Build a fully-canonical KickoffEndpoint dict.

        Mirrors contract.py's docstring (lines 69-85) verbatim: top-level
        ``method/path/response_key/auth_required`` + ``response.tables``.
        """
        ep = {
            "id": endpoint_id(method, path),
            "method": method,
            "path": path,
            "response_key": "data",
            "auth_required": False,
            "response": {
                "tables": list(response_tables) if response_tables else [],
                "shape": {"type": "object"},
            },
            "request": {"body": {}, "query": []},
        }
        # Closed-by-construction: assert the fixture itself is canonical.
        findings = validate_kickoff_endpoint(ep)
        self.assertEqual(findings, [], f"fixture not canonical: {findings}")
        for key in REQUIRED_ENDPOINT_KEYS:
            self.assertIn(key, ep)
        return ep

    # ------------------------------------------------------------------
    # api_vs_data_model: response.tables = ["users"] but no "users" table
    # ------------------------------------------------------------------
    def test_api_vs_data_model_canonical_shape_undeclared_users_fails(self):
        ep = self._canonical_endpoint(
            method="GET",
            path="/api/users",
            response_tables=["users"],
        )
        dm = {"tables": [{"name": "posts"}]}  # NO "users" declared
        out = api_vs_data_model([ep], dm)
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["severity"], "error")
        # offending_field MUST name the endpoint position + the
        # canonical ``response.tables`` sub-path.
        self.assertIn("api_endpoints[0]", out["offending_field"])
        self.assertIn("response.tables", out["offending_field"])
        # Detail names the offending table AND the endpoint
        # (METHOD PATH per canonical _endpoint_key).
        self.assertIn("users", out["detail"])
        self.assertIn("GET /api/users", out["detail"])

    # ------------------------------------------------------------------
    # api_vs_frontend: endpoint declared but no frontend screen refs it
    # ------------------------------------------------------------------
    def test_api_vs_frontend_canonical_shape_dead_endpoint_fails(self):
        ep = self._canonical_endpoint(
            method="POST",
            path="/api/posts",
            response_tables=["posts"],
        )
        # Screen exists but never calls the canonical endpoint.
        screens = [{"id": "feed", "api_calls": []}]
        out = api_vs_frontend([ep], screens, dead_endpoint_severity="error")
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["severity"], "error")
        # offending_field points at the dead endpoint slot.
        self.assertIn("api_endpoints[0]", out["offending_field"])
        # Detail explains it has no UI consumer + names METHOD PATH.
        self.assertIn("no UI consumer", out["detail"])
        self.assertIn("POST /api/posts", out["detail"])

    # Round 8e.1: ui_pages_vs_user_flows fail-case retired.
    # ------------------------------------------------------------------
    # test_strategy_coverage: critical flow declared, zero predicates
    # ------------------------------------------------------------------
    def test_test_strategy_coverage_critical_flow_uncovered_fails(self):
        # Canonical predicate shape: {id, flow}; canonical flow shape
        # includes the ``critical`` bool that gates this check.
        preds = [{"id": "p1", "flow": "settings"}]  # covers wrong flow
        flows = [{
            "id": "checkout",
            "critical": True,
            "pages": ["cart"],
            "predicates": [],
        }]
        out = test_strategy_coverage(preds, flows)
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["severity"], "error")
        self.assertIn("user_flows[0].id", out["offending_field"])
        self.assertIn("checkout", out["detail"])
        self.assertIn("acceptance predicate", out["detail"])


# ---------------------------------------------------------------------------
# Round 8h Fix #J: tolerant extractor matching. Smoke #9-octavus
# (2026-06-03) caught the cross-check extractor reading
# ``drafts["backend"]["api_endpoints"]`` while real-LLM backend wrote
# the list under ``drafts["backend"]["endpoints"]``. Extractor returned
# []; every frontend api_call appeared "undefined endpoint"; facilitator
# escalated at round 3 chasing a phantom. Also caught frontend mixing
# ``{endpoint_id: "POST /api/posts"}`` with the canonical
# ``{method, path}`` form for api_calls. Both are accepted now.
# ---------------------------------------------------------------------------


class CrossCheckSchemaToleranceTests(unittest.TestCase):
    def test_run_cross_checks_accepts_backend_endpoints_key(self):
        """Smoke #9-octavus regression: backend wrote `endpoints` not
        `api_endpoints`. The dispatcher MUST accept both."""
        from multi_agent.runtime.kickoff.cross_check_suite import run_cross_checks
        drafts = {
            "backend": {
                "endpoints": [  # ← real-LLM key, not 'api_endpoints'
                    {"method": "GET", "path": "/api/posts",
                     "response": {"tables": ["posts"]}},
                ],
                "data_model": {"tables": [{"name": "posts"}]},
            },
            "frontend": {
                "screens": [{
                    "id": "feed",
                    "api_calls": [{"method": "GET", "path": "/api/posts"}],
                }],
                "user_flows": [{"id": "browse", "critical": True, "pages": ["feed"]}],
            },
            "verifier": {"predicates": [{"id": "p1", "flow": "browse"}]},
        }
        out = run_cross_checks(drafts)
        api_check = next(c for c in out["items"] if c["id"] == "api_vs_frontend")
        # Pre-fix: extractor read [] → frontend api_call seen as undefined → fail.
        # Post-fix: extractor reads endpoints → match → pass.
        self.assertEqual(api_check["status"], "pass", out)

    def test_api_vs_frontend_accepts_endpoint_id_shorthand(self):
        """Frontend sometimes emits api_calls as
        ``{endpoint_id: "POST /api/posts", purpose: ...}`` rather than
        the canonical ``{method, path}`` pair. The match MUST canonicalize
        both forms to the same ``METHOD PATH`` key."""
        from multi_agent.runtime.kickoff.cross_check_suite import api_vs_frontend
        endpoints = [{"method": "POST", "path": "/api/posts"}]
        screens = [{
            "id": "feed",
            "api_calls": [
                {"endpoint_id": "POST /api/posts", "purpose": "create a post"}
            ],
        }]
        out = api_vs_frontend(endpoints, screens)
        self.assertEqual(out["status"], "pass", out)

    def test_api_vs_frontend_endpoint_id_normalizes_method_case(self):
        """``endpoint_id`` case-insensitive on the method, like
        the canonical _endpoint_key."""
        from multi_agent.runtime.kickoff.cross_check_suite import api_vs_frontend
        endpoints = [{"method": "GET", "path": "/api/posts"}]
        screens = [{
            "id": "feed",
            "api_calls": [{"endpoint_id": "get /api/posts"}],  # lowercase
        }]
        out = api_vs_frontend(endpoints, screens)
        self.assertEqual(out["status"], "pass", out)

    def test_api_vs_frontend_endpoint_id_malformed_falls_back_to_method_path(self):
        """If ``endpoint_id`` doesn't split into 2 parts, fall back to
        ``method`` + ``path`` so a partial schema still works."""
        from multi_agent.runtime.kickoff.cross_check_suite import api_vs_frontend
        endpoints = [{"method": "GET", "path": "/api/posts"}]
        screens = [{
            "id": "feed",
            "api_calls": [{
                "endpoint_id": "garbage",  # malformed
                "method": "GET", "path": "/api/posts",
            }],
        }]
        out = api_vs_frontend(endpoints, screens)
        self.assertEqual(out["status"], "pass", out)

    def test_frontend_screens_or_ui_pages_both_accepted(self):
        """Real-LLM frontend writes both ``screens`` and ``ui_pages``;
        the extractor MUST prefer ``screens`` but accept ``ui_pages``
        as a fallback so a section that only has one still validates."""
        from multi_agent.runtime.kickoff.cross_check_suite import run_cross_checks
        drafts = {
            "backend": {
                "endpoints": [{"method": "GET", "path": "/api/x",
                               "response": {"tables": ["x"]}}],
                "data_model": {"tables": [{"name": "x"}]},
            },
            # ui_pages only (no screens key) — should still extract for the check.
            "frontend": {
                "ui_pages": [{
                    "id": "x", "api_calls": [{"method": "GET", "path": "/api/x"}],
                }],
                "user_flows": [{"id": "view_x", "critical": True, "pages": ["x"]}],
            },
            "verifier": {"predicates": [{"id": "p1", "flow": "view_x"}]},
        }
        out = run_cross_checks(drafts)
        api_check = next(c for c in out["items"] if c["id"] == "api_vs_frontend")
        self.assertEqual(api_check["status"], "pass", out)


if __name__ == "__main__":
    unittest.main()
