"""#1095 — a provisioned join table retypes its parent's PRIMARY KEY, and every by-id call 500s.

Found by probing, not by reading: rendering 20 real contracts and exercising their endpoints
against a live postgres, run51's `POST /api/posts/{id}/like` and `/comment` returned 500 —

    psycopg.errors.UndefinedFunction: operator does not exist: text = integer
    WHERE posts.id = $1::INTEGER

The chain, reproduced through `write_backend_skeleton` itself:

  1. run51's contract declares `posts.id` as `serial primary key` → Integer.
  2. `interaction_tables_to_provision` (#196) adds a `likes` join table for the like/comment
     action endpoints, and types its FK from the parent: `_pk_type_of(tbl_lower[p_table])`.
  3. `_pk_type_of` reads ONLY `table["schema"]["columns"]`. Handed a table record in the
     FLATTENED `{"columns": [...]}` shape it finds nothing and returns its `"text"` default —
     for every table, including `integer + primary_key=True`. The sibling accessor
     `_columns_of` exists precisely for this and is already imported and used twice in this
     module; `_pk_type_of` is the one place that hand-rolls the lookup.
  4. So `likes.post_id` is declared `text`, and `render_models`' FK-type reconciliation makes
     the REFERENCED pk match: `posts.id` flips Integer -> `Column(Text, default=uuid)`.
  5. `route_projector` types the `{id}` path param from the CONTRACT (serial → `int`), so the
     handler binds an INTEGER against a TEXT column. 500 on every by-id read and write of the
     app's central resource. (`users.id` is typed `text` by the same bug but survives: the
     spine pins users/tenants PK categories, so the reconciler skips it.)

Scale: 1 of the 68 corpus contracts flips a PK this way — but the affected resource is
`posts` in an Instagram clone, and the failure is a hard 500 on every by-id endpoint, which
is #1022's class ("the FK type does not match the PK it references"), a shape this project
already treats as must-fix.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _pk_type_of, interaction_tables_to_provision, render_models)

_FLAT = {"columns": [{"name": "id", "type": "serial primary key"},
                     {"name": "caption", "type": "text"}]}
_NESTED = {"schema": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]}}
_TEXT_PK = {"columns": [{"name": "id", "type": "text", "primary_key": True}]}


class ThePkTypeIsReadFromEitherShape(unittest.TestCase):

    def test_the_flattened_shape_is_no_longer_read_as_text(self):
        self.assertNotEqual(_pk_type_of(_FLAT), "text",
                            "a serial PK still reads as text — every provisioned FK will be wrong")
        self.assertIn("serial", _pk_type_of(_FLAT).lower())

    def test_an_integer_pk_in_the_flattened_shape(self):
        flat_int = {"columns": [{"name": "id", "type": "integer", "primary_key": True}]}
        self.assertEqual(_pk_type_of(flat_int), "integer")

    def test_the_canonical_nested_shape_is_unchanged(self):
        self.assertEqual(_pk_type_of(_NESTED), "integer")

    def test_a_real_text_pk_still_reads_text(self):
        self.assertEqual(_pk_type_of(_TEXT_PK), "text")

    def test_no_pk_column_still_defaults_to_text(self):
        self.assertEqual(_pk_type_of({"columns": [{"name": "title", "type": "text"}]}), "text")
        self.assertEqual(_pk_type_of({}), "text")


def _pk_column_line(tables, cls):
    src = render_models(tables)
    m = re.search(r"class %s\(Base\):.*?\n\n" % cls, src, re.S)
    body = m.group(0) if m else ""
    return next((l.strip() for l in body.splitlines() if l.strip().startswith("id =")), "")


class TheParentsPkSurvivesProvisioning(unittest.TestCase):
    """run51's shape, end to end through the provisioning the framework actually does."""

    def _tables(self):
        return {
            "posts": {"columns": [{"name": "id", "type": "serial primary key"},
                                  {"name": "user_id", "type": "integer"},
                                  {"name": "caption", "type": "text"}]},
        }

    def _eps(self):
        return [{"method": "POST", "path": "/api/posts/{id}/like"},
                {"method": "POST", "path": "/api/posts/{id}/comment"},
                {"method": "GET", "path": "/api/posts/{id}"}]

    def test_the_provisioned_fk_matches_the_parent_pk(self):
        prov = interaction_tables_to_provision(self._eps(), self._tables()) or []
        self.assertTrue(prov, "no join table was provisioned — the fixture stopped exercising #196")
        fks = [c for s in prov for c in (s.get("schema") or s).get("columns", [])
               if str(c.get("references") or "").startswith("posts.")]
        self.assertTrue(fks, "no FK to posts in the provisioned table(s)")
        for c in fks:
            self.assertNotEqual(str(c.get("type")).lower(), "text",
                                f"provisioned FK {c.get('name')} is text against an integer PK")

    def test_the_parent_pk_does_not_flip_to_text(self):
        """The property that matters: after provisioning, posts.id is still an Integer PK.

        (An earlier version compared the rendered line before vs after. Rendering the contract
        ALONE does not emit a `class Post` this regex matches, so `before` was the empty
        string and the comparison failed for a fixture reason rather than a real one — the
        same "suspect your own call first" lesson this session keeps re-learning.)"""
        tables = self._tables()
        after_tables = dict(tables)
        for s in (interaction_tables_to_provision(self._eps(), tables) or []):
            after_tables.setdefault(s["name"], s)
        after = _pk_column_line(after_tables, "Post")
        self.assertTrue(after, "no Post model was rendered")
        self.assertIn("Integer", after,
                      f"provisioning retyped the parent PK ({after}) — by-id handlers will 500")
        self.assertNotIn("Text", after)


if __name__ == "__main__":
    unittest.main()
