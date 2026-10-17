r"""#1203mx: the chain sent another entity's id, and the note named every suspect but that.

r190's verifier registered `for_you_feed_to_sound_detail`: save `items.0.id` from
`GET /api/videos/feed`, then call `/api/videos/${videoId}/comments`. The app's feed returns
FEED rows, so `items.0.id` is `feed-1` -- and that run's seed declares `feed` ids
`feed-1..feed-8` beside `videos` ids `1..6`. Every attempt 404'd.

What the run was told, 57 times over three hours:

    GET /api/videos/feed-1/comments → 404 … TABLE `videos` HAS 35 LIVE ROW(S) (a seeded id is
    '1') — the table is populated, so the id this step names is the thing that does not
    exist. ⚠ the route RAN … Fix the CHAIN's captured id or the seed, NOT the endpoint (#1052)

Correct about the route, and silent about the one fact that identifies the mistake: `feed-1`
is a `feed` id. M3 cut no release; the resume spent 3h and ~$293 of a $1021 run on it.

MEASURED over every chain hub on disk: 69 steps fail with #1052's "does not resolve", and
**47 (68%)** carry a value that IS an id in another seeded table -- all 47 `feed-1` → `feed`.
In the same sweep the number of failing ids that are a BARE INTEGER colliding with another
table's id is **0**, so nothing asks for a numeric exclusion and none is added (#647).

Silent unless EXACTLY ONE other table owns the value: "it is an id in 7 tables" names nothing,
and this exists to replace a sentence that was already too vague.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    foreign_id_owner_1203mx as owner,
    _seed_shape_note_1202id as note,
)
from env_generator.llm_generator.multi_agent.runtime.seed_audit import seed_id_sets_1203mx

R190_SEED = {
    "videos": [{"id": str(i)} for i in range(1, 7)],
    "feed": [{"id": "feed-%d" % i, "video_id": str(i)} for i in range(1, 9)],
    "sounds": [{"id": str(i)} for i in range(1, 6)],
    "video_likes": [{"user_id": "1", "video_id": "1"}],      # association row, no `id`
}


def _project(seed=None, counts=None):
    d = Path(tempfile.mkdtemp())
    be = d / "app" / "backend"
    be.mkdir(parents=True)
    if seed is not None:
        (be / "seed_data.json").write_text(json.dumps(seed))
    if counts is not None:
        sh = d / "shared"
        sh.mkdir(parents=True, exist_ok=True)
        (sh / "seed_live_counts_1202dj.json").write_text(
            json.dumps({"at": time.time(), "counts": counts}))
    return d


class TheOwningTableIsNamed(unittest.TestCase):
    def test_r190s_exact_shape(self):
        d = _project(R190_SEED)
        self.assertEqual(owner(d, "/api/videos/feed-1/comments", "videos"), ("feed-1", "feed"))

    def test_every_feed_id_of_that_run_resolves_the_same_way(self):
        d = _project(R190_SEED)
        for i in range(1, 9):
            with self.subTest(i=i):
                self.assertEqual(
                    owner(d, "/api/videos/feed-%d/comments" % i, "videos"), ("feed-%d" % i, "feed"))

    def test_it_works_on_a_flat_by_id_path_too(self):
        d = _project(R190_SEED)
        self.assertEqual(owner(d, "/api/videos/feed-3", "videos"), ("feed-3", "feed"))

    def test_the_query_string_is_not_searched(self):
        """The query must carry a SLASH for this to bite: without one it stays glued to the
        last segment and both readings agree, which is how my first version of this case
        passed against a mutant that searched the query (mutation MX5)."""
        d = _project(R190_SEED)
        self.assertIsNone(owner(d, "/api/videos/1/comments?next=/api/videos/feed-2", "videos"))


class ItStaysSilentWhereItCannotAttribute(unittest.TestCase):
    def test_a_value_the_target_declares_is_not_foreign(self):
        d = _project(R190_SEED)
        self.assertIsNone(owner(d, "/api/videos/1/comments", "videos"))

    def test_an_id_in_no_table_says_nothing(self):
        d = _project(R190_SEED)
        self.assertIsNone(owner(d, "/api/videos/9999/comments", "videos"))

    def test_a_value_owned_by_two_tables_says_nothing(self):
        """'it is an id in 7 tables' names nothing a lane can act on."""
        d = _project({"videos": [{"id": "1"}],
                      "sounds": [{"id": "x7"}],
                      "users": [{"id": "x7"}]})
        self.assertIsNone(owner(d, "/api/videos/x7/comments", "videos"))

    def test_an_association_table_is_never_an_owner(self):
        """`video_likes` has a composite pk and no `id`; a lookup against it must not match."""
        self.assertNotIn("video_likes", seed_id_sets_1203mx(R190_SEED))

    def test_no_seed_file_says_nothing(self):
        self.assertIsNone(owner(_project(None), "/api/videos/feed-1", "videos"))

    def test_a_corrupt_seed_says_nothing(self):
        d = _project(R190_SEED)
        (d / "app" / "backend" / "seed_data.json").write_text("{not json")
        self.assertIsNone(owner(d, "/api/videos/feed-1", "videos"))


class TypeLoosenessIsHandledTheWayMtEstablished(unittest.TestCase):
    def test_int_ids_in_the_seed_match_a_string_segment(self):
        d = _project({"videos": [{"id": i} for i in (1, 2)],
                      "feed": [{"id": i} for i in (7, 8)]})
        self.assertEqual(owner(d, "/api/videos/7/comments", "videos"), ("7", "feed"))

    def test_an_int_id_the_target_declares_is_still_skipped(self):
        d = _project({"videos": [{"id": i} for i in (1, 2)], "feed": [{"id": 7}]})
        self.assertIsNone(owner(d, "/api/videos/1/comments", "videos"))


class TheNoteCarriesIt(unittest.TestCase):
    """End to end through the sentence a lane actually reads."""

    def _note(self, path, seed=None, counts=None):
        d = _project(R190_SEED if seed is None else seed,
                     {"videos": 35} if counts is None else counts)
        eps = [{"path": "/api/videos/{id}/comments", "method": "GET"}]
        return note("GET", path, d, {"videos": "1"}, eps)

    def test_the_sentence_names_the_value_and_its_table(self):
        s = self._note("/api/videos/feed-1/comments")
        self.assertIn("feed-1", s)
        self.assertIn("`feed`", s)

    def test_it_says_the_capture_is_what_to_change(self):
        s = self._note("/api/videos/feed-1/comments")
        self.assertIn("ANOTHER ENTITY'S id", s)
        self.assertIn("capture", s)

    def test_the_old_sentence_is_still_there(self):
        """Additive: #1202id's live-row reading and #1202jk's verdict are untouched."""
        s = self._note("/api/videos/feed-1/comments")
        self.assertIn("TABLE `videos` HAS 35 LIVE ROW(S)", s)
        self.assertIn("does not exist", s)

    def test_a_resolvable_id_adds_nothing(self):
        s = self._note("/api/videos/1/comments")
        self.assertIn("TABLE `videos` HAS 35 LIVE ROW(S)", s)
        self.assertNotIn("ANOTHER ENTITY", s)

    def test_an_empty_table_keeps_its_own_verdict(self):
        s = self._note("/api/videos/feed-1/comments", counts={"videos": 0})
        self.assertIn("0 LIVE ROWS", s)
        self.assertNotIn("ANOTHER ENTITY", s)   # a seed defect, not a capture one

    def test_no_measurement_still_says_nothing(self):
        """#1202dj: NOT MEASURED is not 'the table is empty'."""
        d = _project(R190_SEED)                 # no live-counts artifact
        eps = [{"path": "/api/videos/{id}/comments", "method": "GET"}]
        self.assertEqual(note("GET", "/api/videos/feed-1/comments", d, {}, eps), "")


if __name__ == "__main__":
    unittest.main()
