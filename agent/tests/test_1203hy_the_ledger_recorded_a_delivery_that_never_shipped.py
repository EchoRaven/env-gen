"""#1203hy: a milestone was recorded `delivered` with no release cut for it.

#1125 marks the CURRENT milestone `delivered` when `_project_delivered_event` is set, because
the only other writer marks the PREVIOUS ones -- so the final milestone of every run could
never be marked at all (68 of 69 runs, measured there).

That event has TWO setters:

  * `_maybe_framework_deliver`, which cuts the release FIRST (`create_release`, then
    `_project_delivered = True` some seventy lines later -- verified by reading the file, not
    the comments), and
  * the `deliver_project` TOOL, whose own docstring says it "just sets
    `_project_delivered_event` -- it does not cut a release".

The tool gates on the confirmation string and a retro policy. The four gates that would have
stopped it (coverage / visual / seed / runhub) were deleted on 2026-05-30 as dead code that
read a `hub_registry` attribute production never set, and that deletion's comment flags
re-wiring them as a follow-up -- never done. So an orchestrator LLM calling `deliver_project`
with the delivery gate RED sets the event, and the ledger records a delivery that never
shipped.

    tiktok-r171   deliver_project at 17:22:46, run over at 17:27.
                  milestones.json  ['delivered','delivered','delivered','delivered']
                  release tags     ['1.0.0','1.1.0','1.2.0']          <- no v1.3.0
                  terminal_reason  "the loop exited with the app not delivered ...
                                    the delivery gate declined"
    tiktok-r119   the same shape one milestone earlier (1.2.0 flagged, two tags).

Across every run holding a milestones.json, 15 of 105 carry a `delivered` with no matching
tag; 13 are an era with no release ledger at all, leaving these two. It cost a real answer:
r171 was counted as a full 4/4 delivery off this flag and had to be retracted to 3 of 4.

THE THIRD STATE IS THE POINT. A ledger that cannot be read is not evidence that nothing
shipped, so "unknown" marks the milestone exactly as before -- reading an error as "no
release" would silently restore the bug #1125 measured.
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
    def __init__(self): self.warnings = []; self.debugs = []
    def warning(self, m, *a, **k): self.warnings.append(str(m) % a if a else str(m))
    def debug(self, m, *a, **k): self.debugs.append(str(m) % a if a else str(m))
    info = error = warning


class _Releases:
    def __init__(self, value): self._v = value
    def value(self):
        if isinstance(self._v, Exception):
            raise self._v
        return self._v


def _orch(releases):
    o = object.__new__(orch_mod.Orchestrator)
    o._logger = _Log()
    o.hubs = type("H", (), {})()
    o.hubs.codehub = type("C", (), {})()
    o.hubs.codehub.stores = type("S", (), {})()
    o.hubs.codehub.stores.releases = _Releases(releases)
    return o


def _ledger(*tags):
    d = {"_meta": {"version": 7}}
    for i, t in enumerate(tags):
        d["rel_%d" % i] = {"tag": t, "branch": "release-v%s" % t}
    return d


class TheTwoRunsThisWasWrittenFor(unittest.TestCase):

    def test_r171_the_fourth_milestone_has_no_release(self):
        o = _orch(_ledger("1.0.0", "1.1.0", "1.2.0"))
        self.assertEqual(o._milestone_release_state_1203hy("1.3.0"), "no")

    def test_r171s_earlier_milestones_do_have_one(self):
        o = _orch(_ledger("1.0.0", "1.1.0", "1.2.0"))
        for v in ("1.0.0", "1.1.0", "1.2.0"):
            self.assertEqual(o._milestone_release_state_1203hy(v), "yes", v)

    def test_r177_the_run_that_actually_shipped_four(self):
        o = _orch(_ledger("1.0.0", "1.1.0", "1.2.0", "1.3.0"))
        self.assertEqual(o._milestone_release_state_1203hy("1.3.0"), "yes")

    def test_an_empty_ledger_is_a_no_not_an_unknown(self):
        """It read cleanly and holds nothing -- that is evidence."""
        o = _orch({"_meta": {"version": 1}})
        self.assertEqual(o._milestone_release_state_1203hy("1.0.0"), "no")

    def test_only_a_tag_counts_never_a_version(self):
        """★ A record carrying a `version` and no `tag` is not a release. This is what makes
        the `_meta` skip redundant rather than load-bearing: a mutation dropping that skip
        survived a round, correctly, because `tag` already excludes `_meta` -- the same thing
        #1202jg verified about its own copy of the filter. What is NOT redundant is requiring
        `tag`: dropping to `version or tag` also survived, and together the two mutations
        would let `_meta`'s own revision counter answer "yes"."""
        o = _orch({"_meta": {"version": "1.3.0"},
                   "rel_0": {"version": "1.3.0", "branch": "release-v1.3.0"}})
        self.assertEqual(o._milestone_release_state_1203hy("1.3.0"), "no")

    def test_meta_is_never_mistaken_for_a_release(self):
        """`_meta` carries a `version` but never a `tag` -- the distinction #1202jg records
        after misreading it as a release once."""
        o = _orch({"_meta": {"version": "1.0.0"}})
        self.assertEqual(o._milestone_release_state_1203hy("1.0.0"), "no")


class UnknownMustNotReadAsNo(unittest.TestCase):
    """Reading an error as "no release" would restore the #1125 bug on every run whose
    ledger read happens to fail."""

    def test_an_unreadable_ledger_is_unknown(self):
        o = _orch(RuntimeError("store locked"))
        self.assertEqual(o._milestone_release_state_1203hy("1.0.0"), "unknown")
        self.assertTrue(o._logger.debugs, "the unreadable ledger was not even mentioned")

    def test_a_non_dict_ledger_is_unknown(self):
        for junk in ([], "", 7, None):
            o = _orch(junk)
            self.assertEqual(o._milestone_release_state_1203hy("1.0.0"), "unknown", junk)

    def test_a_missing_version_is_unknown_not_no(self):
        """With nothing to compare against, the ledger cannot answer."""
        o = _orch(_ledger("1.0.0"))
        for v in ("", None, "   "):
            self.assertEqual(o._milestone_release_state_1203hy(v), "unknown", repr(v))

    def test_no_hubs_at_all_is_unknown(self):
        o = object.__new__(orch_mod.Orchestrator)
        o._logger = _Log()
        self.assertEqual(o._milestone_release_state_1203hy("1.0.0"), "unknown")

    def test_it_never_raises(self):
        for rel in (RuntimeError("x"), KeyError("y"), [], {"a": None}, {"a": 7}):
            o = _orch(rel)
            self.assertIn(o._milestone_release_state_1203hy("1.0.0"),
                          ("yes", "no", "unknown"))


class OnlyAKnownNoSuppressesTheMarking(unittest.TestCase):

    @staticmethod
    def _src():
        return textwrap.dedent(inspect.getsource(orch_mod.Orchestrator.run))

    def _delivered_marks(self, tree):
        out = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "mark_status"
                    and any(isinstance(a, ast.Constant) and a.value == "delivered"
                            for a in n.args)):
                out.append(n)
        return out

    def test_the_current_milestone_marking_is_guarded_by_the_release_state(self):
        tree = ast.parse(self._src())
        marks = self._delivered_marks(tree)
        self.assertTrue(marks, "found no `mark_status(..., 'delivered')` to check")
        guarded = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.If):
                continue
            test_names = {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
            if "_rel1203hy" not in test_names:
                continue
            guarded += [m for m in self._delivered_marks(n) if m in marks]
        self.assertEqual(len(guarded), 1,
                         "expected exactly one delivered-marking behind the #1203hy state, "
                         "found %d" % len(guarded))

    def test_a_known_no_takes_the_branch_that_does_not_mark(self):
        """The warning branch and the marking branch must be the two sides of one `if`, so a
        "no" cannot fall through into the mark."""
        tree = ast.parse(self._src())
        found = False
        for n in ast.walk(tree):
            if not isinstance(n, ast.If):
                continue
            if not any(isinstance(c, ast.Constant) and c.value == "no"
                       for c in ast.walk(n.test)):
                continue
            if not any(isinstance(x, ast.Name) and x.id == "_rel1203hy"
                       for x in ast.walk(n.test)):
                continue
            found = True
            self.assertEqual(self._delivered_marks(ast.Module(body=n.body, type_ignores=[])),
                             [], "the `no` branch marks the milestone delivered")
            self.assertTrue(self._delivered_marks(
                ast.Module(body=n.orelse, type_ignores=[])),
                "the else branch does not mark the milestone delivered")
        self.assertTrue(found, "no branch compares the #1203hy state against 'no'")

    def test_the_warning_names_the_version_that_did_not_ship(self):
        """Landmark-anchored, not a byte window (#943): the call's own arguments end at the
        `)` the AST reports, so take the branch's warning call from the tree."""
        tree = ast.parse(self._src())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "warning"
                 and any(isinstance(a, ast.Constant)
                         and "signalled delivery but NO release was" in str(a.value)
                         for a in ast.walk(n))]
        self.assertEqual(len(calls), 1, "expected one such warning, found %d" % len(calls))
        passed = {a.attr for a in ast.walk(calls[0]) if isinstance(a, ast.Attribute)}
        names = {a.id for a in ast.walk(calls[0]) if isinstance(a, ast.Name)}
        self.assertIn("_m_idx", names, names)
        self.assertIn("_milestone", names,
                      "the warning does not pass the milestone it is about: %r" % (names,))
        self.assertIn("get", passed, passed)


if __name__ == "__main__":
    unittest.main()
