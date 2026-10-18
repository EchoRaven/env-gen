r"""#1203nf: `{username}` resolved against `users.name`, and nobody said so.

`_lookup_field`'s ladder, for a by-name path param: the param's own column, then `username`
when the param is user-ish, then `slug`, then any `_NAMED_LOOKUP_COLS` entry RELATED to the
param, then any of them at all, then `id`. Step 4 matches on substring, and `"name"` is a
substring of `"username"` -- so `{username}` on a table with `name` and no `username` resolves
to `name`. That is the best column available and the projection is not wrong. What was missing
is that nobody could know.

THIS FILE ALREADY NAMES THE FAILURE MODE. #1203a9's comment, 150 lines above: "The override
announces itself so the choice is auditable rather than silent -- the failure mode this whole
area keeps producing."

MEASURED by replaying this very ladder over every run's `registryhub_tables` +
`registryhub_endpoints`: 9 by-name params in 4 runs resolve to a column other than themselves,
and all 9 are `{username}` -> `users.name`:

    tiktok-web-r58   4   /api/users/{username}, /{username}/videos, /{username}/follow x2
    tiktok-web-r190  2   POST and DELETE /api/users/{username}/follow
    tiktok-web-r81   2   /api/users/{username}/follow x2
    tiktok-web-r103  1   /api/users/{username}

r190's two are the endpoint its final milestone died on.

WHAT THE SILENCE COST THERE: the lane worked the binding out by failure and wrote
`UPDATE users SET name = :username, username = :username, display_name = :display_name ...`,
commenting "The framework-projected follow handler resolves /api/users/{username}/follow with
``users.name == username``. Keep that natural-key alias true for any pre-existing creator row
in this tenant". It overwrote the human display name with the handle to satisfy a binding it
could not see. 64 of the 102 runs whose registration carries a `users` table DO register a
`username` column -- the other route was open, and unsaid.

Behaviour is unchanged. The ladder is untouched; `_lookup_field` returns exactly what
`_lookup_field_col_1203nf` decides, and a failure inside the announcement cannot alter it.
"""
import ast
import inspect
import logging
import unittest

from env_generator.llm_generator.multi_agent.runtime import route_projector as RP
from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _is_id_param,
    _lookup_field,
    _lookup_field_col_1203nf,
    reset_said_lookup_1203nf,
)

_SPINE = {"cols": ["id", "email", "name", "password_hash", "tenant_id", "created_at"]}


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _Caught:
    """Capture what this module logs, without depending on pytest's caplog shape."""

    def __enter__(self):
        self.log = logging.getLogger(RP.__name__)
        self.h = _Cap()
        self.old = self.log.level
        self.log.addHandler(self.h)
        self.log.setLevel(logging.WARNING)
        return self.h

    def __exit__(self, *a):
        self.log.removeHandler(self.h)
        self.log.setLevel(self.old)
        return False


class ItSaysWhichColumnItChose(unittest.TestCase):
    def setUp(self):
        reset_said_lookup_1203nf()

    def test_r190s_follow_endpoint(self):
        with _Caught() as cap:
            got = _lookup_field("username", _SPINE, table="users",
                                path="/api/users/{username}/follow")
        self.assertEqual(got, "name")
        self.assertTrue(cap.lines)
        msg = cap.lines[0]
        for part in ("/api/users/{username}/follow", "{username}", "users", "'name'"):
            self.assertIn(part, msg)

    def test_it_names_the_registered_columns(self):
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/x")
        for col in _SPINE["cols"]:
            self.assertIn(col, cap.lines[0])

    def test_a_long_column_list_declares_its_cut(self):
        """#1034: a list must say what it left out."""
        meta = {"cols": ["name"] + ["c%02d" % i for i in range(30)]}
        with _Caught() as cap:
            _lookup_field("username", meta, table="users", path="/x")
        self.assertIn("more not shown", cap.lines[0])

    def test_it_points_at_the_route_that_was_open(self):
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/x")
        self.assertIn("REGISTER", cap.lines[0])

    def test_it_warns_against_the_compensation_r190_chose(self):
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/x")
        self.assertIn("Do NOT overwrite", cap.lines[0])


class ItSpeaksOncePerBinding(unittest.TestCase):
    def setUp(self):
        reset_said_lookup_1203nf()

    def test_a_repeat_is_silent(self):
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/a")
            _lookup_field("username", _SPINE, table="users", path="/b")
        self.assertEqual(len(cap.lines), 1)

    def test_a_different_table_speaks(self):
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/a")
            _lookup_field("username", _SPINE, table="authors", path="/b")
        self.assertEqual(len(cap.lines), 2)

    def test_a_different_param_on_the_same_table_speaks(self):
        """The latch is keyed on the BINDING, not the table: two params resolving to two
        different columns are two facts the lane needs."""
        meta = {"cols": ["id", "email", "name", "slug"]}
        with _Caught() as cap:
            _lookup_field("username", meta, table="users", path="/a")
            _lookup_field("nickname", meta, table="users", path="/b")
        self.assertEqual(len(cap.lines), 2, cap.lines)

    def test_the_reset_is_part_of_the_contract(self):
        """#762: module state must not leak between tests in one session."""
        with _Caught() as cap:
            _lookup_field("username", _SPINE, table="users", path="/a")
            reset_said_lookup_1203nf()
            _lookup_field("username", _SPINE, table="users", path="/a")
        self.assertEqual(len(cap.lines), 2)


class ItStaysQuietWhenThereIsNothingToSay(unittest.TestCase):
    def setUp(self):
        reset_said_lookup_1203nf()

    def test_a_table_that_has_the_column(self):
        with _Caught() as cap:
            got = _lookup_field("username", {"cols": ["id", "username", "name"]},
                                table="users", path="/x")
        self.assertEqual(got, "username")
        self.assertEqual(cap.lines, [])

    def test_an_id_like_param(self):
        for param in ("id", "video_id", "videoId"):
            with self.subTest(param=param):
                reset_said_lookup_1203nf()
                with _Caught() as cap:
                    got = _lookup_field(param, {"cols": ["id", "name"]},
                                        table="videos", path="/x")
                self.assertEqual(got, "id")
                self.assertEqual(cap.lines, [])
                self.assertTrue(_is_id_param(param))

    def test_a_param_that_is_its_own_column(self):
        with _Caught() as cap:
            got = _lookup_field("slug", {"cols": ["id", "slug"]}, table="posts", path="/x")
        self.assertEqual(got, "slug")
        self.assertEqual(cap.lines, [])


class TheLadderIsUntouched(unittest.TestCase):
    """The announcement must not become a second decision (#1032)."""

    _CASES = (
        ("username", {"cols": ["id", "email", "name"]}, "name"),
        ("username", {"cols": ["id", "username", "name"]}, "username"),
        ("handle", {"cols": ["id", "username"]}, "username"),
        ("slug", {"cols": ["id", "slug", "name"]}, "slug"),
        ("title", {"cols": ["id", "title"]}, "title"),
        ("code", {"cols": ["id", "code", "name"]}, "code"),
        ("whatever", {"cols": ["id", "email"]}, "email"),
        ("whatever", {"cols": ["id"]}, "id"),
        ("video_id", {"cols": ["id", "name"]}, "id"),
    )

    def test_the_wrapper_returns_what_the_ladder_decides(self):
        for param, meta, want in self._CASES:
            with self.subTest(param=param, cols=meta["cols"]):
                reset_said_lookup_1203nf()
                self.assertEqual(_lookup_field_col_1203nf(param, meta), want)
                with _Caught():
                    self.assertEqual(_lookup_field(param, meta, table="t", path="/p"), want)

    def test_a_broken_announcement_cannot_change_the_answer(self):
        """The whole point of the try: an announcement is never load-bearing."""
        from unittest import mock
        reset_said_lookup_1203nf()
        with mock.patch.object(RP, "_SAID_LOOKUP_1203NF", None):   # `in` on None raises
            self.assertEqual(_lookup_field("username", _SPINE, table="users", path="/x"),
                             "name")


class TheCallSitesPassTheTable(unittest.TestCase):
    """Without the table name the message cannot say WHERE to register the column."""

    def _calls(self):
        tree = ast.parse(inspect.getsource(RP))
        out = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_lookup_field"):
                out.append({k.arg for k in n.keywords})
        return out

    def test_both_call_sites_name_the_table_and_the_path(self):
        calls = self._calls()
        self.assertGreaterEqual(len(calls), 2, calls)
        for kw in calls:
            self.assertIn("table", kw)
            self.assertIn("path", kw)


class TheCorpusShapes(unittest.TestCase):
    def test_every_measured_shape_still_resolves_the_same_way(self):
        """The 9 corpus bindings, as their registrations hold them."""
        for cols in (["id", "email", "name", "password_hash", "tenant_id", "created_at"],
                     ["id", "email", "name", "password_hash", "tenant_id"],
                     ["id", "name", "email"]):
            with self.subTest(cols=cols):
                reset_said_lookup_1203nf()
                with _Caught() as cap:
                    self.assertEqual(
                        _lookup_field("username", {"cols": cols}, table="users",
                                      path="/api/users/{username}/follow"), "name")
                self.assertTrue(cap.lines)


if __name__ == "__main__":
    unittest.main()
