r"""#1203my: the same wrong id, one chain over, travelling in the request BODY.

#1203mx named the owning table for an id in the PATH, and r190's lane acted on it inside the
hour: told that `feed-1` is a `feed` id, it changed `for_you_feed_to_sound_detail` to save
`items.0.video_id`, and that chain -- 57 failures across 8h16m of milestone time, the run's
final hold twice -- now records `broken: []` and `status: passing`.

The run then stopped on the same mistake one chain over, where #1203mx is silent by
construction:

    GET  /api/videos/feed                           save videoId = items.0.id
    POST /api/comments  {"video_id": "${videoId}"}   -> 404

`comment_panel_comment_readback` carries the identical capture and sends the value in the
body, so the path has no id in it at all. The hold r190 ended on reads "TABLE `comments` HAS
29 LIVE ROW(S) (a seeded id is 'comment-1') … the id this step sent does not resolve" -- and
`comments` is not even the table the value should have come from.

MEASURED over every chain hub on disk: of 95 steps failing with #1052's "does not resolve",
68 carry the unresolved id in the path and 27 do not; 18 of those 27 are this POST, in the
run it blocked.

The implied table comes from the FIELD (`video_id` → `videos`), not from the endpoint's
resource, which is what makes it right for a POST whose path carries no id.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    foreign_body_id_owner_1203my as body_owner,
    _seed_shape_note_1202id as note,
)
from env_generator.llm_generator.multi_agent.runtime.seed_audit import fk_target_table_1203my

R190_SEED = {
    "videos": [{"id": str(i)} for i in range(1, 7)],
    "feed": [{"id": "feed-%d" % i} for i in range(1, 9)],
    "comments": [{"id": "comment-%d" % i} for i in range(1, 30)],
}


def _project(seed=R190_SEED, counts=None):
    d = Path(tempfile.mkdtemp())
    be = d / "app" / "backend"
    be.mkdir(parents=True)
    if seed is not None:
        (be / "seed_data.json").write_text(json.dumps(seed))
    if counts is not None:
        (d / "shared").mkdir(parents=True, exist_ok=True)
        (d / "shared" / "seed_live_counts_1202dj.json").write_text(
            json.dumps({"at": time.time(), "counts": counts}))
    return d


class TheFieldSaysWhichTableWasMeant(unittest.TestCase):
    def test_r190s_blocking_body(self):
        self.assertEqual(body_owner(_project(), {"video_id": "feed-1", "text": "hi"}),
                         ("video_id", "feed-1", "videos", "feed"))

    def test_the_implied_table_is_the_fields_not_the_routes(self):
        """The failing POST is /api/comments; the value belongs under `videos`."""
        _f, _v, implied, owner = body_owner(_project(), {"video_id": "feed-2"})
        self.assertEqual((implied, owner), ("videos", "feed"))

    def test_a_singular_table_name_resolves_too(self):
        d = _project({"video": [{"id": "1"}], "feed": [{"id": "feed-1"}]})
        self.assertEqual(body_owner(d, {"video_id": "feed-1"})[2], "video")

    def test_an_int_value_matches_a_string_seed_id(self):
        d = _project({"videos": [{"id": "1"}], "feed": [{"id": "7"}]})
        self.assertEqual(body_owner(d, {"video_id": 7})[1], "7")


class ItStaysSilentWhereItCannotAttribute(unittest.TestCase):
    def test_a_value_the_implied_table_declares(self):
        self.assertIsNone(body_owner(_project(), {"video_id": "3", "text": "hi"}))

    def test_a_valid_id_that_ANOTHER_table_also_declares(self):
        """The case that makes the skip load-bearing, and the common one: numeric ids
        collide across tables. `video_id=1` is a real video; that `sounds` also has a row 1
        says nothing, and reporting it would fire on every valid numeric FK in the corpus.
        (Mutation MY2 removed the skip and my first version of this class never noticed,
        because its value was owned by the implied table alone.)"""
        d = _project({"videos": [{"id": "1"}, {"id": "2"}],
                      "sounds": [{"id": "1"}, {"id": "2"}]})
        self.assertIsNone(body_owner(d, {"video_id": "1"}))
        self.assertIsNone(body_owner(d, {"sound_id": "2"}))

    def test_a_field_that_is_not_a_foreign_key(self):
        self.assertIsNone(body_owner(_project(), {"text": "feed-1"}))

    def test_the_rows_own_id_is_not_a_foreign_key(self):
        self.assertIsNone(body_owner(_project(), {"id": "feed-1"}))

    def test_a_field_naming_no_seeded_table(self):
        self.assertIsNone(body_owner(_project(), {"widget_id": "feed-1"}))

    def test_a_value_owned_by_two_tables(self):
        d = _project({"videos": [{"id": "1"}], "feed": [{"id": "x"}], "sounds": [{"id": "x"}]})
        self.assertIsNone(body_owner(d, {"video_id": "x"}))

    def test_a_bool_is_not_an_id(self):
        """A flag must not be looked up as id 1 -- but note WHY it is not: every compare
        goes through `str()`, and `str(True)` is "True". The `isinstance(val, bool)` guard
        in the helper is belt-and-braces, not what makes this pass (mutation MY4 removes it
        and nothing changes), so this asserts the mechanism that actually holds."""
        d = _project({"videos": [{"id": "0"}], "feed": [{"id": "1"}, {"id": "True"}]})
        self.assertIsNone(body_owner(d, {"video_id": True}),
                          "a bool must never be attributed, by either route")

    def test_no_body_and_no_seed(self):
        self.assertIsNone(body_owner(_project(), None))
        self.assertIsNone(body_owner(_project(), "not a mapping"))
        self.assertIsNone(body_owner(_project(seed=None), {"video_id": "feed-1"}))


class TheSharedFieldRule(unittest.TestCase):
    """#1032: #1203ga asks this of a seed row, #1203my of a request body. One copy."""

    IDS = {"videos": set(), "boxes": set(), "feed": set()}

    def test_plural(self):
        self.assertEqual(fk_target_table_1203my("video_id", self.IDS), "videos")

    def test_es_plural(self):
        self.assertEqual(fk_target_table_1203my("box_id", self.IDS), "boxes")

    def test_exact(self):
        self.assertEqual(fk_target_table_1203my("feed_id", self.IDS), "feed")

    def test_the_rows_own_id(self):
        self.assertIsNone(fk_target_table_1203my("id", self.IDS))

    def test_a_column_that_is_not_a_fk(self):
        self.assertIsNone(fk_target_table_1203my("text", self.IDS))

    def test_an_unknown_table(self):
        self.assertIsNone(fk_target_table_1203my("widget_id", self.IDS))

    def test_the_SUFFIX_is_what_makes_a_column_a_foreign_key(self):
        """Without it `base = col[:-3]` runs on every column name, and any spelling whose
        last three characters can be chopped to a table name becomes an FK. Contrived on
        purpose -- nothing in the corpus spells it this way, and that is exactly why the
        rule had no test until mutation MY12 removed it and stayed green."""
        ids = {"comments": set()}
        self.assertIsNone(fk_target_table_1203my("commentsid", ids))
        self.assertEqual(fk_target_table_1203my("comment_id", ids), "comments")

    def test_the_exact_name_wins_over_the_plural(self):
        """Nothing in the corpus declares both, so the order is a DECISION, not a
        measurement -- pinned here because mutation MY11 reversed it unnoticed."""
        both = {"video": set(), "videos": set()}
        self.assertEqual(fk_target_table_1203my("video_id", both), "video")


class TheNoteCarriesIt(unittest.TestCase):
    def _note(self, path, body, counts):
        eps = [{"path": "/api/comments", "method": "POST"},
               {"path": "/api/videos/{id}/comments", "method": "GET"}]
        return note("POST", path, _project(counts=counts), {"comments": "comment-1"}, eps,
                    body=body)

    def test_the_sentence_names_the_field_value_and_both_tables(self):
        s = self._note("/api/comments", {"video_id": "feed-1"}, {"comments": 29})
        self.assertIn("video_id", s)
        self.assertIn("feed-1", s)
        self.assertIn("`feed`", s)
        self.assertIn("`videos`", s)

    def test_it_says_the_capture_is_what_to_change(self):
        s = self._note("/api/comments", {"video_id": "feed-1"}, {"comments": 29})
        self.assertIn("ANOTHER ENTITY'S id", s)
        self.assertIn("capture", s)

    def test_the_existing_reading_survives(self):
        s = self._note("/api/comments", {"video_id": "feed-1"}, {"comments": 29})
        self.assertIn("TABLE `comments` HAS 29 LIVE ROW(S)", s)

    def test_a_clean_body_adds_nothing(self):
        s = self._note("/api/comments", {"video_id": "3"}, {"comments": 29})
        self.assertIn("TABLE `comments` HAS 29 LIVE ROW(S)", s)
        self.assertNotIn("THE BODY sent", s)

    def test_no_body_at_all_adds_nothing(self):
        s = self._note("/api/comments", None, {"comments": 29})
        self.assertNotIn("THE BODY sent", s)


class BothHalvesOfTheSentenceCompose(unittest.TestCase):
    """#1203mx (path) and #1203my (body) land in the SAME sentence builder on the same day.

    Each is green alone; this is the case neither covers -- a step that carries a foreign id
    in both places must say both, in one note, without either clause eating the other.
    """

    def _note(self, body):
        eps = [{"path": "/api/videos/{id}/comments", "method": "POST"}]
        return note("POST", "/api/videos/feed-4/comments", _project(counts={"videos": 35}),
                    {"videos": "1"}, eps, body=body)

    def test_both_clauses_appear(self):
        s = self._note({"video_id": "feed-5"})
        self.assertIn("'feed-4' IS an id in `feed`", s)       # #1203mx, from the path
        self.assertIn("THE BODY sent `video_id`", s)          # #1203my, from the body
        self.assertIn("feed-5", s)

    def test_an_unseeded_implied_table_stays_silent(self):
        """`sound_id` with no `sounds` in the seed: the value IS a `feed` id, but nothing
        here establishes that a sound id could not look like that, so #883 applies -- this
        says nothing rather than guessing. (My first composition case used this shape and
        failed, which is how the behaviour got stated instead of assumed.)"""
        s = self._note({"sound_id": "feed-5"})
        self.assertNotIn("THE BODY sent", s)
        self.assertIn("'feed-4' IS an id in `feed`", s)       # the path half is unaffected

    def test_the_path_clause_survives_an_empty_body(self):
        s = self._note(None)
        self.assertIn("'feed-4' IS an id in `feed`", s)
        self.assertNotIn("THE BODY sent", s)

    def test_the_body_clause_survives_a_clean_path(self):
        eps = [{"path": "/api/videos/{id}/comments", "method": "POST"}]
        s = note("POST", "/api/videos/2/comments", _project(counts={"videos": 35}),
                 {"videos": "1"}, eps, body={"video_id": "feed-5"})
        self.assertNotIn("'feed-4' IS an id in `feed`", s)
        self.assertIn("THE BODY sent `video_id`", s)


class TheCallSitePassesTheResolvedBody(unittest.TestCase):
    def test_the_executor_hands_the_body_in(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE
        tree = ast.parse(inspect.getsource(CE))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "_seed_shape_note_1202id"]
        self.assertEqual(len(calls), 1)
        kw = {k.arg: k.value for k in calls[0].keywords}
        self.assertIn("body", kw, "the note is built without the body it needs")
        self.assertEqual(getattr(kw["body"], "id", None), "body",
                         "it must be the RESOLVED body (`body`), not the raw step's")


if __name__ == "__main__":
    unittest.main()
