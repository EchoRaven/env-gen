"""Guard: FIX #197 — the DDL renderer must reconcile FK types like the ORM does.

r7 live docker_up killer: models.py had `author_id = Column(Integer,
ForeignKey("users.id"))` (correct — render_models runs
_reconcile_fk_types_in_map, and users is the INTEGER spine) but 01_init.sql
had `"author_id" TEXT REFERENCES "users"("id")` → postgres CREATE TABLE videos
aborts on the TEXT→INTEGER FK type clash → docker_up wedges EVERY cycle (the
framework re-emits the mismatch → the lane can't fix it → 75-min wall). Root:
render_schema_sql renders raw contract columns and never reconciled FK types,
so the two renderers diverged. Apply the SAME reconciliation in the DDL path.
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


class DdlFkReconcileTests(unittest.TestCase):
    def test_spine_fk_coerced_to_integer_in_ddl(self):
        # author_id TEXT referencing the INTEGER users spine → DDL must emit
        # INTEGER (matching the ORM), not TEXT.
        tables = {"videos": _tbl("videos", [
            {"name": "id", "primary_key": True, "type": "text"},
            {"name": "author_id", "references": "users.id", "type": "text"},
        ])}
        ddl = render_schema_sql(tables)
        # the author_id line must be INTEGER, not TEXT
        line = next(l for l in ddl.splitlines() if "author_id" in l)
        self.assertIn("INTEGER", line.upper())
        self.assertNotIn("TEXT", line.upper())

    def test_app_fk_majority_reconciled(self):
        # channels.id text but every *.channel_id FK integer → coerce channels.id
        # (the youtube run#16 class) so the app FKs and the PK agree.
        tables = {
            "channels": _tbl("channels", [
                {"name": "id", "primary_key": True, "type": "text"}]),
            "videos": _tbl("videos", [
                {"name": "id", "primary_key": True, "type": "integer"},
                {"name": "channel_id", "references": "channels.id", "type": "integer"}]),
        }
        ddl = render_schema_sql(tables)
        # channels.id must be coerced to INTEGER (the FK majority) so the
        # channel_id FKs and the PK agree — youtube run#16 class.
        block = ddl.split('CREATE TABLE IF NOT EXISTS "channels"', 1)[1].split(");", 1)[0]
        id_line = next(l for l in block.splitlines() if '"id"' in l)
        # an integer PK renders as SERIAL (postgres auto-increment int) — the
        # point is it's an INTEGER family, not the original TEXT.
        self.assertTrue(any(t in id_line.upper() for t in ("INTEGER", "SERIAL", "BIGINT")))
        self.assertNotIn("TEXT", id_line.upper())

    def test_text_pk_uniform_left_alone(self):
        # a uniform text/uuid PK with text FKs must NOT be coerced (no false churn).
        tables = {
            "orgs": _tbl("orgs", [{"name": "id", "primary_key": True, "type": "text"}]),
            "teams": _tbl("teams", [
                {"name": "id", "primary_key": True, "type": "text"},
                {"name": "org_id", "references": "orgs.id", "type": "text"}]),
        }
        ddl = render_schema_sql(tables)
        block = ddl.split('CREATE TABLE IF NOT EXISTS "orgs"', 1)[1].split(");", 1)[0]
        id_line = next(l for l in block.splitlines() if '"id"' in l)
        self.assertIn("TEXT", id_line.upper())

    def test_no_tables_still_renders_spine(self):
        ddl = render_schema_sql({})
        self.assertIn("users", ddl)


if __name__ == "__main__":
    unittest.main()
