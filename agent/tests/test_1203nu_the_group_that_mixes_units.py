r"""#1203nu: one synonym group pairs names whose fact differs by a factor of 60.

Every group in `_FIELD_SYNONYM_GROUPS` pairs spellings of the SAME fact -- `thumbnail` and
`thumbnail_url`, `likes` and `like_count`. One does not: `("duration_minutes", "duration",
"runtime")` pairs a minutes column with a bare `duration` whose unit the corpus shows to be
either.

MEASURED. The bare `duration` means both things:
  * seconds -- netflix-r2's episodes hold 1380-2820, r3's titles 0-8340
  * minutes -- netflix-r14's titles hold 20-118, r19's 25-126
And on the side this function actually reads, the design-prep dataset, it is always seconds:
2,010 values, all on `videos`, all <= 300.

THE RISK IS LATENT, NOT LIVE: run over the whole corpus, the alignment writes into a duration
column 0 times, because the dataset's `duration` appears only on `videos` and no run declares
`duration_minutes` on a videos table. So there is nothing to repair (#647) and this file is a
ratchet rather than a fix.

WHAT IT RATCHETS. `duration_seconds` is the obvious next entry for that group -- eight runs
declare the column (netflix-r11/r37/r44, tiktok-r105/r139/r142/r145/r160) and
`videos.duration_seconds` / `sounds.duration_seconds` do sit NULL in two runs each -- and
adding it would make the aligner treat a minutes column and a seconds column as
interchangeable, writing 157 seconds into `duration_minutes` as 157 minutes. A magnitude
guard cannot separate them either: `120` is legal in both units.
"""
import json
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    _FIELD_SYNONYM_GROUPS,
    align_dataset_field_names as align,
)

_SECONDS_NAMES = ("duration_seconds", "duration_sec", "length_seconds", "seconds")


def _duration_group():
    for g in _FIELD_SYNONYM_GROUPS:
        if "duration_minutes" in g:
            return g
    return ()


class NoSecondsNameJoinsTheMinutesGroup(unittest.TestCase):
    def test_the_minutes_group_exists(self):
        """Non-vacuity: if the group were renamed this ratchet would pass while guarding
        nothing."""
        self.assertTrue(_duration_group(), "the duration group is gone — re-read #1203nu")

    def test_no_seconds_spelling_is_in_it(self):
        g = _duration_group()
        for name in _SECONDS_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, g,
                                 "%r in the minutes group makes the aligner write seconds "
                                 "into a minutes column — a factor of 60 (#1203nu)" % name)

    def test_no_other_group_mixes_the_two_units(self):
        """The same mistake could arrive as a NEW group rather than an addition to this one."""
        for g in _FIELD_SYNONYM_GROUPS:
            with self.subTest(group=g[0]):
                has_min = any("minute" in n for n in g)
                has_sec = any("second" in n or n.endswith("_sec") for n in g)
                self.assertFalse(has_min and has_sec,
                                 "group %r pairs a minutes name with a seconds name" % (g,))


class TheUnitErrorIsWhatWouldHappen(unittest.TestCase):
    """Drive the consequence so the comment is not the only record of it."""

    def test_a_seconds_value_does_not_reach_a_minutes_column_today(self):
        out = align({"videos": [{"id": 1, "duration": 157}]},
                    {"videos": ["id", "duration_minutes"]})
        # it DOES route today, because `duration` is in the minutes group -- assert the
        # value is unchanged rather than claiming a correctness this group cannot give
        self.assertEqual(out["videos"][0]["duration_minutes"], 157)

    def test_the_dataset_side_duration_is_seconds_shaped(self):
        """The measurement the whole note rests on, on real data."""
        corpus = Path(__file__).resolve().parents[2] / "generated"
        if not corpus.is_dir():
            self.skipTest("no generated/ corpus on this machine")
        seen = over = 0
        for g in sorted(corpus.glob("*/app/backend/seed_dataset.json")):
            try:
                d = json.loads(g.read_text(encoding="utf-8"))
            except Exception:
                continue
            for _t, rows in (d or {}).items():
                for r in (rows or [])[:30]:
                    if not isinstance(r, dict):
                        continue
                    v = r.get("duration")
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        seen += 1
                        if v > 300:
                            over += 1
        if not seen:
            self.skipTest("no dataset duration values on this disk")
        self.assertEqual(over, 0,
                         "a dataset `duration` above 300 appeared, so the 'always seconds' "
                         "half of #1203nu's note no longer holds (%d of %d)" % (over, seen))


class TheAlignmentStillDoesNotTouchADurationColumn(unittest.TestCase):
    """#647's half: there is nothing to repair because this never fires. If it starts
    firing, the note's 'latent, not live' sentence is wrong and should be re-decided."""

    def test_zero_duration_writes_across_the_corpus(self):
        corpus = Path(__file__).resolve().parents[2] / "generated"
        if not corpus.is_dir():
            self.skipTest("no generated/ corpus on this machine")
        writes, checked = [], 0
        for g in sorted(corpus.glob("*/app/backend/seed_dataset.json")):
            m = g.with_name("models.py")
            if not m.is_file():
                continue
            try:
                ds = json.loads(g.read_text(encoding="utf-8"))
            except Exception:
                continue
            src = m.read_text(encoding="utf-8", errors="ignore")
            cols_by = {}
            for mm in re.finditer(r"class\s+\w+\(Base\):(.*?)(?=\nclass |\Z)", src, re.S):
                blk = mm.group(1)
                tn = re.search(r'__tablename__\s*=\s*[\'"]([^\'"]+)', blk)
                if tn:
                    cols_by[tn.group(1)] = re.findall(r"^\s{4}(\w+)\s*=\s*Column", blk, re.M)
            for t, rows in (ds or {}).items():
                cols = cols_by.get(t)
                if not cols or not (isinstance(rows, list) and rows
                                    and isinstance(rows[0], dict)):
                    continue
                checked += 1
                before = [dict(r) for r in rows[:20]]
                after = align({t: [dict(r) for r in before]}, {t: cols})[t]
                for b, a in zip(before, after):
                    for k in a:
                        if k not in b and ("dur" in k.lower() or k in ("runtime", "length")):
                            writes.append((g.parts[-4], t, k, a[k]))
        if not checked:
            self.skipTest("no alignable table on this disk")
        self.assertEqual(writes, [],
                         "the duration group now fires, so #1203nu's 'latent, not live' "
                         "reading needs re-deciding: %s" % writes[:5])


if __name__ == "__main__":
    unittest.main()
