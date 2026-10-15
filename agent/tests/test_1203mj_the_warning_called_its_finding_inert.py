r"""#1203mj: the warning called its own finding inert, and it blocks the cut.

`#743`'s emitted warning said BOTH "and nothing reads them" and "Reported, not enforced".
Seventy lines below, in the same function, `#751` does:

    if _bugs743.get("failed_count"):
        failed_checks.append("unresolved_failed_tasks")

so a FAILED task at the cut is release-BLOCKING. `#1202wi`'s `_note1202wi` carries the list
into the ledger entry, and `remediation_dispatcher` iterates `_b743["failed"]` to re-open
them. Three readers, one of them a gate.

That is the worst direction for this particular falsehood: an operator who believes the
finding is inert stops looking for why the cut is held, and the warning fires hard where it
fires (51x in r114, 47x in r173, 25x in r184, and r189 live).

Second half, the same file: `#755` corrected two counts — the open-P0 block rate 90 -> 86,
and the released-share of failed-task runs "all 20" -> 4 of 20, after finding the release
test `tag or version` scored EVERY run as released off a bootstrap document. The correction
reached the emitted warning and no comment, so the pre-correction figures outlived it in
`unresolved_bug_tasks_743`'s own docstring (four lines under the paragraph that debunks them)
and in `#751`'s comment, which cites `#743` as its source. `#1202vs` states the rule being
applied: a correction has to REPLACE the number it corrects.

Re-measured 2026-10-15 on the 102-run corpus: 9 runs end with a FAILED task (9%), 4 of those
carry a real release tag; modern era (r150+) has 1.

★ MIRROR TRAP (#1203l5's shape, and #1203mh's): the correction QUOTES the stale figures in
order to say they were wrong, so "the string is gone" is not the criterion and would fail on
a correct fix. The criterion is that a stale figure may appear only next to a correction
marker, and never inside the emitted warning.
"""
import ast
import inspect
import re
import unittest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as DG

STALE = re.compile(r"all 20|90 of 129")
MARKERS = ("#1203mj", "#755", "#1202vs")


def _tree():
    return ast.parse(inspect.getsource(DG))


def _warning_743_literals():
    """Concatenated string literals of every logger call whose message starts with '#743 '."""
    out = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        parts, stack = [], [node.args[0]]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                parts.append(cur.value)
            elif isinstance(cur, ast.BinOp):
                stack.extend([cur.right, cur.left])
        msg = "".join(parts)
        if msg.startswith("#743 "):
            out.append(msg)
    return out


class TheWarningDoesNotCallItselfInert(unittest.TestCase):
    def test_the_743_warnings_exist(self):
        msgs = _warning_743_literals()
        self.assertTrue(msgs, "the #743 warnings are gone entirely")

    def test_the_failed_task_warning_does_not_say_nothing_reads_them(self):
        hits = [m for m in _warning_743_literals() if "FAILED at the delivery cut" in m]
        self.assertTrue(hits, "the FAILED-at-the-cut warning is gone")
        for m in hits:
            self.assertNotIn(
                "nothing reads them", m,
                "#743 still tells the operator the FAILED task is unread while #751 blocks "
                "the cut on it (#1203mj)")
            self.assertNotIn(
                "Reported, not enforced", m,
                "#743 still calls the FAILED-task finding unenforced while #751 appends "
                "`unresolved_failed_tasks` to `failed_checks` (#1203mj)")

    def test_it_names_the_gate_that_does_read_them(self):
        hits = [m for m in _warning_743_literals() if "FAILED at the delivery cut" in m]
        self.assertTrue(hits)
        for m in hits:
            self.assertIn("#751", m,
                          "the warning does not say which gate blocks on it")
            self.assertIn("unresolved_failed_tasks", m,
                          "the warning does not name the failed_check it produces")

    def test_the_open_p0_warning_keeps_saying_it_is_reported(self):
        """The OTHER half of #743 really is reported-not-enforced, and must stay that way --
        #751's own comment is explicit that blocking 70% of runs is a halt, not a gate."""
        hits = [m for m in _warning_743_literals() if "P0 BUG task(s) are still open" in m]
        self.assertTrue(hits, "the open-P0 warning is gone")
        for m in hits:
            self.assertIn("reported rather than blocking", m)


class TheClaimItMakesIsTrue(unittest.TestCase):
    """A sentence naming a gate is only worth anything while that gate exists."""

    def test_a_failed_count_appends_the_blocking_check(self):
        found = False
        for node in ast.walk(_tree()):
            if not isinstance(node, ast.If):
                continue
            if "failed_count" not in ast.dump(node.test):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "append"
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "failed_checks"
                        and sub.args
                        and isinstance(sub.args[0], ast.Constant)
                        and sub.args[0].value == "unresolved_failed_tasks"):
                    found = True
        self.assertTrue(
            found,
            "nothing appends `unresolved_failed_tasks` to failed_checks under a failed_count "
            "test any more — #1203mj's sentence would now be false in the other direction")


class EveryStaleFigureSitsNextToItsCorrection(unittest.TestCase):
    """The mirror-trap-safe criterion for the #755 numbers."""

    def test_the_withdrawn_phrase_is_only_ever_quoted_never_asserted(self):
        """The criterion #1203l5 arrived at, and the one mutation MJ4 forced here.

        My first version asked for a correction marker within 8 lines. That is not a
        criterion, it is an amnesty: the correction paragraph I had just written sat inside
        the window, so restoring `and all 20 released` one line above it still passed, and
        MJ4 went MISSED. What separates a correction from a relapse is not proximity but
        GRAMMAR -- the withdrawn wording may appear as a quoted object ("it used to say X"),
        never as a statement.
        """
        src = " ".join(inspect.getsource(DG).split())
        for m in re.finditer(r'.?and all 20 released.?', src):
            frag = m.group(0)
            self.assertTrue(
                frag.startswith('"') and frag.endswith('"'),
                "`and all 20 released` is ASSERTED rather than quoted as the withdrawn "
                "figure (#755 replaced it with 4 of 20): ...%s..."
                % src[max(0, m.start() - 70):m.end() + 20])

    def test_the_docstring_states_the_corrected_share(self):
        doc = " ".join((DG.unresolved_bug_tasks_743.__doc__ or "").split())
        self.assertIn("4 of those 20", doc,
                      "`unresolved_bug_tasks_743`'s own docstring no longer states #755's "
                      "corrected released-share, which is the figure its argument rests on")

    def test_a_stale_figure_in_the_emitted_text_is_marked_as_superseded(self):
        """Not "never appears" -- my first version of this assertion said that, and it failed
        on the correct fix.

        The warning has carried `(#755: my first count said all 20, inflated by a bootstrap
        doc read as a release tag)` since #755, deliberately: a reader who remembers the old
        number needs to be told it was withdrawn, and dropping the note would just move the
        confusion. So the rule is the one #1202vs states -- the correction must REPLACE the
        figure, not sit beside it as an equal -- which in an emitted sentence means the stale
        number may appear only as the object of its own correction, with the live figure in
        the same message."""
        for m in _warning_743_literals():
            hit = STALE.search(m)
            if hit is None:
                continue
            self.assertIn("#755", m,
                          "a pre-#755 figure is stated in the warning with no correction "
                          "marker: %r" % m[:140])
            self.assertTrue(
                re.search(r"4 of (the|those) 20", m) or "86 of 129" in m,
                "the warning restates a withdrawn figure without stating the one that "
                "replaced it: %r" % m[:140])

    def test_the_corrected_figures_are_the_ones_stated(self):
        src = inspect.getsource(DG)
        self.assertIn("86 of 129", src,
                      "#755's corrected open-P0 block rate is stated nowhere")
        hits = [m for m in _warning_743_literals() if "FAILED at the delivery cut" in m]
        self.assertTrue(any("4 of the 20" in m or "4 of those 20" in m for m in hits),
                        "the warning no longer states #755's corrected released-share")


if __name__ == "__main__":
    unittest.main()
