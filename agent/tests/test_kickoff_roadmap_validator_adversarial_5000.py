"""Adversarial round-7a probe: 5000-task linear chain MUST NOT recurse.

The roadmap_validator iterative-DFS rewrite (round-7a) replaced a recursive
``_dfs`` that would crash with ``RecursionError`` on dep chains longer than
Python's default recursion limit (~1000). This probe goes well past that
ceiling — 5000 tasks — and asserts:

  * a clean 5000-long linear chain validates without raising
    ``RecursionError`` (proving the recursion-free rewrite holds at 5x the
    default ceiling),
  * a 5000-long chain with a tail-back edge still produces a cycle finding
    via the iterative DFS (proving cycle detection survives at depth).

These tests guard the round-7a reviewer-residue #1 fix; they would crash
or silently miss the cycle on the pre-round-7a recursive implementation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.roadmap_validator import (  # noqa: E402
    validate_roadmap,
)


def _valid_contract() -> dict:
    return {
        "endpoints": [
            {
                "method": "POST",
                "path": "/api/auth/login",
                "response_key": "token",
                "auth_required": False,
            },
        ],
        "data_model": {
            "tables": [
                {
                    "name": "users",
                    "columns": [{"name": "id", "type": "uuid"}],
                },
            ],
        },
        "auth": {"model": "jwt", "required": True},
    }


def _valid_predicates() -> list:
    return [
        {
            "id": "p_smoke",
            "flow": "auth.login",
            "form": {"kind": "api_smoke", "endpoint": "POST /api/auth/login"},
        },
    ]


def _roadmap_with_chain(chain: list) -> dict:
    return {
        "milestone_index": 2,
        "contract": _valid_contract(),
        "task_tree": chain,
        "acceptance_predicates": _valid_predicates(),
        "done_def": ["all M2 tasks status==done"],
    }


class FiveThousandTaskChainTests(unittest.TestCase):
    """Adversarial-depth probe — 5x Python's default recursion limit."""

    def test_5000_linear_chain_does_not_raise_recursion_error(self) -> None:
        n = 5000
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
        # The whole point: this MUST NOT raise RecursionError.
        try:
            result = validate_roadmap(
                _roadmap_with_chain(chain), milestone_index=2
            )
        except RecursionError as exc:  # pragma: no cover — failure path
            self.fail(
                f"validate_roadmap raised RecursionError on a {n}-task linear "
                f"chain (iterative DFS regressed to recursion): {exc!r}"
            )
        # A clean chain should validate without error-severity findings.
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertTrue(
            result["ok"],
            msg=f"unexpected errors on clean {n}-task chain: {errors}",
        )

    def test_5000_chain_with_tail_back_cycle_detected_not_recursion_error(
        self,
    ) -> None:
        n = 5000
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
        try:
            result = validate_roadmap(
                _roadmap_with_chain(chain), milestone_index=2
            )
        except RecursionError as exc:  # pragma: no cover — failure path
            self.fail(
                f"validate_roadmap raised RecursionError on a {n}-task "
                f"tail-back-cycle chain: {exc!r}"
            )
        # Cycle MUST be detected — findings (non-empty), ok=False, with at
        # least one cycle finding from the task_tree section.
        self.assertFalse(
            result["ok"],
            msg="expected ok=False for a tail-back-cycle chain",
        )
        self.assertTrue(
            result["findings"],
            msg="expected non-empty ValidationFindings",
        )
        cycle_findings = [
            f for f in result["findings"]
            if f["section"] == "task_tree" and f["id"].startswith("cycle:")
        ]
        self.assertTrue(
            cycle_findings,
            msg=(
                "expected at least one cycle finding from the iterative DFS; "
                f"got findings={result['findings'][:5]!r}..."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
