r"""#1203nd: the framework knew the running database was older than its models, and told a
reader to go fix it by hand.

`create_all` creates missing TABLES and never touches an existing one, and `01_init.sql` is
mounted at /docker-entrypoint-initdb.d, which Postgres runs ONLY on an empty volume -- with
`CREATE TABLE IF NOT EXISTS` besides. So a business table that gains a column after the stack
is up keeps its old shape, and the projected handlers SELECT a column that does not exist.

THE DETECTOR WAS ALREADY RIGHT. `schema_currency_1202fj` compares the ORM models against
`information_schema` and says:

    the running database is older than these models -- 1 modelled column(s) do not exist in
    it (videos.metadata_visibility). A projected read of any of them 500s with
    UndefinedColumn. Recreate the stack (compose down -v && up) before trusting these results.

MEASURED: 94 firings across 17 runs, 59 distinct columns, one run short 60 columns at once.
`videos.metadata_visibility` was checked against r190's own models.py -- line 62,
`metadata_visibility = Column(Text)` -- so the finding is accurate, not a flattened-metadata
artefact. Its entire remedy was that sentence, addressed to a reader. Nothing performed it.

MEANWHILE THE LANE DID IT BY HAND: 370 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
in `app/backend/custom_routes.py` across 12 runs and 3 products (googlemaps-r16 186,
tiktok-web-r190 39, netflix-local-r11 36, tiktok-web-r191 28, netflix-local-r5 28, ...), and
**248 of those columns are ones the registered table schema DECLARES**. The other 116 are
lane extensions beyond the contract and are not this ticket's business. The lane's own comment
names the cost: "Add the enriched response-shape columns before the projected nested GET
serializes Comment rows so GET /api/videos/{id}/comments cannot omit contract fields."

This tests the SHIPPED generated code, extracted from the template rather than copied, driven
against a fake Postgres connection that records the DDL it is given.
"""
import ast
import pathlib
import unittest

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

_SKEL = pathlib.Path(
    "env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py")
_FN = "_ensure_modelled_columns_1203nd"


def _template():
    tree = ast.parse(_SKEL.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _FN in n.value:
            return n.value
    raise AssertionError("the generated main.py template no longer carries %s" % _FN)


def _function_source():
    tpl = _template()
    tree = ast.parse(tpl)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == _FN:
            return ast.get_source_segment(tpl, n)
    raise AssertionError("%s is not a top-level function in the template" % _FN)


class _Conn:
    def __init__(self, live):
        self.live, self.ddl = live, []

    def execute(self, stmt):
        sql = str(stmt)
        if "information_schema" in sql:
            return _Rows([(t, c) for t, cols in self.live.items() for c in cols])
        self.ddl.append(sql)
        return _Rows([])


class _Rows(list):
    def fetchall(self):
        return list(self)


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *a):
        return False


class _Engine:
    def __init__(self, conn, name="postgresql"):
        self._conn, self.dialect = conn, postgresql.dialect()
        self.dialect.name = name

    def begin(self):
        return _Begin(self._conn)


def _models():
    md = sa.MetaData()
    sa.Table("videos", md,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("caption", sa.Text),
             sa.Column("metadata_visibility", sa.Text),
             sa.Column("save_count", sa.Integer, nullable=False, server_default="0"),
             sa.Column("sound_id", sa.Integer, sa.ForeignKey("sounds.id")),
             sa.Column("slug", sa.String(64), unique=True))
    sa.Table("sounds", md, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("never_created", md,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("x", sa.Text))
    return md


def _run(live, dialect_name="postgresql"):
    """exec the SHIPPED function with a fake engine and report (ddl, printed)."""
    conn = _Conn(live)
    printed = []
    ns = {"engine": _Engine(conn, dialect_name),
          "Base": type("B", (), {"metadata": _models()}),
          "print": lambda *a, **k: printed.append(" ".join(str(x) for x in a))}
    exec(compile(_function_source(), "<1203nd>", "exec"), ns)
    ns[_FN]()
    return conn.ddl, printed


class ItAddsOnlyWhatIsMissing(unittest.TestCase):
    def test_r190s_case(self):
        """videos exists with the old shape; metadata_visibility is the column #1202fj named."""
        ddl, _ = _run({"videos": {"id", "caption"}, "sounds": {"id"}})
        joined = " | ".join(ddl)
        self.assertIn('ALTER TABLE "videos" ADD COLUMN IF NOT EXISTS "metadata_visibility"',
                      joined)
        self.assertNotIn('"caption"', joined)
        self.assertNotIn('"id"', joined)

    def test_a_current_database_gets_no_ddl(self):
        ddl, printed = _run({"videos": {"id", "caption", "metadata_visibility", "save_count",
                                        "sound_id", "slug"},
                             "sounds": {"id"}})
        self.assertEqual(ddl, [])
        self.assertEqual(printed, [])

    def test_a_table_the_database_does_not_have_is_left_to_create_all(self):
        ddl, _ = _run({"videos": {"id", "caption", "metadata_visibility", "save_count",
                                  "sound_id", "slug"}, "sounds": {"id"}})
        self.assertFalse([d for d in ddl if "never_created" in d])

    def test_the_column_name_match_is_case_insensitive(self):
        """The live side is lowercased at ingest, so this only bites when a MODEL column
        carries uppercase -- a quoted `"createdAt"` column survives in information_schema and
        comes back folded. Without the fold on the model side the column is treated as
        missing: `ADD COLUMN IF NOT EXISTS` makes the DDL harmless, but `added` records it and
        the run announces a stale schema that is not stale. Mutation ND4 came back MISSED on
        the lowercase-only fixture, which is why this one is mixed-case on BOTH sides."""
        md = _models()
        md.tables["videos"].append_column(sa.Column("createdAt", sa.Text))
        conn = _Conn({"videos": {"id", "caption", "metadata_visibility", "save_count",
                                 "sound_id", "slug", "createdAt"}, "sounds": {"id"}})
        printed = []
        ns = {"engine": _Engine(conn), "Base": type("B", (), {"metadata": md}),
              "print": lambda *a, **k: printed.append(" ".join(str(x) for x in a))}
        exec(compile(_function_source(), "<1203nd>", "exec"), ns)
        ns[_FN]()
        self.assertEqual(conn.ddl, [], "a column that exists was treated as missing")
        self.assertEqual(printed, [], "it announced a stale schema that is not stale")

    def test_the_type_is_rendered_by_the_dialect(self):
        ddl, _ = _run({"videos": {"id"}, "sounds": {"id"}})
        caption = [d for d in ddl if '"caption"' in d][0]
        self.assertIn("TEXT", caption.upper())
        slug = [d for d in ddl if '"slug"' in d][0]
        self.assertIn("VARCHAR(64)", slug.upper())


class ItAddsPlainColumnsOnly(unittest.TestCase):
    """A table that already holds rows is the whole point, so NOT NULL / UNIQUE / a FK
    constraint would abort the DDL on exactly the databases this exists for."""

    def test_no_not_null(self):
        ddl, _ = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertFalse([d for d in ddl if "NOT NULL" in d.upper()], ddl)

    def test_no_unique(self):
        ddl, _ = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertFalse([d for d in ddl if "UNIQUE" in d.upper()], ddl)

    def test_no_foreign_key(self):
        ddl, _ = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertFalse([d for d in ddl if "REFERENCES" in d.upper()], ddl)

    def test_every_statement_is_idempotent(self):
        ddl, _ = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertTrue(ddl)
        for d in ddl:
            self.assertIn("ADD COLUMN IF NOT EXISTS", d)


class ItSaysWhatItDid(unittest.TestCase):
    """#1202fj's warning is the evidence that this run judged a stale database. A silent
    repair would delete it."""

    def test_it_announces_the_repair(self):
        """Anchored on the MESSAGE, not on a ticket tag: #1202tf forbids a framework ticket
        inside anything the delivered app emits, and it caught the first version of this
        line. The announcement is the property worth asserting."""
        _, printed = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertTrue(printed)
        self.assertIn("[schema]", printed[0])
        self.assertIn("older than these models", printed[0])

    def test_the_message_carries_no_framework_ticket(self):
        import re
        _, printed = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertFalse(re.findall(r"#\d{3,4}\w*", printed[0]), printed[0])

    def test_it_names_the_columns_and_counts_them(self):
        _, printed = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertIn("metadata_visibility", printed[0])
        self.assertIn("5 modelled column(s)", printed[0])

    def test_it_declares_a_cut_list(self):
        """#1034: a count must not sit beside a silent cut."""
        md = _models()
        extra = md.tables["videos"]
        for i in range(9):
            extra.append_column(sa.Column("x%d" % i, sa.Text))
        conn = _Conn({"videos": {"id"}, "sounds": {"id"}})
        printed = []
        ns = {"engine": _Engine(conn), "Base": type("B", (), {"metadata": md}),
              "print": lambda *a, **k: printed.append(" ".join(str(x) for x in a))}
        exec(compile(_function_source(), "<1203nd>", "exec"), ns)
        ns[_FN]()
        self.assertIn("more not shown", printed[0])

    def test_it_says_the_columns_are_unconstrained(self):
        _, printed = _run({"videos": {"id"}, "sounds": {"id"}})
        self.assertIn("NULLABLE", printed[0])


class ItNeverBlocksBoot(unittest.TestCase):
    def test_a_non_postgres_dialect_does_nothing(self):
        ddl, printed = _run({"videos": {"id"}}, dialect_name="sqlite")
        self.assertEqual((ddl, printed), ([], []))

    def test_an_unreadable_information_schema_is_swallowed(self):
        class _Boom(_Conn):
            def execute(self, stmt):
                raise RuntimeError("no database")
        conn = _Boom({})
        ns = {"engine": _Engine(conn), "Base": type("B", (), {"metadata": _models()}),
              "print": lambda *a, **k: None}
        exec(compile(_function_source(), "<1203nd>", "exec"), ns)
        ns[_FN]()                      # must not raise

    def test_one_failing_alter_does_not_stop_the_others(self):
        class _Picky(_Conn):
            def execute(self, stmt):
                sql = str(stmt)
                if '"caption"' in sql:
                    raise RuntimeError("nope")
                return super().execute(stmt)
        conn = _Picky({"videos": {"id"}, "sounds": {"id"}})
        ns = {"engine": _Engine(conn), "Base": type("B", (), {"metadata": _models()}),
              "print": lambda *a, **k: None}
        exec(compile(_function_source(), "<1203nd>", "exec"), ns)
        ns[_FN]()
        self.assertTrue([d for d in conn.ddl if "metadata_visibility" in d])


class ItRunsBeforeAnythingReadsTheSchema(unittest.TestCase):
    def test_the_boot_order(self):
        """It must land before the temporal mirrors (which read live columns) and before
        seeding (which writes the new columns)."""
        tpl = _template()
        i_new = tpl.index("_ensure_modelled_columns_1203nd()\n")
        i_tmp = tpl.index("_ensure_temporal_alias_columns()\n")
        i_seed = tpl.index("seed_if_empty()")
        i_create = tpl.index("Base.metadata.create_all(bind=engine)")
        self.assertLess(i_create, i_new)
        self.assertLess(i_new, i_tmp)
        self.assertLess(i_new, i_seed)

    def test_the_generated_module_still_parses(self):
        ast.parse(_template())


if __name__ == "__main__":
    unittest.main()
