"""Regression tests for runtime.kickoff.arbitration_table.

Closed-by-construction discipline: each test pins EXACTLY one
invariant the module promises in its docstring.

Pinned invariants:
1. ARBITRATION_TABLE matches plan §Step-3 verbatim (4 rows, exact
   (authority, reviser) tuples). If anyone edits the table, this
   test breaks first.
2. resolve_conflict picks the pinned reviser for each registered
   kind — the determinism contract for the kickoff polling loop.
3. resolve_conflict falls back to the alphabetical-agent tiebreak
   when kind is unregistered — guards the "unknown check kind" path
   the orchestrator hits when the cross-check suite grows.
4. resolve_conflict raises ValueError (no phantom default) on
   missing/empty id, kind, or agents — the charter no-fallback
   discipline at the function boundary.
5. tiebreak_by_alphabetical_agent_id raises ValueError on empty
   input — the obvious failure mode for the helper.
6. arbitrate preserves input order 1:1 and reports ok=False the
   moment any conflict falls through to the tiebreak path
   (deferral signal for run_kickoff).
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

from multi_agent.runtime.kickoff.arbitration_table import (  # noqa: E402
    ARBITRATION_TABLE,
    arbitrate,
    resolve_conflict,
    tiebreak_by_alphabetical_agent_id,
)


class ArbitrationTableShapeTests(unittest.TestCase):
    def test_table_matches_plan_step3_verbatim(self):
        # Invariant 1: round-8e.1 collapsed 4 rows → 3. The
        # ui_pages_vs_user_flows row was retired with the
        # design→frontend merge (both fields now intra-section in
        # frontend, no cross-section arbitration needed).
        self.assertEqual(
            ARBITRATION_TABLE,
            {
                "api_vs_frontend": ("backend", "frontend"),
                "api_vs_data_model": ("backend", "backend"),
                "test_strategy_coverage": ("verifier", "verifier"),
            },
        )


class ResolveConflictHappyPathTests(unittest.TestCase):
    def _conflict(self, kind, agents=("backend", "frontend")):
        return {"id": f"c_{kind}", "kind": kind, "agents": list(agents)}

    def test_api_vs_frontend_reviser_is_frontend(self):
        # Invariant 2: pinned reviser per row.
        self.assertEqual(
            resolve_conflict(self._conflict("api_vs_frontend")),
            "frontend",
        )

    def test_api_vs_data_model_reviser_is_backend(self):
        self.assertEqual(
            resolve_conflict(
                self._conflict("api_vs_data_model", ("backend", "backend"))
            ),
            "backend",
        )

    def test_ui_pages_vs_user_flows_unknown_kind_falls_through_to_tiebreak(self):
        # Round 8e.1: ui_pages_vs_user_flows row removed; if a stale
        # caller emits the kind, it falls through to alphabetical
        # tiebreak rather than matching the table.
        # (design is sorted < frontend, but design isn't a valid actor
        # post-merge — this test pins the fallthrough is "ANY
        # alphabetically-first agent", not "design".)
        result = resolve_conflict(
            self._conflict("ui_pages_vs_user_flows", ("frontend",))
        )
        self.assertEqual(result, "frontend")

    def test_test_strategy_coverage_reviser_is_verifier(self):
        self.assertEqual(
            resolve_conflict(
                self._conflict("test_strategy_coverage", ("verifier",))
            ),
            "verifier",
        )

    def test_resolve_is_deterministic_across_repeated_calls(self):
        # Invariant 2: same input → same output, every time.
        conflict = self._conflict("api_vs_frontend")
        seen = {resolve_conflict(conflict) for _ in range(50)}
        self.assertEqual(seen, {"frontend"})


class ResolveConflictTiebreakTests(unittest.TestCase):
    def test_unknown_kind_falls_through_to_alphabetical_tiebreak(self):
        # Invariant 3: unregistered kind → alphabetical reviser.
        # ("zeta" > "alpha"; alphabetically-first is "alpha")
        conflict = {
            "id": "c1",
            "kind": "totally_unknown_kind_v9",
            "agents": ["zeta", "alpha", "mu"],
        }
        self.assertEqual(resolve_conflict(conflict), "alpha")

    def test_tiebreak_helper_picks_first_alphabetically(self):
        self.assertEqual(
            tiebreak_by_alphabetical_agent_id(["frontend", "backend", "design"]),
            "backend",
        )


class ResolveConflictFailureModeTests(unittest.TestCase):
    # Invariant 4: missing/empty required fields raise ValueError.

    def test_missing_id_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict({"kind": "api_vs_frontend", "agents": ["backend", "frontend"]})

    def test_empty_id_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict({"id": "", "kind": "api_vs_frontend", "agents": ["backend"]})

    def test_missing_kind_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict({"id": "c1", "agents": ["backend", "frontend"]})

    def test_empty_kind_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict({"id": "c1", "kind": "", "agents": ["backend"]})

    def test_missing_agents_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict({"id": "c1", "kind": "api_vs_frontend"})

    def test_empty_agents_list_raises(self):
        # Invariant 4 + 5: empty agents → no possible reviser → fail loud.
        with self.assertRaises(ValueError):
            resolve_conflict({"id": "c1", "kind": "anything_unregistered", "agents": []})

    def test_non_mapping_input_raises(self):
        with self.assertRaises(ValueError):
            resolve_conflict("not a mapping")  # type: ignore[arg-type]


class TiebreakEdgeCaseTests(unittest.TestCase):
    # Invariant 5: empty-input edge case for the helper.

    def test_empty_agents_iterable_raises(self):
        with self.assertRaises(ValueError):
            tiebreak_by_alphabetical_agent_id([])

    def test_empty_string_agent_raises(self):
        with self.assertRaises(ValueError):
            tiebreak_by_alphabetical_agent_id(["backend", ""])

    def test_non_string_agent_raises(self):
        with self.assertRaises(ValueError):
            tiebreak_by_alphabetical_agent_id(["backend", 42])  # type: ignore[list-item]


class ArbitrateAggregateTests(unittest.TestCase):
    def test_all_registered_kinds_yield_ok_true(self):
        # Invariant 6: pinned-table path → ok=True, source=arbitration_table.
        conflicts = [
            {"id": "c1", "kind": "api_vs_frontend", "agents": ["backend", "frontend"]},
            {"id": "c2", "kind": "test_strategy_coverage", "agents": ["verifier"]},
        ]
        result = arbitrate(conflicts)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["items"],
            [
                {
                    "conflict_id": "c1",
                    "kind": "api_vs_frontend",
                    "reviser": "frontend",
                    "source": "arbitration_table",
                },
                {
                    "conflict_id": "c2",
                    "kind": "test_strategy_coverage",
                    "reviser": "verifier",
                    "source": "arbitration_table",
                },
            ],
        )

    def test_any_tiebreak_flips_ok_to_false(self):
        # Invariant 6: tiebreak path is a deferral signal, not silent pass.
        conflicts = [
            {"id": "c1", "kind": "api_vs_frontend", "agents": ["backend", "frontend"]},
            {"id": "c2", "kind": "novel_kind", "agents": ["zeta", "alpha"]},
        ]
        result = arbitrate(conflicts)
        self.assertFalse(result["ok"])
        # input order preserved 1:1
        self.assertEqual([i["conflict_id"] for i in result["items"]], ["c1", "c2"])
        # tiebreak item sourced + resolved correctly
        self.assertEqual(result["items"][1]["source"], "tiebreak")
        self.assertEqual(result["items"][1]["reviser"], "alpha")

    def test_empty_conflicts_yields_ok_true_empty_items(self):
        # Edge case: no conflicts is a no-op success.
        result = arbitrate([])
        self.assertEqual(result, {"ok": True, "items": []})


if __name__ == "__main__":
    unittest.main()
