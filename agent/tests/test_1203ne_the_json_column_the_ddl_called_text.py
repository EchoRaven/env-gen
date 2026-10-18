r"""#1203ne: `Column(JSON)` in models.py became `"user" TEXT` in the DDL.

THE TWO RENDERERS DISAGREED, which is the #393/#403 family. The spec-derived path maps it
correctly -- `_TYPE_ALIASES["json"] == "JSONB"` -- but the ORM-introspected path
(`introspect_orm_schema` -> `_ddl_type_from_introspect` -> `_ddl_base_type`) had no JSON
branch, so JSON fell through to `text`. That path is the one that wins whenever models.py
exists, so the DDL shipped TEXT while the ORM kept JSON.

WHAT THAT COSTS: Postgres JSON operators (`->`, `->>`, `jsonb_build_object`) do not work on a
text column, and a raw-SQL read returns the serialized STRING instead of an object.

MEASURED by comparing every delivered `models.py` against its `01_init.sql`: 27 columns in 11
runs disagree on type, and 16 of them -- in 7 runs -- are exactly JSON vs TEXT. It is live:

    2026-10-16  tiktok-web-r191   comments.user, comments.video
    2026-10-11  tiktok-web-r180   comments.author, comments.viewer_state, comments.replies_preview
    2026-10-11  tiktok-web-r181   conversations.participant_user_ids
    2026-10-09  tiktok-web-r170   videos.author, videos.sound, comments.author, comments.replies
    ... r164, r157, r126

r191's registration says `{"name": "user", "type": "json"}`, its models.py says
`user = Column(JSON)`, and its `01_init.sql` says `"user" TEXT` -- rendered 13 minutes AFTER
the registration was last updated, and a fresh `render_schema_sql` over that same
registration produces `"user" JSONB`. So this was not a stale artefact: of the 15 tables and
every column, those two were the only real difference.

Its lane found it and patched the schema from inside a request handler:
`ALTER TABLE comments ALTER COLUMN "user" TYPE JSONB USING NULLIF("user"::text, '')::jsonb`,
commented "Normalize pre-existing validation DB columns to JSONB so projected SQLAlchemy JSON
serialization returns objects, not JSON strings."

ONLY JSON IS ADDED (#647). Across 101 runs' models.py the types `_ddl_base_type` sends to
`text` are JSON, String and Text -- there is no ARRAY, LargeBinary, Time or Enum column
anywhere in the corpus, so the other unmapped types are measured-absent, not forgotten.

REMAINING GAP, said out loud: an already-created table keeps its TEXT column, because
`CREATE TABLE IF NOT EXISTS` skips it and #1203nd's boot migration only ADDS missing columns.
Changing a live column's type needs the `USING` clause the lane hand-wrote, and that is not
this ticket.
"""
import pathlib
import tempfile
import unittest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _TYPE_ALIASES,
    _ddl_base_type,
    _ddl_type_from_introspect,
    _sql_type,
    introspect_orm_schema,
    render_schema_sql,
)


class TheJsonColumnIsJsonb(unittest.TestCase):
    def test_json_and_jsonb(self):
        self.assertEqual(_ddl_base_type("JSON"), "jsonb")
        self.assertEqual(_ddl_base_type("JSONB"), "jsonb")

    def test_the_introspected_column(self):
        self.assertEqual(_ddl_type_from_introspect({"name": "user", "type": "JSON"}), "jsonb")

    def test_a_json_primary_key_keeps_its_clause(self):
        """#1202's Bug 1 in this function: a non-integer PK must not lose `primary key`."""
        self.assertEqual(_ddl_type_from_introspect({"name": "k", "type": "JSON", "pk": True}),
                         "jsonb primary key")

    def test_an_fk_to_a_json_pk_inherits_the_type(self):
        got = _ddl_type_from_introspect({"name": "blob_id", "type": "INTEGER",
                                         "fk": "blobs.id"}, {"blobs": "jsonb"})
        self.assertTrue(got.startswith("jsonb references"), got)


class TheOtherTypesAreUntouched(unittest.TestCase):
    _CASES = (("INTEGER", "integer"), ("BIGINT", "integer"), ("SMALLINT", "integer"),
              ("BOOLEAN", "boolean"), ("DATETIME", "timestamptz"), ("DATE", "timestamptz"),
              ("FLOAT", "numeric"), ("NUMERIC", "numeric"), ("REAL", "numeric"),
              ("UUID", "uuid"), ("TEXT", "text"), ("VARCHAR(64)", "text"), ("", "text"))

    def test_every_other_mapping(self):
        for raw, want in self._CASES:
            with self.subTest(type=raw):
                self.assertEqual(_ddl_base_type(raw), want)

    def test_json_does_not_capture_an_integer(self):
        """`"JSON" in t_upper` must not fire on anything else -- no corpus type contains it,
        and the INT branch still runs first."""
        self.assertEqual(_ddl_base_type("INTEGER"), "integer")


class TheTwoRenderersAgree(unittest.TestCase):
    """#403's standard: the spec-derived and ORM-derived renderers must not diverge on a type.
    That ticket said it for `money`; this is the same assertion for `json`."""

    def test_json(self):
        self.assertEqual(_sql_type("json").upper(), _ddl_base_type("JSON").upper())

    def test_every_alias_the_orm_path_also_sees(self):
        for spec, sql in sorted(_TYPE_ALIASES.items()):
            if spec in ("serial", "bigserial", "money", "smallint", "bigint", "long",
                        "decimal", "real", "double", "number", "float", "time",
                        "date", "timestamp", "str", "string"):
                continue          # width/alias choices the two paths deliberately differ on
            with self.subTest(spec=spec):
                got = _ddl_base_type(sql.upper()).upper()
                self.assertIn(got.split("(")[0], sql.upper(),
                              "%s: spec path says %s, ORM path says %s" % (spec, sql, got))


class EndToEndThroughARealModelsFile(unittest.TestCase):
    """The positive case: a real models.py, introspected by the real subprocess, rendered by
    the real DDL writer. Asserting the mapper alone would not prove the DDL changed."""

    _MODELS = (
        "from sqlalchemy import Column, Integer, Text, JSON\n"
        "from sqlalchemy.orm import declarative_base\n"
        "Base = declarative_base()\n"
        "class Comment(Base):\n"
        "    __tablename__ = 'comments'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    text = Column(Text)\n"
        "    user = Column(JSON)\n"
        "    video = Column(JSON)\n")

    def _ddl(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "models.py").write_text(self._MODELS, encoding="utf-8")
            tables = introspect_orm_schema(d)
            self.assertIsNotNone(tables, "the ORM introspection subprocess failed")
            return render_schema_sql(tables), tables

    def test_the_rendered_ddl_says_jsonb(self):
        ddl, _ = self._ddl()
        self.assertIn("JSONB", ddl.upper())
        for col in ('"user"', '"video"'):
            line = [l for l in ddl.splitlines() if col in l][0]
            self.assertIn("JSONB", line.upper(), line)

    def test_the_text_column_is_still_text(self):
        ddl, _ = self._ddl()
        line = [l for l in ddl.splitlines() if '"text"' in l][0]
        self.assertIn("TEXT", line.upper())
        self.assertNotIn("JSONB", line.upper())

    def test_the_introspection_itself_carries_the_type(self):
        _, tables = self._ddl()
        cols = {c["name"]: c["type"] for c in tables["comments"]["schema"]["columns"]}
        self.assertEqual(cols["user"], "jsonb")
        self.assertEqual(cols["video"], "jsonb")
        self.assertEqual(cols["text"], "text")


class TheCorpusCaseIsFixed(unittest.TestCase):
    def test_r191s_two_columns(self):
        """Driven on the shape r191's registration actually holds."""
        tables = {"comments": {"name": "comments", "schema": {"columns": [
            {"name": "id", "type": "integer primary_key"},
            {"name": "username", "type": "string"},
            {"name": "user", "type": "json"},
            {"name": "video", "type": "json"}]}}}
        ddl = render_schema_sql(tables)
        for col in ('"user"', '"video"'):
            line = [l for l in ddl.splitlines() if col in l][0]
            self.assertIn("JSONB", line.upper(), line)


if __name__ == "__main__":
    unittest.main()


# ★ DECLARED NULL MUTATION (#1203jr), predicted in the spec before it ran: moving the JSON
# branch below the DATE/TIME test comes back MISSED, because no type string matches both --
# `JSON` contains neither `DATE` nor `TIME`, and `INT`/`BOOL` run earlier and are disjoint too.
# The ordering carries no behaviour, so no test is added for it. The 5 mutations that DO carry
# behaviour (removing the branch, `json` instead of `jsonb`, an exact-match comparison, an
# override in the introspect path, and text-renders-as-jsonb) are all CAUGHT.
