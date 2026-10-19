r"""#1203ot: the success line beside two memoised warnings said itself 797 times.

`material_prep.py` already carries `_say_once_1203i4`, and its docstring says, in this file,
exactly what it was written for:

    These two #1202vz warnings printed 319 identical lines in r180 alone -- the seed
    localiser revisits the same unfilled FK column on every pass.

It was applied to those two WARNINGS and not to the SUCCESS line they sit beside. MEASURED on
the modern run logs, where that line is BYTE-FOR-BYTE identical every time:

    r183 1220   r190 797   r185 607   r191 427      median 430 over the 12 r183+ logs
                                                    5,692 lines in all

Larger than every offender #1202ad was written for (134 / 416 / 213) and larger per run than
what #1203i3 had just fixed, in a 16MB log whose budget #1202vx says belongs to the evidence.

★ The state is the COUNT, not #1203i4's constant marker: "20 of 35" moving to "35 of 35"
between passes is news -- "a count that moves is a change", in #1202ad's own words -- while
the same count again is the heartbeat.

★ The sibling `#1202w9` info line in the same loop is deliberately NOT guarded: over
r183/r185/r190/r191 it fires ZERO times, so there is nothing to size a guard against (#647),
and an unexercised branch is its own cost. Frozen below so the decision stays checkable.
"""
from __future__ import annotations

import glob
import io
import logging
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import material_prep as MP  # noqa: E402
from multi_agent.runtime import message_format as MF  # noqa: E402

_CORPUS = ROOT.parent / "generated"
_LOGGER = "multi_agent.runtime.material_prep"


def _dataset():
    return {"videos": [{"sound": "A"}, {"sound": "B"}],
            "sounds": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}


_SCHEMA = {"videos": {"sound_id": {"fk": "sounds.id"}, "sound": {}},
           "sounds": {"id": {}, "name": {}}}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.said = []

    def emit(self, record):
        self.said.append(record.getMessage())


class TheHeartbeatStops(unittest.TestCase):

    def setUp(self):
        MF._STATE_SAID_1202AD.clear()
        self.cap = _Capture()
        self.lg = logging.getLogger(_LOGGER)
        self.lg.addHandler(self.cap)
        self._lvl = self.lg.level
        self.lg.setLevel(logging.INFO)

    def tearDown(self):
        self.lg.removeHandler(self.cap)
        self.lg.setLevel(self._lvl)
        MF._STATE_SAID_1202AD.clear()

    def _resolved(self):
        return [m for m in self.cap.said if "#1202vz resolved" in m]

    def test_four_passes_over_the_same_dataset_say_it_once(self):
        """★ Non-vacuity: before the memo, this very input produced one line per pass --
        verified by running it, which is how the 797 was explained."""
        for _ in range(4):
            MP.resolve_dataset_fks_1202vz(_dataset(), _SCHEMA)
        self.assertEqual(len(self._resolved()), 1, self._resolved())
        self.assertIn("2 of 2 rows", self._resolved()[0])

    def test_a_count_that_moves_is_news(self):
        """★ The first version moved the count from 2 of 2 to 1 of 2, which never reaches this
        line at all: `_FK_MATCH_FLOOR_1202VZ` is 0.8, so a half-matching natural key is
        refused outright and takes the WARNING branch. 5 of 5 -> 4 of 5 both clear the floor,
        so the count really does move on the path under test."""
        five = lambda last: {
            "videos": [{"sound": x} for x in ("A", "B", "C", "D", last)],
            "sounds": [{"id": i, "name": n} for i, n in
                       enumerate(("A", "B", "C", "D", "E"), start=1)]}
        MP.resolve_dataset_fks_1202vz(five("E"), _SCHEMA)
        MP.resolve_dataset_fks_1202vz(five("ZZZ"), _SCHEMA)
        said = self._resolved()
        self.assertEqual(len(said), 2, said)
        self.assertIn("5 of 5", said[0])
        self.assertIn("4 of 5", said[1])

    def test_two_columns_do_not_silence_each_other(self):
        ds = {"videos": [{"sound": "A", "creator": "u1"}],
              "sounds": [{"id": 1, "name": "A"}],
              "users": [{"id": 9, "name": "u1"}]}
        schema = {"videos": {"sound_id": {"fk": "sounds.id"}, "creator_id": {"fk": "users.id"},
                             "sound": {}, "creator": {}},
                  "sounds": {"id": {}, "name": {}}, "users": {"id": {}, "name": {}}}
        MP.resolve_dataset_fks_1202vz(ds, schema)
        said = self._resolved()
        self.assertEqual(len(said), 2, said)
        self.assertTrue(any("sound_id" in m for m in said), said)
        self.assertTrue(any("creator_id" in m for m in said), said)

    def test_a_memo_failure_never_silences_the_report(self):
        """A dedup that can swallow the report is worse than the repetition it replaces."""
        orig = MF.state_changed_1202ad

        def boom(*a, **k):
            raise RuntimeError("memo down")

        MF.state_changed_1202ad = boom
        try:
            for _ in range(3):
                MP.resolve_dataset_fks_1202vz(_dataset(), _SCHEMA)
        finally:
            MF.state_changed_1202ad = orig
        self.assertEqual(len(self._resolved()), 3, self._resolved())

    def test_the_ambiguous_key_warning_beside_it_still_dedupes(self):
        """★ Mutation OT6 found this missing: my first composition test exercised the
        `fk_unfilled` warning (no base column at all) and left the `fk_ambiguous` one -- the
        other half of #1203i4's own docstring ("these TWO #1202vz warnings") -- untested. A
        half-matching natural key is below the 0.8 floor, so it takes that branch."""
        ds = lambda: {"videos": [{"sound": "A"}, {"sound": "ZZZ"}],
                      "sounds": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
        for _ in range(4):
            MP.resolve_dataset_fks_1202vz(ds(), _SCHEMA)
        warned = [m for m in self.cap.said if "ambiguous natural key is refused" in m]
        self.assertEqual(len(warned), 1, warned)
        self.assertEqual(self._resolved(), [],
                         "a half-matching key must not reach the success line")

    def test_the_two_warnings_beside_it_still_dedupe(self):
        """#1203i4's own property, asserted here because both memos now live in one loop --
        two patches in one function are not green together just because each is alone."""
        ds = {"videos": [{"title": "t"}], "sounds": [{"id": 1, "name": "A"}]}
        schema = {"videos": {"sound_id": {"fk": "sounds.id"}, "title": {}},
                  "sounds": {"id": {}, "name": {}}}
        for _ in range(4):
            MP.resolve_dataset_fks_1202vz(dict(ds), schema)
        warned = [m for m in self.cap.said if "NO dataset row fills" in m]
        self.assertEqual(len(warned), 1, warned)


class WhatTheCorpusSays(unittest.TestCase):
    _MEASURED = {"gm_tiktok_r183.log": 1220, "gm_tiktok_r190.log": 797,
                 "gm_tiktok_r185.log": 607, "gm_tiktok_r191.log": 427}

    def setUp(self):
        if not (_CORPUS.parent / "gm_tiktok_r190.log").is_file():
            self.skipTest("the run logs are not beside this checkout")

    def test_the_line_was_byte_identical_every_time(self):
        checked = 0
        for name, n in sorted(self._MEASURED.items()):
            f = _CORPUS.parent / name
            if not f.is_file():
                continue
            checked += 1
            lines = [l for l in io.open(f, encoding="utf-8", errors="replace")
                     if "#1202vz resolved" in l]
            self.assertEqual(len(lines), n, "%s: %d lines, measured %d" % (name, len(lines), n))
            bodies = {l.split("#1202vz", 1)[1].strip() for l in lines}
            self.assertEqual(len(bodies), 1,
                             "%s: %d distinct bodies, so the repetition carried news: %r"
                             % (name, len(bodies), sorted(bodies)[:2]))
        # ★ ON4's lesson: a ratchet that looked at nothing passes vacuously.
        self.assertEqual(checked, len(self._MEASURED),
                         "only %d of the %d measured logs were read" % (checked,
                                                                        len(self._MEASURED)))

    def test_the_sibling_line_this_deliberately_leaves_alone_fires_nowhere(self):
        """The #647 half of the decision. If #1202w9 ever starts repeating, this goes red and
        the trade-off is re-decided with a number instead of from scratch."""
        total, checked = 0, 0
        for name in sorted(self._MEASURED):
            f = _CORPUS.parent / name
            if not f.is_file():
                continue
            checked += 1
            total += sum(1 for l in io.open(f, encoding="utf-8", errors="replace")
                         if "#1202w9 filled" in l)
        self.assertEqual(checked, len(self._MEASURED))
        self.assertEqual(total, 0, "#1202w9 now fires %d time(s); size a guard and copy the "
                                   "#1203ot pattern" % total)


if __name__ == "__main__":
    unittest.main()
