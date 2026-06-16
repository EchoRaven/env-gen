"""Unit tests for the deterministic database scaffold (B1).

The compose file (orchestrator._generate_docker) unconditionally declares
a ``database`` service with ``build: ../app/database``, and the delivery
gate requires ``app/database/*.sql`` to exist. No LLM lane reliably writes
that directory, so across ~10 smoke runs ``app/database/Dockerfile`` was
generated 0/10 times and every ``docker_up`` failed on the missing build
context.

This module is the runtime's deterministic answer: ``app/database/`` is a
pure projection of the registered SchemaHub tables (which the kickoff
validator guarantees carry a non-empty ``columns: [{name, type}]`` list).
The runtime is the SOLE owner of ``app/database/`` — closed-by-construction,
zero LLM variance, always matching the kickoff contract.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import unittest
from pathlib import Path

# Same sys.path bootstrap as test_dockerfile_lint.py
ROOT = Path(__file__).resolve().parents[4]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.database_scaffold import (  # noqa: E402
    render_schema_sql,
    write_database_scaffold,
)


def _table(name, columns, **extra):
    """Build a table in the exact shape SchemaHub.list_tables() returns:
    the contract table minus ``name`` is stored verbatim under ``schema``."""
    schema = {"columns": columns, **extra}
    return {"id": name, "name": name, "status": "implemented", "schema": schema}


class RenderSchemaSqlTests(unittest.TestCase):
    def test_renders_create_table_per_table_with_mapped_types(self):
        tables = {
            "widgets": _table("widgets", [
                {"name": "id", "type": "integer"},
                {"name": "email", "type": "string"},
            ]),
        }
        sql = render_schema_sql(tables)
        self.assertIn('CREATE TABLE IF NOT EXISTS "widgets" (', sql)
        self.assertIn('"id" INTEGER', sql)
        self.assertIn('"email" TEXT', sql)
        self.assertIn(");", sql)

    def test_abstract_types_map_to_postgres(self):
        cols = [
            {"name": "a", "type": "boolean"},
            {"name": "b", "type": "uuid"},
            {"name": "c", "type": "timestamp"},
            {"name": "d", "type": "json"},
            {"name": "e", "type": "float"},
            {"name": "f", "type": "bigint"},
        ]
        sql = render_schema_sql({"t": _table("t", cols)})
        self.assertIn('"a" BOOLEAN', sql)
        self.assertIn('"b" UUID', sql)
        self.assertIn('"c" TIMESTAMPTZ', sql)
        self.assertIn('"d" JSONB', sql)
        self.assertIn('"e" DOUBLE PRECISION', sql)
        self.assertIn('"f" BIGINT', sql)

    def test_unknown_type_passes_through_verbatim(self):
        # Charter §8: no silent substitution. A type that isn't a known
        # abstract alias is trusted as a literal SQL type — postgres
        # rejects genuine garbage at build time (surfaced by the verifier),
        # we never swap in a default.
        cols = [
            {"name": "a", "type": "VARCHAR(255)"},
            {"name": "b", "type": "geometry"},
        ]
        sql = render_schema_sql({"t": _table("t", cols)})
        self.assertIn('"a" VARCHAR(255)', sql)
        self.assertIn('"b" geometry', sql)

    def test_explicit_constraints_are_honored(self):
        cols = [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "email", "type": "string", "unique": True, "nullable": False},
            {"name": "created_at", "type": "timestamp", "default": "now()"},
        ]
        sql = render_schema_sql({"t": _table("t", cols)})
        self.assertIn('"id" INTEGER PRIMARY KEY', sql)
        self.assertIn('"email" TEXT NOT NULL UNIQUE', sql)
        self.assertIn('"created_at" TIMESTAMPTZ DEFAULT now()', sql)

    def test_columns_without_explicit_constraints_emit_just_name_and_type(self):
        sql = render_schema_sql({"t": _table("t", [{"name": "id", "type": "integer"}])})
        # No invented PRIMARY KEY / NOT NULL on a bare business column (the spine
        # legitimately has its own PRIMARY KEY/NOT NULL, so scope to the quoted col).
        self.assertIn('"id" INTEGER', sql)
        self.assertNotIn('"id" INTEGER PRIMARY KEY', sql)
        self.assertNotIn('"id" INTEGER NOT NULL', sql)

    def test_always_includes_tenancy_identity_spine(self):
        # Forgingground tenancy model (deterministic, closed-by-construction): the
        # env owns a tenants table + a users identity table (the env IS the
        # embedded OAuth2 AS, zoom-style: users carries password_hash) + the
        # embedded OAuth AS tables — never LLM-authored. Always present even with
        # no contract. JWT sub == str(users.id); login scoped by (email, tenant_id).
        sql = render_schema_sql({})
        self.assertIn('CREATE TABLE IF NOT EXISTS tenants', sql)
        self.assertIn("INSERT INTO tenants (id, name) VALUES ('default', 'Default Tenant')", sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS users', sql)
        self.assertIn('password_hash TEXT NOT NULL', sql)   # embedded-AS: env owns credentials
        self.assertIn('UNIQUE (email, tenant_id)', sql)
        self.assertIn('oauth_clients', sql)
        self.assertIn('oauth_authorization_codes', sql)
        self.assertIn('code_challenge_method', sql)         # PKCE S256 column the AS reads/writes

    def test_contract_users_tenants_tables_are_skipped_spine_owns_them(self):
        # If the kickoff contract declares users/tenants, the spine owns them —
        # skip the contract version to avoid a duplicate/conflicting definition.
        tables = {
            "users": _table("users", [{"name": "id", "type": "integer"}, {"name": "password", "type": "text"}]),
            "posts": _table("posts", [{"name": "id", "type": "integer"}, {"name": "user_id", "type": "integer references users(id)"}]),
        }
        sql = render_schema_sql(tables)
        # exactly one users table (the spine's), with the embedded-AS password_hash
        # column — NOT the contract's free-form "password" column.
        self.assertEqual(sql.count('CREATE TABLE IF NOT EXISTS "users"'), 0)  # contract users skipped
        self.assertEqual(sql.count('CREATE TABLE IF NOT EXISTS users'), 1)    # spine users
        self.assertNotIn('"password"', sql)                                    # contract col never rendered
        self.assertIn('password_hash TEXT NOT NULL', sql)                      # spine credential col
        self.assertIn('CREATE TABLE IF NOT EXISTS "posts"', sql)               # business table kept

    def test_multiple_tables_all_rendered(self):
        tables = {
            "widgets": _table("widgets", [{"name": "id", "type": "integer"}]),
            "posts": _table("posts", [{"name": "id", "type": "integer"}]),
        }
        sql = render_schema_sql(tables)
        self.assertIn('CREATE TABLE IF NOT EXISTS "widgets"', sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS "posts"', sql)

    def test_empty_tables_yields_spine_only_sql(self):
        # Empty contract → the tenancy/identity spine, no business tables.
        sql = render_schema_sql({})
        self.assertIn("CREATE TABLE IF NOT EXISTS tenants", sql)   # spine present
        self.assertNotIn("CREATE TABLE IF NOT EXISTS \"", sql)     # no quoted business tables
        self.assertTrue(sql.strip().startswith("--"))

    def test_raises_on_table_with_no_columns(self):
        with self.assertRaises(ValueError):
            render_schema_sql({"t": _table("t", [])})

    def test_raises_on_column_missing_name_or_type(self):
        with self.assertRaises(ValueError):
            render_schema_sql({"t": _table("t", [{"type": "integer"}])})
        with self.assertRaises(ValueError):
            render_schema_sql({"t": _table("t", [{"name": "x"}])})

    def test_normalizes_dotted_inline_fk_to_parenthesized(self):
        # Postgres inline FK is `REFERENCES table (col)`. Kickoff contracts
        # routinely cram the whole column def into `type` as
        # `bigint references users.id` — which postgres parses as
        # schema=users/table=id → "schema users does not exist", init fails,
        # the db container exits(3). Confirmed via manual docker. Normalize
        # the unambiguous dotted form to the valid parenthesized form.
        cols = [{"name": "author_id", "type": "bigint references users.id not null"}]
        sql = render_schema_sql({"posts": _table("posts", cols)})
        self.assertIn('references users(id)', sql)
        self.assertNotIn('references users.id', sql)

    def test_leaves_correct_fk_syntax_untouched(self):
        cols = [{"name": "author_id", "type": "bigint references users(id)"}]
        sql = render_schema_sql({"posts": _table("posts", cols)})
        self.assertIn('references users(id)', sql)
        self.assertEqual(sql.count('references users(id)'), 1)  # no double-wrap

    def test_normalizes_quoted_dotted_fk(self):
        cols = [{"name": "author_id", "type": 'bigint references "users"."id"'}]
        sql = render_schema_sql({"posts": _table("posts", cols)})
        self.assertIn('references "users"("id")', sql)


class SpineTableRecordsDriftTests(unittest.TestCase):
    """The SPINE_TABLE_RECORDS manifest (registered into RegistryHub/SchemaHub) must
    never silently diverge from the DDL the embedded AS actually reads/writes.
    Consistency-by-construction: one drift gate, both sides locked."""

    def test_manifest_table_names_match_spine_owned_set(self):
        from multi_agent.runtime.database_scaffold import (
            SPINE_TABLE_RECORDS, _SPINE_OWNED_TABLES,
        )
        names = {t["name"] for t in SPINE_TABLE_RECORDS}
        self.assertEqual(names, set(_SPINE_OWNED_TABLES))

    def test_every_manifest_column_appears_in_the_ddl(self):
        # Each registered column name must exist in the rendered spine DDL —
        # otherwise the contract advertises a column the AS can't read.
        from multi_agent.runtime.database_scaffold import SPINE_TABLE_RECORDS
        sql = render_schema_sql({})
        for table in SPINE_TABLE_RECORDS:
            for col in table["columns"]:
                self.assertIn(
                    col["name"], sql,
                    f"spine column {table['name']}.{col['name']} missing from DDL",
                )

    def test_records_are_register_table_shaped(self):
        from multi_agent.runtime.database_scaffold import SPINE_TABLE_RECORDS
        for t in SPINE_TABLE_RECORDS:
            self.assertIn("name", t)
            self.assertTrue(t["columns"])
            for c in t["columns"]:
                self.assertIn("name", c)
                self.assertIn("type", c)


class WriteDatabaseScaffoldTests(unittest.TestCase):
    def test_writes_init_sql_under_output_dir_no_dockerfile(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            tables = {"widgets": _table("widgets", [{"name": "id", "type": "integer"}])}
            result = write_database_scaffold(out, tables)

            sql = out / "app" / "database" / "init" / "01_init.sql"
            self.assertTrue(sql.is_file())
            # stock postgres image + init mount → NO custom db Dockerfile
            self.assertFalse((out / "app" / "database" / "Dockerfile").exists())
            self.assertNotIn("dockerfile", result)
            self.assertEqual(result["table_count"], 1)
            self.assertEqual(Path(result["schema_sql"]), sql)
            self.assertIn('CREATE TABLE IF NOT EXISTS "widgets"', sql.read_text())

    def test_idempotent_rewrite(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            tables = {"widgets": _table("widgets", [{"name": "id", "type": "integer"}])}
            write_database_scaffold(out, tables)
            # Second call must not raise on existing dirs.
            write_database_scaffold(out, tables)
            sql = out / "app" / "database" / "init" / "01_init.sql"
            self.assertEqual(sql.read_text().count('CREATE TABLE IF NOT EXISTS "widgets"'), 1)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _FakeSchemaHub:
    def __init__(self, tables):
        self._tables = tables

    def list_tables(self):
        return dict(self._tables)


class _FakeHubs:
    def __init__(self, tables):
        self.schema_hub = _FakeSchemaHub(tables)


class _StubOrchestrator:
    """Minimal bind target for the unbound ``_generate_database`` coroutine
    — avoids booting the full Orchestrator (mirrors
    test_orchestrator_stall_escalation._StubOrchestrator)."""

    def __init__(self, output_dir, tables):
        self.output_dir = Path(output_dir)
        self.hubs = _FakeHubs(tables)
        self._logger = logging.getLogger("stub_orchestrator_db")


def _generate_database_method():
    from multi_agent.orchestrator import Orchestrator
    return Orchestrator._generate_database


class GenerateDatabaseWiringTests(unittest.TestCase):
    def test_reads_schemahub_tables_and_writes_scaffold(self):
        with tempfile.TemporaryDirectory() as td:
            tables = {"widgets": _table("widgets", [{"name": "id", "type": "integer"}])}
            stub = _StubOrchestrator(td, tables)
            _run(_generate_database_method()(stub))

            sql = Path(td) / "app" / "database" / "init" / "01_init.sql"
            self.assertTrue(sql.is_file())
            self.assertIn('CREATE TABLE IF NOT EXISTS "widgets"', sql.read_text())

    def test_no_tables_still_authors_init_sql(self):
        # Defensive: even with an empty SchemaHub, app/database/init/01_init.sql
        # must exist so the stock-postgres init mount has something to run.
        with tempfile.TemporaryDirectory() as td:
            stub = _StubOrchestrator(td, {})
            _run(_generate_database_method()(stub))
            self.assertTrue(
                (Path(td) / "app" / "database" / "init" / "01_init.sql").is_file()
            )


if __name__ == "__main__":
    unittest.main()
