"""Regression test for `runtime.kickoff.ready_set` (charter §8).

Closed-by-construction: exercises EXACTLY the contract the function
promises in its module docstring — happy path, the obvious failure
mode (cycle + orphan dep), and the empty-input edge case. Not an
exhaustive matrix — one assertion per invariant.
"""

import sys
import unittest
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.ready_set import ready_set  # noqa: E402


class ReadySetHappyPathTests(unittest.TestCase):
    def test_empty_input_returns_empty_list(self) -> None:
        """Empty task tree -> empty ready set; no spurious errors."""
        self.assertEqual(ready_set([]), [])

    def test_returns_pending_tasks_whose_deps_are_done_in_input_order(self) -> None:
        """The single happy-path invariant: status in {pending,ready} AND
        every dep is status=done -> id appears in output; output order
        matches input order."""
        tasks = [
            {"id": "a", "depends_on": [], "status": "done"},
            {"id": "b", "depends_on": ["a"], "status": "pending"},
            {"id": "c", "depends_on": ["a"], "status": "ready"},
            {"id": "d", "depends_on": ["b"], "status": "pending"},       # b not done yet
            {"id": "e", "depends_on": [], "status": "in_progress"},      # not ready-shaped
            {"id": "f", "depends_on": [], "status": "done"},             # already done
        ]
        self.assertEqual(ready_set(tasks), ["b", "c"])


class ReadySetFailureModeTests(unittest.TestCase):
    def test_dependency_cycle_raises_value_error(self) -> None:
        """The obvious failure mode: a cycle in depends_on must raise
        a ValueError with a readable cycle path (so the orchestrator
        log can quote it)."""
        tasks = [
            {"id": "a", "depends_on": ["b"], "status": "pending"},
            {"id": "b", "depends_on": ["a"], "status": "pending"},
        ]
        with self.assertRaises(ValueError) as cm:
            ready_set(tasks)
        msg = str(cm.exception)
        self.assertIn("cycle", msg)
        # cycle path must mention both members.
        self.assertIn("a", msg)
        self.assertIn("b", msg)

    def test_orphan_dependency_raises_value_error(self) -> None:
        """depends_on referencing an unknown task id must raise with
        both the dependent and the missing dep named (so the kickoff
        log points at exactly the row to fix)."""
        tasks = [
            {"id": "a", "depends_on": ["ghost"], "status": "pending"},
        ]
        with self.assertRaises(ValueError) as cm:
            ready_set(tasks)
        msg = str(cm.exception)
        self.assertIn("orphan", msg)
        self.assertIn("a", msg)
        self.assertIn("ghost", msg)


class ReadySetThinContractTests(unittest.TestCase):
    """Five thin invariant pins (reviewer round-7 list).

    Each test fails if the corresponding fix is removed from
    `ready_set` (duplicate-id detection, wrong-type guard, diamond
    dep release semantics, dep-not-done filter, and the iterative-DFS
    recursion-safety property).
    """

    def test_duplicate_id_raises_value_error(self) -> None:
        """Two tasks with the same id -> ValueError naming the id.

        Without the duplicate-id check, the second insertion would
        silently clobber the first in `by_id` and the helper would
        return a wrong (but plausible-looking) ready set.
        """
        tasks = [
            {"id": "a", "depends_on": [], "status": "done"},
            {"id": "a", "depends_on": [], "status": "pending"},
        ]
        with self.assertRaises(ValueError) as cm:
            ready_set(tasks)
        msg = str(cm.exception)
        self.assertIn("duplicate", msg)
        self.assertIn("a", msg)

    def test_non_mapping_task_raises_value_error(self) -> None:
        """A non-dict entry in the task list -> ValueError.

        Without the isinstance(task, Mapping) guard, the helper would
        crash later with an opaque AttributeError / TypeError instead
        of the structured contract error the orchestrator log expects.
        """
        tasks = [
            {"id": "a", "depends_on": [], "status": "done"},
            "not-a-dict",  # wrong type — must be rejected up-front
        ]
        with self.assertRaises(ValueError) as cm:
            ready_set(tasks)
        msg = str(cm.exception)
        # The shape-guard message names the offending type so the log
        # points at the exact row to fix.
        self.assertIn("mapping", msg.lower())

    def test_diamond_deps_release_only_when_both_parents_done(self) -> None:
        """A -> B, A -> C, B -> D, C -> D.

        D appears in ready_set ONLY when BOTH B and C are done. With
        only one parent done, D must NOT appear. With both done, D
        must appear. This pins the `all(...)` dep-conjunction.
        """
        # Phase 1: A done, B done, C still in_progress -> D not ready.
        tasks_one_parent = [
            {"id": "A", "depends_on": [], "status": "done"},
            {"id": "B", "depends_on": ["A"], "status": "done"},
            {"id": "C", "depends_on": ["A"], "status": "in_progress"},
            {"id": "D", "depends_on": ["B", "C"], "status": "pending"},
        ]
        self.assertEqual(ready_set(tasks_one_parent), [])

        # Phase 2: both parents done -> D appears.
        tasks_both_parents = [
            {"id": "A", "depends_on": [], "status": "done"},
            {"id": "B", "depends_on": ["A"], "status": "done"},
            {"id": "C", "depends_on": ["A"], "status": "done"},
            {"id": "D", "depends_on": ["B", "C"], "status": "pending"},
        ]
        self.assertEqual(ready_set(tasks_both_parents), ["D"])

    def test_dep_in_progress_does_not_release_dependent(self) -> None:
        """A dep with status=in_progress must NOT release its dependent.

        Only `done` counts as dep-satisfied (per _DEP_SATISFIED_STATUSES).
        Without that filter, the dependent would leak into the ready
        set and a second agent would claim work that's still active.
        """
        tasks = [
            {"id": "a", "depends_on": [], "status": "in_progress"},
            {"id": "b", "depends_on": ["a"], "status": "pending"},
        ]
        self.assertEqual(ready_set(tasks), [])

    def test_deep_linear_chain_does_not_recurse(self) -> None:
        """A 1500-node linear dep chain must not blow the recursion limit.

        This pins the iterative-DFS property: with a recursive DFS,
        the cycle-detection pass would raise RecursionError on the
        deeper end of the chain. The chain is acyclic and the leaf
        is `pending` with all deps done, so the leaf must appear in
        the ready set.
        """
        # Build chain t0 (done) -> t1 (done) -> ... -> t1498 (done) -> t1499 (pending).
        # Each ti depends on ti-1; the last task is the one we expect in ready_set.
        n = 1500
        tasks: list[dict[str, Any]] = []
        for i in range(n):
            depends_on = [f"t{i-1}"] if i > 0 else []
            status = "pending" if i == n - 1 else "done"
            tasks.append({"id": f"t{i}", "depends_on": depends_on, "status": status})

        # Sanity check: Python's default recursion limit is well below n,
        # so a recursive DFS over this chain would crash. We pin a limit
        # lower than the chain length to prove the helper is iterative.
        original_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(500)  # << n (1500)
            result = ready_set(tasks)
        finally:
            sys.setrecursionlimit(original_limit)

        self.assertEqual(result, [f"t{n-1}"])


if __name__ == "__main__":
    unittest.main()
