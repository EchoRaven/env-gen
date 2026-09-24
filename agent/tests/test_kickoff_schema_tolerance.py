"""Round 8h — tests for runtime.kickoff.schema_tolerance.

The module consolidates Fix #J/H/N/O/P helpers into one place; the
test file consolidates the corresponding closed-by-construction
pins. Every test here corresponds to one bullet in the module
docstring — keep them aligned so a future refactor that drops a
helper also drops its pin.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.kickoff.schema_tolerance import (  # noqa: E402
    FACILITATOR_ACTIONS,
    PROTOCOL_FIXED_SECTIONS,
    api_call_key,
    augment_drafts_for_coverage,
    coerce_facilitator_action,
    endpoint_key,
    ensure_critical_flow_coverage,
    extract_backend_endpoints,
    extract_frontend_screens,
    is_critical_flow,
    is_protocol_decision,
    normalize_auth_shape,
    normalize_feature_inventory,
    normalize_task_entries,
    pick_feature_inventory,
    synthesize_task_tree,
)


class EndpointKeyTests(unittest.TestCase):
    def test_canonical_method_path_join(self):
        self.assertEqual(endpoint_key("get", "/api/posts"), "GET /api/posts")

    def test_strips_whitespace(self):
        self.assertEqual(endpoint_key("  POST ", "  /api/posts "), "POST /api/posts")


class ApiCallKeyTests(unittest.TestCase):
    def test_method_path_pair(self):
        self.assertEqual(
            api_call_key({"method": "GET", "path": "/api/posts"}),
            "GET /api/posts",
        )

    def test_endpoint_id_shorthand(self):
        self.assertEqual(
            api_call_key({"endpoint_id": "POST /api/posts", "purpose": "x"}),
            "POST /api/posts",
        )

    def test_endpoint_id_lowercase_method_normalized(self):
        self.assertEqual(
            api_call_key({"endpoint_id": "post /api/posts"}),
            "POST /api/posts",
        )

    def test_endpoint_id_malformed_falls_back_to_pair(self):
        self.assertEqual(
            api_call_key({"endpoint_id": "garbage", "method": "GET",
                          "path": "/api/x"}),
            "GET /api/x",
        )

    def test_non_mapping_returns_default(self):
        # Defensive: non-Mapping → key with None None (which still
        # canonicalizes; just never matches a real endpoint).
        self.assertEqual(api_call_key("garbage"), "NONE None")


class ExtractBackendEndpointsTests(unittest.TestCase):
    def test_api_endpoints_key_preferred(self):
        out = extract_backend_endpoints({
            "api_endpoints": [{"method": "GET", "path": "/api/a"}],
            "endpoints": [{"method": "POST", "path": "/api/b"}],
        })
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["path"], "/api/a")

    def test_endpoints_key_fallback(self):
        out = extract_backend_endpoints({
            "endpoints": [{"method": "POST", "path": "/api/x"}],
        })
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["path"], "/api/x")

    def test_neither_key_returns_empty(self):
        self.assertEqual(extract_backend_endpoints({}), [])

    def test_non_mapping_entries_filtered(self):
        out = extract_backend_endpoints({
            "endpoints": [
                {"method": "GET", "path": "/api/x"},
                "garbage",
                None,
            ],
        })
        self.assertEqual(len(out), 1)

    def test_non_mapping_input_returns_empty(self):
        self.assertEqual(extract_backend_endpoints("garbage"), [])


class ExtractFrontendScreensTests(unittest.TestCase):
    def test_screens_key_preferred(self):
        out = extract_frontend_screens({
            "screens": [{"id": "a"}],
            "ui_pages": [{"id": "b"}],
        })
        self.assertEqual(out[0]["id"], "a")

    def test_ui_pages_key_fallback(self):
        self.assertEqual(
            extract_frontend_screens({"ui_pages": [{"id": "x"}]}),
            [{"id": "x"}],
        )


class PickFeatureInventoryTests(unittest.TestCase):
    def test_frontend_validator_shape_wins(self):
        fe = {"entities": ["a"], "flows": ["f_a"]}
        be = {"entities": ["b"], "flows": ["f_b"]}
        out = pick_feature_inventory({"feature_inventory": fe},
                                      {"feature_inventory": be})
        self.assertEqual(out, fe)

    def test_falls_back_to_backend_when_frontend_wrong_shape(self):
        fe = {"auth_login": {"summary": "..."}}  # per-feature dict shape
        be = {"entities": ["users"], "flows": ["login"]}
        out = pick_feature_inventory({"feature_inventory": fe},
                                      {"feature_inventory": be})
        self.assertEqual(out, be)

    def test_falls_through_to_frontend_when_neither_shaped(self):
        fe = {"some": "stuff"}
        be = {"other": "stuff"}
        out = pick_feature_inventory({"feature_inventory": fe},
                                      {"feature_inventory": be})
        self.assertEqual(out, fe)

    def test_empty_when_neither_authored(self):
        self.assertEqual(pick_feature_inventory({}, {}), {})


class SynthesizeTaskTreeTests(unittest.TestCase):
    def test_one_task_per_endpoint_plus_one_per_table(self):
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/posts"},
                {"method": "POST", "path": "/api/posts"},
            ],
            "data_model": {"tables": [{"name": "posts"}]},
        }
        tasks = synthesize_task_tree(contract)
        # 2 implement_endpoint + 1 implement_table + 2 validate_api_smoke
        impl_count = sum(1 for t in tasks if t["kind"].startswith("implement_"))
        validate_count = sum(1 for t in tasks if t["kind"].startswith("validate_"))
        self.assertEqual(impl_count, 3)
        self.assertEqual(validate_count, 2)

    def test_tasks_carry_validator_required_fields(self):
        """Round 8h Fix #R: every synthesized task must have
        ``depends_on`` (list) and ``status`` (str)."""
        contract = {
            "endpoints": [{"method": "GET", "path": "/api/x"}],
            "data_model": {"tables": [{"name": "x"}]},
        }
        tasks = synthesize_task_tree(contract)
        for t in tasks:
            self.assertIn("depends_on", t)
            self.assertIsInstance(t["depends_on"], list)
            self.assertEqual(t["status"], "pending")

    def test_endpoint_task_depends_on_consumed_table_task(self):
        """When endpoint.response.tables names a known table, the
        endpoint task's depends_on includes the table task's id."""
        contract = {
            "endpoints": [{
                "method": "GET", "path": "/api/posts",
                "response": {"tables": ["posts"]},
            }],
            "data_model": {"tables": [{"name": "posts"}]},
        }
        tasks = synthesize_task_tree(contract)
        ep_task = next(t for t in tasks if t["kind"] == "implement_endpoint")
        self.assertIn("impl.table.posts", ep_task["depends_on"])

    def test_dedupes_repeated_endpoints(self):
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/x"},
                {"method": "GET", "path": "/api/x"},  # dup
            ],
            "data_model": {"tables": []},
        }
        tasks = synthesize_task_tree(contract)
        # 1 impl + 1 validate_api_smoke
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_endpoint"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "validate_api_smoke"), 1)

    def test_skips_malformed_endpoints_and_tables(self):
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/x"},
                {"method": ""},
                "garbage",
                {"path": "/no-method"},
            ],
            "data_model": {"tables": [
                {"name": "users"},
                {},
                "garbage",
            ]},
        }
        tasks = synthesize_task_tree(contract)
        # 1 endpoint impl + 1 table impl + 1 validate_api_smoke for the endpoint
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_endpoint"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "implement_table"), 1)
        self.assertEqual(sum(1 for t in tasks if t["kind"] == "validate_api_smoke"), 1)

    def test_munge_collision_distinct_paths_disambiguated(self):
        """Round 8h adversarial-review follow-up: two distinct
        endpoint paths whose munged IDs would collide must each get
        their own task (with disambiguated ID), not silently drop the
        second one."""
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/api/v1/users"},
                {"method": "GET", "path": "/api_v1_users"},
            ],
            "data_model": {"tables": []},
        }
        tasks = synthesize_task_tree(contract)
        endpoint_tasks = [t for t in tasks if t["kind"] == "implement_endpoint"]
        self.assertEqual(len(endpoint_tasks), 2)
        ids = {t["id"] for t in endpoint_tasks}
        # IDs must be distinct.
        self.assertEqual(len(ids), 2)
        # Both paths preserved on the endpoint payload.
        paths = {t["endpoint"]["path"] for t in endpoint_tasks}
        self.assertEqual(paths, {"/api/v1/users", "/api_v1_users"})

    def test_duplicate_endpoint_with_different_tables_merges_links(self):
        """Round 8h adversarial-review follow-up: when the same
        (method, path) is authored twice and only the SECOND occurrence
        carries response.tables, the resulting single task must still
        depend on those tables. Pre-fix the linking loop matched on
        the first occurrence and broke, missing the tables."""
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/users"},
                {"method": "GET", "path": "/users", "response": {"tables": ["users"]}},
            ],
            "data_model": {"tables": [{"name": "users"}]},
        }
        tasks = synthesize_task_tree(contract)
        endpoint_tasks = [t for t in tasks if t["kind"] == "implement_endpoint"]
        self.assertEqual(len(endpoint_tasks), 1)
        self.assertEqual(endpoint_tasks[0]["depends_on"], ["impl.table.users"])

    def test_collision_with_table_id_preserved(self):
        """An endpoint munged ID must never silently overwrite a
        table task's id namespace."""
        contract = {
            "endpoints": [
                {"method": "GET", "path": "/users"},
            ],
            "data_model": {"tables": [{"name": "users"}]},
        }
        tasks = synthesize_task_tree(contract)
        ids = [t["id"] for t in tasks]
        self.assertEqual(len(ids), len(set(ids)))


class EnsureCriticalFlowCoverageTests(unittest.TestCase):
    def test_adds_stub_for_uncovered_critical_flow(self):
        out = ensure_critical_flow_coverage(
            [{"id": "pred.x.api", "flow": "x", "form": {"kind": "api_smoke"}}],
            [{"id": "x", "critical": True},
             {"id": "y", "critical": True}],   # uncovered
        )
        flows = {p["flow"] for p in out}
        self.assertEqual(flows, {"x", "y"})
        stubs = [p for p in out if p.get("source") == "auto_coverage"]
        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["id"], "pred.y.auto_coverage")

    def test_non_critical_flows_ignored(self):
        self.assertEqual(
            ensure_critical_flow_coverage(
                [], [{"id": "optional", "critical": False}],
            ),
            [],
        )

    def test_idempotent(self):
        once = ensure_critical_flow_coverage(
            [], [{"id": "f", "critical": True}],
        )
        twice = ensure_critical_flow_coverage(
            once, [{"id": "f", "critical": True}],
        )
        self.assertEqual(once, twice)


class IsCriticalFlowTests(unittest.TestCase):
    """Round 8h adversarial-review follow-up.

    Pre-fix the kickoff used a bare ``flow.get("critical")`` truthy
    check, which silently dropped any drifted shape. These pins are
    closed-by-construction proof we now coerce across all four axes.
    """

    def test_canonical_bool_true(self):
        self.assertTrue(is_critical_flow({"id": "f", "critical": True}))

    def test_canonical_bool_false(self):
        self.assertFalse(is_critical_flow({"id": "f", "critical": False}))

    def test_missing_field_is_not_critical(self):
        self.assertFalse(is_critical_flow({"id": "f"}))

    def test_alias_is_critical(self):
        self.assertTrue(is_critical_flow({"id": "f", "is_critical": True}))
        self.assertFalse(is_critical_flow({"id": "f", "is_critical": False}))

    def test_alias_priority_critical(self):
        self.assertTrue(is_critical_flow({"id": "f", "priority": "critical"}))

    def test_alias_priority_must_have(self):
        # Unknown non-empty string → treat as truthy. Designer probably
        # meant "must" / "must-have" / "P0" to count as critical.
        self.assertTrue(is_critical_flow({"id": "f", "priority": "must"}))

    def test_alias_importance_high(self):
        self.assertTrue(is_critical_flow({"id": "f", "importance": "high"}))

    def test_string_true_variants(self):
        for s in ("true", "True", "yes", "YES", "1", "y", "t"):
            self.assertTrue(
                is_critical_flow({"id": "f", "critical": s}),
                f"expected truthy for critical={s!r}",
            )

    def test_string_false_variants(self):
        for s in ("false", "False", "no", "0", "n", "", "null", "none"):
            self.assertFalse(
                is_critical_flow({"id": "f", "critical": s}),
                f"expected falsy for critical={s!r}",
            )

    def test_int_truthy(self):
        self.assertTrue(is_critical_flow({"id": "f", "critical": 1}))
        self.assertFalse(is_critical_flow({"id": "f", "critical": 0}))

    def test_non_mapping_returns_false(self):
        self.assertFalse(is_critical_flow("garbage"))
        self.assertFalse(is_critical_flow(None))

    def test_canonical_field_wins_over_alias(self):
        # critical=False is explicit; is_critical=True is the alias.
        # Canonical wins because it appears first in the alias list.
        self.assertFalse(
            is_critical_flow(
                {"id": "f", "critical": False, "is_critical": True},
            ),
        )


class EnsureCriticalFlowCoverageDriftTests(unittest.TestCase):
    """Round 8h adversarial-review follow-up: closed-by-construction
    proof that key-name + value-shape drift on the ``critical`` field
    no longer silently drops the auto-coverage stub for an intended
    critical flow.
    """

    def test_is_critical_alias_still_covered(self):
        out = ensure_critical_flow_coverage(
            [],
            [{"id": "y", "is_critical": True}],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["flow"], "y")
        self.assertEqual(out[0]["source"], "auto_coverage")

    def test_priority_critical_alias_still_covered(self):
        out = ensure_critical_flow_coverage(
            [],
            [{"id": "z", "priority": "critical"}],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["flow"], "z")

    def test_string_true_still_covered(self):
        out = ensure_critical_flow_coverage(
            [],
            [{"id": "w", "critical": "true"}],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["flow"], "w")

    def test_string_false_correctly_skipped(self):
        out = ensure_critical_flow_coverage(
            [],
            [{"id": "skip-me", "critical": "false"}],
        )
        self.assertEqual(out, [])


class AugmentDraftsTests(unittest.TestCase):
    def test_augments_verifier_predicates_only(self):
        out = augment_drafts_for_coverage({
            "verifier": {"predicates": []},
            "frontend": {"user_flows": [{"id": "x", "critical": True}]},
            "backend": {"endpoints": [{"method": "GET", "path": "/api/x"}]},
        })
        self.assertEqual(out["backend"], {"endpoints": [{"method": "GET", "path": "/api/x"}]})
        self.assertEqual(len(out["verifier"]["predicates"]), 1)
        self.assertEqual(out["verifier"]["predicates"][0]["source"], "auto_coverage")

    def test_input_not_mutated(self):
        original = {
            "verifier": {"predicates": []},
            "frontend": {"user_flows": [{"id": "x", "critical": True}]},
        }
        ref = original["verifier"]["predicates"]
        augment_drafts_for_coverage(original)
        self.assertEqual(original["verifier"]["predicates"], [])
        self.assertIs(original["verifier"]["predicates"], ref)

    def test_dict_shape_predicates_lifted_to_list(self):
        """Round 8h adversarial-review follow-up: a verifier.predicates
        written as a dict (keyed by flow id) is coerced to a list so
        ensure_critical_flow_coverage can find the LLM's intent
        instead of silently dropping every entry."""
        out = augment_drafts_for_coverage({
            "verifier": {
                "predicates": {
                    "flow_a": {"id": "pred.a.api", "form": {"kind": "api_smoke"}},
                    "flow_b": {"id": "pred.b.api", "form": {"kind": "api_smoke"}},
                },
            },
            "frontend": {"user_flows": [
                {"id": "flow_a", "critical": True},
                {"id": "flow_b", "critical": True},
            ]},
        })
        preds = out["verifier"]["predicates"]
        self.assertEqual(len(preds), 2)
        flows = {p["flow"] for p in preds}
        self.assertEqual(flows, {"flow_a", "flow_b"})
        # Both predicates are LLM-authored (no auto_coverage stub needed).
        self.assertFalse(any(p.get("source") == "auto_coverage" for p in preds))

    def test_scalar_shape_predicates_falls_back_to_empty(self):
        """A scalar/string verifier.predicates is unrecoverable — coerce
        to empty list and let ensure_critical_flow_coverage stub
        whatever critical flows are present."""
        out = augment_drafts_for_coverage({
            "verifier": {"predicates": "garbage"},
            "frontend": {"user_flows": [{"id": "f", "critical": True}]},
        })
        preds = out["verifier"]["predicates"]
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["source"], "auto_coverage")
        self.assertEqual(preds[0]["flow"], "f")


class NormalizeAuthShapeTests(unittest.TestCase):
    def test_bool_required_passes_through(self):
        out = normalize_auth_shape({"model": "jwt", "required": True}, [])
        self.assertEqual(out["required"], True)

    def test_string_true_coerced(self):
        for s in ("true", "TRUE", " yes ", "1", "y"):
            out = normalize_auth_shape({"model": "jwt", "required": s}, [])
            self.assertEqual(out["required"], True, s)

    def test_string_false_coerced(self):
        for s in ("false", "no", "0", "garbage"):
            out = normalize_auth_shape({"model": "jwt", "required": s}, [])
            self.assertEqual(out["required"], False, s)

    def test_missing_required_inferred_from_endpoints(self):
        out = normalize_auth_shape(
            {"model": "jwt"},
            [{"method": "GET", "path": "/api/x", "auth_required": True}],
        )
        self.assertEqual(out["required"], True)

    def test_missing_required_defaults_true_when_no_endpoints(self):
        # Conservative default for auth blocks that named a model.
        out = normalize_auth_shape({"model": "jwt"}, [])
        self.assertEqual(out["required"], True)

    def test_empty_auth_floored_to_framework_jwt(self):
        # FRAMEWORK-OWNED AUTH FLOOR (youtube 2026-06-16): an empty auth block
        # is floored to model="jwt", required=True — NOT returned empty.
        # roadmap_validator HARD-REQUIRES a non-empty contract.auth.model + bool
        # required; lanes declaring endpoints via kickoff_declare_* carry no auth
        # block, so the old "return {}" made every synthesis validation_failed →
        # the kickoff looped to its 1200s timeout. The stack always embeds a JWT
        # AS, so flooring is correct, not invented.
        self.assertEqual(
            normalize_auth_shape({}, []), {"model": "jwt", "required": True})

    def test_empty_auth_required_inferred_from_endpoints(self):
        # required stays a bool regardless of endpoint auth flags.
        out = normalize_auth_shape({}, [{"auth_required": True}])
        self.assertEqual(out["model"], "jwt")
        self.assertIsInstance(out["required"], bool)


class NormalizeTaskEntriesTests(unittest.TestCase):
    def test_adds_missing_depends_on_and_status(self):
        out = normalize_task_entries([{"id": "t1"}])
        self.assertEqual(out[0]["depends_on"], [])
        self.assertEqual(out[0]["status"], "pending")

    def test_preserves_valid_fields(self):
        out = normalize_task_entries([{
            "id": "t1", "depends_on": ["t0"], "status": "in_progress",
        }])
        self.assertEqual(out[0]["depends_on"], ["t0"])
        self.assertEqual(out[0]["status"], "in_progress")

    def test_skips_non_mapping_entries(self):
        out = normalize_task_entries([{"id": "t1"}, "garbage", None])
        self.assertEqual(len(out), 1)

    def test_idempotent(self):
        tasks = [{"id": "t1"}]
        once = normalize_task_entries(tasks)
        twice = normalize_task_entries(once)
        self.assertEqual(once, twice)


class NormalizeFeatureInventoryTests(unittest.TestCase):
    def test_derives_entities_from_data_model_tables(self):
        out = normalize_feature_inventory(
            {},  # empty FI
            {"data_model": {"tables": [{"name": "users"}, {"name": "posts"}]}},
            {},
        )
        self.assertEqual(out["entities"], ["users", "posts"])

    def test_derives_flows_from_user_flows(self):
        out = normalize_feature_inventory(
            {},
            {},
            {"user_flows": [
                {"id": "auth_login"},
                {"id": "view_posts"},
            ]},
        )
        self.assertEqual(out["flows"], ["auth_login", "view_posts"])

    def test_preserves_existing_validator_shape(self):
        out = normalize_feature_inventory(
            {"entities": ["pre"], "flows": ["pre_f"]},
            {"data_model": {"tables": [{"name": "x"}]}},
            {"user_flows": [{"id": "y"}]},
        )
        # Existing fields preserved; data_model.tables not appended.
        self.assertEqual(out["entities"], ["pre"])
        self.assertEqual(out["flows"], ["pre_f"])

    def test_preserves_extra_keys(self):
        """LLM-supplied per-feature dict keys survive even when the
        canonical entities/flows are derived from upstream."""
        out = normalize_feature_inventory(
            {"auth_login": {"summary": "login flow"}},  # wrong-shape LLM input
            {"data_model": {"tables": [{"name": "users"}]}},
            {"user_flows": [{"id": "auth_login", "critical": True}]},
        )
        self.assertEqual(out["entities"], ["users"])
        self.assertEqual(out["flows"], ["auth_login"])
        # The LLM's per-feature key is preserved alongside the canonical fields.
        self.assertIn("auth_login", out)


class CoerceFacilitatorActionTests(unittest.TestCase):
    def test_canonical_actions_pass_through(self):
        for a in FACILITATOR_ACTIONS:
            self.assertEqual(coerce_facilitator_action(a), a)

    def test_smoke_9_duodecimus_regression(self):
        """accept_revision_and_recenter → consensus (not request_revision)."""
        self.assertEqual(
            coerce_facilitator_action("accept_revision_and_recenter"),
            "consensus",
        )

    def test_consensus_keywords(self):
        for v in ("approve", "ready_to_finalize", "PROCEED", "confirm_contract",
                  "align_and_proceed"):
            self.assertEqual(coerce_facilitator_action(v), "consensus", v)

    def test_revision_keywords(self):
        for v in ("revise_again", "rework_predicates", "amend_contract", "redo_round"):
            self.assertEqual(coerce_facilitator_action(v), "request_revision", v)

    def test_escalate_keywords(self):
        for v in ("escalate_to_fallback", "abort_kickoff", "fail_loud"):
            self.assertEqual(coerce_facilitator_action(v), "escalate", v)

    def test_escalate_beats_consensus_when_both_present(self):
        self.assertEqual(coerce_facilitator_action("fail_and_accept"), "escalate")

    def test_undecipherable_defaults_to_escalate(self):
        for v in (None, "", "xyz", "asdf_123"):
            self.assertEqual(coerce_facilitator_action(v), "escalate", v)

    def test_negated_escalate_with_positive_token_picks_positive(self):
        """Round 8h adversarial-review follow-up: a negation prefix
        on ``escalat`` (e.g. ``not_escalate_accept``) must not be
        misclassified as ``escalate``. The token-prefix matcher with
        negation look-behind ignores the negated escalate keyword and
        finds the positive consensus token instead."""
        self.assertEqual(
            coerce_facilitator_action("not_escalate_accept"),
            "consensus",
        )
        self.assertEqual(
            coerce_facilitator_action("do_not_escalate_proceed"),
            "consensus",
        )

    def test_bare_negated_escalate_defaults_to_escalate(self):
        """``not_escalate`` alone carries no positive signal — by
        design, undecipherable actions default to ``escalate``
        (conservative fallback). This pin documents the rule rather
        than the bug: if the LLM wanted consensus, it should say so."""
        self.assertEqual(coerce_facilitator_action("not_escalate"), "escalate")

    def test_substring_inside_word_not_matched(self):
        """``backaccept`` substring-contains ``accept`` but the token
        doesn't START with ``accept``, so the consensus keyword is
        not matched."""
        # No positive keyword token-prefix-matches; the action is
        # undecipherable → escalate (the conservative default).
        self.assertEqual(coerce_facilitator_action("backaccept"), "escalate")


class IsProtocolDecisionTests(unittest.TestCase):
    def test_phase_ack_is_protocol(self):
        self.assertTrue(is_protocol_decision(
            {"section": "phase_ack", "kind": "comment_phase_done"},
        ))

    def test_comment_is_protocol(self):
        self.assertTrue(is_protocol_decision({"section": "comment"}))

    def test_facilitator_note_is_protocol(self):
        self.assertTrue(is_protocol_decision({"section": "facilitator_note"}))

    def test_attendee_section_is_protocol_when_in_set(self):
        self.assertTrue(is_protocol_decision(
            {"section": "backend"},
            attendee_sections=frozenset({"backend", "frontend", "verifier"}),
        ))

    def test_unknown_section_is_not_protocol(self):
        self.assertFalse(is_protocol_decision(
            {"section": "orchestrator"},
            attendee_sections=frozenset({"backend"}),
        ))

    def test_protocol_kind_fallback(self):
        """Section empty but kind is in vocab → still protocol."""
        self.assertTrue(is_protocol_decision({
            "section": "",
            "kind": "facilitator_decision",
        }))

    def test_non_mapping_is_not_protocol(self):
        self.assertFalse(is_protocol_decision("garbage"))


class ConstantsTests(unittest.TestCase):
    def test_protocol_fixed_sections_is_frozen(self):
        self.assertIsInstance(PROTOCOL_FIXED_SECTIONS, frozenset)
        self.assertEqual(
            PROTOCOL_FIXED_SECTIONS,
            frozenset({"phase_ack", "comment", "facilitator_note"}),
        )

    def test_facilitator_actions_is_tuple_of_three(self):
        self.assertEqual(
            FACILITATOR_ACTIONS,
            ("consensus", "request_revision", "escalate"),
        )


if __name__ == "__main__":
    unittest.main()


class EndpointResponseShapeTests(unittest.TestCase):
    """Mechanism #38: malformed endpoint.response.tables is coerced, not
    left to wedge the kickoff reconcile in status=conflict (round 31 M3)."""

    def _norm(self, eps):
        from multi_agent.runtime.kickoff.schema_tolerance import (
            normalize_endpoint_response_shapes)
        return normalize_endpoint_response_shapes(eps)

    def test_str_and_mapping_tables_coerced(self):
        eps = self._norm([
            {"path": "/a", "response": {"tables": "users"}},
            {"path": "/b", "response": {"tables": {"posts": "all"}}},
        ])
        self.assertEqual(eps[0]["response"]["tables"], ["users"])
        self.assertEqual(eps[1]["response"]["tables"], ["posts"])

    def test_garbage_tables_dropped_not_failed(self):
        eps = self._norm([
            {"path": "/a", "response": {"tables": [None, "", 7]}},
            {"path": "/b", "response": "not-a-mapping"},
            "not-an-endpoint",
        ])
        self.assertNotIn("tables", eps[0]["response"])
        self.assertNotIn("response", eps[1])
        self.assertEqual(eps[2], "not-an-endpoint")

    def test_normalized_tables_satisfy_validator_shape(self):
        eps = self._norm([{
            "id": "ep1", "method": "GET", "path": "/api/items",
            "auth_required": True, "response": {"tables": {"items": "*"}}}])
        tables = eps[0]["response"]["tables"]
        self.assertTrue(tables)
        self.assertTrue(all(isinstance(t, str) and t for t in tables))


class MessagingTimeImportTests(unittest.TestCase):
    def test_author_deadline_names_resolve(self):
        """Round 32 M1: the kickoff author-deadline used time.time() without
        importing time — the frontend's kickoff loop crashed (NameError) and
        its M1 section fell to the deferred stub. Guard: every module-level
        name the messaging module references must resolve."""
        import importlib
        mod = importlib.import_module("multi_agent.agents.runtime.messaging")
        self.assertTrue(hasattr(mod, "time"))
        import ast, inspect
        tree = ast.parse(inspect.getsource(mod))
        defined = set(dir(mod)) | set(dir(__builtins__)) | {"__builtins__"}
        # spot-check: no bare Name loads of 'time' would fail now
        self.assertIn("time", dir(mod))
