"""#1203hx: the failing chains came down to zero and no convergence signal existed.

`business_chain_failing` is the third check to hit the shape #1138 fixed for ui-evidence and
#1202ls for task instances -- and the only one with NO depth signal of any kind. #228's grace
asks whether the failing CHECK SET shrank; a run held by this check alone has a set of size
one, so it never can. Underneath, the chains converge.

Both no-convergence aborts on this check, from the chain registry's own snapshots:

    r178, aborted 07:57:26    06:33  14 failing -> 07:01  ONE -> 07:15  ZERO
    r179, aborted 13:31:08    12:49   2 failing -> 13:16  ZERO   (14 min before the abort)

Both reached ZERO failing chains before aborting on this check, and both were granted EXACTLY
ZERO grace (`CONVERGING-GRACE` appears nowhere in either log). Across the corpus the registry
snapshots hold 33 count-shrinks and 6 identity turnovers that nothing can see.

Running this predicate over those snapshot sequences says what it would have changed: r179's
last credit is 862s before the abort and `convergence_grace` returns 900s -- the grace fires.
r178's last credit on the snapshot timeline is 2521s before its abort, outside the 1800s
recency window, so that one returns 0; snapshots are 15-30 minutes apart while the gate
evaluates every tick, so r178's last 42 minutes are not knowable from disk. One demonstrated
save, one unknown. The trajectory tests below assert the SIGNAL, which is what this changes;
they do not claim either abort was averted.

Nothing new is published for this: `business_chain_blockers` already returns
`{"reason", "detail", "chains"}` and the gate already carries the whole result as
`gate["business_chain"]`. The consumer appended `reason` to `failed_checks`, passed `detail`
to a note, and left `chains` unread.
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent import orchestrator as orch_mod  # noqa: E402


class _Log:
    def __init__(self): self.lines = []
    def info(self, m, *a, **k): self.lines.append(str(m) % a if a else str(m))
    warning = error = debug = info


def _orch():
    o = object.__new__(orch_mod.Orchestrator)
    o._logger = _Log()
    return o


def _gate(chains, reason="business_chain_failing"):
    """A gate dict shaped like the real one: the whole blocker result under one key."""
    return {"failed_checks": [reason],
            "business_chain": {"reason": reason, "detail": "...", "chains": list(chains)}}


def _satisfied():
    """`business_chain_blockers` returns {} when satisfied, so there is no `chains` key."""
    return {"failed_checks": [], "business_chain": {}}


class TheTwoAbortsThisWasWrittenFor(unittest.TestCase):

    def test_the_r178_trajectory(self):
        """14 -> 1 -> 0. The signal fires twice; the later one is 42 minutes before the
        abort, i.e. outside the grace's own recency window -- this pins the signal, not a
        claim that r178 would have been saved."""
        o = _orch()
        seen = [o._chain_depth_converged_1203hx(_gate(c)) for c in (
            ["c%d" % i for i in range(14)],
            ["fyp_comments_engagement_flow"],
            [],
        )]
        self.assertEqual(seen, [False, True, True], seen)

    def test_the_r179_trajectory(self):
        """2 -> 0, fourteen minutes before the abort."""
        o = _orch()
        o._chain_depth_converged_1203hx(
            _gate(["tenant_session_header_mismatch_rejected_v3", "fyp_feed"]))
        self.assertTrue(o._chain_depth_converged_1203hx(_gate([])))

    def test_a_growing_set_is_not_convergence(self):
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        self.assertFalse(o._chain_depth_converged_1203hx(_gate(["a", "b"])))

    def test_the_same_chain_failing_again_is_not_convergence(self):
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        for _ in range(5):
            self.assertFalse(o._chain_depth_converged_1203hx(_gate(["a"])))

    def test_a_turnover_at_equal_size_counts(self):
        """One chain repaired, the next surfaced -- the 6 cases a pure count cannot see."""
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        self.assertTrue(o._chain_depth_converged_1203hx(_gate(["b"])))

    def test_a_turnover_that_grows_does_not_count(self):
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        self.assertFalse(o._chain_depth_converged_1203hx(_gate(["b", "c"])))

    def test_it_says_how_many_and_which(self):
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["alpha", "beta"]))
        o._chain_depth_converged_1203hx(_gate(["beta"]))
        said = " ".join(o._logger.lines)
        self.assertIn("alpha", said, said)
        self.assertIn("2", said, said)


class AbsenceIsNotZero(unittest.TestCase):

    def test_a_satisfied_check_publishes_no_chains_and_says_nothing(self):
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        self.assertFalse(o._chain_depth_converged_1203hx(_satisfied()))

    def test_a_satisfied_reading_does_not_erase_the_previous_one(self):
        """Otherwise the next real reading has nothing to compare against -- the same rule
        #1138 states for a missing count."""
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a", "b"]))
        o._chain_depth_converged_1203hx(_satisfied())
        self.assertTrue(o._chain_depth_converged_1203hx(_gate(["b"])))

    def test_the_first_observation_is_not_convergence(self):
        o = _orch()
        self.assertFalse(o._chain_depth_converged_1203hx(_gate([])))

    def test_another_chain_reason_without_a_chains_key_says_nothing(self):
        """`business_chain_missing` / `_coverage` carry no `chains`."""
        o = _orch()
        o._chain_depth_converged_1203hx(_gate(["a"]))
        missing = {"failed_checks": ["business_chain_missing"],
                   "business_chain": {"reason": "business_chain_missing", "detail": "..."}}
        self.assertFalse(o._chain_depth_converged_1203hx(missing))

    def test_junk_gates_cannot_raise(self):
        o = _orch()
        for junk in (None, {}, [], "", 7, {"business_chain": None},
                     {"business_chain": {"chains": None}}, {"business_chain": "x"}):
            self.assertFalse(o._chain_depth_converged_1203hx(junk), junk)


class ItFeedsTheExistingGraceAndNothingElse(unittest.TestCase):

    @staticmethod
    def _src():
        return textwrap.dedent(
            inspect.getsource(orch_mod.Orchestrator._maybe_framework_deliver))

    def test_the_signal_is_wired_to_the_shrink_stamp(self):
        tree = ast.parse(self._src())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_chain_depth_converged_1203hx"]
        self.assertEqual(len(calls), 1, "expected one call site, found %d" % len(calls))
        owner = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and any(c in calls for c in ast.walk(n.test))]
        self.assertEqual(len(owner), 1, "the call is not the test of exactly one `if`")
        assigned = {t.attr for st in owner[0].body if isinstance(st, ast.Assign)
                    for t in st.targets if isinstance(t, ast.Attribute)}
        self.assertEqual(assigned, {"_fwdeliver_last_shrink_ts"}, assigned)

    def test_each_depth_signal_keeps_its_own_if(self):
        """Three signals now feed one stamp (#1138's count, #1203hv's pages, this one). If any
        were nested in another's branch, the ticks where the outer one returns False would
        never update the inner one's previous observation -- which are the ticks it is for."""
        tree = ast.parse(self._src())
        names = ("_ui_depth_shrank_1138", "_ui_pages_retired_1203hv",
                 "_chain_depth_converged_1203hx")
        for outer in names:
            for node in ast.walk(tree):
                if not isinstance(node, ast.If):
                    continue
                if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                           and n.func.attr == outer for n in ast.walk(node.test)):
                    continue
                inner = [n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr in names and n.func.attr != outer]
                self.assertEqual(inner, [], "%s nests %s" % (outer, inner))

    def test_the_grace_it_feeds_is_still_bounded(self):
        from multi_agent.runtime.delivery_gate import convergence_grace
        self.assertGreater(
            convergence_grace(failed_count=1, last_shrink_age_s=0.0, grace_used=0), 0.0)
        self.assertEqual(
            convergence_grace(failed_count=1, last_shrink_age_s=0.0, grace_used=2), 0.0)


if __name__ == "__main__":
    unittest.main()
