"""Guard: FIX #199 — a type string that embeds a column constraint must not
double it in the DDL.

r9 live docker_up killer: the lane typed a PK column as ``type: "integer
primary key"`` (a full DDL fragment, not a bare type). _render_column rendered
_sql_type("integer primary key") = "integer primary key" AND THEN appended
"PRIMARY KEY" because primary_key=True → ``"id" integer primary key PRIMARY
KEY`` → postgres "multiple primary keys for table videos" → docker_up wedges.
The ORM path (render_models) already parses this correctly (Integer +
primary_key=True); only the DDL renderer doubled it. Strip an embedded
primary key / not null / unique from the type (like the existing CHECK
handling) and fold it into the constraint flags so nothing is lost or doubled.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.database_scaffold import render_schema_sql  # noqa: E402


def _tbl(name, cols):
    return {"name": name, "schema": {"columns": cols}}


def _videos_block(ddl):
    return ddl.split('CREATE TABLE IF NOT EXISTS "videos"', 1)[1].split(");", 1)[0]


class EmbeddedConstraintTests(unittest.TestCase):
    def test_integer_primary_key_type_not_doubled(self):
        tables = {"videos": _tbl("videos", [
            {"name": "id", "primary_key": True, "type": "integer primary key"},
            {"name": "caption", "type": "text"}])}
        block = _videos_block(render_schema_sql(tables))
        id_line = next(l for l in block.splitlines() if '"id"' in l)
        self.assertEqual(id_line.upper().count("PRIMARY KEY"), 1)
        # still a PK, promoted to SERIAL (int PK auto-increment)
        self.assertIn("SERIAL", id_line.upper())

    def test_type_only_pk_still_gets_constraint(self):
        # primary_key flag absent, but the TYPE says "primary key" → keep the PK
        tables = {"widgets": _tbl("widgets", [
            {"name": "id", "type": "uuid primary key"},
            {"name": "label", "type": "text"}])}
        ddl = render_schema_sql(tables)
        block = ddl.split('CREATE TABLE IF NOT EXISTS "widgets"', 1)[1].split(");", 1)[0]
        id_line = next(l for l in block.splitlines() if '"id"' in l)
        self.assertEqual(id_line.upper().count("PRIMARY KEY"), 1)

    def test_embedded_not_null_not_doubled(self):
        tables = {"videos": _tbl("videos", [
            {"name": "id", "primary_key": True, "type": "text"},
            {"name": "title", "not_null": True, "type": "text not null"}])}
        block = _videos_block(render_schema_sql(tables))
        title_line = next(l for l in block.splitlines() if '"title"' in l)
        self.assertEqual(title_line.upper().count("NOT NULL"), 1)

    def test_embedded_unique_not_doubled(self):
        tables = {"videos": _tbl("videos", [
            {"name": "id", "primary_key": True, "type": "text"},
            {"name": "slug", "unique": True, "type": "text unique"}])}
        block = _videos_block(render_schema_sql(tables))
        slug_line = next(l for l in block.splitlines() if '"slug"' in l)
        self.assertEqual(slug_line.upper().count("UNIQUE"), 1)

    def test_plain_types_unaffected(self):
        tables = {"videos": _tbl("videos", [
            {"name": "id", "primary_key": True, "type": "text"},
            {"name": "caption", "type": "text"}])}
        block = _videos_block(render_schema_sql(tables))
        self.assertEqual(block.upper().count("PRIMARY KEY"), 1)
        id_line = next(l for l in block.splitlines() if '"id"' in l)
        self.assertIn("TEXT", id_line.upper())


if __name__ == "__main__":
    unittest.main()
