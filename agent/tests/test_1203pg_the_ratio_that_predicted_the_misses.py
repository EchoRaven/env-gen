"""#1203pg: rank tests by source-text assertion ratio, and make the detector prove itself first.

Four guards were mutation-tested in one batch and the ratio predicted every outcome:
`test_fwval_early_return_checklist_502.py` (a pure predicate, ratio 0.00) caught 4 of 4, while
`test_redispatch_nags_without_cloning_794.py` (0.95) and the two fail-open guards
`..._888.py` / `..._882.py` (both 1.00) missed 7 real defects between them. Every miss was the
same shape: `"<line of code>" in getsource(mod)` is satisfied by the line EXISTING, so a mutation
that keeps the line and makes it unreachable reads identical to working code.

These tests pin the two things the tool got WRONG, because both produced a confident number:

  * the transitive step. `_src()` returns `getsource(...)`, `s = _src()`, `blk = s[i:j]` -- three
    hops. The first version matched only the direct form, scored #794 at 0.05 against a hand
    count of 18/19, and reported 7 entirely-text tests.
  * a FIXTURE read is not a source read. `.read()` matched on its own, so
    `open("fixture.json").read()` counted as source text and every ratio came out high.
  * names were matched WITHOUT SCOPE. One test doing `i = src.index(...)` poisoned another
    doing `out = reasons([dict(EP, id="n%d" % i) for i in range(5)])`, where `i` is a
    comprehension variable -- so `out`, the return value of the function under test, counted as
    source text and a fully behavioural file ranked 0.90.

And the self-check's own anchoring, which is the most expensive lesson here: it first anchored on
two real files' hand-counted ratios, and those rotted within the hour -- adding the behavioural
tests this very finding called for moved 18/19 to 18/27, so the check failed on correct work
(#1203oa: a parked measurement rots). The anchors are now cases whose answers are known BY
CONSTRUCTION.
"""

import importlib.util
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_ROOT, "scripts", "text_assertion_ratio.py")


def _load():
    spec = importlib.util.spec_from_file_location("_tar1203pg", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheScriptExists(unittest.TestCase):

    def test_it_is_in_the_repo_not_a_scratchpad(self):
        """#826/#1203pe: a check that lives in a habit is not a check."""
        self.assertTrue(os.path.exists(_SCRIPT), _SCRIPT)


class TheDetectorProvesItselfBeforeRanking(unittest.TestCase):

    def setUp(self):
        self.tar = _load()

    def test_check_passes_on_the_current_tree(self):
        self.assertEqual(self.tar.check(), [])

    def test_the_constructed_cases_are_what_check_rests_on(self):
        """Not the count -- the KIND. Real-file hand counts rot; constructed ones cannot."""
        self.assertGreaterEqual(len(self.tar._SELF_TEST), 4)
        for label, source, want_text, want_total in self.tar._SELF_TEST:
            got = self.tar._ratio_of_source(source)
            self.assertEqual(got, (want_text, want_total), label)

    def test_the_real_file_anchors_assert_a_shape_not_a_number(self):
        """A shape survives new tests being added; a hand-counted ratio does not."""
        for name, shape in self.tar._SHAPE.items():
            self.assertIn(shape, ("pure", "mixed"), name)

    def test_a_broken_detector_refuses_to_rank(self):
        """#1039: "could not tell" must not read as a clean ranking."""
        self.tar._STRONG = __import__("re").compile(r"zzz_no_such_pattern")
        self.assertTrue(self.tar.check(), "a detector that matches nothing reported no problem")
        self.assertEqual(self.tar.main(["--limit", "1"]), 1)


class TheFiveDetectorBugsStayFixed(unittest.TestCase):
    """Each bug produced a confident number, which is why each keeps a named case.

    The sources come from the script's own `_SELF_TEST` rather than being retyped here: one
    owner per rule (#1032), and a copy here would drift from the cases `--check` actually runs.
    """

    def setUp(self):
        self.tar = _load()

    def _case(self, fragment):
        hits = [c for c in self.tar._SELF_TEST if fragment in c[0]]
        self.assertEqual(len(hits), 1,
                         "no single constructed case matches %r -- re-anchor this test"
                         % fragment)
        return hits[0]

    def _assert_case_holds(self, fragment, why):
        label, source, want_text, want_total = self._case(fragment)
        self.assertEqual(self.tar._ratio_of_source(source), (want_text, want_total),
                         "%s (%s)" % (why, label))

    def test_a_name_three_hops_from_getsource_is_still_source_text(self):
        """`_src()` -> `s = _src()` -> `blk = s[i:j]`: the transitive step the first version
        missed, which scored #794 at 0.05 against a hand count of 18/19."""
        self._assert_case_holds("three hops",
                                "the transitive step regressed -- ratios will understate")

    def test_reading_a_fixture_is_not_reading_source(self):
        """`.read()` matched on its own, so a test reading its own DATA counted as source text
        the headline count came out nearly twice too high."""
        self._assert_case_holds("FIXTURE",
                                "a data read counted as source -- ratios will overstate")

    def test_a_read_that_DOES_name_a_source_locator_still_counts(self):
        """The narrowing must not throw away the real case it was narrowing."""
        src = ("import inspect\n"
               "def test_e():\n"
               "    t = pathlib.Path(inspect.getfile(object)).read_text()\n"
               '    assert "def" in t\n')
        self.assertEqual(self.tar._ratio_of_source(src), (1, 1))

    def test_a_locator_split_across_statements_is_a_KNOWN_limitation(self):
        """Stated rather than discovered later: the locator must be in the SAME expression.

        `s = inspect.getfile(x)` then `pathlib.Path(s).read_text()` is not tracked, because the
        read expression alone names no locator. The ranking therefore UNDERSTATES such a file --
        the safe direction for a tool whose job is to say where to look, and the cost of the
        alternative is a second propagation set that could start marking data reads as source
        reads again. If this ever stops being acceptable, the fix is to propagate locator names
        the way text names are propagated, and this test is where to change the claim.
        """
        src = ("import inspect\n"
               "def test_f():\n"
               "    s = inspect.getfile(object)\n"
               "    t = pathlib.Path(s).read_text()\n"
               '    assert "def" in t\n')
        self.assertEqual(self.tar._ratio_of_source(src), (0, 1),
                         "the limitation changed -- update the claim in this docstring")

    def test_a_text_name_inside_a_string_literal_does_not_leak(self):
        """The third bug, and the worst: matching a name as a WORD in the unparsed text.

        `test_1202z0` built the chain `src` -> `tree` -> `fn` -> `calls`, all genuinely
        source-derived, and then `wh = _WH([{"title": "... calls an auth-required endpoint"}])`
        picked `calls` out of a STRING. That marked `wh`, which marked
        `d = wh.created[0]["description"]`, and all 18 of that file's assertions were counted as
        source text -- in one of the most behavioural files in the directory. Comparing
        `ast.Name` ids cannot do this.
        """
        self._assert_case_holds("inside a STRING",
                                "a name leaked out of a string literal and cascaded")

    def test_source_that_is_evaluated_counts_as_driven(self):
        """The fourth: reading source and RUNNING source are opposite things.

        `test_1202kn` lifts the shipped guard out with `getsource` and `eval`s it against fake
        gate objects. It ranked 1.00 while its mutations came back 2 of 2 CAUGHT.
        """
        self._assert_case_holds("EVALUATED", "evaluated source was counted as merely read")

    def test_the_real_file_that_exposed_the_leak_is_scored_as_behavioural(self):
        """Anchored on a SHAPE, not a count, so adding tests to it cannot rot this (#1203oa)."""
        hits = [p for d in self.tar._TEST_DIRS
                for p in (self.tar._ROOT / d).glob("test_1202z0_*.py")]
        if not hits:
            self.skipTest("test_1202z0 is gone; the leak case in _SELF_TEST still covers it")
        text, total = self.tar.ratio(hits[0])
        self.assertGreater(total, 0)
        self.assertLess(text / total, 0.5,
                        "a file that builds a fake WorkHub and asserts on the created task "
                        "scored as mostly source text (%d/%d)" % (text, total))

    def test_a_string_that_spells_a_source_pattern_is_not_source(self):
        """Found by mutating the detector: removing the string-blanking was MISSED, because no
        constructed case contained a literal that SPELLS `getsource`. The self-test suite had
        the same hole it exists to find."""
        self._assert_case_holds("spells a source pattern",
                                "a string literal naming a source pattern counted as source")

    def test_a_name_is_scoped_to_the_function_that_binds_it(self):
        """The fifth bug: `i` as a source offset in one test, a loop variable in another."""
        self._assert_case_holds("scoped to the function",
                                "a name leaked across function scopes")

    def test_the_real_file_that_exposed_the_scope_bug_is_mostly_behavioural(self):
        """Shape, not a count, so adding tests cannot rot it (#1203oa).

        Every assertion in this file is about `out`, the return value of the function under
        test. It ranked 0.90.
        """
        hits = [p for d in self.tar._TEST_DIRS
                for p in (self.tar._ROOT / d).glob("test_1203g3_*.py")]
        if not hits:
            self.skipTest("test_1203g3 is gone; the constructed case still covers the bug")
        text, total = self.tar.ratio(hits[0])
        self.assertGreater(total, 0)
        self.assertLess(text / total, 0.5,
                        "a file whose assertions are all about a return value scored as mostly "
                        "source text (%d/%d)" % (text, total))

    def test_a_behavioural_assert_is_never_text(self):
        self._assert_case_holds("behavioural",
                                "a behavioural assert was counted as source text")


class TheRankingSaysWhatItCut(unittest.TestCase):

    def test_a_capped_listing_declares_its_cut(self):
        """#1034: a capped list must say it was capped."""
        out = subprocess.run(
            [sys.executable, _SCRIPT, "--limit", "3"],
            capture_output=True, text=True, cwd=_ROOT, timeout=600).stdout
        self.assertIn("more not shown", out, out[-400:])

    def test_check_mode_is_read_only_and_exits_zero_when_it_holds(self):
        r = subprocess.run([sys.executable, _SCRIPT, "--check"],
                           capture_output=True, text=True, cwd=_ROOT, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("detector holds", r.stdout)


class TheGuardsThisFoundAreNowDriven(unittest.TestCase):
    """Non-vacuity for the finding itself: the four files it ranked must still be mutation-covered.

    Without this, a later edit could drop the behavioural tests and the only record that the
    ratio ever found anything would be this docstring.
    """

    def test_each_of_the_four_has_a_mutation_spec(self):
        import glob
        import json
        tests = set()
        for p in glob.glob(os.path.join(_ROOT, "scripts", "mutations", "*.json")):
            try:
                # #1202eu: a handle per file, in a loop over a whole tree. The ratchet caught
                # this version of the test on the run that landed it.
                with open(p, encoding="utf-8") as fh:
                    t = json.load(fh).get("test")
            except Exception:
                continue
            if isinstance(t, str):
                tests.add(os.path.basename(t))
        for name in ("test_redispatch_nags_without_cloning_794.py",
                     "test_the_visual_defer_check_that_failed_open_888.py",
                     "test_the_kickoff_guard_that_failed_open_882.py",
                     "test_fwval_early_return_checklist_502.py"):
            self.assertIn(name, tests, "%s lost its mutation spec" % name)


if __name__ == "__main__":
    unittest.main()
