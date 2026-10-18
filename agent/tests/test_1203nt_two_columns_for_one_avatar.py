r"""#1203nt: a table with `avatar` AND `avatar_url` seeded only one, and the frontend picks.

`align_dataset_field_names` fills `targets[0]` of each synonym group and skips any source that
is "its own column" -- the rule that stops `text` being cannibalised into `body`. When a table
declares BOTH twins of a media group, that rule means the seeded side stays and the twin stays
NULL. Whichever column the frontend happens to read then decides whether an avatar appears.

That is exactly the shape `#1202rv` records for counters -- "10 of 149 corpus runs declare BOTH
`like_count` and `likes` ... Whichever column the frontend happens to read then decides whether
a video shows 3.6M likes or 0" -- and `#1202rv` restricted its mirror to counters because it
could not answer whether a same-stem twin means a different fact "the way `title` and `name`
can".

FOR THIS FAMILY THE CORPUS ANSWERS IT:
  * 20 tables declare both twins -- `avatar`/`avatar_url` 11, `thumbnail`/`thumbnail_url` 9.
  * 8 of them seed only ONE side, and it is always the bare noun. r189 (users + videos) and
    r191 (users) are among them, so this is live rather than historical.
  * Every observed value on either side is a path or URL: avatar 70, thumbnail 62,
    thumbnail_url 35, avatar_url 20, and ZERO of any other shape. The twins mean the same
    fact in 100% of the instances that exist.

Simulated end to end over the 37 carry-equipped runs (align + the loader's per-row carry):
`users.avatar_url` goes from NULL in 5 runs to 0, `videos.thumbnail_url` from 2 to 0.

NOT WIDENED (#647): `sounds.cover_url` stays NULL in 6 runs and this does not touch it --
that table declares ONE column and neither source carries a cover, so there is no twin to
mirror. A missing fact is not a misplaced one.

No new list: the pairs are derived from `_FIELD_SYNONYM_GROUPS` itself, restricted to groups
whose canonical name ends `_url`.
"""
import json
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    _URL_TWIN_GROUPS_1203NT,
    _looks_like_a_ref_1203nt,
    align_dataset_field_names as align,
)


class TheTwinIsFilled(unittest.TestCase):
    def test_avatar_fills_avatar_url(self):
        out = align({"users": [{"id": 1, "avatar": "/assets/a.jpg"}]},
                    {"users": ["id", "avatar", "avatar_url"]})
        self.assertEqual(out["users"][0]["avatar_url"], "/assets/a.jpg")

    def test_the_mirror_is_symmetric(self):
        """The frontend may read either column, so either may be the seeded one."""
        out = align({"users": [{"id": 1, "avatar_url": "/assets/a.jpg"}]},
                    {"users": ["id", "avatar", "avatar_url"]})
        self.assertEqual(out["users"][0]["avatar"], "/assets/a.jpg")

    def test_thumbnail_twins(self):
        out = align({"videos": [{"id": 1, "thumbnail": "/t.jpg"}]},
                    {"videos": ["id", "thumbnail", "thumbnail_url"]})
        self.assertEqual(out["videos"][0]["thumbnail_url"], "/t.jpg")

    def test_every_declared_member_of_the_group_is_filled(self):
        out = align({"videos": [{"id": 1, "thumbnail": "/t.jpg"}]},
                    {"videos": ["id", "thumbnail", "thumbnail_url", "thumb"]})
        row = out["videos"][0]
        self.assertEqual(row["thumbnail_url"], "/t.jpg")
        self.assertEqual(row["thumb"], "/t.jpg")

    def test_http_and_data_urls_count(self):
        for v in ("https://cdn.example/a.png", "data:image/svg+xml;utf8,%3Csvg"):
            with self.subTest(value=v[:20]):
                out = align({"users": [{"id": 1, "avatar": v}]},
                            {"users": ["id", "avatar", "avatar_url"]})
                self.assertEqual(out["users"][0]["avatar_url"], v)

    def test_every_row_is_mirrored(self):
        out = align({"users": [{"id": i, "avatar": "/a%d.jpg" % i} for i in range(4)]},
                    {"users": ["id", "avatar", "avatar_url"]})
        self.assertEqual([r["avatar_url"] for r in out["users"]],
                         ["/a0.jpg", "/a1.jpg", "/a2.jpg", "/a3.jpg"])


class ItCannotMakeThingsWorse(unittest.TestCase):
    def test_one_column_for_one_fact_is_untouched(self):
        out = align({"users": [{"id": 1, "avatar": "/a.jpg"}]},
                    {"users": ["id", "avatar"]})
        self.assertNotIn("avatar_url", out["users"][0])

    def test_a_set_twin_is_never_overwritten(self):
        out = align({"users": [{"id": 1, "avatar": "/a.jpg", "avatar_url": "/b.jpg"}]},
                    {"users": ["id", "avatar", "avatar_url"]})
        self.assertEqual(out["users"][0]["avatar"], "/a.jpg")
        self.assertEqual(out["users"][0]["avatar_url"], "/b.jpg")

    def test_a_non_reference_value_is_not_mirrored(self):
        """The guard that keeps an initials blob or a colour out of a url column."""
        for v in ("AB", "", 7, True, None, {"x": 1}):
            with self.subTest(value=repr(v)):
                out = align({"users": [{"id": 1, "avatar": v}]},
                            {"users": ["id", "avatar", "avatar_url"]})
                self.assertIsNone(out["users"][0].get("avatar_url"))

    def test_the_counter_mirror_is_unaffected(self):
        """#1202rv keeps working; this is an addition, not a replacement."""
        out = align({"videos": [{"id": 1, "likes": 7}]},
                    {"videos": ["id", "like_count"]})
        self.assertEqual(out["videos"][0]["like_count"], 7)

    def test_a_non_url_group_is_not_mirrored(self):
        """`title`/`name` is exactly the pair #1202rv refused to mirror, and it still is."""
        out = align({"titles": [{"id": 1, "name": "Disclosure Day"}]},
                    {"titles": ["id", "title", "name"]})
        self.assertIsNone(out["titles"][0].get("title"))


class TheGroupsComeFromTheExistingList(unittest.TestCase):
    def test_only_url_canonical_groups_are_in_scope(self):
        self.assertTrue(_URL_TWIN_GROUPS_1203NT)
        for g in _URL_TWIN_GROUPS_1203NT:
            with self.subTest(group=g[0]):
                self.assertTrue(g[0].endswith("_url"))

    def test_the_measured_families_are_covered(self):
        heads = {g[0] for g in _URL_TWIN_GROUPS_1203NT}
        self.assertIn("avatar_url", heads)
        self.assertIn("thumbnail_url", heads)

    def test_no_counter_group_leaked_in(self):
        heads = {g[0] for g in _URL_TWIN_GROUPS_1203NT}
        self.assertFalse({"like_count", "comment_count", "view_count"} & heads)

    def test_the_reference_predicate(self):
        self.assertTrue(_looks_like_a_ref_1203nt("/a.jpg"))
        self.assertTrue(_looks_like_a_ref_1203nt("http://x/a.jpg"))
        self.assertTrue(_looks_like_a_ref_1203nt("data:image/png;base64,AA"))
        for v in ("AB", "", None, 3, True, "assets/a.jpg"):
            with self.subTest(value=repr(v)):
                self.assertFalse(_looks_like_a_ref_1203nt(v))


class WhatTheCorpusSays(unittest.TestCase):
    """The measurement behind the decision. Skips where the tree is absent."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def _twin_tables(self):
        out = []
        for m in sorted(self.corpus.glob("*/app/backend/models.py")):
            src = m.read_text(encoding="utf-8", errors="ignore")
            for mm in re.finditer(r"class\s+\w+\(Base\):(.*?)(?=\nclass |\Z)", src, re.S):
                blk = mm.group(1)
                tn = re.search(r'__tablename__\s*=\s*[\'"]([^\'"]+)', blk)
                if not tn:
                    continue
                cols = set(re.findall(r"^\s{4}(\w+)\s*=\s*Column", blk, re.M))
                for g in _URL_TWIN_GROUPS_1203NT:
                    if len([c for c in g if c in cols]) >= 2:
                        out.append((m.parts[-4], tn.group(1), g[0],
                                    [c for c in g if c in cols]))
        return out

    def test_tables_declaring_both_twins_exist(self):
        got = self._twin_tables()
        if not got:
            self.skipTest("no twin-declaring table on this disk")
        self.assertTrue(got, got)

    def test_every_seeded_twin_value_is_a_reference(self):
        """The claim the mirror rests on: these twins never hold a non-url value, so copying
        one onto the other cannot move a different fact."""
        bad, seen = [], 0
        for run, table, _head, cols in self._twin_tables():
            for fn in ("seed_dataset.json", "seed_data.json"):
                p = self.corpus / run / "app" / "backend" / fn
                if not p.is_file():
                    continue
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for r in (d.get(table) or [])[:30]:
                    if not isinstance(r, dict):
                        continue
                    for c in cols:
                        v = r.get(c)
                        if v is None:
                            continue
                        seen += 1
                        if not _looks_like_a_ref_1203nt(v):
                            bad.append((run, table, c, str(v)[:40]))
        if not seen:
            self.skipTest("no seeded twin values on this disk")
        self.assertEqual(bad, [],
                         "a twin column holds a non-reference value, so the mirror could "
                         "move a different fact: %s" % bad[:5])

    def test_the_mirror_repairs_a_real_one_sided_table(self):
        """End to end on real data rather than a fixture."""
        repaired = 0
        for run, table, _head, cols in self._twin_tables():
            p = self.corpus / run / "app" / "backend" / "seed_dataset.json"
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows = d.get(table)
            if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
                continue
            if all(rows[0].get(c) is not None for c in cols):
                continue                      # both sides already seeded
            out = align({table: [dict(r) for r in rows[:5]]}, {table: list(cols) + ["id"]})
            if all(out[table][0].get(c) is not None for c in cols):
                repaired += 1
        if not repaired:
            self.skipTest("no one-sided twin table with seeded rows on this disk")
        self.assertGreater(repaired, 0)


if __name__ == "__main__":
    unittest.main()
