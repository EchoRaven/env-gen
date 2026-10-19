"""#1203oy: the release note must carry the visual verdict the same call just computed.

`create_release` computes `_visual_state_1202jr()` -- `visual_passed`, the blocking average,
the screens below the bar -- and in the same record stores the framework's constant note,
"the delivery gate is fully clear". Over this corpus 78 releases carry that note and 22 of
them were cut with `visual_passed=False` (r167, r168, r169, r173 x2, r177 x2, r184, r190,
r191), blocking averages down to 0.02 and up to 9 screens below.

#1202jr found the same silence and fixed the RECORD half by stamping the fields.
`live_monitor_server.build_releases_list` hands a human six keys per release -- tag, branch, sha,
notes, createdAt, snapshots -- and no `visual_*` field, so the note is the only visual fact
that reaches that page. #1148's shape.
"""
from __future__ import annotations

import ast
import inspect
import logging
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hubs.codehub import service as SVC


class TheClauseSaysWhatTheVerdictWas(unittest.TestCase):
    def test_a_passing_verdict_says_passed(self) -> None:
        out = SVC._notes_with_visual_1203oy("base.", {"visual_passed": True})
        self.assertIn("base.", out)
        self.assertIn("passed", out.lower())
        self.assertNotIn("not passed", out.lower())
        self.assertNotIn("not recorded", out.lower())

    def test_a_failing_verdict_names_the_count_the_average_and_the_screens(self) -> None:
        out = SVC._notes_with_visual_1203oy(
            "Framework delivery: the delivery gate is fully clear.",
            {"visual_passed": False, "visual_blocking_average_live": 0.1957,
             "visual_screens_below": ["a", "b", "c"]})
        low = out.lower()
        self.assertIn("not passed", low)
        self.assertIn("3 screen", low)
        self.assertIn("0.1957", out)
        for name in ("a", "b", "c"):
            self.assertIn(name, out)

    def test_an_unmeasured_verdict_does_not_read_as_a_clean_one(self) -> None:
        # #1039: "not measured" and "measured and failing" are different facts, and neither
        # may read as "measured and clean".
        out = SVC._notes_with_visual_1203oy("base.", {"visual_passed": None})
        low = out.lower()
        self.assertIn("not recorded", low)
        self.assertNotIn("not passed", low)
        # and it must not be mistakable for the passing clause
        self.assertNotIn("verdict: passed", low)

    def test_a_long_screen_list_declares_its_cut(self) -> None:
        # #1034
        names = ["s%d" % i for i in range(9)]
        out = SVC._notes_with_visual_1203oy("", {"visual_passed": False,
                                                 "visual_screens_below": names})
        self.assertIn("9 screen", out.lower())
        shown = [n for n in names if n in out]
        self.assertLess(len(shown), len(names), "the whole list went into the note")
        self.assertIn("more", out.lower(), "the cut is not declared: %r" % out)
        self.assertIn("+%d" % (len(names) - len(shown)), out)

    def test_it_is_idempotent(self) -> None:
        once = SVC._notes_with_visual_1203oy("base.", {"visual_passed": False,
                                                       "visual_screens_below": ["a"]})
        twice = SVC._notes_with_visual_1203oy(once, {"visual_passed": True})
        self.assertEqual(once, twice)

    def test_it_keeps_the_callers_own_note(self) -> None:
        mine = "Lane cut: milestone 2 shipped."
        out = SVC._notes_with_visual_1203oy(mine, {"visual_passed": True})
        self.assertTrue(out.startswith(mine), out)

    def test_a_broken_verdict_object_announces_instead_of_going_quiet(self) -> None:
        # `warn_once_1201` is once PER SITE for the whole process, so an earlier test that
        # tripped this same site would make `assertLogs` fail for a reason that has nothing
        # to do with the property. Clear just this site's memo.
        from env_generator.llm_generator.multi_agent.runtime import message_format as MF
        MF._WARNED_1201.discard("codehub.service._notes_with_visual_1203oy")

        class Hostile:
            def get(self, *a, **k):
                raise RuntimeError("verdict unreadable")

        with self.assertLogs(level=logging.WARNING) as cap:
            out = SVC._notes_with_visual_1203oy("base.", Hostile())
        self.assertEqual(out, "base.")
        self.assertTrue(any("1201" in r.getMessage() or "visual verdict" in r.getMessage()
                            for r in cap.records),
                        "nothing was announced: %r" % [r.getMessage() for r in cap.records])


def _fn(src: str, name: str):
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("%s is gone" % name)


class OneReadingUsedTwice(unittest.TestCase):
    """The note and the stamp must not be two separate measurements. (#1203l8's M6 shape.)"""

    def setUp(self) -> None:
        self.fn = _fn(inspect.getsource(SVC), "create_release")

    def test_the_verdict_is_read_exactly_once(self) -> None:
        reads = [n for n in ast.walk(self.fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_visual_state_1202jr"]
        self.assertEqual(len(reads), 1,
                         "the visual verdict is read %d times inside create_release" % len(reads))

    def test_the_note_is_routed_through_the_clause_builder(self) -> None:
        found = False
        for node in ast.walk(self.fn):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "notes":
                    found = True
                    self.assertTrue(
                        isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                        and v.func.id == "_notes_with_visual_1203oy",
                        "the stored note no longer goes through the clause builder")
        self.assertTrue(found, "the release record has no `notes` key any more")


class TheHumanFacingSurfaceCarriesItSomehow(unittest.TestCase):
    """The reason #1203oy exists. An OR, so improving the monitor is not a failure."""

    def test_either_the_monitor_shows_the_verdict_or_the_note_does(self) -> None:
        mon = (Path(SVC.__file__).resolve().parents[4] / "live_monitor_server.py")
        self.assertTrue(mon.is_file(), "live_monitor_server.py moved: %s" % mon)
        fn = _fn(mon.read_text(encoding="utf-8", errors="replace"), "build_releases_list")
        keys = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
        monitor_shows = any("visual" in k.lower() for k in keys)
        note_carries = hasattr(SVC, "_notes_with_visual_1203oy")
        self.assertTrue(
            monitor_shows or note_carries,
            "the release payload a human reads (%s) has no visual key and the note no "
            "longer carries the verdict either" % sorted(keys))
        # Deliberately NOT a skip when the monitor starts serving the verdict: a skipped
        # test passes the suite, and this assertion is the one that must keep biting.


if __name__ == "__main__":
    unittest.main()
