"""#1076 — a 12-line assignee scan fed a condition that could not fail.

`_dispatch_implementation_phase` selected the lanes to wake with:

    targets = [lane for lane in self._orch._agents
               if lane in impl_lanes and (lane in assignees or True)]

`X or True` is always True, so `lane in assignees` never mattered — and the
`assignees` set above it (iterate the task tree, read each task's owner/assignee,
lowercase, collect) exists only to be ignored. Nothing else in the function reads
it.

The BEHAVIOUR was right and stays: this function's whole reason for existing is
that lanes must be woken at the kickoff→implementation boundary or they "burn
their idle budget on empty kickoff-reply finishes and get
LaneIdleCircuitBreaker-halted before they ever implement" (smoke #3, 2026-06-05).
Filtering by current assignment would risk waking nobody when the task tree has
not been read yet, which is presumably why the `or True` was put there.

So the fix is to say that, not to encode it as a dead check: every impl lane the
orchestrator holds is woken, deliberately, and the scan that pretended otherwise
is gone.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.kickoff_driver import (  # noqa: E402
    _impl_dispatch_targets_1076 as _targets,
)


class EveryImplLaneIsWoken(unittest.TestCase):

    def test_both_impl_lanes_are_targeted(self):
        got = _targets(["orchestrator", "backend", "frontend", "verifier", "knowledge"])
        self.assertEqual(sorted(got), ["backend", "frontend"])

    def test_non_impl_lanes_are_never_targeted(self):
        """The verifier validates later, the orchestrator coordinates, knowledge observes."""
        got = _targets(["orchestrator", "verifier", "knowledge", "debugger"])
        self.assertEqual(got, [])

    def test_a_lane_the_orchestrator_does_not_hold_is_not_invented(self):
        self.assertEqual(_targets(["backend"]), ["backend"])

    def test_the_orchestrators_order_is_preserved(self):
        self.assertEqual(_targets(["frontend", "backend"]), ["frontend", "backend"])


class ItDoesNotDependOnTaskAssignment(unittest.TestCase):
    """The property the dead `lane in assignees` pretended to enforce."""

    def test_no_assignment_argument_exists(self):
        import inspect
        params = list(inspect.signature(_targets).parameters)
        self.assertEqual(params, ["agents"], (
            "waking is deliberately unconditional — reintroducing an assignment "
            "filter risks waking nobody at the boundary this function exists for"))

    def test_no_condition_in_the_module_is_short_circuited_by_a_truthy_constant(self):
        """AST, not text — the fix's own comment quotes the old `or True` line."""
        import ast, inspect
        from multi_agent.runtime import kickoff_driver as m
        tree = ast.parse(inspect.getsource(m))
        # Only the bug shape: a COMPARISON short-circuited by a truthy constant.
        # `getattr(x, "n", None) or "default"` is the ordinary fallback idiom and
        # appears 500+ times in this package — flagging it would make the test noise.
        bad = [ast.unparse(n) for n in ast.walk(tree)
               if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)
               and isinstance(n.values[0], ast.Compare)
               and any(isinstance(v, ast.Constant) and v.value not in (None, False, 0, "")
                       for v in n.values[1:])]
        self.assertEqual(bad, [], f"a condition that cannot fail: {bad}")


class ItNeverRaises(unittest.TestCase):

    def test_empty_and_junk_inputs(self):
        self.assertEqual(_targets([]), [])
        self.assertEqual(_targets(None), [])
        self.assertEqual(_targets(["backend", None, 7]), ["backend"])


if __name__ == "__main__":
    unittest.main()
