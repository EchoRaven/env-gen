"""#1203pm: the invisible-icon finding reached a logger and nobody else.

`#1203n0` finds icons loaded through `<img>`/`url()` whose SVG paints only `currentColor` (or
names no paint at all, #1203nv) -- they are in the DOM and invisible on screen, because CSS
colour cannot cross an `<img>` boundary. From the first run it shipped in, it only WARNED.

The corpus gives a controlled comparison inside the same subsystem, on the same axis, in the
same era, which is why this is a defect rather than a preference:

    #1203kd  a character doing an icon's job   FILES a P1 task
             -> 31 such tasks in 120391 records, 30 completed, ALL in r190 and r191
             -> its detector now finds ZERO residual findings in exactly those runs
             (r185 had 12 at its cap and 28 in fact)

    #1203n0  an icon CSS colour cannot reach   LOGS ONLY
             -> 34 findings across the 7 modern runs, including 9 in r190 and 8 in r191,
                the two newest
             -> ZERO tasks about the mechanism anywhere in those 120391 records

The task channel converged; the log channel did not. #1203f6's rule with evidence behind it: a
finding has to reach a recipient who can act on it, and the orchestrator's log is not one.

The wording is a pure function because the call site is 650 lines into `repair_frontend_api`
and nothing can drive it there -- the same reason #1203pg extracted
`_capture_unavailable_summary_1203pg` and `_checklist_pending_note_1203pg`. The remedy DIFFERS
by mechanism (#1203nv measured it in real Chromium), so the body has to explain both or the
lane fixes one kind and leaves the other.
"""

import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    invisible_icon_task_1203pm as task)

_CC = "A.jsx -> icons/x.svg (currentColor)"
_NP = "B.jsx -> icons/y.svg (no paint at all)"


class TheTaskSaysWhatToDo(unittest.TestCase):

    def test_the_title_carries_the_count(self):
        t, _ = task([_CC, _NP])
        self.assertIn("2 staged icon(s)", t)

    def test_the_title_says_the_icons_are_invisible_not_merely_odd(self):
        """A lane triaging a P1 queue reads titles. "make them visible" is actionable;
        "icon colour issue" is not."""
        t, _ = task([_CC])
        self.assertIn("visible", t.lower())
        self.assertIn("<img>", t)

    def test_the_rows_reach_the_body(self):
        _, b = task([_CC, _NP])
        self.assertIn("A.jsx", b)
        self.assertIn("B.jsx", b)

    def test_BOTH_mechanisms_are_explained(self):
        """#1203nv: `currentColor` inlines correctly under a CSS `color`; a no-paint SVG needs
        the CSS to set `fill`. A body that explains one leaves the other broken.

        Asserted on the EXPLANATION, not on the words appearing anywhere. The first version
        checked `"no paint at all" in b` -- and the fixture ROW is
        `B.jsx -> icons/y.svg (no paint at all)`, so deleting the whole explaining sentence was
        MISSED: my own test was fed by its own input. The rows are passed through verbatim, so
        anything that quotes a mechanism name has to look past them.
        """
        _, b = task([_CC, _NP])
        body = b.split("\n\n", 2)[-1]          # past the row list
        self.assertIn("cannot inherit through an", body, "the currentColor remedy is missing")
        self.assertIn("names no paint", body, "the no-paint remedy is missing")
        self.assertIn("set\n`fill`", body.replace("set `fill`", "set\n`fill`"))
        self.assertIn("INLINE", body)

    def test_the_explanation_survives_rows_that_quote_the_mechanisms(self):
        """The trap above, pinned: with NO rows the explanation must still be whole."""
        _, b = task([])
        self.assertIn("cannot inherit through an", b)
        self.assertIn("names no paint", b)

    def test_the_measurement_is_quoted_so_the_remedy_is_not_a_guess(self):
        """Real Chromium, 48x48 on #121212: `fill:#fff` on a no-paint icon reads 7.9 / 0 bright,
        a currentColor icon inlined under `color` reads 151.3 / 1296."""
        _, b = task([_CC])
        self.assertIn("151.3", b)
        self.assertIn("7.9", b)

    def test_the_other_legitimate_fix_is_offered(self):
        """#551/#1203kw keep the <img> channel open for assets that carry their own colours,
        so the task must not tell the lane to inline everything."""
        _, b = task([_CC])
        self.assertIn("carries its own colours", b.replace("carry its own colours",
                                                           "carries its own colours"))

    def test_a_long_list_declares_its_cut(self):
        """#1034, and #1203pl is what forgetting it costs on this very axis."""
        rows = ["f%02d.jsx -> icons/i%02d.svg (currentColor)" % (i, i) for i in range(20)]
        t, b = task(rows)
        self.assertIn("20 staged icon(s)", t)
        self.assertIn("more", b, "twenty rows were cut to eight with no note of the cut")

    def test_an_empty_list_does_not_crash(self):
        t, b = task([])
        self.assertIn("0 staged icon(s)", t)

    def test_none_does_not_crash(self):
        self.assertTrue(task(None)[0])


class TheWiringFilesIt(unittest.TestCase):
    """The half #1203f6 is about: the text existing is not the text arriving."""

    def _block(self):
        src = inspect.getsource(HP.HealPipeline.repair_frontend_api) \
            if hasattr(HP, "HealPipeline") else inspect.getsource(HP)
        i = src.index("#1203pm: AND FILE IT")
        # from the LINE start, so the block has a uniform indent and `textwrap.dedent` works.
        # Slicing from the marker text left the first line flush and the rest indented, which
        # made dedent a no-op and the AST parse fail on "unexpected indent".
        i = src.rfind("\n", 0, i) + 1
        return src[i:src.index("except Exception as _iv_err", i)]

    def test_a_task_is_created_from_the_owner(self):
        b = self._block()
        self.assertIn("invisible_icon_task_1203pm(_inv1203n0)", b)
        self.assertIn("create_task(", b)

    def test_the_create_task_is_an_actual_STATEMENT(self):
        """`"create_task(" in b` is satisfied by `None and orch.hubs.workhub.create_task(...)`,
        which never runs -- a mutation proved it. The call site is 650 lines into
        `repair_frontend_api` and cannot be driven, so this is structural on purpose: the call
        must be an expression STATEMENT, not an operand of a boolean.
        """
        import textwrap
        tree = ast.parse(textwrap.dedent(self._block()))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and getattr(n.value.func, "attr", "") == "create_task"]
        self.assertEqual(len(calls), 1, (
            "the filing is not a bare statement -- it is reachable only if some expression "
            "evaluates truthy first: %s" % ast.unparse(tree)[:300]))

    def test_it_goes_to_the_lane_that_can_fix_it(self):
        b = self._block()
        self.assertIn('assignee="frontend"', b)
        self.assertIn('priority="P1"', b)
        self.assertIn('kind="fidelity"', b)

    def test_it_is_deduped_so_a_steady_state_does_not_refile(self):
        """#1041: task storms. The key has to be the finding SET, not a constant, or a changed
        finding set would never produce a second task."""
        b = self._block()
        self.assertIn("state_changed_1202ad", b)
        self.assertIn("tuple(sorted(map(str, _inv1203n0)))", b)

    def test_a_filing_failure_is_announced_not_swallowed(self):
        b = self._block()
        self.assertIn("except Exception as _e1203pm", b)
        self.assertIn("warn_once_1201", b)
        self.assertIn("log-only again", b)

    def test_the_announcement_is_an_actual_STATEMENT_too(self):
        """Same trap as the filing: `None and _w1203pm(...)` keeps every asserted string and
        never runs, so a filing failure would be silent -- #1201's exact subject, in the code
        added to stop a finding being silent.
        """
        import textwrap
        tree = ast.parse(textwrap.dedent(self._block()))
        handlers = [h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers
                    if getattr(h, "name", None) == "_e1203pm"]
        self.assertEqual(len(handlers), 1, "the #1203pm handler moved")
        warns = [n for n in ast.walk(handlers[0])
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and getattr(n.value.func, "id", "") == "_w1203pm"]
        self.assertEqual(len(warns), 1, (
            "the warning is not a bare statement, so a filing failure can be silent: %s"
            % ast.unparse(handlers[0])[:300]))

    def test_the_log_line_was_not_replaced_by_the_task(self):
        """#1203n0's warning stays. The task is an ADDITION -- a reader of the log should still
        see the finding, and #1203pm's own point is that two channels are not one."""
        src = inspect.getsource(HP)
        self.assertIn("#1203n0 %s loads a staged icon CSS colour cannot reach", src)

    def test_the_filing_cannot_break_the_heal_pass(self):
        """AST: the create_task must sit inside a try whose handler is a bare Exception."""
        import textwrap
        tree = ast.parse(textwrap.dedent(self._block()))
        self.assertTrue(
            any(isinstance(n, ast.Try) and n.handlers
                and isinstance(n.handlers[0].type, ast.Name)
                and n.handlers[0].type.id == "Exception"
                for n in ast.walk(tree)),
            "the filing is not wrapped in a bare-Exception try")


if __name__ == "__main__":
    unittest.main()
