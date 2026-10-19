"""#1203pe: the mutation specs now live in the repo, and the census is a check not a habit.

A mutation only tests something while its `find` anchor appears EXACTLY ONCE in the target
file. A later patch that rewrites that region turns the property into "nothing is verifying
this" while the suite stays green. Catching that means re-checking PAST specs against the
current tree -- and `scripts/README.md` told everyone to write the spec to `/tmp/spec.json`,
so the past specs were thrown away every session.

MEASURED when this landed: 62 specs / 253 mutations existed for the running session and ZERO
in any earlier session's scratchpad, and no copy anywhere in the repo. So the cross-session
half of a discipline I had written down had never been runnable. `mutate.py`'s own header
quotes #826 for this exact shape: "a check that lives in a habit is not a check".
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")
_SPECS = os.path.join(_SCRIPTS, "mutations")
_CENSUS = os.path.join(_SCRIPTS, "mutation_census.py")


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, _CENSUS, *args], cwd=cwd or _ROOT,
                          capture_output=True, text=True)


class TheSpecsArePersisted(unittest.TestCase):

    def test_the_directory_exists_and_holds_specs(self):
        self.assertTrue(os.path.isdir(_SPECS), "the specs are back in /tmp")
        names = [n for n in os.listdir(_SPECS) if n.endswith(".json")]
        self.assertGreater(len(names), 40, "only %d spec(s) persisted" % len(names))

    def test_every_spec_parses_and_names_a_target_and_a_test(self):
        for name in sorted(os.listdir(_SPECS)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(_SPECS, name), encoding="utf-8") as fh:
                spec = json.load(fh)
            self.assertTrue(spec.get("file"), "%s names no target" % name)
            self.assertTrue(spec.get("test"), "%s names no test" % name)
            self.assertTrue(spec.get("mutations"), "%s has no mutations" % name)

    def test_every_target_file_still_exists(self):
        """A spec whose target is gone cannot be censused, and the census must SAY so rather
        than count it as clean (#883)."""
        for name in sorted(os.listdir(_SPECS)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(_SPECS, name), encoding="utf-8") as fh:
                spec = json.load(fh)
            self.assertTrue(os.path.isfile(os.path.join(_ROOT, spec["file"])),
                            "%s targets a file that is gone: %s" % (name, spec["file"]))

    def test_the_readme_no_longer_sends_specs_to_tmp(self):
        with open(os.path.join(_SCRIPTS, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("scripts/mutations", text,
                      "the documented workflow still throws the spec away")


class TheCensusIsAChance(unittest.TestCase):

    def test_it_runs_and_reports_zero_unexplained_today(self):
        out = _run()
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertIn("UNEXPLAINED 0", out.stdout,
                      "an anchor lost without an explanation: %s" % out.stdout[-600:])

    def test_strict_mode_passes_today(self):
        self.assertEqual(_run("--strict").returncode, 0)

    def test_it_can_actually_FAIL(self):
        """The census must be falsifiable, or it is the thing it was written to replace.

        Driven on a throwaway spec dir with one deliberately broken anchor and no label.
        """
        with tempfile.TemporaryDirectory() as d:
            spec_dir = os.path.join(d, "mutations")
            os.makedirs(spec_dir)
            with open(os.path.join(spec_dir, "mut_probe.json"), "w", encoding="utf-8") as fh:
                json.dump({"file": "scripts/mutation_census.py", "test": "tests/test_1203pe_the_census_the_habit_could_not_do.py",
                           "mutations": [{"label": "a property nobody carries now",
                                          "find": "THIS STRING IS NOT IN THE FILE 1203pe",
                                          "replace": "y"}]}, fh)
            sys.path.insert(0, _SCRIPTS)
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("_census1203pe", _CENSUS)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                rows, problems, _retired = mod.census(spec_dir=spec_dir, root=_ROOT)
            finally:
                sys.path.remove(_SCRIPTS)
        self.assertEqual(problems, [])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0][3], "an unlabelled loss must read as UNEXPLAINED")

    def test_a_documented_loss_reads_as_explained(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_census1203pe_b", _CENSUS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            spec_dir = os.path.join(d, "mutations")
            os.makedirs(spec_dir)
            with open(os.path.join(spec_dir, "mut_probe.json"), "w", encoding="utf-8") as fh:
                json.dump({"file": "scripts/mutation_census.py", "test": "tests/test_1203pe_the_census_the_habit_could_not_do.py",
                           "mutations": [{"label": "moved  [SUPERSEDED 2026-10-19: the "
                                                   "predicate was inlined at its only reader]",
                                          "find": "NOT IN THE FILE EITHER 1203pe",
                                          "replace": "y"}]}, fh)
            rows, problems, _retired = mod.census(spec_dir=spec_dir, root=_ROOT)
        self.assertEqual(problems, [])
        self.assertTrue(rows[0][3], "[SUPERSEDED ...] must count as an explanation")

    def test_an_unreadable_spec_dir_is_not_reported_as_clean(self):
        """#883: 'I could not look' and 'I looked and found nothing' are different answers."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_census1203pe_c", _CENSUS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows, problems, _retired = mod.census(spec_dir="/nonexistent/1203pe", root=_ROOT)
        self.assertEqual(rows, [])
        self.assertTrue(problems, "a missing spec dir must be a PROBLEM, not an empty census")

    def test_the_specs_are_collected_by_SHAPE_not_by_filename(self):
        """The first collection step used `cp mut_*.json` and took 62 of 248 specs.

        248 specs exist; only 62 are named `mut_*` -- the rest are `glyph_now.json`,
        `oc_spec1.json`, `p6_mut.json`, `mu_spec*.json`, `spec_j*.json`, `n6_*.json` and so
        on. A census over a quarter of the inventory that reports "UNEXPLAINED 0" is the
        failure this census exists to prevent. #1203ow's criterion, written down before this
        happened: filter by ROLE, not by spelling.
        """
        names = [n for n in os.listdir(_SPECS) if n.endswith(".json")]
        self.assertGreater(len(names), 200,
                           "only %d spec(s) -- the collection step filtered by name again"
                           % len(names))
        prefixed = [n for n in names if n.startswith("mut_")]
        self.assertLess(len(prefixed), len(names) * 3 // 4,
                        "if nearly every spec is `mut_*`, the shape-based collection was lost")

    def test_an_explanation_that_names_a_missing_carrier_is_not_an_explanation(self):
        """7 of the first 9 explanations pointed at a spec the collection had not copied."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_census1203pe_e", _CENSUS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            spec_dir = os.path.join(d, "mutations")
            os.makedirs(spec_dir)
            with open(os.path.join(spec_dir, "mut_probe.json"), "w", encoding="utf-8") as fh:
                json.dump({"file": "scripts/mutation_census.py", "test": "tests/test_1203pe_the_census_the_habit_could_not_do.py",
                           "mutations": [{"label": "moved  [SUPERSEDED 2026-10-19: carried in "
                                                   "mut_nowhere.json as X]",
                                          "find": "NOT IN THE FILE 1203pe carrier",
                                          "replace": "y"}]}, fh)
            rows, problems, _retired = mod.census(spec_dir=spec_dir, root=_ROOT)
        self.assertEqual(problems, [])
        self.assertFalse(rows[0][3],
                         "a carrier that does not exist cannot carry anything")
        self.assertIn("CARRIER MISSING", rows[0][4])

    def test_a_present_carrier_still_counts_as_an_explanation(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_census1203pe_f", _CENSUS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            spec_dir = os.path.join(d, "mutations")
            os.makedirs(spec_dir)
            with open(os.path.join(spec_dir, "mut_carrier.json"), "w", encoding="utf-8") as fh:
                json.dump({"file": "scripts/mutation_census.py", "test": "tests/test_1203pe_the_census_the_habit_could_not_do.py",
                           "mutations": [{"label": "ok", "find": "def census(", "replace": "x"}]}, fh)
            with open(os.path.join(spec_dir, "mut_probe.json"), "w", encoding="utf-8") as fh:
                json.dump({"file": "scripts/mutation_census.py", "test": "tests/test_1203pe_the_census_the_habit_could_not_do.py",
                           "mutations": [{"label": "moved  [SUPERSEDED 2026-10-19: carried in "
                                                   "mut_carrier.json as X]",
                                          "find": "NOT IN THE FILE 1203pe carrier2",
                                          "replace": "y"}]}, fh)
            rows, problems, _retired = mod.census(spec_dir=spec_dir, root=_ROOT)
        self.assertEqual(problems, [])
        bad = [r for r in rows if not r[3]]
        self.assertEqual(bad, [], "a present carrier must satisfy the explanation")

    def test_only_a_closed_vocabulary_explains_a_loss(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_census1203pe_d", _CENSUS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(tuple(mod._EXPLAINED),
                         ("[SUPERSEDED", "[NOT RUNNABLE", "[BAD-ANCHOR"),
                         "'the code changed' must not become an explanation")


if __name__ == "__main__":
    unittest.main()
