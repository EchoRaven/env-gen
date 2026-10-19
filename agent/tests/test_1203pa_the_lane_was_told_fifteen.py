"""#1203pa: the lane was told fifteen missing components out of however many there were.

`remediation_text` builds the frontend lane's task body, and one of its lines reads
"Missing components (build these first): …" from a list the record silently capped at fifteen.

MEASURED on the corpus: 123 of 767 persisted screen records sit AT that cap (16.0%), counted
through the structural path verdict.json -> screens[] -> dimensions.components.missing. (A bare
scan for the key name answers 2333 of 10321 -- it also counts `kickoff_driver`'s own cap-20
`missing` lists, so that figure is about a different population.) The truncation lands on the
screens that need the list most: of those 123 records, 5 passed (4%, mean similarity 0.248)
against 423 of 644 below the cap (66%, mean 0.629).
The cap is not what makes those screens bad (a broken screen HAS more missing components), but
it does mean the worst screens are the ones whose instructions are incomplete -- and nobody
could tell how many were dropped, because the record keeps fifteen and the judge's raw reply is
itself capped at 400 characters.

Why #1034's ratchet never saw it: `_count_beside_cut_list_1203jx` walks `JoinedStr` nodes for
`len(whole)` beside `join(whole[:n])`. This site has no count beside it AND is a `.append()` of
a concatenation rather than an f-string -- two independent reasons to be invisible.
"""

import ast
import inspect
import os
import unittest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
from env_generator.llm_generator.multi_agent.runtime.message_format import join_capped

_VF = os.path.join(os.path.dirname(inspect.getfile(VF)), "visual_fidelity.py")


def _src():
    with open(_VF, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _fn(name):
    tree = ast.parse(_src())
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError("%s not found" % name)


class TheLaneIsToldTheRemainder(unittest.TestCase):

    def test_the_line_declares_its_cut(self):
        out = join_capped(["a"] * 15, 30, cap=15, sep=", ")
        self.assertIn("+15 more not shown", out)

    def test_an_untruncated_list_gains_no_noise(self):
        self.assertEqual(join_capped(["nav", "hero"], 2, cap=2, sep=", "), "nav, hero")

    def test_a_record_written_before_this_ticket_degrades_quietly(self):
        """No `missing_total` must mean today's wording, never an invented number."""
        self.assertNotIn("more not shown", join_capped(["a"] * 15, None, cap=15, sep=", "))

    def test_a_total_below_the_shown_count_invents_no_negative(self):
        self.assertNotIn("-", join_capped(["a"] * 15, 3, cap=15, sep=", "))

    def test_the_comma_separator_the_line_always_used_is_preserved(self):
        self.assertEqual(join_capped(["a", "b"], 2, cap=2, sep=", "), "a, b")

    def test_remediation_text_routes_the_list_through_the_owner(self):
        body = ast.unparse(_fn("remediation_text"))
        self.assertIn("join_capped", body)
        self.assertNotIn("', '.join(missing)", body)
        self.assertNotIn('", ".join(missing)', body)

    def test_remediation_text_reads_the_true_total(self):
        self.assertIn("missing_total", ast.unparse(_fn("remediation_text")))


class TheRecordCarriesTheTotal(unittest.TestCase):

    def test_the_record_site_writes_a_sibling_count(self):
        src = _src()
        self.assertIn('rec["missing_total"] = len(_all1203pa)', src)

    def test_the_record_keeps_a_PLAIN_list_with_no_sentinel(self):
        """#893's `_miss()` unions this list into a set to compare two rounds of the same tree.

        A sentinel item would enter that set as a fake component name and make byte-identical
        rounds read as unstable -- the declaration here has to be the count, not an item.
        """
        # #943: anchored on the STATEMENT, not on a byte count -- the comment above this
        # line is one I keep editing, and a byte window would drift onto it.
        stmt = [l for l in _src().split("\n") if 'rec["missing"]' in l and "=" in l]
        self.assertTrue(stmt, "the record site moved; re-aim this test")
        for l in stmt:
            self.assertNotIn("more not shown", l)

    def test_the_893_comparison_still_reads_only_the_list(self):
        """If `_miss` ever starts reading `missing_total`, the two keys must be reconciled."""
        # #943: the function's own AST body, not a byte window after its `def`.
        import ast as _ast
        tree = _ast.parse(_src())
        body = None
        for n in _ast.walk(tree):
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == "_miss":
                body = _ast.unparse(n)
        self.assertIsNotNone(body, "#893's _miss() moved; re-aim this test")
        # `ast.unparse` normalises string literals to single quotes, so asserting on the
        # source's quote style would fail on correct code. Read the key NAMES instead.
        reads = {n.args[0].value for n in _ast.walk(_ast.parse(body))
                 if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                 and n.func.attr == "get" and n.args
                 and isinstance(n.args[0], _ast.Constant)
                 and isinstance(n.args[0].value, str)}
        self.assertIn("missing", reads)
        self.assertNotIn("missing_total", reads,
                         "if _miss() starts reading the total, the two keys must be reconciled")

    def test_the_cap_is_still_fifteen(self):
        """The ticket declares the cut, it does not raise the cap -- raising it would change
        what the judge's answer costs to carry, which is a different decision."""
        self.assertIn("_all1203pa[:15]", _src())


if __name__ == "__main__":
    unittest.main()
