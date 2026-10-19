"""#1203oz: a non-vacuity floor that grew 3.7x of slack stopped being a check.

Several ratchets guard themselves with a REACH FLOOR -- "the scan parsed at least N things,
otherwise it did not look" -- which is #947's rule and the reason those ratchets are not
vacuous. A floor is a check only while it sits close to what the scan actually reaches.

`test_lazy_imports_resolve_802` wrote its own number next to it: "364 at the time of
writing", floor 300. That is an ~82% margin and a real check. The scan has since grown to
1103 (#1203n6 widened it 840 -> 945 by itself) while the floor stayed at 300, so the
assertion could no longer tell "looked at 1103" from "looked at 301" -- 73% of the reach
could vanish behind a passing test. Measured across the tree on 2026-10-19:

    #802  _IMPORTS   300 -> 1103   3.7x        #885  defs      300 ->  630   2.1x
    #1034 visited    100 ->  267   2.7x        #843  sl        100 ->  175   1.8x
    #814  _MODULES   100 ->  170   1.7x

New numbers rot the same way, which is #1203oa's whole lesson, so this file re-derives each
subject's size TODAY, refuses a floor carrying more than `_MAX_SLACK_1203OZ` of slack, and
names the number to raise it to. Floors may always be raised; that is the direction a floor
moves as a tree grows.

The floors are DISCOVERED from the tree, not listed here: a hard-coded list is the thing
that goes stale, and #1203ow is the same lesson one level out (filter by role, not by
spelling). Anything discovered must be watched or exempted with a reason.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import unittest
from typing import Optional

# A check that can lose HALF its reach silently is already generous; every watched floor
# sits at ~1.2x after #1203oz, so this ceiling is not tight against any of them.
_MAX_SLACK_1203OZ = 2.0

# Phrases that make a function's job "prove the scan looked". Discovery keys on the
# FUNCTION's name and docstring -- its role -- rather than on the variable's spelling.
_VACUITY_WORDS_1203OZ = (
    "vacuous", "vacuity", "non-vacuity", "did not look", "reach", "finds something",
    "finds the tree", "sees the tree", "looked", "in scope", "instrument-zero",
    "has marked", "corpus has", "exercised",
)
# ^ "exercised" was MISSING from the first draft and cost one floor's coverage: a recall
# audit of this very vocabulary (every `assert len(X) >= N` with N >= 100 in a function the
# words do NOT match) found exactly one -- #834's `test_the_corpus_is_being_exercised`,
# `len(docs) >= 100`. Its slack is 1.0x today (104 design docs), i.e. the TIGHTEST floor in
# the tree and in no need of raising -- but unwatched it would rot the moment the corpus
# grows. #1203ow's lesson, applied to this file: a role filter is only as wide as its words,
# so the words have to be audited against what they fail to match.
_FLOOR_MIN_1203OZ = 100          # below this a threshold is a small expectation, not a reach floor

# Watched: (module, how to size the subject). `call:<fn>` / `call:<fn>#<i>` is for a floor
# whose subject is produced by the ratchet's own scan rather than held as a constant --
# #1034's `visited` is the second element of `_scan_pkg_1203jx()`, and leaving it out
# because it is awkward to reach is exactly how it would rot next.
_WATCHED_1203OZ = {
    ("test_lazy_imports_resolve_802", "_IMPORTS"): "_IMPORTS",
    ("test_every_module_compiles_and_imports_814", "_MODULES"): "_MODULES",
    ("test_counts_and_lists_agree_1034", "visited"): "call:_scan_pkg_1203jx#1",
    ("test_one_name_one_value_885", "defs"): "call:_defs#0",
    ("test_spec_table_dialects_843", "sl"): "call:_marked_slices",
    ("test_enrichment_guard_requires_components_834", "docs"): "call:_docs",
}

# Discovered but NOT a scan-reach floor. Each reason says what the number is about instead.
_EXEMPT_1203OZ = {
    ("test_1203e6_the_log_recut_a_tail_from_the_front", "UNTAUGHT"):
        "a FIXTURE length -- its own message is 'fixture too short to truncate', so the "
        "number is about the input this test needs, not about a scan's reach",
    ("test_postgres_error_carries_its_statement_973", "out"):
        "one string's bounded widening -- 'must reach the offset the error names', paired "
        "with a `<= 2000` ceiling on the same value; nothing is being scanned",
}


def _tests_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def discover_reach_floors_1203oz(root=None):
    """[(module, var, floor)] for every `assert len(<name>) >= <int>` whose enclosing
    function's ROLE is to prove the scan looked.

    `root` is injectable so the discovery rules can be exercised on a SYNTHETIC tree.
    Mutation testing is why: on the real tree every watched floor is healthy and no stray
    exists, so narrowing or emptying any of these rules is invisible without one.
    """
    out = []
    for f in sorted(pathlib.Path(root or _tests_dir()).glob("test_*.py")):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            blob = (fn.name + " " + (ast.get_docstring(fn) or "")).lower()
            if not any(w in blob for w in _VACUITY_WORDS_1203OZ):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
                    continue
                c = node.test
                if len(c.ops) != 1 or not isinstance(c.ops[0], ast.GtE):
                    continue
                left, right = c.left, c.comparators[0]
                if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Name)
                        and left.func.id == "len" and len(left.args) == 1
                        and isinstance(left.args[0], ast.Name)):
                    continue
                if isinstance(right, ast.Constant) and isinstance(right.value, int) \
                        and right.value >= _FLOOR_MIN_1203OZ:
                    out.append((f.stem, left.args[0].id, right.value))
    return out


def slack_verdict_1203oz(floor: int, size: int) -> Optional[str]:
    """None when the floor is still a check; otherwise what is wrong with it.

    Pure, so the branches can be exercised with fabricated numbers. Mutation testing said
    why: with every real floor healthy, loosening any of these comparisons is invisible
    unless something is CURRENTLY violating it.
    """
    if size <= 0:
        return "the subject is empty (%d), so the scan itself produced nothing" % size
    if floor > size:
        return ("the floor (%d) is ABOVE what the scan reaches (%d), so that ratchet is red "
                "for a reason this check cannot fix" % (floor, size))
    slack = size / float(floor)
    if slack > _MAX_SLACK_1203OZ:
        return ("reaches %d against a floor of %d (%.1fx slack): the scan could lose %d%% of "
                "its reach and still read as non-vacuous. Raise the floor to about %d (~82%%, "
                "the margin test_lazy_imports_resolve_802 chose when it recorded its own "
                "count) and write today's number beside it."
                % (size, floor, slack, int(round(100.0 * (1 - floor / float(size)))),
                   int(size * 0.82)))
    return None


def stray_floors_1203oz(found):
    """Discovered floors that are neither watched nor exempt."""
    return [(m, v, n) for m, v, n in found
            if (m, v) not in _WATCHED_1203OZ and (m, v) not in _EXEMPT_1203OZ]


def missing_watched_1203oz(found):
    """Watched floors discovery no longer finds -- renamed, moved, or the function stopped
    saying what it is for."""
    keys = {(m, v) for m, v, _ in found}
    return sorted(k for k in _WATCHED_1203OZ if k not in keys)


def exemption_is_explained_1203oz(why) -> bool:
    """An exemption has to carry a reason, not a shrug."""
    return len(str(why or "").strip()) > 40


def _subject_1203oz(mod_obj, spec: str):
    """The collection a floor is about, from an attribute or from the scan that builds it."""
    if not spec.startswith("call:"):
        return getattr(mod_obj, spec)
    fn, _, idx = spec[len("call:"):].partition("#")
    out = getattr(mod_obj, fn)()
    return out[int(idx)] if idx else out


class TheVerdictItselfBites(unittest.TestCase):
    """Positive controls on fabricated numbers -- the only way these branches are observable
    while every real floor is healthy."""

    def test_a_healthy_floor_is_accepted(self) -> None:
        self.assertIsNone(slack_verdict_1203oz(900, 1103))

    def test_the_real_rot_this_ticket_found_is_rejected(self) -> None:
        v = slack_verdict_1203oz(300, 1103)          # #802 as it stood before #1203oz
        self.assertIsNotNone(v)
        self.assertIn("3.7x", v)
        self.assertIn("73%", v)
        self.assertIn("904", v, "the complaint must name the number to raise the floor to")

    def test_a_floor_above_its_scan_is_rejected_differently(self) -> None:
        v = slack_verdict_1203oz(500, 100)
        self.assertIsNotNone(v)
        self.assertIn("ABOVE", v)

    def test_an_empty_subject_is_rejected(self) -> None:
        v = slack_verdict_1203oz(100, 0)
        self.assertIsNotNone(v)
        self.assertIn("empty", v)

    def test_the_boundary_is_the_ceiling_not_a_rounding(self) -> None:
        self.assertIsNone(slack_verdict_1203oz(100, 200))      # exactly 2.0x is allowed
        self.assertIsNotNone(slack_verdict_1203oz(100, 201))   # one over is not


class EveryDiscoveredFloorIsWatchedOrExempt(unittest.TestCase):
    def test_discovery_finds_the_floors_this_ticket_measured(self) -> None:
        found = discover_reach_floors_1203oz()
        self.assertGreaterEqual(len(found), 6, "discovery reached almost nothing: %r" % found)
        self.assertFalse(
            missing_watched_1203oz(found),
            "watched but no longer discovered: %r -- the floor moved, was renamed, or its "
            "function stopped saying what it is for" % (missing_watched_1203oz(found),))

    def test_nothing_is_discovered_that_is_neither_watched_nor_exempt(self) -> None:
        found = discover_reach_floors_1203oz()
        stray = stray_floors_1203oz(found)
        self.assertFalse(
            stray,
            "new reach floor(s) nobody is watching: %r -- measure what the scan reaches "
            "today, add it to _WATCHED_1203OZ, or exempt it with the reason it is not a "
            "scan-reach floor" % (stray,))

    def test_every_exemption_says_why(self) -> None:
        for k, why in _EXEMPT_1203OZ.items():
            self.assertTrue(exemption_is_explained_1203oz(why),
                            "exemption %r has no real reason" % (k,))


class TheDiscoveryRulesBite(unittest.TestCase):
    """Synthetic trees and fabricated inputs -- the branches above are unobservable on the
    real tree, where every floor is healthy and nothing is stray."""

    def test_a_floor_is_found_when_only_the_FUNCTION_NAME_says_what_it_is_for(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "test_synthetic_1203oz.py").write_text(
                "def test_the_scan_looked():\n"
                "    xs = [1]\n"
                "    assert len(xs) >= 150\n", encoding="utf-8")
            found = discover_reach_floors_1203oz(root=d)
        self.assertEqual(found, [("test_synthetic_1203oz", "xs", 150)],
                         "discovery missed a floor whose role is stated in the name alone")

    def test_a_threshold_below_the_floor_minimum_is_not_a_reach_floor(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "test_synthetic_small_1203oz.py").write_text(
                '"""non-vacuity."""\n'
                "def test_it():\n"
                "    xs = [1]\n"
                "    assert len(xs) >= 3\n", encoding="utf-8")
            self.assertEqual(discover_reach_floors_1203oz(root=d), [])

    def test_a_stray_floor_is_reported(self) -> None:
        self.assertEqual(
            stray_floors_1203oz([("test_nobody_watches_this", "things", 100)]),
            [("test_nobody_watches_this", "things", 100)])

    def test_a_watched_floor_that_vanished_is_reported(self) -> None:
        self.assertEqual(missing_watched_1203oz([]), sorted(_WATCHED_1203OZ))

    def test_a_shrug_is_not_an_exemption(self) -> None:
        self.assertFalse(exemption_is_explained_1203oz("n/a"))
        self.assertFalse(exemption_is_explained_1203oz(""))
        self.assertFalse(exemption_is_explained_1203oz(None))
        self.assertTrue(exemption_is_explained_1203oz("x" * 41))


class NoWatchedFloorHasRotted(unittest.TestCase):
    def test_each_watched_floor_is_still_a_check(self) -> None:
        found = {(m, v): n for m, v, n in discover_reach_floors_1203oz()}
        verdicts = {}
        for (mod, var), spec in _WATCHED_1203OZ.items():
            with self.subTest(module=mod, var=var):
                floor = found.get((mod, var))
                self.assertIsNotNone(
                    floor, "%s: no floor discovered for `%s` any more" % (mod, var))
                size = len(_subject_1203oz(importlib.import_module(mod), spec))
                verdicts[(mod, var)] = slack_verdict_1203oz(floor, size)
                self.assertIsNone(verdicts[(mod, var)],
                                  "%s.%s: %s" % (mod, var, verdicts[(mod, var)]))
        # #947 and the ON4 lesson: a loop that examined nothing must not read as clean.
        self.assertEqual(sorted(verdicts), sorted(_WATCHED_1203OZ),
                         "only %d of %d watched floors were examined"
                         % (len(verdicts), len(_WATCHED_1203OZ)))


if __name__ == "__main__":
    unittest.main()
