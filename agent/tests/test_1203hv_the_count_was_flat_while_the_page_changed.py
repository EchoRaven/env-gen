"""#1203hv: the ui-evidence record COUNT is flat while a different page fails each tick.

#1138 fixed this livelock one level up: a run held by `validation_ui_evidence_failed` alone
has a failing CHECK SET of size one, which can never be a strict subset of itself, so #228's
convergence grace never fired. #1138's answer was to look at the evidence underneath --
`ui_evidence_failed_records`, a COUNT.

A count cannot tell "the same page is still broken" from "that page was fixed and a different
one surfaced". The same gate dict already carries the identities
(`ui_evidence_failed_pages`, written beside the count in delivery_gate.py from
`_breadth739`), so the livelock reappears one level down whenever the count is flat.

Measured over every `#1017 validation_ui_evidence_failed` evaluation on the corpus, by
adjacent pairs:

    count shrank (what #1138 already sees)        74
    page set turned over, count flat              41   across 28 runs
    nothing changed                             1454

and SEVEN runs show turnover with ZERO shrinks -- #1138's signal never fired once for them
while convergence was happening:

    r169   login_modal -> ui_smoke (x12) -> signup-modal      three records repaired, count 1
    r180   login_modal (x3) -> /friends (x29)                 live, count 1 throughout
    r166   three turnovers, no shrink ever

This is the rule already recorded as "a global count cannot test a per-item property".
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


def _gate(pages, records=1):
    return {"ui_evidence_failed_records": records,
            "ui_evidence_failed_pages": list(pages)}


class ARetiredPageIsConvergence(unittest.TestCase):

    def test_the_r180_shape(self):
        """login_modal repaired, /friends surfaces, the count never moves."""
        o = _orch()
        self.assertFalse(o._ui_pages_retired_1203hv(_gate(["login_modal"])))  # 1st
        self.assertTrue(o._ui_pages_retired_1203hv(_gate(["/friends"])))

    def test_the_r169_shape_three_records_repaired_in_sequence(self):
        o = _orch()
        seq = ["login_modal", "ui_smoke", "signup-modal"]
        seen = [o._ui_pages_retired_1203hv(_gate([p])) for p in seq]
        self.assertEqual(seen, [False, True, True], seen)
        # and #1138, on the same ticks, sees nothing at all.
        o2 = _orch()
        self.assertEqual([o2._ui_depth_shrank_1138({"ui_evidence_failed_records": 1})
                          for _ in seq], [False, False, False])

    def test_the_same_page_failing_again_is_not_convergence(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["/friends"]))
        for _ in range(5):
            self.assertFalse(o._ui_pages_retired_1203hv(_gate(["/friends"])))

    def test_losing_one_of_two_counts(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["login_page", "signup_page"], records=2))
        self.assertTrue(o._ui_pages_retired_1203hv(_gate(["signup_page"])))

    def test_a_set_that_grew_is_not_convergence(self):
        """prev={A} -> cur={B,C} retires A but leaves MORE broken than before."""
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["a"]))
        self.assertFalse(o._ui_pages_retired_1203hv(_gate(["b", "c"], records=2)))

    def test_a_disjoint_set_of_equal_size_counts(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["a", "b"], records=2))
        self.assertTrue(o._ui_pages_retired_1203hv(_gate(["c", "d"], records=2)))


class AbsenceIsNotAnEmptySet(unittest.TestCase):
    """#1138's own rule, one field over: unknown must not read as "every page retired"."""

    def test_a_missing_field_says_nothing(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["a"]))
        self.assertFalse(o._ui_pages_retired_1203hv({"ui_evidence_failed_records": 1}))

    def test_an_empty_current_list_says_nothing(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["a"]))
        self.assertFalse(o._ui_pages_retired_1203hv(_gate([])))

    def test_an_empty_previous_list_says_nothing(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate([]))
        self.assertFalse(o._ui_pages_retired_1203hv(_gate(["a"])))

    def test_a_missing_field_does_not_overwrite_what_was_known(self):
        """Same as #1138: an unknown tick leaves the previous observation standing, so the
        next real one still has something to compare against."""
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["a"]))
        o._ui_pages_retired_1203hv({"ui_evidence_failed_records": 1})
        self.assertTrue(o._ui_pages_retired_1203hv(_gate(["b"])))

    def test_a_junk_gate_is_not_convergence(self):
        o = _orch()
        for junk in (None, [], "", 7, {"ui_evidence_failed_pages": None}):
            self.assertFalse(o._ui_pages_retired_1203hv(junk), junk)

    def test_it_says_which_pages_retired(self):
        o = _orch()
        o._ui_pages_retired_1203hv(_gate(["login_modal"]))
        o._ui_pages_retired_1203hv(_gate(["/friends"]))
        said = " ".join(o._logger.lines)
        self.assertIn("login_modal", said, said)
        self.assertIn("/friends", said, said)


class ItFeedsTheExistingGraceAndNothingElse(unittest.TestCase):

    @staticmethod
    def _run_src():
        # The gate block lives in `_maybe_framework_deliver`, not `run` -- named, not
        # guessed: the call site was located by walking the module AST for the enclosing
        # FunctionDef, so this anchor cannot drift to a different method unnoticed.
        return textwrap.dedent(
            inspect.getsource(orch_mod.Orchestrator._maybe_framework_deliver))

    def test_the_signal_is_wired_to_the_shrink_stamp(self):
        tree = ast.parse(self._run_src())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_ui_pages_retired_1203hv"]
        self.assertEqual(len(calls), 1, "expected one call site, found %d" % len(calls))
        owner = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and any(c in calls for c in ast.walk(n.test))]
        self.assertEqual(len(owner), 1, "the call is not the test of exactly one `if`")
        assigned = {t.attr for st in owner[0].body if isinstance(st, ast.Assign)
                    for t in st.targets if isinstance(t, ast.Attribute)}
        self.assertEqual(assigned, {"_fwdeliver_last_shrink_ts"}, assigned)

    def test_it_is_its_own_if_not_nested_in_1138s(self):
        """Nested, a tick where #1138 returns False would never update this signal's own
        previous observation -- and those are exactly the ticks it exists for."""
        tree = ast.parse(self._run_src())
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "_ui_depth_shrank_1138"
                       for n in ast.walk(node.test)):
                continue
            inner = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "_ui_pages_retired_1203hv"]
            self.assertEqual(inner, [], "#1203hv is nested inside #1138's branch")

    def test_the_grace_it_feeds_is_still_bounded(self):
        """It must not be able to buy an unbudgeted extension: the grace this stamp feeds
        refuses once `grace_used` reaches its max, whatever the stamp says."""
        from multi_agent.runtime.delivery_gate import convergence_grace
        fresh = convergence_grace(failed_count=1, last_shrink_age_s=0.0, grace_used=0)
        self.assertGreater(fresh, 0.0)
        spent = convergence_grace(failed_count=1, last_shrink_age_s=0.0, grace_used=2)
        self.assertEqual(spent, 0.0)


if __name__ == "__main__":
    unittest.main()
