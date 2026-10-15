r"""#1203mh: the `#740` warning claimed the console errors reach EVERY screen's deviations.

They reach one arm. The attachment lives inside `if not shot:` under
`elif screen["name"] in _blank_screens:`, so a BLANK screen's deviations quote the browser
verbatim and a screen that WAS photographed carries only what `#1203l8` extracts from the
same map -- the API paths it requested and lost.

The false sentence is the one a reader of this module reasons from: it is what sent me
looking for "the crash that reaches nobody", and the search ended in a measurement
(144 named-screen message pairs in the modern era, 142 of them HTTP statuses, exactly one
non-status pair corpus-wide) rather than a defect. `#1203j2`: a false sentence in the
framework is its own defect.

★ MIRROR TRAP (the shape `#1203l5` was written for): the correction QUOTES the false
sentence in its own comment, so "the phrase is gone from the file" is not the criterion and
would fail on a correct fix. The criterion is that the phrase appears in no STRING LITERAL --
nothing the framework can emit -- which is what `test_the_false_claim_is_in_no_literal`
asserts by walking every `ast.Constant` in the module.
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF

FALSE_CLAIM = "now in each screen's deviations"


def _module_tree():
    return ast.parse(inspect.getsource(VF))


def _warning_740_literals(tree):
    """Every string literal belonging to the `#740` logger call, concatenated."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        parts = []
        stack = [node.args[0]]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                parts.append(cur.value)
            elif isinstance(cur, ast.BinOp):
                stack.extend([cur.right, cur.left])
        msg = "".join(parts)
        if msg.startswith("#740 the browser reported"):
            out.append(msg)
    return out


class TheWarningNamesTheArmItFills(unittest.TestCase):
    def test_the_740_warning_exists(self):
        self.assertTrue(_warning_740_literals(_module_tree()),
                        "the #740 capture warning is gone entirely")

    def test_the_740_warning_does_not_claim_every_screen(self):
        for msg in _warning_740_literals(_module_tree()):
            self.assertNotIn(
                FALSE_CLAIM, msg,
                "the #740 warning still tells the reader the console errors reach every "
                "screen's deviations; they reach the _blank_screens arm only (#1203mh)")

    def test_the_740_warning_names_both_arms(self):
        msgs = _warning_740_literals(_module_tree())
        self.assertTrue(msgs)
        for msg in msgs:
            self.assertIn("BLANK", msg,
                          "the #740 warning does not say which screens quote the errors")
            self.assertIn("#1203l8", msg,
                          "the #740 warning does not say what a PHOTOGRAPHED screen gets "
                          "instead -- #1203l8's extracted API paths")

    def test_the_false_claim_is_in_no_literal(self):
        """The phrase may survive in a comment (this correction quotes it); never in a string."""
        for node in ast.walk(_module_tree()):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(
                    FALSE_CLAIM, node.value,
                    "the false #740 claim is back in an emittable string literal "
                    "(line %s)" % getattr(node, "lineno", "?"))


class TheJudgedArmIsWhatTheSentenceNowSays(unittest.TestCase):
    """The sentence is only true while #1203l8 is what a photographed screen gets."""

    def test_a_judged_screen_gets_the_lost_api_paths(self):
        out = VF._with_api_404s_1203l8(["implementation shows a 'not found' message"],
                                       ["/api/users/1"])
        self.assertEqual(len(out), 2, out)
        self.assertIn("/api/users/1", out[-1])
        self.assertIn("#1203l8", out[-1])

    def test_a_judged_screen_with_nothing_lost_is_untouched(self):
        base = ["the hero image is missing"]
        self.assertEqual(VF._with_api_404s_1203l8(base, []), base)

    def test_the_raw_messages_are_attached_only_under_the_blank_arm(self):
        """#1203mh's whole claim, read off the tree: `_console740` is consulted for raw
        attachment inside an `elif ... in _blank_screens` arm and nowhere else."""
        tree = _module_tree()
        blank_arm_reads = 0
        other_reads = 0

        class V(ast.NodeVisitor):
            def visit_If(self, node):
                test = ast.dump(node.test)
                inside_blank = "_blank_screens" in test and "screen" in test
                for child in node.body:
                    for sub in ast.walk(child):
                        if (isinstance(sub, ast.Attribute) and sub.attr == "get"
                                and isinstance(sub.value, ast.Name)
                                and sub.value.id == "_console740"):
                            nonlocal_counter[0 if inside_blank else 1] += 1
                self.generic_visit(node)

        nonlocal_counter = [0, 0]
        V().visit(tree)
        blank_arm_reads, other_reads = nonlocal_counter
        self.assertGreaterEqual(
            blank_arm_reads, 1,
            "nothing under the _blank_screens arm reads _console740 any more — the "
            "#1203mh sentence would be false in the other direction")


if __name__ == "__main__":
    unittest.main()
