"""Closed-by-construction tests for ``runtime/kickoff/roadmap_validator.py``.

One sharp test per invariant the function promises (per workflow rules):

  * happy-path: well-formed M2 roadmap → ``ok=True`` with no error findings
  * happy-path: well-formed M1 roadmap with feature_inventory → ``ok=True``
  * obvious failure mode: task_tree dependency cycle → ``ok=False`` and a
    cycle finding (the dominant generated-code bug class this validator
    is designed to catch — see charter §8)
  * empty-input edge case: ``{}`` → ``ok=False`` with errors per missing
    section, AND caller-misuse (None roadmap / milestone_index < 1) raises
    ValueError (no phantom defaults, per charter)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.roadmap_validator import (  # noqa: E402
    ACCEPTANCE_PREDICATE_KINDS,
    VALID_TASK_STATUSES,
    validate_roadmap,
)


# ---------------------------------------------------------------------------
# Fixtures (well-formed snapshots — single source of truth, mutated per test)
# ---------------------------------------------------------------------------


def _valid_contract() -> dict:
    return {
        "endpoints": [
            {
                "method": "POST",
                "path": "/api/auth/login",
                "response_key": "token",
                "auth_required": False,
            },
            {
                "method": "GET",
                "path": "/api/posts",
                "response_key": "posts",
                "auth_required": True,
            },
        ],
        "data_model": {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "uuid"},
                        {"name": "email", "type": "text"},
                    ],
                },
                {
                    "name": "posts",
                    "columns": [
                        {"name": "id", "type": "uuid"},
                        {"name": "author_id", "type": "uuid"},
                    ],
                },
            ],
        },
        "auth": {"model": "jwt", "required": True},
    }


def _valid_task_tree() -> list:
    return [
        {
            "id": "t1_schema",
            "owner": "backend",
            "depends_on": [],
            "kind": "schema",
            "status": "pending",
        },
        {
            "id": "t2_auth_api",
            "owner": "backend",
            "depends_on": ["t1_schema"],
            "kind": "endpoint",
            "status": "pending",
        },
        {
            "id": "t3_ui",
            "owner": "frontend",
            "depends_on": ["t2_auth_api"],
            "kind": "ui",
            "status": "pending",
        },
    ]


def _valid_predicates() -> list:
    return [
        {
            "id": "p_login_smoke",
            "flow": "auth.login",
            "form": {"kind": "api_smoke", "endpoint": "POST /api/auth/login"},
        },
        {
            "id": "p_posts_list",
            "flow": "posts.list",
            "form": {"kind": "ui_flow", "route": "/feed"},
        },
    ]


def _valid_m2_roadmap() -> dict:
    return {
        "milestone_index": 2,
        "contract": _valid_contract(),
        "task_tree": _valid_task_tree(),
        "acceptance_predicates": _valid_predicates(),
        "done_def": [
            "all M2 tasks status==done",
            "api_smoke passes for new endpoints",
        ],
    }


def _valid_m1_roadmap() -> dict:
    rm = _valid_m2_roadmap()
    rm["milestone_index"] = 1
    rm["feature_inventory"] = {
        "entities": ["user", "post", "comment"],
        "flows": ["auth.login", "posts.list", "posts.create"],
    }
    return rm


# ---------------------------------------------------------------------------
# Tests — one per invariant the function promises.
# ---------------------------------------------------------------------------


class HappyPathTests(unittest.TestCase):
    """Well-formed roadmaps validate cleanly."""

    def test_m2_well_formed_ok_true_no_errors(self) -> None:
        result = validate_roadmap(_valid_m2_roadmap(), milestone_index=2)
        self.assertTrue(
            result["ok"],
            msg=f"unexpected findings: {result['findings']}",
        )
        self.assertEqual(result["milestone_index"], 2)
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [])

    def test_m1_with_feature_inventory_ok_true(self) -> None:
        result = validate_roadmap(_valid_m1_roadmap(), milestone_index=1)
        self.assertTrue(
            result["ok"],
            msg=f"unexpected findings: {result['findings']}",
        )
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [])

    def test_m1_without_feature_inventory_fails(self) -> None:
        # M1 demands feature_inventory; M2+ does not.
        rm = _valid_m1_roadmap()
        rm.pop("feature_inventory")
        result = validate_roadmap(rm, milestone_index=1)
        self.assertFalse(result["ok"])
        sections = {f["section"] for f in result["findings"]
                    if f["severity"] == "error"}
        self.assertIn("feature_inventory", sections)

    def test_predicate_kinds_v1_vocabulary(self) -> None:
        # The published v1 vocabulary — guard against silent expansion.
        self.assertEqual(
            ACCEPTANCE_PREDICATE_KINDS,
            {"api_smoke", "ui_flow", "sql_check", "predicate_dsl"},
        )


class TaskTreeCycleTests(unittest.TestCase):
    """The dominant failure mode the validator must catch: depends_on cycles
    in the task tree would cause the polling loop to deadlock."""

    def test_simple_cycle_flagged_as_error(self) -> None:
        rm = _valid_m2_roadmap()
        rm["task_tree"] = [
            {
                "id": "a", "owner": "backend", "depends_on": ["b"],
                "kind": "endpoint", "status": "pending",
            },
            {
                "id": "b", "owner": "backend", "depends_on": ["a"],
                "kind": "endpoint", "status": "pending",
            },
        ]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        cycle_findings = [
            f for f in result["findings"]
            if f["section"] == "task_tree"
            and f["id"].startswith("cycle:")
            and f["severity"] == "error"
        ]
        self.assertEqual(
            len(cycle_findings), 1,
            msg=f"expected exactly one cycle finding, got: {cycle_findings}",
        )

    def test_self_loop_flagged_as_cycle(self) -> None:
        rm = _valid_m2_roadmap()
        rm["task_tree"] = [
            {
                "id": "loops", "owner": "backend", "depends_on": ["loops"],
                "kind": "endpoint", "status": "pending",
            },
        ]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        cycle_ids = [f["id"] for f in result["findings"]
                     if f["id"].startswith("cycle:")]
        self.assertTrue(cycle_ids, msg=f"got: {result['findings']}")

    def test_unknown_dep_flagged_as_error(self) -> None:
        rm = _valid_m2_roadmap()
        rm["task_tree"][0]["depends_on"] = ["nonexistent_task"]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        unknown = [
            f for f in result["findings"]
            if "unknown_dep:nonexistent_task" in f["id"]
        ]
        self.assertEqual(len(unknown), 1)


class EmptyInputAndCallerMisuseTests(unittest.TestCase):
    """Empty data → error findings (not raises). Caller misuse → ValueError."""

    def test_empty_roadmap_returns_errors_per_missing_section(self) -> None:
        result = validate_roadmap({}, milestone_index=1)
        self.assertFalse(result["ok"])
        sections = {
            f["section"] for f in result["findings"]
            if f["severity"] == "error"
        }
        # Every charter §5 required section is missing — each must produce
        # an error finding (closed-by-construction).
        self.assertIn("contract", sections)
        self.assertIn("task_tree", sections)
        self.assertIn("acceptance_predicates", sections)
        self.assertIn("done_def", sections)
        # M1 also requires feature_inventory.
        self.assertIn("feature_inventory", sections)

    def test_milestone_index_below_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_roadmap(_valid_m2_roadmap(), milestone_index=0)

    def test_milestone_index_none_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_roadmap(_valid_m2_roadmap(), milestone_index=None)  # type: ignore[arg-type]

    def test_roadmap_non_mapping_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_roadmap("not a mapping", milestone_index=1)  # type: ignore[arg-type]

    def test_milestone_index_echo_mismatch_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        rm["milestone_index"] = 5  # caller passes 2, roadmap echoes 5
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        mismatches = [
            f for f in result["findings"]
            if f["id"] == "milestone_index_mismatch"
        ]
        self.assertEqual(len(mismatches), 1)


class DeepChainTests(unittest.TestCase):
    """Round-7 reviewer residue #1: cycle detection MUST NOT recurse — a
    long linear dep chain MUST validate without raising RecursionError."""

    def test_long_linear_chain_no_recursion_error(self) -> None:
        # Build a 1500-task linear chain (well above Python's default
        # recursion limit of 1000). A recursive DFS would crash with
        # RecursionError; the iterative DFS must produce a clean result.
        n = 1500
        chain = []
        for i in range(n):
            deps = [f"t{i - 1}"] if i > 0 else []
            chain.append({
                "id": f"t{i}",
                "owner": "backend",
                "depends_on": deps,
                "kind": "endpoint",
                "status": "pending",
            })
        rm = _valid_m2_roadmap()
        rm["task_tree"] = chain
        # Must not raise — the whole point of the iterative rewrite.
        result = validate_roadmap(rm, milestone_index=2)
        self.assertTrue(
            result["ok"],
            msg=f"unexpected errors: "
                f"{[f for f in result['findings'] if f['severity'] == 'error']}",
        )

    def test_deep_cycle_at_chain_tail_detected(self) -> None:
        # Build a long chain that loops back at the end — the iterative
        # DFS must still detect the cycle (no recursion bail-out).
        n = 1500
        chain = []
        for i in range(n):
            if i == 0:
                deps = [f"t{n - 1}"]  # head depends on tail → cycle
            else:
                deps = [f"t{i - 1}"]
            chain.append({
                "id": f"t{i}",
                "owner": "backend",
                "depends_on": deps,
                "kind": "endpoint",
                "status": "pending",
            })
        rm = _valid_m2_roadmap()
        rm["task_tree"] = chain
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        cycle_findings = [
            f for f in result["findings"]
            if f["section"] == "task_tree" and f["id"].startswith("cycle:")
        ]
        self.assertTrue(cycle_findings, msg="expected at least one cycle finding")


class TaskStatusVocabularyTests(unittest.TestCase):
    """Round-7 reviewer residue #3: task.status MUST be checked against the
    closed vocabulary, not just non-emptiness."""

    def test_vocabulary_constant_is_published(self) -> None:
        # Guard against silent expansion — the v1 vocabulary is closed.
        self.assertEqual(
            VALID_TASK_STATUSES,
            {"pending", "ready", "claimed", "done",
             "blocked", "failed", "cancelled"},
        )

    def test_unknown_status_flagged_as_error(self) -> None:
        rm = _valid_m2_roadmap()
        rm["task_tree"][0]["status"] = "in_progress"  # not in v1 vocab
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        status_errors = [
            f for f in result["findings"]
            if f["section"] == "task_tree"
            and f["id"].endswith(".status")
            and f["severity"] == "error"
            and "in_progress" in f["message"]
        ]
        self.assertEqual(
            len(status_errors), 1,
            msg=f"expected one status-vocab error, got: {result['findings']}",
        )

    def test_every_valid_status_accepted(self) -> None:
        # Each member of the published vocabulary MUST be accepted.
        for status in sorted(VALID_TASK_STATUSES):
            rm = _valid_m2_roadmap()
            for t in rm["task_tree"]:
                t["status"] = status
            result = validate_roadmap(rm, milestone_index=2)
            status_errors = [
                f for f in result["findings"]
                if f["section"] == "task_tree" and f["id"].endswith(".status")
            ]
            self.assertEqual(
                status_errors, [],
                msg=f"status {status!r} should be accepted; got: {status_errors}",
            )


class EndpointResponseTablesTests(unittest.TestCase):
    """KickoffEndpoint.response.tables MUST be a list of non-empty strings
    when present (cross_check_suite.api_vs_data_model reads them verbatim)."""

    def test_response_tables_list_of_strings_accepted(self) -> None:
        rm = _valid_m2_roadmap()
        rm["contract"]["endpoints"][1]["response"] = {
            "tables": ["posts", "users"],
            "shape": {"type": "list", "items": "Post"},
        }
        result = validate_roadmap(rm, milestone_index=2)
        self.assertTrue(
            result["ok"],
            msg=f"unexpected findings: {result['findings']}",
        )

    def test_response_not_mapping_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        rm["contract"]["endpoints"][0]["response"] = "not a mapping"
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "contract"
            and f["id"].endswith(".response")
        ]
        self.assertEqual(len(bad), 1)

    def test_response_tables_not_list_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        rm["contract"]["endpoints"][0]["response"] = {"tables": "posts"}
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "contract"
            and f["id"].endswith(".response.tables")
        ]
        self.assertEqual(len(bad), 1)

    def test_response_tables_non_string_entry_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        rm["contract"]["endpoints"][0]["response"] = {
            "tables": ["posts", "", 42],
        }
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "contract"
            and ".response.tables[" in f["id"]
        ]
        # Empty string AND integer entry — both flagged.
        self.assertEqual(len(bad), 2)


class PredicateShapeTests(unittest.TestCase):
    """Acceptance predicates: shape + v1 vocabulary."""

    def test_unsupported_predicate_kind_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        rm["acceptance_predicates"][0]["form"]["kind"] = "magic_oracle"
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "acceptance_predicates"
            and "form.kind" in f["id"]
        ]
        self.assertEqual(len(bad), 1)

    def test_missing_predicate_form_flagged(self) -> None:
        rm = _valid_m2_roadmap()
        del rm["acceptance_predicates"][0]["form"]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])


class ReviewerThinListTests(unittest.TestCase):
    """Round-7 reviewer thin-test list for roadmap_validator (REFUTED #4).

    Each test below is a verbatim regression guard for one bullet on the
    reviewer's published list; each MUST fail closed-by-construction if
    the corresponding check is removed from ``roadmap_validator.py``.
    """

    # --- 1) duplicate-id detection -----------------------------------------

    def test_duplicate_task_ids_flagged_as_error(self) -> None:
        # Two tasks with the same id MUST surface as a single
        # ``duplicate_id:<id>`` error finding under section=task_tree.
        # Without the duplicate-id branch in _check_task_tree, the second
        # occurrence would silently overwrite by_id and ok would stay True.
        rm = _valid_m2_roadmap()
        rm["task_tree"] = [
            {
                "id": "twin", "owner": "backend", "depends_on": [],
                "kind": "schema", "status": "pending",
            },
            {
                "id": "twin", "owner": "backend", "depends_on": [],
                "kind": "endpoint", "status": "pending",
            },
        ]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        dups = [
            f for f in result["findings"]
            if f["section"] == "task_tree"
            and f["id"] == "duplicate_id:twin"
            and f["severity"] == "error"
        ]
        self.assertEqual(
            len(dups), 1,
            msg=f"expected exactly one duplicate_id finding, got: {result['findings']}",
        )

    # --- 2) missing response_key / non-bool auth_required ------------------

    def test_endpoint_missing_response_key_flagged(self) -> None:
        # Strip response_key from an endpoint — _check_contract MUST emit
        # an ``endpoint[<idx>].response_key`` error. Without the
        # required-keys loop, the endpoint would slip through silently.
        rm = _valid_m2_roadmap()
        del rm["contract"]["endpoints"][0]["response_key"]
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        missing = [
            f for f in result["findings"]
            if f["section"] == "contract"
            and f["id"] == "endpoint[0].response_key"
            and f["severity"] == "error"
        ]
        self.assertEqual(
            len(missing), 1,
            msg=f"expected one missing-response_key finding, got: {result['findings']}",
        )

    def test_endpoint_auth_required_non_bool_flagged(self) -> None:
        # auth_required='yes' (string) MUST be rejected — the polling loop
        # downstream branches on a bool. Without the isinstance(..., bool)
        # check, a truthy string would coerce to True and pass silently.
        rm = _valid_m2_roadmap()
        rm["contract"]["endpoints"][0]["auth_required"] = "yes"
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "contract"
            and f["id"] == "endpoint[0].auth_required"
            and f["severity"] == "error"
        ]
        self.assertEqual(
            len(bad), 1,
            msg=f"expected one non-bool auth_required finding, got: {result['findings']}",
        )

    # --- 3) deep-chain non-crash (regression guard for round-7a fix) -------

    def test_deep_chain_does_not_raise_recursion_error(self) -> None:
        # The round-7a fix replaced the recursive DFS with an iterative
        # one. This test is the explicit regression guard: a 2000-task
        # linear chain (well above Python's default recursion limit of
        # 1000) MUST return a ValidationResult, NOT raise RecursionError.
        # If the iterative DFS is reverted, ``validate_roadmap`` will
        # crash with RecursionError and this test FAILs closed-by-
        # construction.
        n = 2000
        chain = [
            {
                "id": f"t{i}",
                "owner": "backend",
                "depends_on": [f"t{i - 1}"] if i > 0 else [],
                "kind": "endpoint",
                "status": "pending",
            }
            for i in range(n)
        ]
        rm = _valid_m2_roadmap()
        rm["task_tree"] = chain
        # Direct assertion: the call MUST NOT raise. assertRaises is the
        # wrong tool here (we want NO exception); we wrap in try/except
        # so a RecursionError surfaces as a clear test failure rather
        # than an error.
        try:
            result = validate_roadmap(rm, milestone_index=2)
        except RecursionError as exc:  # pragma: no cover — regression guard
            self.fail(
                f"validate_roadmap raised RecursionError on a {n}-task "
                f"linear chain — the iterative DFS rewrite has been "
                f"reverted: {exc}"
            )
        # A pure linear chain has no cycles → must validate cleanly.
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(
            errors, [],
            msg=f"unexpected errors on linear chain: {errors}",
        )
        self.assertTrue(result["ok"])

    # --- 4) task status vocabulary: status='banana' → finding --------------

    def test_status_banana_flagged_as_error(self) -> None:
        # Reviewer's literal example: status='banana' MUST produce an
        # error finding. Without the ``status not in VALID_TASK_STATUSES``
        # branch, an arbitrary string would coerce to "non-empty and
        # therefore fine" and the polling loop would deadlock waiting
        # for it to transition to a known terminal state.
        rm = _valid_m2_roadmap()
        rm["task_tree"][0]["status"] = "banana"
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "task_tree"
            and f["id"].endswith(".status")
            and f["severity"] == "error"
            and "banana" in f["message"]
        ]
        self.assertEqual(
            len(bad), 1,
            msg=f"expected one banana-status finding, got: {result['findings']}",
        )

    # --- 5) predicate body shape: wholly missing form body -----------------

    def test_predicate_form_wholly_missing_flagged(self) -> None:
        # Predicate with NO ``form`` key at all MUST be rejected — without
        # this guard, a predicate with only {id, flow} would slip through
        # and the runtime predicate-runner would KeyError at execution.
        # This is the "predicate body shape" entry on the reviewer's
        # list: the future deeper check, with the minimum-viable guard
        # being "catch when predicate body is wholly missing".
        rm = _valid_m2_roadmap()
        # Drop the form key entirely from the first predicate.
        rm["acceptance_predicates"][0] = {
            "id": "p_no_body",
            "flow": "auth.login",
            # NOTE: no "form" key at all
        }
        result = validate_roadmap(rm, milestone_index=2)
        self.assertFalse(result["ok"])
        bad = [
            f for f in result["findings"]
            if f["section"] == "acceptance_predicates"
            and f["id"] == "predicate[0].form"
            and f["severity"] == "error"
        ]
        self.assertEqual(
            len(bad), 1,
            msg=f"expected one missing-form finding, got: {result['findings']}",
        )


if __name__ == "__main__":
    unittest.main()
