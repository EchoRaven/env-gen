"""Regression tests for runtime.kickoff.run_kickoff.

Closed-by-construction discipline (mirrors sibling kickoff tests):
each test pins exactly one invariant the module promises in its
docstring. Hubs are mocked end-to-end so the tests stay fast
and decoupled from workhub/eventhub/registryhub/schema_hub
implementation details — this module's contract IS the call
shape it produces against those mocks.

Pinned invariants:
1. start_kickoff creates the meeting page via workhub.create_meeting
   AND emits one kickoff_request event via eventhub.publish_event
   with the expected payload (meeting_id, milestone_index,
   requirements, expected_sections).
2. try_synthesize returns ``status="awaiting"`` with the full
   ``missing`` attendee list when no decisions have been submitted.
3. try_synthesize returns ``status="conflict"`` with a populated
   ``revisers`` map keyed by the arbitration_table reviser when
   quorum is reached but a cross-check fails.
4. try_synthesize returns ``status="ready"`` with a structured
   contract + task_tree + predicates when every gate passes.
5. finalize_kickoff registers each endpoint via
   registryhub.register_endpoint, each table via
   schema_hub.register_table, each task via workhub.create_task,
   closes the meeting via workhub.close_meeting, and emits a
   single kickoff_complete event via eventhub.publish_event.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    EXPECTED_SECTIONS,
    finalize_kickoff,
    start_kickoff,
    try_synthesize,
)


# ---------------------------------------------------------------------------
# Shared fixtures — minimal mock hubs registry built from MagicMocks.
# ---------------------------------------------------------------------------

# Round 8e.1: design merged into frontend; attendees 4 → 3.
ATTENDEES = ["backend", "frontend", "verifier"]


def _mock_hubs(decisions=None, meeting_id="page_meeting_1"):
    """Build a SimpleNamespace registry with MagicMock hubs.

    ``decisions`` is the list returned by
    ``workhub.get_meeting_decisions(meeting_id)`` — defaults to [].
    """
    workhub = MagicMock(name="workhub")
    workhub.create_meeting.return_value = {
        "id": meeting_id,
        "title": "M1 kickoff: build social app",
        "metadata": {"decisions": list(decisions or [])},
    }
    workhub.get_meeting_decisions.return_value = list(decisions or [])
    workhub.create_task.side_effect = (
        lambda **kwargs: {"id": kwargs.get("task_id") or "task_x", **kwargs}
    )
    workhub.add_meeting_decision.return_value = {"id": meeting_id}
    workhub.close_meeting.return_value = {"id": meeting_id, "status": "closed"}

    eventhub = MagicMock(name="eventhub")
    eventhub.publish_event.return_value = {"id": "evt_1"}

    registryhub = MagicMock(name="registryhub")
    registryhub.register_endpoint.return_value = {"id": "GET /api/posts"}

    schema_hub = MagicMock(name="schema_hub")
    schema_hub.register_table.return_value = {"id": "posts"}

    return SimpleNamespace(
        workhub=workhub,
        eventhub=eventhub,
        registryhub=registryhub,
        schema_hub=schema_hub,
    )


# ---------------------------------------------------------------------------
# Decision builders — produce the shape try_synthesize reads.
# ---------------------------------------------------------------------------


# Round 8e.1: design merged into frontend — its kickoff section
# content (user_flows + feature_inventory + done_def + auth +
# task_tree) is now part of frontend's draft. The legacy
# _clean_design_decision() helper is gone; tests build the merged
# frontend decision below via _clean_frontend_decision().


def _clean_backend_decision():
    return {
        "section": "backend",
        "agent": "backend",
        "content": {
            "api_endpoints": [
                {
                    "method": "GET",
                    "path": "/api/posts",
                    "response_key": "posts",
                    "auth_required": True,
                    "response": {
                        "tables": ["posts"],
                        "shape": {"type": "list", "items": "Post"},
                    },
                    "request": {"body": {}, "query": []},
                }
            ],
            "data_model": {
                "tables": [
                    {
                        "name": "posts",
                        "columns": [
                            {"name": "id", "type": "uuid"},
                            {"name": "body", "type": "text"},
                        ],
                    }
                ]
            },
        },
    }


def _clean_frontend_decision():
    # Round 8e.1: frontend now owns the former design fields too —
    # user_flows + feature_inventory + done_def + auth + task_tree
    # + ui_pages + reference_image_manifest — in addition to native
    # screens.
    return {
        "section": "frontend",
        "agent": "frontend",
        "content": {
            "screens": [
                {
                    "id": "feed",
                    "api_calls": [{"method": "GET", "path": "/api/posts"}],
                }
            ],
            "ui_pages": [{"id": "feed"}],
            "user_flows": [
                {
                    "id": "post_create",
                    "critical": True,
                    "pages": ["feed"],
                    "predicates": ["pred_post_create"],
                }
            ],
            "feature_inventory": {
                "entities": ["post"],
                "flows": ["post_create"],
            },
            "done_def": ["smoke test green", "lighthouse > 90"],
            "auth": {"model": "jwt", "required": True},
            "task_tree": [
                {
                    "id": "t_backend_impl",
                    "title": "Implement /api/posts",
                    "owner": "backend",
                    "depends_on": [],
                    "kind": "implementation",
                    "status": "pending",
                },
                {
                    "id": "t_frontend_impl",
                    "title": "Build feed page",
                    "owner": "frontend",
                    "depends_on": ["t_backend_impl"],
                    "kind": "implementation",
                    "status": "pending",
                },
            ],
        },
    }


def _clean_verifier_decision():
    return {
        "section": "verifier",
        "agent": "verifier",
        "content": {
            "predicates": [
                {
                    "id": "pred_post_create",
                    "flow": "post_create",
                    "form": {"kind": "api_smoke"},
                }
            ]
        },
    }


def _all_clean_decisions():
    return [
        _clean_backend_decision(),
        _clean_frontend_decision(),
        _clean_verifier_decision(),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class StartKickoffTests(unittest.TestCase):
    def test_start_kickoff_creates_meeting_and_emits_request(self):
        """Invariant 1: opens the meeting page AND broadcasts kickoff_request."""
        hubs = _mock_hubs()
        handle = start_kickoff(
            hubs=hubs,
            milestone_index=1,
            requirements=["build a social posting app"],
            attendees=ATTENDEES,
        )

        # Meeting created exactly once with the right shape.
        hubs.workhub.create_meeting.assert_called_once()
        cm_kwargs = hubs.workhub.create_meeting.call_args.kwargs
        self.assertEqual(cm_kwargs["kind"], "kickoff")
        self.assertEqual(cm_kwargs["milestone_index"], 1)
        self.assertEqual(cm_kwargs["attendees"], ATTENDEES)
        self.assertEqual(cm_kwargs["agent"], "orchestrator")
        self.assertIn("requirements", cm_kwargs["metadata"])

        # Kickoff_request event emitted exactly once with the right shape.
        hubs.eventhub.publish_event.assert_called_once()
        pe_kwargs = hubs.eventhub.publish_event.call_args.kwargs
        self.assertEqual(pe_kwargs["source_hub"], "orchestrator")
        self.assertEqual(pe_kwargs["event_type"], "kickoff_request")
        self.assertEqual(pe_kwargs["recipients"], ATTENDEES)
        self.assertEqual(pe_kwargs["priority"], "high")
        self.assertEqual(pe_kwargs["caller"], "orchestrator")
        self.assertEqual(pe_kwargs["payload"]["meeting_id"], "page_meeting_1")
        self.assertEqual(pe_kwargs["payload"]["milestone_index"], 1)
        self.assertEqual(
            pe_kwargs["payload"]["expected_sections"],
            list(EXPECTED_SECTIONS),
        )
        self.assertIn(
            "build a social posting app",
            pe_kwargs["payload"]["requirements"],
        )

        # Returned handle carries everything try_synthesize needs.
        self.assertEqual(handle["meeting_id"], "page_meeting_1")
        self.assertEqual(handle["milestone_index"], 1)
        self.assertEqual(handle["expected_attendees"], ATTENDEES)
        self.assertEqual(handle["phase"], "awaiting_decisions")
        self.assertIn("started_at", handle)


class TrySynthesizeAwaitingTests(unittest.TestCase):
    def test_try_synthesize_returns_awaiting_when_no_decisions(self):
        """Invariant 2: no decisions ⇒ status='awaiting' with full missing list."""
        hubs = _mock_hubs(decisions=[])
        handle = {
            "meeting_id": "page_meeting_1",
            "milestone_index": 1,
            "expected_attendees": ATTENDEES,
        }
        result = try_synthesize(hubs, handle)
        self.assertEqual(result["status"], "awaiting")
        self.assertEqual(sorted(result["missing"]), sorted(ATTENDEES))
        self.assertEqual(result["milestone_index"], 1)


class TrySynthesizeConflictTests(unittest.TestCase):
    def test_try_synthesize_returns_conflict_with_reviser(self):
        """Invariant 3: quorum + cross-check fail ⇒ status='conflict' with reviser.

        We rig api_vs_frontend to fail by having frontend call an
        endpoint the backend didn't declare. The arbitration table
        pins ``frontend`` as the reviser for that row.
        """
        # Backend draft has NO endpoints; frontend calls one anyway.
        backend = _clean_backend_decision()
        backend["content"]["api_endpoints"] = []
        # Also empty the data_model since cross_check_suite is short-
        # circuiting on the first failing check; this keeps the
        # rigged failure deterministic.
        decisions = [
            backend,
            _clean_frontend_decision(),  # still calls /api/posts
            _clean_verifier_decision(),
        ]
        hubs = _mock_hubs(decisions=decisions)
        handle = {
            "meeting_id": "page_meeting_1",
            "milestone_index": 1,
            "expected_attendees": ATTENDEES,
        }
        result = try_synthesize(hubs, handle)
        self.assertEqual(result["status"], "conflict")
        self.assertGreaterEqual(len(result["findings"]), 1)
        # The reviser map MUST identify at least one agent. For
        # api_vs_frontend the pinned reviser is frontend; we don't
        # over-fit by demanding ONLY frontend (other checks may also
        # fail downstream), but frontend MUST be present.
        self.assertIn(
            "frontend",
            result["revisers"],
            f"expected 'frontend' in revisers, got {list(result['revisers'].keys())}",
        )


class TrySynthesizeReadyTests(unittest.TestCase):
    def test_try_synthesize_returns_ready_with_structured_contract(self):
        """Invariant 4: every gate passes ⇒ status='ready' with synthesized contract."""
        hubs = _mock_hubs(decisions=_all_clean_decisions())
        handle = {
            "meeting_id": "page_meeting_1",
            "milestone_index": 1,
            "expected_attendees": ATTENDEES,
        }
        result = try_synthesize(hubs, handle)
        self.assertEqual(result["status"], "ready", msg=result)
        contract = result["contract"]
        self.assertIn("endpoints", contract)
        self.assertEqual(len(contract["endpoints"]), 1)
        self.assertEqual(contract["endpoints"][0]["path"], "/api/posts")
        self.assertEqual(
            contract["data_model"]["tables"][0]["name"], "posts"
        )
        self.assertEqual(contract["auth"]["model"], "jwt")
        self.assertEqual(len(result["task_tree"]), 2)
        self.assertEqual(len(result["predicates"]), 1)
        self.assertEqual(result["milestone_index"], 1)


class FinalizeKickoffTests(unittest.TestCase):
    def test_finalize_registers_endpoints_tables_tasks_closes_meeting(self):
        """Invariant 5: each artifact flows to its hub + kickoff_complete emitted."""
        hubs = _mock_hubs(decisions=_all_clean_decisions())
        handle = {
            "meeting_id": "page_meeting_1",
            "milestone_index": 1,
            "expected_attendees": ATTENDEES,
        }
        # Synthesize first so finalize gets a real ready-shape payload.
        synthesis = try_synthesize(hubs, handle)
        self.assertEqual(synthesis["status"], "ready", msg=synthesis)

        # Reset the eventhub mock so we only assert on kickoff_complete.
        hubs.eventhub.publish_event.reset_mock()

        receipt = finalize_kickoff(hubs, handle, synthesis)

        # Receipt counts.
        self.assertTrue(receipt["finalized"])
        self.assertEqual(receipt["endpoints_registered"], 1)
        self.assertEqual(receipt["tables_registered"], 1)
        self.assertEqual(receipt["tasks_created"], 2)
        self.assertEqual(receipt["predicates_persisted"], 1)
        self.assertEqual(receipt["meeting_id"], "page_meeting_1")
        self.assertEqual(receipt["milestone_index"], 1)

        # Hub call counts.
        self.assertEqual(hubs.registryhub.register_endpoint.call_count, 1)
        ep_kwargs = hubs.registryhub.register_endpoint.call_args.kwargs
        self.assertEqual(ep_kwargs["method"], "GET")
        self.assertEqual(ep_kwargs["path"], "/api/posts")
        self.assertEqual(ep_kwargs["provider"], "backend")
        self.assertEqual(ep_kwargs["status"], "defined")
        self.assertEqual(ep_kwargs["agent"], "orchestrator")
        # response_key + auth_required ride the metadata catch-all.
        # PROPOSAL #46: business /api/ GET collection → canonical "items" (was "posts").
        self.assertEqual(ep_kwargs["response_key"], "items")
        self.assertIs(ep_kwargs["auth_required"], True)

        self.assertEqual(hubs.schema_hub.register_table.call_count, 1)
        tbl_kwargs = hubs.schema_hub.register_table.call_args.kwargs
        self.assertEqual(tbl_kwargs["name"], "posts")
        self.assertEqual(tbl_kwargs["agent"], "orchestrator")
        self.assertEqual(tbl_kwargs["provider"], "backend")

        self.assertEqual(hubs.workhub.create_task.call_count, 2)
        # First task = backend impl with no deps; second = frontend
        # depends on first.
        first_call = hubs.workhub.create_task.call_args_list[0].kwargs
        self.assertEqual(first_call["assignee"], "backend")
        self.assertEqual(first_call["depends_on"], [])
        second_call = hubs.workhub.create_task.call_args_list[1].kwargs
        self.assertEqual(second_call["assignee"], "frontend")
        self.assertEqual(second_call["depends_on"], ["t_backend_impl"])

        # Predicates persisted via add_meeting_decision. The finalize
        # path now ALSO writes phase_transition decisions ("finalizing"
        # on entry, "finalized" on success) — filter to the
        # acceptance_predicates write to keep the invariant clean.
        amd_calls = hubs.workhub.add_meeting_decision.call_args_list
        predicate_calls = [
            c for c in amd_calls
            if c.kwargs.get("decision", {}).get("section")
            == "acceptance_predicates"
        ]
        self.assertEqual(len(predicate_calls), 1)
        amd_kwargs = predicate_calls[0].kwargs
        self.assertEqual(amd_kwargs["meeting_id"], "page_meeting_1")
        self.assertEqual(
            amd_kwargs["decision"]["section"], "acceptance_predicates"
        )
        self.assertEqual(
            len(amd_kwargs["decision"]["content"]["predicates"]), 1
        )
        # Phase state machine: finalizing -> finalized recorded as
        # phase_transition decisions on the meeting page.
        phase_calls = [
            c for c in amd_calls
            if c.kwargs.get("decision", {}).get("section")
            == "phase_transition"
        ]
        phases = [
            c.kwargs["decision"]["content"]["phase"] for c in phase_calls
        ]
        self.assertEqual(phases, ["finalizing", "finalized"])
        self.assertEqual(receipt["phase"], "finalized")

        # Meeting closed.
        hubs.workhub.close_meeting.assert_called_once()
        cm_kwargs = hubs.workhub.close_meeting.call_args.kwargs
        self.assertEqual(cm_kwargs["meeting_id"], "page_meeting_1")
        self.assertEqual(
            cm_kwargs["produced_artifacts"],
            ["contract", "task_tree", "predicates"],
        )
        self.assertEqual(cm_kwargs["milestone_index"], 1)
        self.assertEqual(cm_kwargs["agent"], "orchestrator")

        # Kickoff_complete emitted exactly once.
        self.assertEqual(hubs.eventhub.publish_event.call_count, 1)
        pe_kwargs = hubs.eventhub.publish_event.call_args.kwargs
        self.assertEqual(pe_kwargs["source_hub"], "orchestrator")
        self.assertEqual(pe_kwargs["event_type"], "kickoff_complete")
        self.assertEqual(pe_kwargs["recipients"], ATTENDEES)
        self.assertEqual(pe_kwargs["caller"], "orchestrator")
        self.assertEqual(pe_kwargs["payload"]["meeting_id"], "page_meeting_1")
        self.assertEqual(pe_kwargs["payload"]["milestone_index"], 1)
        self.assertEqual(pe_kwargs["payload"]["endpoints_registered"], 1)


# ---------------------------------------------------------------------------
# Round 8h Fix #N: synthesizer tolerance for real-LLM shape drift.
# Smoke #9-undecimus (2026-06-03) caught backend writing `endpoints`
# instead of `api_endpoints`, frontend writing per-feature dict for
# feature_inventory instead of {entities, flows}, and frontend
# emitting empty task_tree. Each silently dropped the corresponding
# contract field and forced the facilitator to escalate.
# ---------------------------------------------------------------------------


class Round8hFixNSchemaToleranceTests(unittest.TestCase):

    def _hubs_with(self, backend_content, frontend_content, verifier_content=None):
        be = {"section": "backend", "agent": "backend", "content": backend_content}
        fe = {"section": "frontend", "agent": "frontend", "content": frontend_content}
        ve = verifier_content or _clean_verifier_decision()["content"]
        vd = {"section": "verifier", "agent": "verifier", "content": ve}
        return _mock_hubs(decisions=[be, fe, vd])

    def test_backend_endpoints_key_accepted_alongside_api_endpoints(self):
        """Smoke #9-undecimus regression: real-LLM backend writes
        `endpoints`, not `api_endpoints`. The synthesizer must accept
        both so the contract.endpoints slot doesn't end up empty
        and trigger a phantom roadmap_validator failure."""
        # Backend with `endpoints` (real-LLM key), not `api_endpoints`.
        be_content = {
            "endpoints": [{
                "method": "GET", "path": "/api/posts",
                "response_key": "posts", "auth_required": True,
                "response": {"tables": ["posts"], "shape": {"type": "list", "items": "Post"}},
                "request": {"body": {}, "query": []},
            }],
            "data_model": {"tables": [{"name": "posts", "columns": [
                {"name": "id", "type": "uuid"}, {"name": "body", "type": "text"}]}]},
        }
        hubs = self._hubs_with(be_content, _clean_frontend_decision()["content"])
        handle = {"meeting_id": "page_meeting_1", "milestone_index": 1,
                  "expected_attendees": ATTENDEES}
        result = try_synthesize(hubs, handle)
        self.assertEqual(result["status"], "ready", msg=result)
        self.assertEqual(len(result["contract"]["endpoints"]), 1)
        self.assertEqual(result["contract"]["endpoints"][0]["path"], "/api/posts")

    def test_feature_inventory_picks_backend_when_frontend_shape_wrong(self):
        """Real-LLM frontend writes feature_inventory as per-feature
        dict (e.g. {auth_login: {...}, post_compose: {...}}); validator
        wants {entities, flows}. Backend writes the validator shape.
        Synthesizer must prefer the validator-shaped source."""
        from multi_agent.runtime.kickoff.run_kickoff import _pick_feature_inventory
        frontend_wrong = {"auth_login": {"summary": "login flow"},
                          "post_compose": {"summary": "compose"}}
        backend_right = {"entities": ["post"], "flows": ["post_create"]}
        out = _pick_feature_inventory({"feature_inventory": frontend_wrong},
                                       {"feature_inventory": backend_right})
        self.assertEqual(out, backend_right)

    def test_feature_inventory_prefers_frontend_when_both_have_right_shape(self):
        """Charter §5 ownership: frontend wins when both are valid."""
        from multi_agent.runtime.kickoff.run_kickoff import _pick_feature_inventory
        fe = {"entities": ["a"], "flows": ["f_a"]}
        be = {"entities": ["b"], "flows": ["f_b"]}
        out = _pick_feature_inventory({"feature_inventory": fe},
                                       {"feature_inventory": be})
        self.assertEqual(out, fe)

    def test_feature_inventory_falls_through_to_frontend_when_neither_shaped(self):
        """Neither has {entities, flows} — return frontend's so the
        validator's shape error surfaces against the canonical source."""
        from multi_agent.runtime.kickoff.run_kickoff import _pick_feature_inventory
        fe = {"some": "stuff"}
        be = {"other": "stuff"}
        out = _pick_feature_inventory({"feature_inventory": fe},
                                       {"feature_inventory": be})
        self.assertEqual(out, fe)

    def test_task_tree_synthesized_from_contract_when_frontend_empty(self):
        """If frontend's task_tree is empty (real-LLM common case),
        synthesize a minimum task per endpoint + per table + per
        validation deliverable so finalize_kickoff has dispatchable
        work for both backend and verifier lanes."""
        from multi_agent.runtime.kickoff.run_kickoff import _synthesize_task_tree
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/posts"},
                {"method": "POST", "path": "/api/posts"},
            ],
            "data_model": {"tables": [{"name": "posts"}]},
        }
        tasks = _synthesize_task_tree(contract)
        kinds = [t["kind"] for t in tasks]
        self.assertEqual(kinds.count("implement_endpoint"), 2)
        self.assertEqual(kinds.count("implement_table"), 1)
        self.assertEqual(kinds.count("validate_api_smoke"), 2)
        impl_tasks = [t for t in tasks if t["kind"].startswith("implement_")]
        validate_tasks = [t for t in tasks if t["kind"].startswith("validate_")]
        for t in impl_tasks:
            self.assertEqual(t["owner"], "backend")
            self.assertIn("id", t)
            self.assertIn("summary", t)
        for t in validate_tasks:
            self.assertEqual(t["owner"], "verifier")

    def test_task_tree_synthesis_skips_malformed_entries(self):
        """Defensive: incomplete endpoints / tables don't crash."""
        from multi_agent.runtime.kickoff.run_kickoff import _synthesize_task_tree
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/posts"},
                {"method": ""},  # missing path
                "garbage",  # not a mapping
                {"path": "/api/x"},  # missing method
            ],
            "data_model": {"tables": [
                {"name": "posts"},
                {},  # missing name
                "garbage",  # not a mapping
            ]},
        }
        tasks = _synthesize_task_tree(contract)
        # 1 valid endpoint impl + 1 valid table impl + 1 validate_api_smoke.
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_endpoint"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_table"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "validate_api_smoke"), 1)

    def test_task_tree_synthesis_deduplicates(self):
        """Same endpoint repeated in the contract → 1 impl task + 1 validate task."""
        from multi_agent.runtime.kickoff.run_kickoff import _synthesize_task_tree
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/posts"},
                {"method": "GET", "path": "/api/posts"},
            ],
            "data_model": {"tables": []},
        }
        tasks = _synthesize_task_tree(contract)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_endpoint"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "validate_api_smoke"), 1)


# ---------------------------------------------------------------------------
# Round 8h Fix #P: auto-coverage for critical user_flow predicates.
# Verifier consistently under-authors predicates across smokes 9 through
# 9-tertius-decimus; the synthesizer fills the gap with stub api_smoke
# predicates rather than escalate.
# ---------------------------------------------------------------------------


class Round8hFixPPredicateCoverageTests(unittest.TestCase):

    def test_missing_critical_flow_gets_synthesized_stub(self):
        from multi_agent.runtime.kickoff.run_kickoff import _ensure_critical_flow_coverage
        verifier_preds = [
            {"id": "pred.auth_login.api", "flow": "auth_login",
             "form": {"kind": "api_smoke"}},
        ]
        flows = [
            {"id": "auth_login", "critical": True},
            {"id": "view_posts", "critical": True},   # uncovered!
            {"id": "create_post", "critical": True},  # uncovered!
        ]
        out = _ensure_critical_flow_coverage(verifier_preds, flows)
        # Original predicate preserved.
        flows_seen = {p["flow"] for p in out}
        self.assertEqual(flows_seen, {"auth_login", "view_posts", "create_post"})
        # New stubs are marked auto_coverage.
        stubs = [p for p in out if p.get("source") == "auto_coverage"]
        self.assertEqual(len(stubs), 2)
        # Stub ids follow the convention.
        stub_ids = {p["id"] for p in stubs}
        self.assertIn("pred.view_posts.auto_coverage", stub_ids)
        self.assertIn("pred.create_post.auto_coverage", stub_ids)

    def test_non_critical_flow_not_covered(self):
        from multi_agent.runtime.kickoff.run_kickoff import _ensure_critical_flow_coverage
        out = _ensure_critical_flow_coverage(
            [],
            [{"id": "settings_optional", "critical": False}],
        )
        self.assertEqual(out, [])

    def test_already_covered_flows_dont_get_duplicated(self):
        from multi_agent.runtime.kickoff.run_kickoff import _ensure_critical_flow_coverage
        verifier_preds = [
            {"id": "pred.x.api", "flow": "x", "form": {"kind": "api_smoke"}},
        ]
        flows = [{"id": "x", "critical": True}]
        out = _ensure_critical_flow_coverage(verifier_preds, flows)
        self.assertEqual(len(out), 1)
        # No auto_coverage stub was added.
        self.assertNotIn("auto_coverage", str(out))

    def test_empty_flows_returns_predicates_verbatim(self):
        from multi_agent.runtime.kickoff.run_kickoff import _ensure_critical_flow_coverage
        verifier_preds = [
            {"id": "pred.x.api", "flow": "x", "form": {"kind": "api_smoke"}},
        ]
        out = _ensure_critical_flow_coverage(verifier_preds, [])
        self.assertEqual(out, verifier_preds)

    def test_synthesized_predicates_pass_test_strategy_coverage(self):
        """End-to-end: after Fix #P synthesis, the
        test_strategy_coverage cross-check MUST pass."""
        from multi_agent.runtime.kickoff.run_kickoff import _ensure_critical_flow_coverage
        from multi_agent.runtime.kickoff.cross_check_suite import test_strategy_coverage
        flows = [
            {"id": "f_a", "critical": True},
            {"id": "f_b", "critical": True},
        ]
        # Verifier only wrote one — the gap that escalates smokes.
        preds = [{"id": "pred.a", "flow": "f_a", "form": {"kind": "api_smoke"}}]
        out = _ensure_critical_flow_coverage(preds, flows)
        result = test_strategy_coverage(out, flows)
        self.assertEqual(result["status"], "pass", msg=result)


if __name__ == "__main__":
    unittest.main()


class Round8hFixPbisDraftAugmentTests(unittest.TestCase):
    """Round 8h Fix #P-bis: drafts augmented BEFORE run_cross_checks
    so the test_strategy_coverage check sees the auto-coverage stubs."""

    def test_augment_drafts_for_coverage_adds_stubs_in_verifier(self):
        from multi_agent.runtime.kickoff.run_kickoff import _augment_drafts_for_coverage
        drafts = {
            "verifier": {"predicates": [
                {"id": "pred.x.api", "flow": "x", "form": {"kind": "api_smoke"}},
            ]},
            "frontend": {"user_flows": [
                {"id": "x", "critical": True},
                {"id": "y", "critical": True},  # uncovered
            ]},
        }
        out = _augment_drafts_for_coverage(drafts)
        out_preds = out["verifier"]["predicates"]
        flows_seen = {p["flow"] for p in out_preds}
        self.assertEqual(flows_seen, {"x", "y"})
        self.assertTrue(any(p.get("source") == "auto_coverage" for p in out_preds))

    def test_augment_drafts_is_idempotent(self):
        from multi_agent.runtime.kickoff.run_kickoff import _augment_drafts_for_coverage
        drafts = {
            "verifier": {"predicates": []},
            "frontend": {"user_flows": [{"id": "x", "critical": True}]},
        }
        once = _augment_drafts_for_coverage(drafts)
        twice = _augment_drafts_for_coverage(once)
        self.assertEqual(once, twice)

    def test_augment_drafts_does_not_mutate_input(self):
        from multi_agent.runtime.kickoff.run_kickoff import _augment_drafts_for_coverage
        drafts = {
            "verifier": {"predicates": []},
            "frontend": {"user_flows": [{"id": "x", "critical": True}]},
        }
        original_preds = drafts["verifier"]["predicates"]
        _augment_drafts_for_coverage(drafts)
        self.assertEqual(drafts["verifier"]["predicates"], [])
        self.assertIs(drafts["verifier"]["predicates"], original_preds)

    def test_augment_drafts_other_sections_passed_through(self):
        from multi_agent.runtime.kickoff.run_kickoff import _augment_drafts_for_coverage
        drafts = {
            "backend": {"endpoints": [{"method": "GET", "path": "/api/x"}]},
            "verifier": {"predicates": []},
            "frontend": {"user_flows": []},
        }
        out = _augment_drafts_for_coverage(drafts)
        self.assertEqual(out["backend"], drafts["backend"])

    def test_try_synthesize_passes_cross_check_via_auto_coverage(self):
        """End-to-end: real synthesis where verifier authors one
        predicate while there are 3 critical flows. Pre-Fix #P-bis
        this returned status='conflict' (test_strategy_coverage
        fail). Post-fix, status='ready'."""
        from multi_agent.runtime.kickoff.run_kickoff import try_synthesize
        # Build hubs from clean decisions but mutate frontend to
        # include extra critical flows + verifier to under-cover.
        verifier = _clean_verifier_decision()
        # 1 predicate (auth_register style)
        verifier["content"]["predicates"] = [
            {"id": "pred.auth_register.api", "flow": "auth_register",
             "form": {"kind": "api_smoke"}},
        ]
        frontend = _clean_frontend_decision()
        # 3 critical flows, only 1 covered by verifier's predicate.
        frontend["content"]["user_flows"] = [
            {"id": "auth_register", "critical": True, "pages": ["feed"], "predicates": []},
            {"id": "view_posts", "critical": True, "pages": ["feed"], "predicates": []},
            {"id": "create_post", "critical": True, "pages": ["feed"], "predicates": []},
        ]
        hubs = _mock_hubs(decisions=[_clean_backend_decision(), frontend, verifier])
        handle = {"meeting_id": "page_meeting_1", "milestone_index": 1,
                  "expected_attendees": ATTENDEES}
        result = try_synthesize(hubs, handle)
        # Pre-fix this was "conflict"; post-fix it's "ready".
        self.assertEqual(result["status"], "ready", msg=result)
        # Predicates in the result include the 2 synthesized stubs.
        flows_seen = {p.get("flow") for p in result["predicates"]}
        self.assertEqual(flows_seen, {"auth_register", "view_posts", "create_post"})
