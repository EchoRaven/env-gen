"""Guard: FIX #211 — CREATE TABLE statements must be emitted in FK-dependency
order (a referenced table before the table that references it).

r15 live docker_up WEDGE: the contract registered `videos` (with
`sound_id INTEGER REFERENCES sounds(id)`) BEFORE `sounds`, and render_schema_sql
emitted them in registration order → postgres init aborted with
`relation "sounds" does not exist` → docker_up failed every cycle. The lanes
CAN'T fix it (01_init.sql is auto-generated from the contract), so the run
churned to the wall guessing a wrong cause (an "api.js export" build error).
render_schema_sql must topologically sort business tables so an inline FK's
target always exists first. Env-agnostic: any contract whose table order
doesn't match its FK dependency order hits this.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.database_scaffold import (  # noqa: E402
    render_schema_sql, _topological_table_order,
)


def _tbl(name, cols):
    return {"name": name, "columns": cols}


def _order(sql, *names):
    """Return the CREATE-TABLE positions of *names* in the rendered SQL."""
    return [sql.index(f'CREATE TABLE IF NOT EXISTS "{n}"') for n in names]


class RenderOrderTests(unittest.TestCase):
    def test_referenced_table_created_first_structured_fk(self):
        # r15's exact shape: videos declared BEFORE sounds, FK videos->sounds.
        tables = {
            "videos": _tbl("videos", [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "sound_id", "type": "integer", "references": "sounds.id"},
                {"name": "author_id", "type": "integer", "references": "users.id"},
            ]),
            "sounds": _tbl("sounds", [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "title", "type": "text"},
            ]),
        }
        sql = render_schema_sql(tables)
        p_sounds, p_videos = _order(sql, "sounds", "videos")
        self.assertLess(p_sounds, p_videos, "sounds must be created before videos")

    def test_referenced_table_created_first_inline_fk(self):
        # FK written inline in the type string (the other contract shape).
        tables = {
            "posts": _tbl("posts", [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "board_id", "type": "integer references boards(id)"},
            ]),
            "boards": _tbl("boards", [
                {"name": "id", "type": "integer", "primary_key": True},
            ]),
        }
        sql = render_schema_sql(tables)
        p_boards, p_posts = _order(sql, "boards", "posts")
        self.assertLess(p_boards, p_posts)

    def test_spine_only_fk_unaffected(self):
        # a table referencing ONLY the spine (users) needs no reordering and
        # renders fine (spine is created before all business tables).
        tables = {
            "profiles": _tbl("profiles", [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "user_id", "type": "integer", "references": "users.id"},
            ]),
        }
        sql = render_schema_sql(tables)
        self.assertIn('CREATE TABLE IF NOT EXISTS "profiles"', sql)


class TopoHelperTests(unittest.TestCase):
    def _names(self, items):
        return [str(t.get("name")) for _, t in items]

    def test_reorders_dependency_before_dependent(self):
        tables = {
            "videos": _tbl("videos", [{"name": "sound_id", "type": "int",
                                       "references": "sounds.id"}]),
            "sounds": _tbl("sounds", [{"name": "id", "type": "int",
                                       "primary_key": True}]),
        }
        names = self._names(_topological_table_order(tables))
        self.assertLess(names.index("sounds"), names.index("videos"))

    def test_self_reference_no_infinite_loop(self):
        # a tree table (parent_id -> itself) must not deadlock the sort.
        tables = {
            "categories": _tbl("categories", [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "parent_id", "type": "int", "references": "categories.id"},
            ]),
        }
        names = self._names(_topological_table_order(tables))
        self.assertEqual(names, ["categories"])

    def test_cycle_degrades_to_stable_order_no_crash(self):
        # a<->b cycle: can't be fully ordered, but must not hang or drop tables.
        tables = {
            "a": _tbl("a", [{"name": "b_id", "type": "int", "references": "b.id"}]),
            "b": _tbl("b", [{"name": "a_id", "type": "int", "references": "a.id"}]),
        }
        names = self._names(_topological_table_order(tables))
        self.assertEqual(sorted(names), ["a", "b"])  # both present, no loss

    def test_independent_tables_keep_stable_order(self):
        tables = {
            "x": _tbl("x", [{"name": "id", "type": "int", "primary_key": True}]),
            "y": _tbl("y", [{"name": "id", "type": "int", "primary_key": True}]),
        }
        names = self._names(_topological_table_order(tables))
        self.assertEqual(names, ["x", "y"])


if __name__ == "__main__":
    unittest.main()
