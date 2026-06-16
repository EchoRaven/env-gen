"""FIX #19 — deterministic LAST-RESORT kickoff reconciliation.

A large-app kickoff (Instagram run #1, 2026-06-06) aborted the WHOLE run when
the frontend lane invented a screen calling ``GET /api/stories`` (an endpoint
nobody defined) and the lanes would not reconcile it within
``KICKOFF_MAX_ROUNDS``: the ``api_vs_frontend`` cross-check flagged "UI call to
undefined endpoint" → facilitator escalate → ``synthesize_fallback`` →
``kickoff_failed`` → abort (0 files generated).

The deterministic resolution (charter §8 — converge BY CONSTRUCTION, don't abort
on a negotiation the LLMs won't finish): AUTO-REGISTER the missing endpoint onto
the backend contract — the frontend's need becomes the contract, which the skeleton
then generates a handler for. (Earlier this PRUNED the call; auto-register is the
by-construction posture — the page keeps its data instead of losing it.)

These pin:
  * the pure reconcile fn (auto-register dangling / keep valid / no-op / ui_pages key
    / endpoint_id shorthand / resolve against the registered fixed surface);
  * ``try_synthesize`` — a dangling call is a CONFLICT without reconcile and READY
    with ``reconcile=True`` (reporting the auto-registered endpoints);
  * a clean contract is READY either way (reconcile is a no-op when nothing dangles).
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    _derive_response_key,
    _normalize_backend_endpoints_for_reconcile,
    _normalize_roadmap_shape_for_reconcile,
    _reconcile_dangling_frontend_calls,
    try_synthesize,
)

ATTENDEES = ["backend", "frontend", "verifier"]
MEETING = "page_meeting_ig"


def _hubs(decisions, registered=None):
    workhub = MagicMock(name="workhub")
    workhub.get_meeting_decisions.return_value = list(decisions)
    registryhub = MagicMock(name="registryhub")
    registryhub.get_endpoints.return_value = {
        f"{r['method']} {r['path']}": r for r in (registered or [])
    }
    return SimpleNamespace(
        workhub=workhub, registryhub=registryhub,
        eventhub=MagicMock(), schema_hub=MagicMock(),
    )


def _handle():
    return {
        "meeting_id": MEETING,
        "milestone_index": 1,
        "expected_attendees": list(ATTENDEES),
        "started_at": 0.0,
    }


def _backend(extra_endpoints=()):
    return {"section": "backend", "agent": "backend", "content": {
        "api_endpoints": [
            {"method": "GET", "path": "/api/posts", "response_key": "posts",
             "auth_required": True,
             "response": {"tables": ["posts"],
                          "shape": {"type": "list", "items": "Post"}},
             "request": {"body": {}, "query": []}},
        ] + list(extra_endpoints),
        "data_model": {"tables": [
            {"name": "posts", "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "body", "type": "text"}]}]},
    }}


# A backend endpoint NO screen calls — the "dead endpoint" (tightness) direction.
_DEAD_ENDPOINT = {
    "method": "DELETE", "path": "/api/posts/{id}", "response_key": "ok",
    "auth_required": True,
    "response": {"tables": ["posts"], "shape": {"type": "object"}},
    "request": {"body": {}, "query": []},
}


def _frontend(extra_calls):
    calls = [{"method": "GET", "path": "/api/posts"}] + list(extra_calls)
    return {"section": "frontend", "agent": "frontend", "content": {
        "screens": [{"id": "feed", "api_calls": calls}],
        "ui_pages": [{"id": "feed"}],
        "user_flows": [{"id": "post_create", "critical": True,
                        "pages": ["feed"], "predicates": ["pred_post_create"]}],
        "feature_inventory": {"entities": ["post"], "flows": ["post_create"]},
        "done_def": ["smoke test green"],
        "auth": {"model": "jwt", "required": True},
        "task_tree": [
            {"id": "t_b", "title": "Implement /api/posts", "owner": "backend",
             "depends_on": [], "kind": "implementation", "status": "pending"},
            {"id": "t_f", "title": "Build feed", "owner": "frontend",
             "depends_on": ["t_b"], "kind": "implementation",
             "status": "pending"}],
    }}


def _verifier():
    return {"section": "verifier", "agent": "verifier", "content": {
        "predicates": [{"id": "pred_post_create", "flow": "post_create",
                        "form": {"kind": "api_smoke"}}]}}


class ReconcileFnTests(unittest.TestCase):
    def test_autoregisters_dangling_keeps_calls(self):
        drafts = {
            "backend": {"api_endpoints": [{"method": "GET", "path": "/api/posts"}]},
            "frontend": {"screens": [{"id": "f", "api_calls": [
                {"method": "GET", "path": "/api/posts"},
                {"method": "GET", "path": "/api/stories"}]}]},
        }
        nd, added = _reconcile_dangling_frontend_calls(drafts, [])
        self.assertEqual(added, ["GET /api/stories"])
        # the undefined endpoint is now REGISTERED on the backend (skeleton builds it)
        be_paths = [e["path"] for e in nd["backend"]["api_endpoints"]]
        self.assertIn("/api/stories", be_paths)
        self.assertEqual(
            next(e for e in nd["backend"]["api_endpoints"]
                 if e["path"] == "/api/stories")["source"], "auto_from_frontend_call")
        # the frontend calls are KEPT untouched (they now resolve)
        kept = nd["frontend"]["screens"][0]["api_calls"]
        self.assertEqual([c["path"] for c in kept], ["/api/posts", "/api/stories"])

    def test_noop_when_all_defined(self):
        drafts = {
            "backend": {"api_endpoints": [{"method": "GET", "path": "/api/posts"}]},
            "frontend": {"screens": [{"id": "f", "api_calls": [
                {"method": "GET", "path": "/api/posts"}]}]},
        }
        _nd, added = _reconcile_dangling_frontend_calls(drafts, [])
        self.assertEqual(added, [])

    def test_resolves_against_registered_fixed_surface(self):
        # a UI call to the registered fixed surface (e.g. /auth/login) is NOT
        # dangling even though the backend draft didn't redeclare it.
        drafts = {
            "backend": {"api_endpoints": [{"method": "GET", "path": "/api/posts"}]},
            "frontend": {"screens": [{"id": "f", "api_calls": [
                {"method": "POST", "path": "/auth/login"}]}]},
        }
        reg = [{"method": "POST", "path": "/auth/login"}]
        _nd, added = _reconcile_dangling_frontend_calls(drafts, reg)
        self.assertEqual(added, [])

    def test_ui_pages_key_and_endpoint_id_shorthand(self):
        drafts = {
            "backend": {"endpoints": [{"method": "GET", "path": "/api/posts"}]},
            "frontend": {"ui_pages": [{"id": "f", "api_calls": [
                {"endpoint_id": "GET /api/posts"},
                {"endpoint_id": "GET /api/stories"}]}]},
        }
        nd, added = _reconcile_dangling_frontend_calls(drafts, [])
        self.assertEqual(added, ["GET /api/stories"])
        # auto-registered onto the backend's "endpoints" key (the one it used)
        self.assertIn("/api/stories", [e["path"] for e in nd["backend"]["endpoints"]])
        # the frontend calls are kept (both resolve now)
        self.assertEqual(len(nd["frontend"]["ui_pages"][0]["api_calls"]), 2)


class TrySynthesizeReconcileTests(unittest.TestCase):
    def test_dangling_call_conflicts_without_reconcile(self):
        decisions = [_backend(),
                     _frontend([{"method": "GET", "path": "/api/stories"}]),
                     _verifier()]
        res = try_synthesize(_hubs(decisions), _handle())
        self.assertEqual(res["status"], "conflict")

    def test_reconcile_makes_it_ready_and_reports_added(self):
        decisions = [_backend(),
                     _frontend([{"method": "GET", "path": "/api/stories"}]),
                     _verifier()]
        res = try_synthesize(_hubs(decisions), _handle(), reconcile=True)
        self.assertEqual(res["status"], "ready", res)
        self.assertEqual(res.get("reconciled_added"), ["GET /api/stories"])

    def test_clean_contract_ready_either_way(self):
        decisions = [_backend(), _frontend([]), _verifier()]
        self.assertEqual(
            try_synthesize(_hubs(decisions), _handle())["status"], "ready")
        res = try_synthesize(_hubs(decisions), _handle(), reconcile=True)
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res.get("reconciled_added"), [])

    def test_reconcile_tolerates_dead_endpoint_with_autoregister(self):
        # The Instagram run #2 scenario: auto-registering the dangling UI call
        # resolves the undefined-endpoint error, but a backend endpoint NO screen
        # calls (DELETE /api/posts/{id}) would then trip the dead-endpoint direction.
        # Default cross-checks → conflict; reconcile downgrades dead-endpoint →
        # ready (a slightly-loose-but-shippable contract beats aborting).
        decisions = [
            _backend(extra_endpoints=[_DEAD_ENDPOINT]),
            _frontend([{"method": "GET", "path": "/api/messages/threads"}]),
            _verifier(),
        ]
        # Without reconcile: undefined endpoint OR dead endpoint → conflict.
        self.assertEqual(
            try_synthesize(_hubs(decisions), _handle())["status"], "conflict")
        # With reconcile: auto-register undefined + tolerate dead → ready.
        res = try_synthesize(_hubs(decisions), _handle(), reconcile=True)
        self.assertEqual(res["status"], "ready", res)
        self.assertEqual(res.get("reconciled_added"),
                         ["GET /api/messages/threads"])

    def test_dead_endpoint_alone_synthesizes_directly(self):
        # 2026-06-10: dead-endpoint default downgraded error→info (the MCP
        # tool surface legitimately has endpoints no screen calls), so a dead
        # endpoint alone no longer forces a conflict/reconcile round at all.
        decisions = [
            _backend(extra_endpoints=[_DEAD_ENDPOINT]),
            _frontend([]),
            _verifier(),
        ]
        self.assertEqual(
            try_synthesize(_hubs(decisions), _handle())["status"], "ready")
        res = try_synthesize(_hubs(decisions), _handle(), reconcile=True)
        self.assertEqual(res["status"], "ready", res)
        self.assertEqual(res.get("reconciled_added"), [])

    def test_reconcile_registry_downgrades_missing_predicate(self):
        # The EXACT instagram M2 death: a critical user_flow with NO acceptance
        # predicate → test_strategy_coverage error (the reconcile residual
        # user_flows[0]) → abort. The reconcile registry now DOWNGRADES it (gate C
        # validates each flow behaviorally at delivery) so the reconcile can finalize.
        from multi_agent.runtime.kickoff.cross_check_suite import (
            run_cross_checks, reconcile_check_registry)
        drafts = {
            "backend": _backend()["content"],
            "frontend": {
                "screens": [{"id": "f", "api_calls": [
                    {"method": "GET", "path": "/api/posts"}]}],
                "user_flows": [{"id": "orphan", "critical": True,
                                "pages": ["f"], "predicates": []}],
            },
            "verifier": {"predicates": []},  # no predicate for the orphan flow
        }
        # default registry: the missing predicate is a blocking error
        self.assertFalse(run_cross_checks(drafts)["ok"])
        # reconcile registry: downgraded → the contract can finalize
        self.assertTrue(
            run_cross_checks(drafts, checks=reconcile_check_registry())["ok"])


class EndpointNormalizationTests(unittest.TestCase):
    """FIX #20 — reconcile-path endpoint-shape normalization."""

    def test_derive_response_key(self):
        self.assertEqual(_derive_response_key("/api/posts"), "posts")
        self.assertEqual(_derive_response_key("/api/posts/{id}"), "posts")
        self.assertEqual(
            _derive_response_key("/api/posts/{id}/comments"), "comments")
        self.assertEqual(_derive_response_key("/api/auth/login"), "login")
        self.assertEqual(_derive_response_key("/"), "data")
        self.assertEqual(_derive_response_key(None), "data")

    def test_defaults_auth_required_and_response_key(self):
        drafts = {"backend": {"api_endpoints": [
            {"method": "GET", "path": "/api/posts"},  # missing both
            {"method": "POST", "path": "/api/posts", "response_key": "post",
             "auth_required": True},  # complete
        ]}}
        nd, notes = _normalize_backend_endpoints_for_reconcile(drafts)
        eps = nd["backend"]["api_endpoints"]
        self.assertEqual(eps[0]["auth_required"], True)
        self.assertEqual(eps[0]["response_key"], "posts")
        self.assertEqual(eps[1]["response_key"], "post")  # untouched
        self.assertEqual(len(notes), 2)

    def test_drops_method_or_path_less_endpoints(self):
        drafts = {"backend": {"api_endpoints": [
            {"method": "GET", "path": "/api/posts", "response_key": "p",
             "auth_required": True},
            {"path": "/api/x", "response_key": "x", "auth_required": True},  # no method
            {"method": "GET", "response_key": "y", "auth_required": True},  # no path
        ]}}
        nd, notes = _normalize_backend_endpoints_for_reconcile(drafts)
        eps = nd["backend"]["api_endpoints"]
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]["path"], "/api/posts")
        self.assertEqual(sum("dropped" in n for n in notes), 2)

    def test_noop_when_all_well_formed(self):
        drafts = {"backend": {"api_endpoints": [
            {"method": "GET", "path": "/api/posts", "response_key": "p",
             "auth_required": False}]}}
        _nd, notes = _normalize_backend_endpoints_for_reconcile(drafts)
        self.assertEqual(notes, [])

    def test_malformed_endpoint_floored_at_build_then_ready(self):
        # The run #3 / round-37 scenario: a backend endpoint missing
        # response_key/auth_required. As of the round-37 CONTRACT-SHAPE FLOOR
        # (_build_contract coerces EVERY endpoint's response_key from its path
        # and defaults auth_required=True), these recoverable gaps are filled
        # AT BUILD TIME — so the contract is never malformed and try_synthesize
        # reaches 'ready' WITHOUT needing an explicit reconcile pass. This is a
        # stronger guarantee than the old "reconcile recovers it" behavior:
        # the 1200s validation_failed deadlock (round 37) cannot recur.
        bad_ep = {"method": "POST", "path": "/api/posts/{id}/like"}  # missing both
        decisions = [_backend(extra_endpoints=[bad_ep]), _frontend([
            {"method": "POST", "path": "/api/posts/{id}/like"}]), _verifier()]
        res = try_synthesize(_hubs(decisions), _handle())
        self.assertEqual(res["status"], "ready", res)
        # the floored endpoint carries a derived response_key
        eps = (res.get("contract") or {}).get("endpoints") or []
        liked = next((e for e in eps if "like" in str(e.get("path"))), None)
        self.assertIsNotNone(liked)
        self.assertTrue(str(liked.get("response_key") or "").strip())
        self.assertIsInstance(liked.get("auth_required"), bool)


class RoadmapShapeNormalizationTests(unittest.TestCase):
    """FIX #20b — reconcile defaults empty done_def + feature_inventory."""

    def test_defaults_empty_done_def(self):
        drafts = {"frontend": {"done_def": [],
                               "feature_inventory": {"entities": ["x"], "flows": ["y"]}}}
        nd, notes = _normalize_roadmap_shape_for_reconcile(drafts)
        self.assertTrue(nd["frontend"]["done_def"])
        self.assertTrue(any("done_def" in n for n in notes))

    def test_derives_feature_inventory_from_tables_and_flows(self):
        drafts = {
            "backend": {"data_model": {"tables": [{"name": "posts"}, {"name": "users"}]}},
            "frontend": {"done_def": ["ok"], "feature_inventory": {},
                         "user_flows": [{"id": "post_create"}, {"id": "login"}]},
        }
        nd, notes = _normalize_roadmap_shape_for_reconcile(drafts)
        fi = nd["frontend"]["feature_inventory"]
        self.assertEqual(set(fi["entities"]), {"posts", "users"})
        self.assertEqual(set(fi["flows"]), {"post_create", "login"})

    def test_noop_when_shape_valid(self):
        drafts = {"frontend": {"done_def": ["ok"],
                               "auth": {"model": "jwt", "required": True},
                               "feature_inventory": {"entities": ["a"], "flows": ["b"]}}}
        _nd, notes = _normalize_roadmap_shape_for_reconcile(drafts)
        self.assertEqual(notes, [])

    def test_defaults_missing_auth_model(self):
        """instagram M3 2026-06-10: reconcile residual 'contract.auth.model MUST be
        a non-empty string' aborted the run. Auth is framework-owned by
        construction, so the declaration defaults to jwt."""
        drafts = {"frontend": {
            "done_def": ["ok"],
            "feature_inventory": {"entities": ["a"], "flows": ["b"]},
        }}
        nd, notes = _normalize_roadmap_shape_for_reconcile(drafts)
        assert nd["frontend"]["auth"] == {"model": "jwt", "required": True}
        assert any("auth" in n for n in notes)
        # an explicit auth declaration is left alone
        drafts2 = {"frontend": {"done_def": ["ok"], "auth": {"model": "oauth2"},
                                "feature_inventory": {"entities": ["a"], "flows": ["b"]}}}
        nd2, _ = _normalize_roadmap_shape_for_reconcile(drafts2)
        assert nd2["frontend"]["auth"] == {"model": "oauth2"}

    def test_normalizes_malformed_user_flows_shape(self):
        """instagram 2026-06-10 01:56 death: the LLM wrote user_flows[0] as a bare
        string (or a mapping without id) → test_strategy_coverage errors with
        offending_field=user_flows[0], which the reconcile could not clear →
        abort. The reconcile normalizer must coerce the SHAPE (string → {id},
        missing id → synthesized id, junk dropped)."""
        drafts = {"frontend": {
            "done_def": ["ok"],
            "feature_inventory": {"entities": ["a"], "flows": ["b"]},
            "user_flows": ["browse feed", {"critical": True, "pages": ["f"]}, None],
        }}
        nd, notes = _normalize_roadmap_shape_for_reconcile(drafts)
        flows = nd["frontend"]["user_flows"]
        assert flows[0] == {"id": "browse feed", "critical": False}
        assert flows[1]["id"] == "flow_1"          # synthesized id, content kept
        assert flows[1]["critical"] is True
        assert len(flows) == 2                     # the None junk entry dropped
        assert any("user_flows" in n for n in notes)

    def test_empty_metadata_floored_at_build_then_ready(self):
        # run #7 / round-38 scenario: empty done_def + feature_inventory. As of
        # the round-38 CONTRACT-SHAPE FLOOR (_build_roadmap floors done_def with
        # generic done-criteria; _normalize_feature_inventory derives entities/
        # flows at M1) these recoverable gaps are filled AT BUILD TIME — so
        # try_synthesize reaches 'ready' WITHOUT an explicit reconcile pass.
        # Stronger than the old "reconcile recovers it": the done_def_missing
        # validation_failed deadlock (round 38) cannot recur.
        fe = _frontend([])
        fe["content"]["done_def"] = []
        fe["content"]["feature_inventory"] = {}
        decisions = [_backend(), fe, _verifier()]
        res = try_synthesize(_hubs(decisions), _handle())
        self.assertEqual(res["status"], "ready", res)
        # the floored done_def is non-empty in the synthesized roadmap
        self.assertTrue((res.get("roadmap") or {}).get("done_def")
                        or (res.get("contract") is not None))


if __name__ == "__main__":
    unittest.main()
