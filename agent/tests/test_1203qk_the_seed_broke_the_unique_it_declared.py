"""#1203qk: the seed violated the composite uniqueness its own contract declared.

Two halves, and the SECOND one is a guard against a fix rather than a defect:

  1. `constraint_columns_1203qk` is the one owner of "which columns does this constraint
     entry name" (#1032) and now reaches two spellings the DDL never sees -- a composite
     LABEL with the keyword and list in the TYPE (7 corpus entries) and a bare keyword with
     a PROSE TAIL (1, r183). For the 5 whose type is a bare `string`/`text` it returns None:
     `unique_user_video` does not say `user_id` and `unique_follow` says nothing at all.

  2. `_is_constraint_pseudo_column` is deliberately NOT widened, and
     `test_the_DDL_the_predicate_emits_is_unchanged` pins that. Widening it would emit a
     real composite UNIQUE for all 8 recoverable entries -- and all 8 of those tables ship
     seed rows that BREAK the constraint they declare, so the UNIQUE would abort initdb as
     the seed loads (#32's and #1031's whole-stack failure). The seed is fixed here; the
     constraint is a separate change that needs a live run behind it (#1202w6).

The arrival test is DIFFERENTIAL: the identical table, once with the declaration and once
without, so a run where the seeder happened to emit no duplicates fails the control instead
of passing this file vacuously.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _is_constraint_pseudo_column, _render_table_constraint, constraint_columns_1203qk)
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _build_seed_rows, _composite_unique_sets_1203qk, _dedupe_composite_seed_1203qk)

# Every constraint-label column entry on disk: 104 runs, 1504 tables, 9910 column entries.
# `pseudo` and `ddl` are what the renderer produced BEFORE #1203qk and must keep producing.
CORPUS = [
    # run     table            name                         type                                         pseudo ddl-cols
    ("r144", "follows",       "unique_follower_following", "unique(follower_id,following_id)",            False, None),
    ("r144", "video_likes",   "unique_user_video",         "unique(user_id,video_id)",                    False, None),
    ("r144", "video_saves",   "unique_user_video",         "unique(user_id,video_id)",                    False, None),
    ("r154", "video_likes",   "unique_user_video",         "unique(user_id,video_id)",                    False, None),
    ("r154", "saved_videos",  "unique_user_video",         "string",                                      False, None),
    ("r154", "follows",       "unique_follow",             "string",                                      False, None),
    ("r178", "video_likes",   "unique_user_video",         "text",                                        False, None),
    ("r178", "video_saves",   "unique_user_video",         "text",                                        False, None),
    ("r178", "follows",       "unique_follower_following", "text",                                        False, None),
    ("r183", "follows",       "unique",                    "follower_id,following_id enforced in code",   False, None),
    ("r188", "video_likes",   "unique_user_video",         "unique(user_id, video_id)",                   False, None),
    ("r188", "video_saves",   "unique_user_video",         "unique(user_id, video_id)",                   False, None),
    ("r188", "follows",       "unique_follow",             "unique(follower_user_id, followed_user_id)",  False, None),
    ("r171", "follows",       "unique",                    "follower_id,following_id",                    True,
     '    UNIQUE ("follower_id", "following_id")'),
    ("r171", "comment_likes", "unique",                    "comment_id,user_id",                          True,
     '    UNIQUE ("comment_id", "user_id")'),
]

# The columns each entry NAMES -- None where the entry does not write them down.
RECOVERABLE = {
    ("r144", "follows"):       ["follower_id", "following_id"],
    ("r144", "video_likes"):   ["user_id", "video_id"],
    ("r144", "video_saves"):   ["user_id", "video_id"],
    ("r154", "video_likes"):   ["user_id", "video_id"],
    ("r183", "follows"):       ["follower_id", "following_id"],
    ("r188", "video_likes"):   ["user_id", "video_id"],
    ("r188", "video_saves"):   ["user_id", "video_id"],
    ("r188", "follows"):       ["follower_user_id", "followed_user_id"],
    ("r171", "follows"):       ["follower_id", "following_id"],
    ("r171", "comment_likes"): ["comment_id", "user_id"],
}


def _entry(name, ty):
    return {"name": name, "type": ty}


def _fixture(with_declaration):
    """r144's `video_saves` and the two tables its FKs point at."""
    saves = [{"name": "id", "type": "integer primary_key"},
             {"name": "user_id", "type": "integer references users.id",
              "references": "users(id)"},
             {"name": "video_id", "type": "integer references videos.id",
              "references": "videos(id)"},
             {"name": "created_at", "type": "datetime"}]
    if with_declaration:
        saves.append({"name": "unique_user_video", "type": "unique(user_id,video_id)",
                      "unique": True})
    return {
        "users": {"schema": {"columns": [
            {"name": "id", "type": "integer primary key", "primary_key": True},
            {"name": "email", "type": "text"},
            {"name": "name", "type": "text"}]}},
        "videos": {"schema": {"columns": [
            {"name": "id", "type": "integer primary key", "primary_key": True},
            {"name": "author_id", "type": "integer references users.id",
             "references": "users(id)"},
            {"name": "caption", "type": "text"}]}},
        "video_saves": {"schema": {"columns": saves}},
    }


def _composite_keys(rows, cols):
    return [tuple(r.get(c) for c in cols) for r in rows]


def _dupes(rows, cols):
    seen, dup = set(), []
    for k in _composite_keys(rows, cols):
        if any(v is None for v in k):
            continue
        if k in seen:
            dup.append(k)
        seen.add(k)
    return dup


class ConstraintColumnsAreOneOwner(unittest.TestCase):

    def test_the_two_spellings_the_DDL_never_sees_name_their_columns_1203qk(self):
        for run, tbl, name, ty, _p, _d in CORPUS:
            want = RECOVERABLE.get((run, tbl))
            got = constraint_columns_1203qk(_entry(name, ty))
            if want is None:
                continue
            self.assertIsNotNone(got, "%s/%s %r/%r named no columns" % (run, tbl, name, ty))
            self.assertEqual(("UNIQUE", want), got, "%s/%s" % (run, tbl))

    def test_a_label_that_names_no_columns_is_not_guessed_1203qk(self):
        unrecoverable = [(r, t, n, y) for r, t, n, y, _p, _d in CORPUS
                         if (r, t) not in RECOVERABLE]
        self.assertEqual(5, len(unrecoverable), "the corpus population moved")
        for run, tbl, name, ty in unrecoverable:
            self.assertIsNone(constraint_columns_1203qk(_entry(name, ty)),
                              "%s/%s read columns out of %r/%r" % (run, tbl, name, ty))

    def test_a_non_dict_entry_names_nothing_1203qk(self):
        for junk in (None, "unique(a,b)", 7, ["a", "b"]):
            self.assertIsNone(constraint_columns_1203qk(junk))


class TheDDLMustNotMove(unittest.TestCase):
    """The initdb guard: widening the PREDICATE would emit a UNIQUE the seed violates."""

    def test_the_DDL_the_predicate_emits_is_unchanged_1203qk(self):
        rendered = 0
        for run, tbl, name, ty, pseudo, ddl in CORPUS:
            col = _entry(name, ty)
            self.assertEqual(pseudo, _is_constraint_pseudo_column(col),
                             "%s/%s %r/%r changed side" % (run, tbl, name, ty))
            got = _render_table_constraint(col) if pseudo else None
            self.assertEqual(ddl, got, "%s/%s DDL moved" % (run, tbl))
            rendered += 1 if got else 0
        self.assertEqual(2, rendered, "a constraint-label entry started reaching the DDL")


class WhatCountsAsADeclaredSet(unittest.TestCase):

    def test_the_fixture_declares_the_pair_1203qk(self):
        self.assertEqual({"video_saves": [("user_id", "video_id")]},
                         _composite_unique_sets_1203qk(_fixture(True)))

    def test_without_the_entry_nothing_is_declared_1203qk(self):
        self.assertEqual({}, _composite_unique_sets_1203qk(_fixture(False)))

    def test_a_set_naming_a_column_the_table_lacks_is_not_a_set_1203qk(self):
        t = {"likes": {"schema": {"columns": [
            {"name": "user_id", "type": "integer"},
            {"name": "uq", "type": "unique(user_id,absent_col)"}]}}}
        self.assertEqual({}, _composite_unique_sets_1203qk(t))

    def test_a_composite_PRIMARY_KEY_is_left_to_the_pk_path_1203qk(self):
        t = {"m": {"schema": {"columns": [
            {"name": "a", "type": "integer"}, {"name": "b", "type": "integer"},
            {"name": "pk", "type": "primary key(a,b)"}]}}}
        self.assertEqual({}, _composite_unique_sets_1203qk(t))

    def test_a_single_column_set_is_not_composite_1203qk(self):
        t = {"m": {"schema": {"columns": [
            {"name": "a", "type": "integer"},
            {"name": "uq", "type": "unique(a)"}]}}}
        self.assertEqual({}, _composite_unique_sets_1203qk(t))


class TheSeedObeysWhatItDeclares(unittest.TestCase):

    def test_the_declaration_is_what_removes_the_duplicates_1203qk(self):
        """Differential: identical table, with and without the declared pair."""
        cols = ("user_id", "video_id")
        loose = _build_seed_rows(_fixture(False), env_salt="tiktok-web-r144")[0]
        tight = _build_seed_rows(_fixture(True), env_salt="tiktok-web-r144")[0]
        loose_rows, tight_rows = loose["video_saves"], tight["video_saves"]
        self.assertTrue(_dupes(loose_rows, cols),
                        "control emitted no duplicate pair -- this fixture no longer "
                        "exercises the mechanism, so the test below proves nothing")
        self.assertEqual([], _dupes(tight_rows, cols),
                         "the declared composite UNIQUE is still violated by the seed")

    def test_the_row_count_survives_the_fix_1203qk(self):
        """#1202tz bands row counts on purpose; correctness must not be paid for in rows."""
        loose = _build_seed_rows(_fixture(False), env_salt="tiktok-web-r144")[0]
        tight = _build_seed_rows(_fixture(True), env_salt="tiktok-web-r144")[0]
        self.assertEqual(len(loose["video_saves"]), len(tight["video_saves"]))

    def test_a_rerolled_value_stays_a_valid_FK_target_1203qk(self):
        """Re-rolls only ever use values already observed in that column."""
        loose = _build_seed_rows(_fixture(False), env_salt="tiktok-web-r144")[0]
        tight = _build_seed_rows(_fixture(True), env_salt="tiktok-web-r144")[0]
        for c in ("user_id", "video_id"):
            before = {r.get(c) for r in loose["video_saves"] if r.get(c) is not None}
            after = {r.get(c) for r in tight["video_saves"] if r.get(c) is not None}
            self.assertTrue(after <= before, "%s invented a value: %s" % (c, after - before))


class TheDedupeItself(unittest.TestCase):

    def test_a_duplicate_pair_is_rerolled_not_dropped_1203qk(self):
        seed = {"m": [{"a": 1, "b": 1}, {"a": 1, "b": 1}, {"a": 2, "b": 2}]}
        rr, dr, detail = _dedupe_composite_seed_1203qk(seed, {"m": [("a", "b")]})
        self.assertEqual((1, 0), (rr, dr))
        self.assertEqual(3, len(seed["m"]))
        self.assertEqual([], _dupes(seed["m"], ("a", "b")))
        self.assertTrue(detail and "m(a,b)" in detail[0], detail)

    def test_a_NULL_component_never_collides_1203qk(self):
        """The third row is what makes this bite: with `b` entirely NULL the observed
        domain is empty and the empty-domain guard would absorb a missing NULL test, so
        the fixture gives `b` a real value to re-roll ONTO."""
        seed = {"m": [{"a": 1, "b": None}, {"a": 1, "b": None}, {"a": 2, "b": 5}]}
        rr, dr, _ = _dedupe_composite_seed_1203qk(seed, {"m": [("a", "b")]})
        self.assertEqual((0, 0), (rr, dr))
        self.assertEqual([{"a": 1, "b": None}, {"a": 1, "b": None}, {"a": 2, "b": 5}],
                         seed["m"])

    def test_a_row_is_dropped_only_when_the_domain_is_exhausted_1203qk(self):
        seed = {"m": [{"a": 1, "b": 1}, {"a": 1, "b": 1}, {"a": 1, "b": 1}]}
        rr, dr, detail = _dedupe_composite_seed_1203qk(seed, {"m": [("a", "b")]})
        self.assertEqual((0, 2), (rr, dr))
        self.assertEqual(1, len(seed["m"]))
        self.assertIn("2 dropped", detail[0])

    def test_an_already_clean_seed_is_left_alone_1203qk(self):
        rows = [{"a": 1, "b": 1}, {"a": 1, "b": 2}, {"a": 2, "b": 1}]
        seed = {"m": [dict(r) for r in rows]}
        rr, dr, detail = _dedupe_composite_seed_1203qk(seed, {"m": [("a", "b")]})
        self.assertEqual((0, 0, []), (rr, dr, detail))
        self.assertEqual(rows, seed["m"])

    def test_a_column_the_seeder_never_emitted_is_skipped_1203qk(self):
        seed = {"m": [{"a": 1}, {"a": 1}]}
        self.assertEqual((0, 0, []), _dedupe_composite_seed_1203qk(seed, {"m": [("a", "b")]}))

    def test_a_table_with_no_rows_is_skipped_1203qk(self):
        for empty in ({}, {"m": []}, {"m": None}):
            self.assertEqual((0, 0, []),
                             _dedupe_composite_seed_1203qk(empty, {"m": [("a", "b")]}))


if __name__ == "__main__":
    unittest.main()
