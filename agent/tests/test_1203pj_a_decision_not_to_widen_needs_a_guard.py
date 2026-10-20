"""#1203pj: #1203e2 decided NOT to widen a predicate, and nothing held the decision in place.

Two scans in `coverage_audit` skip anything whose status is `defined`:

    if (ep.get("status") or "defined") != "defined":        # endpoint consumers
    if (tool.get("status") or "defined") != "defined":       # MCP tools

#1203d6 widened the same predicate in `plan_probe` to an explicit allowed set, and #1203e2
deliberately did NOT do that here. Its reasoning is measured, and the measurement is the reason:

    2305 of 4990 `implemented` endpoints have no registered consumer. After #1202kf's
    framework-surface exemption, 489 remain -- median 1 per run, max 31, and 81 of 191 runs
    would gain none. Spot-checking the 27 candidates in the four newest runs against the
    frontend source: 20 really are unreferenced, but 7 ARE called, including `GET /api/videos`
    and `POST /api/videos`.

26% false positives on a HARD blocker is not shippable (#1203a5: one false block cost an entire
run), and both things that would justify it are missing -- the consumers registry is known to be
under-populated (#1203b0: the lane's own tool could not express `apis_used`), and a prefix grep
for `/api/comments/` also matches a file calling `/api/comments/${id}/like`, so the 20 and the 7
are both soft.

A decision not to change is still a decision, and #1203oa is the standing lesson: a parked
measurement rots, so the fix is a ratchet on the THING rather than trust in the number. Found by
asking which framework ticket markers no test names -- #1203e2 was one of 27 out of 1934.

This pins the narrow form so a later widening has to come through here, where the cost is
written down. It deliberately does NOT pin the figures above: those will drift, and #1203oa's
own correction is what that costs.
"""

import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime import coverage_audit as CA


def _status_guards():
    """Every `(x.get("status") or "defined") != "defined"` test in the module, from the tree."""
    tree = ast.parse(inspect.getsource(CA))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        src = ast.unparse(node)
        if '"status"' in src or "'status'" in src:
            out.append((node, src))
    return out


class TheNarrowPredicateIsHeldInPlace(unittest.TestCase):

    def test_the_scan_finds_the_guards(self):
        """#947/#1039: a detector that reaches nothing must not read as a clean result."""
        self.assertTrue(_status_guards(), "no status guard found -- re-aim this test")

    def test_both_sites_still_use_the_NARROW_form(self):
        """`!= "defined"` sweeps `implemented` in by construction, which is the whole point:
        94% of endpoints never reach the scan, and that is deliberate."""
        narrow = [s for _, s in _status_guards() if "!= 'defined'" in s or '!= "defined"' in s]
        self.assertGreaterEqual(len(narrow), 2, [s for _, s in _status_guards()])

    def test_neither_site_was_widened_to_a_status_SET(self):
        """The shape #1203d6 used in `plan_probe` and #1203e2 refused here: `status in {...}`.

        If this fails, someone widened the predicate -- which may be right, but it costs a hard
        blocker a measured 26% false-positive rate, so it has to be an argued change rather
        than a drift.
        """
        widened = [s for n, s in _status_guards()
                   if any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)]
        self.assertEqual(widened, [], (
            "a status guard now tests membership in a set: %s -- #1203e2 measured 26%% false "
            "positives for exactly this widening (20 of 27 really unreferenced, 7 genuinely "
            "called), and #1203a5 is what one false block costs" % widened))

    def test_the_default_keeps_an_absent_status_OUT_of_the_scan(self):
        """`or "defined"` is the second half: a record with no status must not be scanned, or
        the under-populated consumers registry (#1203b0) turns straight into false blocks."""
        defaults = [s for _, s in _status_guards() if 'or "defined"' in s or "or 'defined'" in s]
        self.assertGreaterEqual(len(defaults), 2, [s for _, s in _status_guards()])

    def test_the_decision_and_its_cost_are_recorded_where_the_code_is(self):
        """#1203j2: a decision whose reasoning is not next to the code is a decision nobody can
        revisit. Anchored on the load-bearing phrases, not on the figures, which will drift."""
        src = inspect.getsource(CA)
        self.assertIn("DELIBERATELY NOT WIDENED", src)
        self.assertIn("1203a5", src, "the cost of a false block must be cited")
        self.assertIn("1203b0", src, "the reason 'no consumer' does not mean 'unused'")
