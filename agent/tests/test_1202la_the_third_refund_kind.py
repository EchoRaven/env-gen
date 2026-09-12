"""#1202la: #1202kn read two of the THREE refund counters.

#1202kn exists for one situation: the visual gate refunded an attempt, promised "will retry
next tick", and there was no next tick because the delivery gate is red on something else. Its
guard asks whether a refund is outstanding -- and asked only `unreachable_refunds` and
`transient_refunds`.

There is a third. `_refund_compose_race_1202dm` keeps its own counter with its own budget, and
the branch that spends it RETURNS before the `unreachable_refunds` arm is reached, so a
compose-race refund leaves both counters the guard reads at zero.

tiktok-r118 is the case, and it is exactly the situation #1202kn was written for. Its only
refund while the gate had judged nothing was at 17:05:02 -- "capture raced the compose stack
-- 1 screen(s) photographed but 7 refused the connection (...); the app was torn down". The
delivery gate was red on unrelated checks for the rest of the run. #1202kn fired ZERO times in
107 minutes, and the run aborted having judged nothing at all.

Scale, stated honestly: 10 of the corpus's 74 visual refunds are compose-race (14%, 7 runs) --
`unreachable` is 69%. This is not the majority case. It is a producing branch that the one
mechanism written for this situation could not see, which is #934's rule: the guard belongs at
the common ancestor of EVERY producing branch, not most of them.

WHAT IS VERIFIED: the shipped guard now fires on a compose-race-only refund; it still fires on
the two it already read; it still refuses when nothing was judged but nothing was refunded, and
when something HAS been judged; and the counter name matches the attribute the gate actually
increments.

WHAT IS NOT: that re-taking the attempt then succeeds. If the app is still down the capture
fails again -- #1202dm's own budget bounds that. This restores the retry, not the app.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_ORCH = _ROOT / "env_generator/llm_generator/multi_agent/orchestrator.py"
_VF = _ROOT / "env_generator/llm_generator/multi_agent/runtime/visual_fidelity.py"


def _retry_guard() -> str:
    """The shipped guard condition, by AST landmark (#943: no fixed source windows)."""
    tree = ast.parse(_ORCH.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        src = ast.dump(n.test)
        if "_vf1202kn" in src and "total_judgments" in src:
            return ast.unparse(n.test)
    raise AssertionError("the #1202kn retry guard is gone")


def _eval(guard, **attrs):
    class _G:
        pass
    g = _G()
    for k, v in attrs.items():
        setattr(g, k, v)
    return bool(eval(guard, {"getattr": getattr}, {"_vf1202kn": g}))  # noqa: S307


_BASE = dict(total_judgments=0, unreachable_refunds=0,
             transient_refunds=0, compose_race_refunds_1202dm=0)


class TheThirdCounterIsRead(unittest.TestCase):

    def test_r118s_compose_race_refund_now_triggers_it(self):
        """★ The live case: a compose-race refund, nothing judged."""
        self.assertTrue(_eval(_retry_guard(),
                              **{**_BASE, "compose_race_refunds_1202dm": 1}))

    def test_the_two_it_already_read_still_trigger_it(self):
        self.assertTrue(_eval(_retry_guard(), **{**_BASE, "unreachable_refunds": 1}))
        self.assertTrue(_eval(_retry_guard(), **{**_BASE, "transient_refunds": 1}))

    def test_no_refund_at_all_still_refuses(self):
        """Without a refund there is no promise to honour."""
        self.assertFalse(_eval(_retry_guard(), **_BASE))

    def test_an_already_judged_gate_still_refuses(self):
        self.assertFalse(_eval(_retry_guard(),
                               **{**_BASE, "total_judgments": 4,
                                  "compose_race_refunds_1202dm": 1}))

    def test_a_missing_gate_instance_still_refuses(self):
        guard = _retry_guard()
        self.assertFalse(bool(eval(guard, {"getattr": getattr},   # noqa: S307
                                   {"_vf1202kn": None})))


class TheCounterNameIsTheRealOne(unittest.TestCase):
    """Verify against the real attribute, not a name I remembered (#1202fw's lesson)."""

    def test_the_gate_actually_increments_this_attribute(self):
        src = _VF.read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r"self\.compose_race_refunds_1202dm\s*\+=\s*1", src),
            "the gate does not increment compose_race_refunds_1202dm — the guard reads a "
            "name nothing writes")

    def test_the_compose_race_branch_returns_before_the_unreachable_arm(self):
        """This is WHY the two-counter guard could not see it."""
        tree = ast.parse(_VF.read_text(encoding="utf-8"))
        found = False
        for n in ast.walk(tree):
            if not isinstance(n, ast.If):
                continue
            if "compose_race_1202dm" not in ast.dump(n.test):
                continue
            if any(isinstance(b, ast.Return) for b in n.body):
                found = True
        self.assertTrue(found, "the compose-race branch no longer returns early — if it now "
                               "falls through, re-check whether this fix is still needed")


if __name__ == "__main__":
    unittest.main()
