"""#74 (netflix r78, 2026-08-05) — deliver-tail database_sql_missing STALL. r78's api_smoke PASSED
(DB functional) yet the delivery gate stayed red on database_sql_missing (a pure file-existence check:
app/database/**/*.sql). The deterministic app/database/ scaffold (write_database_scaffold →
render_schema_sql) is called ONCE post-finalize_kickoff; if it never ran or a lane merge clobbered
app/database/, there is NO deliver-tail re-emit → the gate froze at 15 failed for 11min and r78 wedged.

FIX: maybe_emit_schema_sql — a deliver-tail self-heal (mirrors #489/#492/#475) that, when
database_sql_missing is failing and no .sql exists, re-emits app/database/ from the registered SchemaHub
tables using the SAME render_schema_sql the by-construction scaffold uses. Deterministic, guarded,
idempotent, never raises. These tests drive the DECISION + the .sql write hermetically (tmp_path stub
orch); the full gate-clear is validated on a run."""
import types
from pathlib import Path

import env_generator.llm_generator.multi_agent.runtime.framework_validation as fv

_FAILED = ["database_sql_missing"]


def _orch(tmp_path, tables, endpoints=None, logger=None):
    hubs = types.SimpleNamespace(
        schema_hub=types.SimpleNamespace(list_tables=lambda: tables),
        registryhub=types.SimpleNamespace(get_endpoints=lambda: (endpoints or {})),
    )
    return types.SimpleNamespace(
        output_dir=str(tmp_path), hubs=hubs,
        _logger=logger or types.SimpleNamespace(
            warning=lambda *a, **k: None, debug=lambda *a, **k: None),
    )


_TABLES = {"movies": {"columns": [{"name": "id", "type": "integer"},
                                  {"name": "title", "type": "text"}]}}


def _sql_files(tmp_path):
    return list((Path(tmp_path) / "app" / "database").glob("**/*.sql"))


def test_emits_schema_when_missing_and_check_failing(tmp_path):
    orch = _orch(tmp_path, _TABLES)
    assert fv.maybe_emit_schema_sql(orch, _FAILED) is True
    sqls = _sql_files(tmp_path)
    assert sqls, "a .sql must be written under app/database/"
    text = sqls[0].read_text()
    assert "CREATE TABLE" in text and "movies" in text, text[:200]


def test_noop_when_check_not_failing(tmp_path):
    orch = _orch(tmp_path, _TABLES)
    assert fv.maybe_emit_schema_sql(orch, ["something_else"]) is False
    assert not _sql_files(tmp_path)
    assert fv.maybe_emit_schema_sql(orch, None) is False
    assert fv.maybe_emit_schema_sql(orch, []) is False


def test_idempotent_noop_when_sql_already_present(tmp_path):
    # a .sql already exists → do NOT rewrite (returns False)
    d = Path(tmp_path) / "app" / "database"
    d.mkdir(parents=True)
    (d / "existing.sql").write_text("CREATE TABLE x();")
    orch = _orch(tmp_path, _TABLES)
    assert fv.maybe_emit_schema_sql(orch, _FAILED) is False


def test_noop_when_no_tables(tmp_path):
    # no registered contract tables → nothing deterministic to emit
    orch = _orch(tmp_path, {})
    assert fv.maybe_emit_schema_sql(orch, _FAILED) is False
    assert not _sql_files(tmp_path)


def test_never_raises_on_bad_orch():
    # bare orch (missing output_dir/hubs) and a list_tables that throws → swallow, return False
    assert fv.maybe_emit_schema_sql(types.SimpleNamespace(), _FAILED) is False

    def _boom():
        raise RuntimeError("schema hub boom")
    bad = types.SimpleNamespace(
        output_dir="/tmp/fg74-nonexistent-xyz",
        hubs=types.SimpleNamespace(schema_hub=types.SimpleNamespace(list_tables=_boom),
                                   registryhub=None),
        _logger=types.SimpleNamespace(warning=lambda *a, **k: None))
    assert fv.maybe_emit_schema_sql(bad, _FAILED) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
