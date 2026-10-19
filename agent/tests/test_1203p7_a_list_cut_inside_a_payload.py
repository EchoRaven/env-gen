"""#1203p7: a list sliced into a dict that is then emitted declares its cut.

`join_capped` (#1034) declares a cut in PROSE, and every ratchet written for #1034 reads
f-strings -- `_count_beside_cut_list_1203jx` walks `JoinedStr` nodes for `len(whole)` beside
`", ".join(whole[:n])`. A list sliced straight into a payload dict was never on that surface,
so two live records cut silently:

  * the delivery-gate progress tick: 411 of 6523 ticks across 82 corpus runs sit exactly at
    its cap of six, while the uncapped ledger of the SAME evaluations
    (`logs/delivery_gate.jsonl`, 8698 rows) reaches 25 and exceeds six in 467 rows (5.4%);
  * the #893 judge-instability record: of 53 persisted records, 27 `appeared` and 33
    `vanished` lists sit at their cap of five -- and that record exists to argue the judge is
    unstable, where the SIZE of the churn is the argument.

Measured and deliberately NOT patched: `tools/docker_tools.py`'s `source_files[:5]`, at its cap
in 2 of 9 corpus records, in a file that needs a dual-spelling import dance -- #647, the fix
would be wider than the evidence.
"""

import ast
import inspect
import os
import unittest

from env_generator.llm_generator.multi_agent.runtime.message_format import (
    list_capped_1203p7, join_capped)

_ORCH = os.path.join(os.path.dirname(inspect.getfile(list_capped_1203p7)),
                     "..", "orchestrator.py")
_VF = os.path.join(os.path.dirname(inspect.getfile(list_capped_1203p7)),
                   "visual_fidelity.py")


def _tree(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return ast.parse(fh.read())


def _dict_of_emit(tree, message):
    """The payload dict of the `emit`/`append` call identified by a literal in it."""
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        lits = [c.value for c in ast.walk(call)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if message not in lits:
            continue
        for arg in list(call.args) + [k.value for k in call.keywords]:
            if isinstance(arg, ast.Dict):
                return arg
    return None


class TheHelperDeclaresItsCut(unittest.TestCase):

    def test_a_cut_list_carries_the_remainder_as_its_last_item(self):
        shown, total = list_capped_1203p7(list("abcdefghij"), 6)
        self.assertEqual(total, 10)
        self.assertEqual(len(shown), 7)
        self.assertIn("4", shown[-1])
        self.assertIn("more", shown[-1])

    def test_an_uncut_list_gains_no_noise(self):
        self.assertEqual(list_capped_1203p7(["a", "b"], 6), (["a", "b"], 2))

    def test_a_list_exactly_at_the_cap_is_not_annotated(self):
        shown, total = list_capped_1203p7(list("abcdef"), 6)
        self.assertEqual((shown, total), (list("abcdef"), 6))

    def test_the_declaration_is_an_ITEM_not_a_sibling_key(self):
        """A reader that only prints the list still has to see the cut."""
        shown, _ = list_capped_1203p7(list("abcdefgh"), 3)
        self.assertTrue(any("more" in x for x in shown),
                        "the cut must be visible to a reader that renders only the list")

    def test_the_total_is_the_TRUE_length_not_the_shown_length(self):
        _, total = list_capped_1203p7(list("abcdefgh"), 3)
        self.assertEqual(total, 8)

    def test_an_unrenderable_input_returns_zero_not_a_clean_empty_list(self):
        """#883: 'could not render' and 'nothing was cut' must not be the same answer.

        The helper cannot distinguish them in its return, so it documents the rule; what IS
        asserted here is that it does not invent items or a total it never saw.
        """
        class Boom(object):
            def __iter__(self):
                raise RuntimeError("no")
        self.assertEqual(list_capped_1203p7(Boom(), 6), ([], 0))
        self.assertEqual(list_capped_1203p7(None, 6), ([], 0))

    def test_a_nonsense_cap_falls_back_without_raising(self):
        shown, total = list_capped_1203p7(["a", "b", "c"], "not a number")
        self.assertEqual(total, 3)
        self.assertEqual(shown, ["a", "b", "c"])

    def test_a_zero_cap_still_declares_what_it_hid(self):
        shown, total = list_capped_1203p7(["a", "b", "c"], 0)
        self.assertEqual(total, 3)
        self.assertEqual(len(shown), 1)
        self.assertIn("3", shown[0])

    def test_a_NEGATIVE_cap_hides_everything_and_says_so(self):
        """A negative cap must not slide into Python's from-the-end slicing: `seq[:-1]`
        would quietly drop one item and declare only that one as hidden."""
        shown, total = list_capped_1203p7(["a", "b", "c"], -1)
        self.assertEqual(total, 3)
        self.assertEqual(len(shown), 1)
        self.assertIn("3", shown[0])

    def test_items_are_stringified_so_the_payload_stays_json_shaped(self):
        shown, _ = list_capped_1203p7([1, {"k": 2}], 6)
        self.assertTrue(all(isinstance(x, str) for x in shown))

    def test_it_is_a_sibling_of_join_capped_not_a_replacement(self):
        """#1032: one owner per rule. Prose keeps its helper; structure gets its own."""
        self.assertIsInstance(join_capped(["a", "b"], 9), str)
        self.assertIsInstance(list_capped_1203p7(["a", "b"], 1)[0], list)


class TheGateTickNoLongerCutsSilently(unittest.TestCase):

    def setUp(self):
        self.d = _dict_of_emit(_tree(_ORCH), "delivery gate tick")
        self.assertIsNotNone(self.d, "the gate tick payload moved; re-aim this test")
        self.keys = [k.value for k in self.d.keys if isinstance(k, ast.Constant)]

    def test_failed_checks_is_no_longer_a_bare_slice(self):
        for k, v in zip(self.d.keys, self.d.values):
            if isinstance(k, ast.Constant) and k.value == "failed_checks":
                self.assertNotIsInstance(
                    v, ast.Subscript,
                    "a slice straight into the payload is the #1203p7 defect itself")

    def test_the_payload_carries_the_true_total(self):
        self.assertIn("failed_checks_total", self.keys)

    def test_the_827_contract_keys_survive(self):
        for k in ("ok", "failed_checks", "did_not_run"):
            self.assertIn(k, self.keys)

    def test_the_tick_routes_through_the_one_owner(self):
        src = ast.dump(_tree(_ORCH))
        self.assertIn("list_capped_1203p7", src)


class TheInstabilityRecordNoLongerCutsSilently(unittest.TestCase):

    def setUp(self):
        tree = _tree(_VF)
        self.d = None
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for arg in call.args:
                if not isinstance(arg, ast.Dict):
                    continue
                ks = [k.value for k in arg.keys if isinstance(k, ast.Constant)]
                if "appeared" in ks and "vanished" in ks:
                    self.d = arg
        self.assertIsNotNone(self.d, "the #893 record moved; re-aim this test")
        self.keys = [k.value for k in self.d.keys if isinstance(k, ast.Constant)]

    def test_neither_list_is_a_bare_slice(self):
        for k, v in zip(self.d.keys, self.d.values):
            if isinstance(k, ast.Constant) and k.value in ("appeared", "vanished"):
                self.assertNotIsInstance(v, ast.Subscript, "%s still cuts silently" % k.value)

    def test_both_totals_are_recorded(self):
        self.assertIn("appeared_total", self.keys)
        self.assertIn("vanished_total", self.keys)

    def test_the_name_the_module_calls_actually_resolves(self):
        """The import line here carried a trailing `# #1034`; appending to it put the new
        name INSIDE the comment, and nothing but a real call would have noticed."""
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
        self.assertEqual(vf._list_capped_1203p7(["a", "b", "c"], 2)[1], 3)


if __name__ == "__main__":
    unittest.main()
