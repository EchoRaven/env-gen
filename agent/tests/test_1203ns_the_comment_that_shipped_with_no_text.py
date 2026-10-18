r"""#1203ns: the synonym list had no group for the primary text of a comment.

`#483`'s `_FIELD_SYNONYM_GROUPS` maps design-prep's dataset field names onto the ORM model's
column names, because the model's names are non-deterministic across runs and the seed
loader's `hasattr(cls, k)` filter DROPS every unmatched field. The list covers titles,
descriptions, media URLs, engagement counters, display names and timestamps — and not the one
field every product with user-generated content has.

MEASURED: 4 runs declare `comments.body` while design-prep emits `text` — tiktok-web-r139,
r140, r145 and r160, **295 comment rows each, 1,180 in all**. `body = Column(Text)` is
nullable in every one, so the rows DID insert and every comment shipped with NO TEXT: a
comments panel of blank entries. Had the column been NOT NULL it would be `#483`'s documented
outcome instead — every per-row insert failing into an empty table, which is how r55 shipped
0 of a 60-title dataset.

`#1202ro`'s warning on this list was about adding another VERTICAL's vocabulary ("adding
tiktok words here would repeat the original mistake one env later"). This is the opposite
case: `body`/`text`/`content`/`message` is the generic content field a film-first list never
needed, and it is domain-neutral in exactly the sense that list asks for.

SIMULATED OVER THE WHOLE CORPUS BEFORE LANDING: 1,180 fills, all `comments.body <- text`, all
string values, 0 non-strings landing in a text column. Exactly ONE table anywhere holds two of
the group as columns at once (r142's `comments` has `body` AND `text`), and
`align_dataset_field_names`'s own rule — never cannibalize a field that is its own column —
means nothing is filled there.
"""
import json
import os
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    _FIELD_SYNONYM_GROUPS,
    align_dataset_field_names as align,
)

_GROUP = ("body", "text", "content", "message")


class TheGroupExists(unittest.TestCase):
    def test_the_content_group_is_in_the_list(self):
        self.assertIn(_GROUP, _FIELD_SYNONYM_GROUPS)

    def test_the_canonical_name_comes_first(self):
        """The list's stated convention: first element is the model-side name, the rest are
        what design-prep emits. The affected runs' column is `body`; the dataset emits
        `text`."""
        group = next(g for g in _FIELD_SYNONYM_GROUPS if set(g) & set(_GROUP))
        self.assertEqual(group[0], "body")
        self.assertIn("text", group[1:])


class TheCorpusCaseIsRepaired(unittest.TestCase):
    def test_body_is_filled_from_text(self):
        ds = {"comments": [{"id": 1, "text": "who else is here in 2026", "likes": 5}]}
        out = align(ds, {"comments": ["id", "body", "likes", "video_id"]})
        self.assertEqual(out["comments"][0]["body"], "who else is here in 2026")

    def test_the_original_key_is_left_alone(self):
        """The loader's hasattr filter drops it harmlessly; rewriting it would be a change
        this function does not make."""
        ds = {"comments": [{"id": 1, "text": "hi"}]}
        out = align(ds, {"comments": ["id", "body"]})
        self.assertEqual(out["comments"][0]["text"], "hi")

    def test_content_and_message_are_sources_too(self):
        out = align({"posts": [{"id": 1, "content": "c"}],
                     "notes": [{"id": 2, "message": "m"}]},
                    {"posts": ["id", "body"], "notes": ["id", "body"]})
        self.assertEqual(out["posts"][0]["body"], "c")
        self.assertEqual(out["notes"][0]["body"], "m")

    def test_every_row_is_filled_not_just_the_first(self):
        ds = {"comments": [{"id": i, "text": "t%d" % i} for i in range(5)]}
        out = align(ds, {"comments": ["id", "body"]})
        self.assertEqual([r["body"] for r in out["comments"]],
                         ["t0", "t1", "t2", "t3", "t4"])


class ItCannotMakeThingsWorse(unittest.TestCase):
    """`align_dataset_field_names`'s three safety conditions, asserted for THIS group."""

    def test_a_model_whose_column_is_already_text_is_a_no_op(self):
        """60 of the corpus's runs are in this shape."""
        ds = {"comments": [{"id": 1, "text": "hi"}]}
        before = json.dumps(ds, sort_keys=True)
        out = align(ds, {"comments": ["id", "text"]})
        self.assertEqual(json.dumps(out, sort_keys=True), before)

    def test_a_table_with_both_columns_is_not_cannibalised(self):
        """r142's `comments` has `body` AND `text`. `text` must not be moved into `body`,
        because it is its own column and the loader will keep it."""
        ds = {"comments": [{"id": 1, "text": "hi"}]}
        out = align(ds, {"comments": ["id", "body", "text"]})
        self.assertNotIn("body", out["comments"][0])
        self.assertEqual(out["comments"][0]["text"], "hi")

    def test_a_target_that_already_has_a_value_is_never_overwritten(self):
        ds = {"comments": [{"id": 1, "body": "real", "text": "other"}]}
        out = align(ds, {"comments": ["id", "body"]})
        self.assertEqual(out["comments"][0]["body"], "real")

    def test_a_table_with_none_of_the_group_as_a_column_is_untouched(self):
        ds = {"videos": [{"id": 1, "text": "caption-ish"}]}
        out = align(ds, {"videos": ["id", "caption"]})
        self.assertNotIn("body", out["videos"][0])
        self.assertNotIn("caption", out["videos"][0])

    def test_an_empty_string_is_still_carried(self):
        """The guard is `is None`, not falsiness — an empty comment body the dataset really
        contains is data, and inventing a difference here would be its own bug."""
        ds = {"comments": [{"id": 1, "text": ""}]}
        out = align(ds, {"comments": ["id", "body"]})
        self.assertEqual(out["comments"][0]["body"], "")


class TheOtherGroupsStillWork(unittest.TestCase):
    """Non-vacuity for the insertion point: adding a group must not shadow its neighbours."""

    def test_the_counter_group_still_fills(self):
        out = align({"videos": [{"id": 1, "likes": 7}]},
                    {"videos": ["id", "like_count"]})
        self.assertEqual(out["videos"][0]["like_count"], 7)

    def test_the_media_group_still_fills(self):
        out = align({"videos": [{"id": 1, "thumbnail": "/a.jpg"}]},
                    {"videos": ["id", "thumbnail_url"]})
        self.assertEqual(out["videos"][0]["thumbnail_url"], "/a.jpg")

    def test_the_description_group_is_not_confused_with_the_body_group(self):
        """`description`/`synopsis` and `body`/`text` are different fields; a row carrying
        both must land both."""
        out = align({"titles": [{"id": 1, "synopsis": "s", "text": "t"}]},
                    {"titles": ["id", "description", "body"]})
        self.assertEqual(out["titles"][0]["description"], "s")
        self.assertEqual(out["titles"][0]["body"], "t")


class WhatTheCorpusSays(unittest.TestCase):
    """The measurement the group rests on. Skips where the tree is absent."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def _runs_needing_the_fill(self):
        out = []
        for g in sorted(self.corpus.glob("*/app/backend/seed_dataset.json")):
            m = g.with_name("models.py")
            if not m.is_file():
                continue
            try:
                fw = json.loads(g.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows = (fw or {}).get("comments")
            if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
                continue
            src = m.read_text(encoding="utf-8", errors="ignore")
            i = src.find("class Comment")
            if i < 0:
                continue
            end = src.find("\nclass ", i + 1)
            cols = set(re.findall(r"^\s{4}(\w+)\s*=\s*Column",
                                  src[i:end if end > 0 else len(src)], re.M))
            keys = set().union(*[set(r) for r in rows[:50]])
            if "body" in cols and "text" not in cols and "text" in keys:
                out.append((g.parts[-4], len(rows)))
        return out

    def test_the_affected_runs_are_still_there_to_be_repaired(self):
        got = self._runs_needing_the_fill()
        if not got:
            self.skipTest("none of the affected runs is on this disk")
        self.assertTrue(got, got)
        # 295 rows each when it was measured
        self.assertTrue(all(n > 0 for _, n in got), got)

    def test_the_fill_recovers_their_text(self):
        """End to end on real data: run the aligner over each affected dataset and require
        every comment row to come out with a body."""
        affected = [r for r, _ in self._runs_needing_the_fill()]
        if not affected:
            self.skipTest("none of the affected runs is on this disk")
        for run in affected:
            g = self.corpus / run / "app" / "backend" / "seed_dataset.json"
            fw = json.loads(g.read_text(encoding="utf-8"))
            with self.subTest(run=run):
                out = align({"comments": fw["comments"]},
                            {"comments": ["id", "body", "video_id", "user_id"]})
                missing = [r for r in out["comments"]
                           if isinstance(r, dict) and r.get("text") is not None
                           and r.get("body") is None]
                self.assertEqual(missing, [], "%d row(s) still have no body" % len(missing))

    def test_only_reachable_two_column_tables_matter_and_the_fill_skips_them(self):
        """The shape where the group must do NOTHING, measured rather than assumed.

        ★ This test caught my own overclaim. The code comment first said "exactly ONE table
        anywhere holds two of these as columns at once"; SIX do (r142 comments +
        notifications, r172 messages + notifications, r180 messages + notifications). The
        simulation behind that sentence had only looked at tables the DATASET covers --
        always comments/sounds/users/videos -- so five of the six were never in view. The
        claim that survives is the narrower one asserted here.
        """
        models = list(self.corpus.glob("*/app/backend/models.py"))
        if not models:
            self.skipTest("no models on this disk")
        both = []
        for m in sorted(models):
            src = m.read_text(encoding="utf-8", errors="ignore")
            for mm in re.finditer(r"class\s+\w+\(Base\):(.*?)(?=\nclass |\Z)", src, re.S):
                blk = mm.group(1)
                tn = re.search(r'__tablename__\s*=\s*[\'"]([^\'"]+)', blk)
                if not tn:
                    continue
                cols = set(re.findall(r"^\s{4}(\w+)\s*=\s*Column", blk, re.M))
                if len(cols & set(_GROUP)) > 1:
                    both.append((m.parts[-4], tn.group(1)))
        # which of them is a table the dataset covers, i.e. one the aligner can reach
        reachable = []
        for run, table in both:
            g = self.corpus / run / "app" / "backend" / "seed_dataset.json"
            if not g.is_file():
                continue
            try:
                ds = json.loads(g.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(ds, dict) and table in ds:
                reachable.append((run, table))
        # the property, for every reachable one: the group fills NOTHING there
        for run, table in reachable:
            g = self.corpus / run / "app" / "backend" / "seed_dataset.json"
            ds = json.loads(g.read_text(encoding="utf-8"))
            rows = ds.get(table) or []
            if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
                continue
            with self.subTest(run=run, table=table):
                out = align({table: [dict(r) for r in rows]},
                            {table: ["id", "body", "text"]})
                self.assertFalse([r for r in out[table]
                                  if r.get("body") is not None and "body" not in rows[0]],
                                 "the group cannibalised `text` into `body` on %s/%s"
                                 % (run, table))


if __name__ == "__main__":
    unittest.main()
