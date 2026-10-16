r"""#1203mt: #1203ga compared foreign keys raw, so a type mismatch read as 247 dangling rows.

`orphan_fk_rows_in_authored_seed_1203ga` gathered raw `id` values and tested
`val not in ids[target]`. JSON carries no integer/string discipline and the lane writes
both, so a seed whose ids are the strings "1".."6" and whose references are the ints 1..6 --
or the reverse -- reads as every row orphaned while the parent is right there.

MEASURED over the seeds on disk: the raw compare reports 99 orphans across 5 runs; the SAME
rule with `str()` on both sides reports 35 across 3. **64 of 99 (65%) are pure type
mismatch.** Two runs lose every report -- tiktok-web-r107 (34, all of `comments.video_id` /
`likes.video_id` / `notifications.video_id`) and tiktok-web-r58 (30, all `comments.user_id`).

It matters because of what the finding is FOR: the docstring's own argument is that
`audit_authored_seed` already tells the lane to "keep it FK-valid" and nothing checked it, so
this is the evidence the lane acts on. r190 printed it 624 times -- 6.7x its next-loudest
warning, and absent from every other run's top six -- while business_chain refused the cut
over `sound_id` values "that do not resolve". r190's FINAL seed is FK-valid under this check,
so whether those 624 were this shape is NOT recoverable from the artifact; what is measurable
is that the detector is 65% false corpus-wide.

The three surviving runs are the real ones, and they include the case the docstring itself
cites: netflix-local-r32 points `continue_watching` / `episodes` at titles 7-12 while
`titles` holds 1-6.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.seed_audit import (
    orphan_fk_rows_in_authored_seed_1203ga as orphans,
)


def _seed(video_ids, feed_refs, extra=None):
    d = {"videos": [{"id": v, "title": "v%s" % v} for v in video_ids],
         "feed": [{"id": i + 1, "video_id": r} for i, r in enumerate(feed_refs)]}
    if extra:
        d.update(extra)
    return d


class ATypeMismatchIsNotADanglingKey(unittest.TestCase):
    def test_string_ids_with_int_references(self):
        """r190's shape: `videos[].id` are strings, the referencing column holds ints."""
        self.assertEqual(orphans(_seed(["1", "2", "3"], [1, 2, 3])), {})

    def test_int_ids_with_string_references(self):
        self.assertEqual(orphans(_seed([1, 2, 3], ["1", "2", "3"])), {})

    def test_mixed_on_both_sides(self):
        self.assertEqual(orphans(_seed([1, "2", 3], ["1", 2, "3"])), {})


class ARealOrphanStillCounts(unittest.TestCase):
    def test_a_reference_to_a_row_that_is_not_there(self):
        got = orphans(_seed(["1", "2", "3"], [1, 2, 7]))
        self.assertEqual(got, {"feed.video_id": 1})

    def test_the_docstrings_own_case(self):
        """netflix-local-r32: children point at titles 7-12 while `titles` holds 1-6."""
        d = {"titles": [{"id": i} for i in range(1, 7)],
             "continue_watching": [{"id": 1, "title_id": 9}, {"id": 2, "title_id": 11}],
             "episodes": [{"id": 1, "title_id": 7}]}
        got = orphans(d)
        self.assertEqual(got.get("continue_watching.title_id"), 2)
        self.assertEqual(got.get("episodes.title_id"), 1)

    def test_several_orphans_are_counted_per_column(self):
        got = orphans(_seed(["1"], [1, 5, 6]))
        self.assertEqual(got, {"feed.video_id": 2})


class TheNarrowingIsOnlyStr(unittest.TestCase):
    """#647: `str()` is the one transform JSON's looseness forces. Nothing else is coerced."""

    def test_whitespace_is_not_stripped(self):
        self.assertEqual(orphans(_seed(["1"], [" 1"])), {"feed.video_id": 1})

    def test_case_is_not_folded(self):
        self.assertEqual(orphans(_seed(["a1"], ["A1"])), {"feed.video_id": 1})

    def test_a_float_is_not_rounded_into_an_int(self):
        self.assertEqual(orphans(_seed(["1"], [1.0])), {})  # 1.0 is not int/str -> skipped

    def test_none_is_still_skipped(self):
        d = _seed(["1"], [1])
        d["feed"].append({"id": 9, "video_id": None})
        self.assertEqual(orphans(d), {})


class ItKeepsTheRestOfItsContract(unittest.TestCase):
    def test_only_tables_with_an_explicit_id_are_targets(self):
        """Without an `id` the row numbering is the database's to choose."""
        d = {"videos": [{"title": "no id"}], "feed": [{"id": 1, "video_id": 99}]}
        self.assertEqual(orphans(d), {})

    def test_the_id_column_itself_is_not_a_foreign_key(self):
        self.assertEqual(orphans({"videos": [{"id": "1"}]}), {})

    def test_plural_and_es_targets_resolve(self):
        self.assertEqual(orphans({"boxes": [{"id": "1"}],
                                  "t": [{"id": 1, "box_id": 1}]}), {})

    def test_it_never_raises(self):
        for bad in (None, [], 7, "x", {"a": 1}, {"t": [None, 3]}):
            self.assertIsInstance(orphans(bad), dict)


if __name__ == "__main__":
    unittest.main()
