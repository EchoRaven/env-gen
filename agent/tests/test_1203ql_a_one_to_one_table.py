"""#1203ql: a UNIQUE foreign key means ONE ROW PER PARENT, and nothing capped the rows.

`user_settings.user_id` ships as `integer references "users"("id") UNIQUE` -- the contract
saying one settings row per user. The row count came from #1202tz's 5..12 band, which never
consulted the parent. All 7 corpus runs that declare such a column break it, 7 of 7, over
two table shapes and two products: 24 rows written only for the loader's per-row SAVEPOINT
to drop them.

THE BOUNDARY WITH #1202ue IS THE POINT OF THIS FILE. #1202ue found
`comments.video_id = [1,2,3,4,5,6,7,8]` -- "each parent used exactly once ... a shape no real
table has" -- and skewed the FK draw to give participation a long tail. #1203ql writes
exactly that deleted shape, and must, because under a UNIQUE constraint the tail is not
unrealistic but unrepresentable. Both directions are pinned here: the UNIQUE column walks
the parents, and a NON-unique column in the identical fixture keeps #1202ue's draw
byte-for-byte. Neither rule may later be applied to the other's columns.

LOCAL-ONLY (gitignored).
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _build_seed_rows, _one_per_owner_1203ql, _unique_fk_parents_1203ql, render_seed_data)

# What #1202ue's skewed draw produces for this fixture. Pinned so a change to the UNIQUE
# path can never quietly alter the ordinary one.
UE_DRAW = [4, 5, 2, 1, 5, 1]


def _fixture(unique, col="user_id", extra=None):
    child = [{"name": "id", "type": "integer primary key", "primary_key": True},
             {"name": col, "type": "integer references users.id",
              "references": "users(id)"}]
    if unique:
        child[1] = dict(child[1], unique=True,
                        type="integer references users.id unique")
    if extra:
        child.append(extra)
    return {"users": {"schema": {"columns": [
                {"name": "id", "type": "integer primary key", "primary_key": True},
                {"name": "email", "type": "text"},
                {"name": "name", "type": "text"}]}},
            "settings": {"schema": {"columns": child}}}


def _emitted_floor(tables):
    """`_demo_floor_1203ql` out of the generated seed_data.py, plus the maps it reads.

    The function is sliced by LANDMARK (to the next top-level `def`), never by a fixed
    width -- #943, and a 1400-character window already told me a lie today."""
    import ast as _ast
    src = render_seed_data(tables)
    i = src.index("def _demo_floor_1203ql(t):")
    j = src.index("\ndef ", i + 1)
    maps = {}
    for node in _ast.parse(src).body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)
                and node.targets[0].id in ("_MEDIA_COL", "_ONE_PER_OWNER", "_DEMO_FLOOR")):
            maps[node.targets[0].id] = _ast.literal_eval(node.value)
    ns = dict(maps)
    exec(compile(src[i:j], "seed_data.py", "exec"), ns)   # noqa: S102 - the artifact itself
    return ns["_demo_floor_1203ql"], maps


def _col(seed, table, col):
    return [r.get(col) for r in (seed.get(table) or [])]


class WhichColumnsAreOnePerParent(unittest.TestCase):

    def test_a_unique_FK_is_one_per_parent_1203ql(self):
        meta = {"unique": ["user_id"], "pk": "id"}
        self.assertEqual({"user_id": "users"},
                         _unique_fk_parents_1203ql(meta, {"user_id": "users"}, {"users"}))

    def test_a_unique_column_that_is_not_an_FK_is_not_capped_1203ql(self):
        """`users.username` is UNIQUE and must not cap anything -- FIX #74 owns it."""
        meta = {"unique": ["username"], "pk": "id"}
        self.assertEqual({}, _unique_fk_parents_1203ql(meta, {}, set()))

    def test_the_primary_key_is_left_to_the_pk_path_1203ql(self):
        meta = {"unique": ["id"], "pk": "id"}
        self.assertEqual({}, _unique_fk_parents_1203ql(meta, {"id": "users"}, {"users"}))

    def test_a_non_unique_FK_is_not_one_per_parent_1203ql(self):
        meta = {"unique": [], "pk": "id"}
        self.assertEqual({}, _unique_fk_parents_1203ql(meta, {"user_id": "users"}, {"users"}))


class TheSeedRespectsIt(unittest.TestCase):

    def test_the_row_count_cannot_exceed_the_parent_1203ql(self):
        seed = _build_seed_rows(_fixture(True), env_salt="probe")[0]
        self.assertEqual(len(seed["users"]), len(seed["settings"]))

    def test_the_unique_FK_has_no_duplicates_1203ql(self):
        """The defect itself: 6 rows over 5 users with 4 distinct values."""
        vals = _col(_build_seed_rows(_fixture(True), env_salt="probe")[0],
                    "settings", "user_id")
        self.assertEqual(len(vals), len(set(vals)), "duplicate parent in a UNIQUE FK: %s" % vals)

    def test_the_unique_FK_walks_the_parents_1203ql(self):
        vals = _col(_build_seed_rows(_fixture(True), env_salt="probe")[0],
                    "settings", "user_id")
        self.assertEqual([1, 2, 3, 4, 5], vals)


class TheBoundaryWith1202ue(unittest.TestCase):
    """The same fixture, the flag the only difference."""

    def test_a_non_unique_FK_keeps_the_skewed_draw_1203ql(self):
        vals = _col(_build_seed_rows(_fixture(False), env_salt="probe")[0],
                    "settings", "user_id")
        self.assertEqual(UE_DRAW, vals, "#1202ue's draw moved")

    def test_the_two_paths_disagree_1203ql(self):
        """If these ever matched, one of the two rules stopped applying."""
        loose = _col(_build_seed_rows(_fixture(False), env_salt="probe")[0],
                     "settings", "user_id")
        tight = _col(_build_seed_rows(_fixture(True), env_salt="probe")[0],
                     "settings", "user_id")
        self.assertNotEqual(loose, tight)
        self.assertTrue(len(loose) > len(set(loose)), "control lost its repeats: %s" % loose)
        self.assertEqual(len(tight), len(set(tight)))

    def test_a_second_non_unique_FK_column_is_untouched_1203ql(self):
        """A UNIQUE column in a table must not straighten its SIBLING column."""
        t = _fixture(True, extra={"name": "actor_id",
                                  "type": "integer references users.id",
                                  "references": "users(id)"})
        seed = _build_seed_rows(t, env_salt="probe")[0]
        actor = _col(seed, "settings", "actor_id")
        walk = list(range(1, len(actor) + 1))
        self.assertNotEqual(walk, actor,
                            "the sibling FK was straightened into the walk too: %s" % actor)


class AChildOfACappedTable(unittest.TestCase):
    """`_seed_cell` draws a FK from `counts`, so the cap has to be recorded there too."""

    def test_a_child_never_references_a_row_the_cap_removed_1203ql(self):
        t = _fixture(True)
        t["notes"] = {"schema": {"columns": [
            {"name": "id", "type": "integer primary key", "primary_key": True},
            {"name": "settings_id", "type": "integer references settings.id",
             "references": "settings(id)"},
            {"name": "body", "type": "text"}]}}
        seed = _build_seed_rows(t, env_salt="probe")[0]
        have = len(seed.get("settings") or [])
        refs = [v for v in _col(seed, "notes", "settings_id") if v is not None]
        self.assertTrue(refs, "fixture produced no references to check")
        self.assertTrue(max(refs) <= have,
                        "child points past the capped parent: %s with %d rows" % (refs, have))


class TheDemoFloor(unittest.TestCase):

    def test_a_unique_owner_table_is_one_per_owner_1203ql(self):
        self.assertEqual({"settings": True},
                         _one_per_owner_1203ql(_fixture(True), {"settings": "user_id"}))

    def test_a_non_unique_owner_is_not_1203ql(self):
        self.assertEqual({}, _one_per_owner_1203ql(_fixture(False), {"settings": "user_id"}))

    def test_a_table_with_no_known_owner_is_not_1203ql(self):
        self.assertEqual({}, _one_per_owner_1203ql(_fixture(True), {}))

    def test_the_floor_is_decided_in_ONE_place_1203ql(self):
        """#1032: the expression was spelled twice, so a third exception needed two edits.

        The emitted module imports the app's own packages, so the helper is driven on its
        own, with the maps read out of the same generated source."""
        floor, maps = _emitted_floor(_fixture(True))
        self.assertEqual(1, floor("settings"), "a one-per-owner table still asks for 8")
        self.assertEqual(maps["_DEMO_FLOOR"], floor("users"))
        self.assertTrue(maps["_ONE_PER_OWNER"].get("settings"))

    def test_both_floor_sites_ask_the_helper_1203ql(self):
        """Reverting ONE site is the regression this catches -- calling the helper from
        only one place reads as fixed and is not."""
        import ast as _ast
        tree = _ast.parse(render_seed_data(_fixture(True)))
        calls = [n for n in _ast.walk(tree)
                 if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                 and n.func.id == "_demo_floor_1203ql"]
        self.assertEqual(2, len(calls),
                         "%d call site(s) ask the helper; both floors must" % len(calls))

    def test_an_ordinary_table_keeps_the_floor_of_eight_1203ql(self):
        floor, _ = _emitted_floor(_fixture(False))
        self.assertEqual(8, floor("settings"))


if __name__ == "__main__":
    unittest.main()
