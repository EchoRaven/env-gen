"""#1202fh: an owner-scoped list read must carry the entity it points at.

The projected list for a join/interaction table returned only its own columns.
netflix-r43, live: GET /api/my-list -> {"items":[{"id":..,"profile_id":..,
"title_id":..}]}. The page has ids and nothing to draw, so it renders a
placeholder grid, which the visual judge reports as an EMPTY state.

The split shows in the pass rates: pages backed directly by the entity table
score 89% (landing) / 60% (movies) / 50% (shows); pages backed by a join or
interaction table score 10% (my_list, new_and_popular, browse_by_languages).
And #528 gives the projected read precedence over any lane GET, so the lane
cannot route around it.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _expandable_fks_1202fh,
    _generate_handler,
)

# Types are part of a real contract and the join guard reads them: a fixture with `types:
# {}` refuses every expansion, which is the guard working (unknown -> refuse) and a fixture
# that does not resemble anything the projector is handed.
MODELS = {
    "my_list": {"cls": "MyList", "cols": ["id", "profile_id", "title_id"],
                "owner_fk": "profile_id",
                "types": {"id": "Integer", "profile_id": "Integer", "title_id": "Integer"}},
    "titles": {"cls": "Titles", "cols": ["id", "name", "poster", "backdrop", "synopsis"],
               "types": {"id": "Integer", "name": "String", "poster": "String",
                         "backdrop": "String", "synopsis": "Text"}},
    "profiles": {"cls": "Profiles", "cols": ["id", "name", "avatar"],
                 "types": {"id": "Integer", "name": "String", "avatar": "String"}},
}


def _handler(models=None, path="/api/my-list", table="my_list"):
    return _generate_handler("GET", path, True, models or MODELS, 4,
                             owner_scoped_reads=True, owner_scoped_tables=[table])


class TestWhichForeignKeysExpand(unittest.TestCase):

    def test_a_public_entity_expands(self):
        got = _expandable_fks_1202fh(["id", "profile_id", "title_id"], MODELS, "my_list")
        self.assertEqual([c for c, _, _ in got], ["title_id"])
        self.assertEqual(got[0][1], "Titles")

    def test_an_actor_fk_never_expands(self):
        """#569/#803: folding an actor in is the leak class. Decided by what the FK
        POINTS AT, never by its name -- #784 lost `recipient_id` to a name-based guard."""
        got = _expandable_fks_1202fh(["id", "profile_id"], MODELS, "my_list")
        self.assertEqual(got, [])

    def test_only_label_and_image_columns_come_along(self):
        cols = _expandable_fks_1202fh(["title_id"], MODELS, "my_list")[0][2]
        self.assertIn("name", cols)
        self.assertIn("poster", cols)
        self.assertIn("id", cols)
        self.assertNotIn("synopsis", cols, "prose is not what a card draws")

    def test_a_degenerate_target_does_not_expand(self):
        """#568: a model with no columns has nothing safe to show."""
        m = dict(MODELS, titles={"cls": "Titles", "cols": [], "types": {"id": "Integer"}})
        self.assertEqual(_expandable_fks_1202fh(["title_id"], m, "my_list"), [])

    def test_it_never_shadows_a_column_the_row_already_has(self):
        got = _expandable_fks_1202fh(["title_id", "title"], MODELS, "my_list")
        self.assertEqual(got, [])

    def test_a_self_reference_does_not_expand(self):
        """A row expanding into its own table adds nothing to a list of that table."""
        m = {"comments": {"cls": "Comments", "cols": ["id", "name", "comment_id"],
                          "types": {"id": "Integer", "name": "String",
                                    "comment_id": "Integer"}}}
        self.assertEqual(_expandable_fks_1202fh(["comment_id"], m, "comments"), [])

    def test_a_target_without_a_join_key_does_not_expand(self):
        """The emitted map is keyed by the target's `id`. Without one every key is None,
        every row resolves to None, and the expansion fails SILENTLY -- the page looks
        exactly as broken as before while the payload claims to carry the entity."""
        m = dict(MODELS, titles={"cls": "Titles", "cols": ["name", "poster"],
                                  "types": {"name": "String", "poster": "String"}})
        self.assertEqual(_expandable_fks_1202fh(["title_id"], m, "my_list"), [])

    def test_mismatched_join_types_do_not_expand(self):
        """THE REGRESSION THIS SHIPPED WITH. tiktok-r96 mixes them: `videos.id` is Text (a
        uuid default) while `sounds.id` and the FKs are Integer. Postgres answers a
        mismatched comparison with `UndefinedFunction: operator does not exist: text =
        integer` -- a 500 on a FRAMEWORK-PROJECTED route no lane can repair. It killed a
        $25 resume, and every fixture in this file had used consistent Integer ids, so four
        layers of verification passed over it."""
        m = {
            "notifications": {"cls": "Notification", "cols": ["id", "video_id"],
                              "types": {"id": "Integer", "video_id": "Integer"}},
            "videos": {"cls": "Video", "cols": ["id", "thumbnail"],
                       "types": {"id": "Text", "thumbnail": "String"}},
        }
        self.assertEqual(_expandable_fks_1202fh(["video_id"], m, "notifications"), [])

    def test_matching_types_still_expand(self):
        m = {
            "notifications": {"cls": "Notification", "cols": ["id", "video_id"],
                              "types": {"id": "Integer", "video_id": "Integer"}},
            "videos": {"cls": "Video", "cols": ["id", "thumbnail"],
                       "types": {"id": "Integer", "thumbnail": "String"}},
        }
        self.assertEqual([c for c, _, _ in
                          _expandable_fks_1202fh(["video_id"], m, "notifications")],
                         ["video_id"])

    def test_text_keys_join_text_keys(self):
        """Both sides text is as safe as both sides integer."""
        m = {
            "saves": {"cls": "Save", "cols": ["id", "video_id"],
                      "types": {"id": "Text", "video_id": "Text"}},
            "videos": {"cls": "Video", "cols": ["id", "thumbnail"],
                       "types": {"id": "Text", "thumbnail": "String"}},
        }
        self.assertTrue(_expandable_fks_1202fh(["video_id"], m, "saves"))

    def test_an_unknown_type_refuses(self):
        """#1202bd's asymmetry: a missing expansion leaves the page as it was; a wrong one
        is a 500 that blocks delivery."""
        m = {
            "x": {"cls": "X", "cols": ["id", "video_id"], "types": {"id": "Integer"}},
            "videos": {"cls": "Video", "cols": ["id", "thumbnail"],
                       "types": {"id": "Integer"}},
        }
        self.assertEqual(_expandable_fks_1202fh(["video_id"], m, "x"), [])

    def test_it_never_raises(self):
        self.assertEqual(_expandable_fks_1202fh(None, None, None), [])
        self.assertEqual(_expandable_fks_1202fh(["x_id"], {}, "t"), [])


class TestTheEmittedHandler(unittest.TestCase):

    def test_it_batches_instead_of_n_plus_one(self):
        """100 rows must not become 100 queries."""
        src = _handler()
        self.assertIn(".in_(_ids_title)", src)
        self.assertEqual(src.count("db.query(Titles)"), 1)

    def test_the_entity_is_merged_into_each_item(self):
        self.assertIn('"title": _m_title.get(getattr(r, "title_id", None))', _handler())

    def test_the_rows_own_columns_survive(self):
        src = _handler()
        for c in ("id", "profile_id", "title_id"):
            self.assertIn('"%s": getattr(r, "%s", None)' % (c, c), src)

    def test_a_public_list_folds_a_public_target_but_never_a_private_one(self):
        """AMENDED by #1202ip. This was `test_a_public_list_is_untouched`, asserting
        constraint 1 ("owner-scoped LIST only"). #1202fh's own header calls that constraint
        "free here: the branch is inside `if read_scoped`" -- a description of where the code
        happened to sit, not an argument that a public list must stay bare.

        Measured cost of keeping it: 123 of 232 public projected list reads across 24 corpus
        runs answered with bare foreign keys, and #528 hands the projected read precedence
        over the lane's own joined GET, so no lane could repair it (r109's custom_routes.py
        defines a richer GET /api/videos that never serves a request).

        #1202fh's safety argument was about the READ -- "the caller is reading THEIR OWN
        rows". That does not survive the move, so #1202ip replaces it with one about the
        TARGET: fold only an entity this app already serves to anyone. `titles` is public and
        comes along; the same fold is refused the moment the app serves `titles` owner-scoped.
        """
        src = _generate_handler("GET", "/api/my-list", True, MODELS, 4,
                                owner_scoped_reads=False)
        self.assertIn("_m_title", src)

        src_private = _generate_handler("GET", "/api/my-list", True, MODELS, 4,
                                        owner_scoped_reads=False,
                                        owner_scoped_tables=["titles"])
        self.assertNotIn("_m_title", src_private)

    def test_the_emitted_code_runs_and_carries_the_artwork(self):
        """The whole point: execute it, do not just read it."""
        src = _handler()
        body = "\n".join(src.split("\n")[2:])

        class Row:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        class Col:
            def __init__(self, n):
                self.n = n

            def __eq__(self, v):
                return ("eq", self.n, v)

            def in_(self, v):
                return ("in", self.n, list(v))

        class Model:
            def __init__(self, rows):
                self._rows = rows

            def __getattr__(self, n):
                return Col(n)

        class Q:
            def __init__(self, m):
                self.m, self.f = m, []

            def filter(self, c):
                self.f.append(c)
                return self

            def limit(self, n):
                return self

            def all(self):
                rows = self.m._rows
                for kind, col, val in self.f:
                    rows = [r for r in rows
                            if (getattr(r, col, None) == val if kind == "eq"
                                else getattr(r, col, None) in val)]
                return rows

        class DB:
            def query(self, m):
                return Q(m)

        ns = {
            "MyList": Model([Row(id=1, profile_id=7, title_id=42)]),
            "Titles": Model([Row(id=42, name="Inception", poster="/assets/p42.jpg",
                                 backdrop="/assets/b42.jpg", synopsis="x")]),
            "_fw_owner_val": lambda cls, fk, user: 7,
        }
        exec("def _h(db, user):\n" + body, ns)
        out = ns["_h"](DB(), object())
        item = out["items"][0]
        self.assertEqual(item["title_id"], 42)
        self.assertEqual(item["title"]["poster"], "/assets/p42.jpg",
                         "the page still has nothing to draw")
        self.assertEqual(item["title"]["name"], "Inception")
        self.assertNotIn("synopsis", item["title"])

    def test_a_missing_reference_yields_none_not_a_crash(self):
        src = _handler()
        body = "\n".join(src.split("\n")[2:])

        class Row:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        class Col:
            def __init__(self, n):
                self.n = n

            def __eq__(self, v):
                return ("eq", self.n, v)

            def in_(self, v):
                return ("in", self.n, list(v))

        class Model:
            def __init__(self, rows):
                self._rows = rows

            def __getattr__(self, n):
                return Col(n)

        class Q:
            def __init__(self, m):
                self.m, self.f = m, []

            def filter(self, c):
                self.f.append(c)
                return self

            def limit(self, n):
                return self

            def all(self):
                rows = self.m._rows
                for kind, col, val in self.f:
                    rows = [r for r in rows
                            if (getattr(r, col, None) == val if kind == "eq"
                                else getattr(r, col, None) in val)]
                return rows

        class DB:
            def query(self, m):
                return Q(m)

        ns = {"MyList": Model([Row(id=1, profile_id=7, title_id=None)]),
              "Titles": Model([]), "_fw_owner_val": lambda c, f, u: 7}
        exec("def _h(db, user):\n" + body, ns)
        self.assertIsNone(ns["_h"](DB(), object())["items"][0]["title"])


if __name__ == "__main__":
    unittest.main()
