r"""#1203fj: the squad gate escaped past a verdict it was already holding.

The background test-user squad is consulted by two things in order: the wall-clock escape
(`squad_release_decision`, 900s / attempt cap) and then `squad_gate_tick_action`, whose own
docstring states the ordering -- the escape "is evaluated by the caller BEFORE this and can
RELEASE the gate regardless of task state". Evaluated first is right: the release must not
wait forever. Dropping the handle without reading it is not, because the squad usually
finishes just AFTER the budget expires and reading a finished task costs nothing.

r159, with the stack still up while this was written:

    07:54:04  TEST-USER SQUAD: spawning 12 agents across modalities ['browser']
    08:09:04  (900s budget expires)
    08:09:17  TEST-USER SQUAD (v1.0.0) verdict=DEFECTS: 5 open P0 / 1 P1
    08:16:35  Test-user squad gate RELEASED (escape after 1353s / 0 attempts) —
              delivering with possibly-open test-user defects.

Thirteen seconds late, and seven minutes before an escape that still reported `0 attempts`
and "possibly-open".

Measured over r130-r159: 19 escapes in 16 runs fired with the verdict already in the log, and
the `consume` branch -- the ONLY place either recording site lives -- has not run since r135,
24 consecutive runs. So two instruments are structurally dead, each with its own ticket:

  * #1202ut's comment calls that branch "the one place this number exists. Recording it here
    is what lets the hold ledger's `defects=` be anything but '?'". The ledger reads
    `defects=?` in all 169 squad holds of r135-r159.
  * #1202rd's relaunch guard needs the app signature AT the verdict to tell "the lanes fixed
    something" from "nothing moved". `squad_relaunch_blocked_1202rd` has held 0 times in 13
    runs.

What this does NOT change is the release decision. Every verdict in this arc is DEFECTS, so
blocking here would simply stop delivering -- the failure r142 cost $153 to learn. The 31 bug
tasks r159's test-users filed reach WorkHub either way; what was lost is the number, the
signature, and an escape line that could say which it was shipping over.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    squad_verdict_in_hand_1203fj as in_hand)

ORCH = LLM_DIR / "multi_agent" / "orchestrator.py"


class _Task:
    def __init__(self, done=True, result=None, raises=None):
        self._done, self._result, self._raises = done, result, raises

    def done(self):
        return self._done

    def result(self):
        if self._raises is not None:
            raise self._raises
        return self._result


class TheVerdictIsReadWhenItExists(unittest.TestCase):
    def test_a_finished_defects_verdict_yields_its_p0_count(self):
        # r159's own shape: five open P0 from the browser test-users.
        self.assertEqual(in_hand(_Task(result={"ran": True, "bugs": {"p0": 5, "p1": 1}})), 5)

    def test_a_clean_run_yields_zero_not_none(self):
        """0 and "no verdict" are different answers: the ledger prints `defects=0` for one
        and `defects=?` for the other, which is the distinction #1202ut was added to make."""
        self.assertEqual(in_hand(_Task(result={"ran": True, "bugs": {"p0": 0}})), 0)

    def test_every_shape_without_a_verdict_is_none(self):
        self.assertIsNone(in_hand(None))                              # never launched
        self.assertIsNone(in_hand(_Task(done=False)))                  # still running
        self.assertIsNone(in_hand(_Task(raises=Exception("cancelled"))))
        self.assertIsNone(in_hand(_Task(result=None)))                 # no report
        self.assertIsNone(in_hand(_Task(result="nope")))               # not the report dict

    def test_it_never_raises_on_a_malformed_report(self):
        """It sits on the release path: an unreadable verdict must not take a delivery with
        it (#1202qm/qn's rule, applied to a value that is advisory by construction)."""
        self.assertIsNone(in_hand(_Task(result={"bugs": {"p0": "five"}})))
        self.assertIsNone(in_hand(_Task(result={"bugs": "none"})))

    def test_a_still_running_task_is_not_awaited(self):
        """`done()` must gate the `result()` call: asking a pending asyncio task for its
        result raises InvalidStateError, and this runs inside the delivery tick."""
        class _Pending(_Task):
            def result(self):
                raise AssertionError("result() called on a task that is not done")
        self.assertIsNone(in_hand(_Pending(done=False)))


class TheEscapeBranchReadsItBeforeCancelling(unittest.TestCase):
    """By AST and by ORDER. The order is the whole point: `.cancel()` and clearing the handle
    make the verdict unreachable, so a read placed after them restores nothing."""

    def _escape_branch(self):
        """The SMALLEST statement list containing the escape warning -- i.e. the `else:` body
        itself. Taking the first match from `ast.walk` instead returned the whole enclosing
        method (208 `return`s), which made the ordering and no-early-return assertions below
        meaningless; the first run of this test caught that, not a missing patch."""
        tree = ast.parse(ORCH.read_text(encoding="utf-8"))
        warn = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "warning"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and "squad gate RELEASED (escape" in node.args[0].value):
                warn = node
                break
        self.assertIsNotNone(warn, "the escape warning is gone from the orchestrator")
        # Smallest by LINE SPAN, not by statement count: the enclosing method's own body is
        # two statements (a docstring and one 1300-line `try`), so "fewest statements" picks
        # the whole method. Span is what "innermost" means here.
        def _span(stmts):
            return (max(getattr(s, "end_lineno", s.lineno) for s in stmts)
                    - min(s.lineno for s in stmts))
        best = None
        for anc in ast.walk(tree):
            for field in ("orelse", "body", "finalbody"):
                stmts = getattr(anc, field, None)
                if not isinstance(stmts, list) or not stmts:
                    continue
                if not any(warn in set(ast.walk(s)) for s in stmts):
                    continue
                if best is None or _span(stmts) < _span(best):
                    best = stmts
        self.assertIsNotNone(best, "could not locate the escape branch body")
        return best, warn

    def test_the_read_precedes_the_cancel_and_the_handle_clear(self):
        stmts, warn = self._escape_branch()
        read = [n.lineno for s in stmts for n in ast.walk(s)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_inhand1203fj"]
        cancel = [n.lineno for s in stmts for n in ast.walk(s)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "cancel"]
        clear = [n.lineno for s in stmts for n in ast.walk(s)
                 if isinstance(n, ast.Attribute) and n.attr == "_tu_squad_task"
                 and isinstance(n.ctx, ast.Store)]
        self.assertTrue(read, "the escape branch does not consult the verdict")
        self.assertTrue(cancel and clear, "the escape branch no longer cancels/clears")
        self.assertLess(max(read), min(cancel), "the verdict is read AFTER the cancel")
        self.assertLess(max(read), min(clear), "the verdict is read AFTER the handle is cleared")

    def test_both_dead_recording_sites_are_fed_here(self):
        """#1202ut's count and #1202rd's signature: the two things the dead branch recorded."""
        stmts, _ = self._escape_branch()
        stored = {n.attr for s in stmts for n in ast.walk(s)
                  if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)}
        self.assertIn("_tu_squad_last_p0_1202ut", stored)
        self.assertIn("_tu_squad_verdict_sig_1202rd", stored)

    def test_the_escape_line_names_the_number_when_it_has_one(self):
        """#1202ds: a line that reports only its own name leaves the reader auditing blind.
        "possibly-open" stays for the case where there genuinely is no verdict."""
        _, warn = self._escape_branch()
        msg = warn.args[0].value
        self.assertNotIn("possibly-open test-user defects", msg,
                         "the message is still unconditionally 'possibly-open'")
        self.assertIn("test-user defects", msg)
        rendered = " | ".join(ast.dump(a) for a in warn.args[1:])
        self.assertIn("open P0", rendered)
        self.assertIn("possibly-open", rendered)       # the no-verdict arm survives
        self.assertIn("_p01203fj", rendered)

    def test_the_release_decision_is_unchanged(self):
        """The branch must not grow a `return` that would hold the release: every verdict in
        this arc is DEFECTS, so blocking here stops delivering altogether (r142, $153)."""
        stmts, _ = self._escape_branch()
        returns = [n for s in stmts for n in ast.walk(s) if isinstance(n, ast.Return)]
        self.assertEqual(returns, [], "the escape branch now returns early -- it must release")


if __name__ == "__main__":
    unittest.main()
