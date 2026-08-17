"""#517 (netflix r89, 2026-08-06) — composite PRIMARY KEY for junction tables.

GROUND TRUTH: r89 WEDGED in the deliver-tail. The framework-authored 01_init.sql emitted a junction
table with a per-column PK on BOTH FK columns:
    CREATE TABLE title_genres ("title_id" SERIAL PRIMARY KEY REFERENCES ...,
                               "genre_id" SERIAL PRIMARY KEY REFERENCES ...);
→ postgres: "multiple primary keys for table not allowed" → initdb exit(3) → the DB never boots →
docker_up hangs → delivery wedged. FIX #517: when >=2 columns are flagged PRIMARY KEY, render them
WITHOUT a per-column PK (and without SERIAL promotion — a composite-PK FK column stays a plain int
FK) and emit ONE table-level `PRIMARY KEY (a, b)`. If one PK-flagged column is 'id', treat 'id' as
the sole PK and demote the mis-marked others to plain FK columns. Generalizes to every M:N join
table; no product literals.

These tests lock: the junction composite PK (exactly one PRIMARY KEY, no SERIAL, NOT NULL cols);
the single-PK path unchanged (id → SERIAL PRIMARY KEY); the id+mis-marked-FK demotion; _col_is_pk."""
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    render_schema_sql, _col_is_pk)


def _table_ddl(sql: str, table: str) -> str:
    i = sql.index(f'"{table}"')
    return sql[i:sql.index(");", i)]


def test_junction_composite_pk_valid():
    tables = {
        "titles": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
        "genres": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
        "title_genres": {"columns": [
            {"name": "title_id", "type": "integer", "primary_key": True, "references": "titles.id"},
            {"name": "genre_id", "type": "integer", "primary_key": True, "references": "genres.id"},
        ]},
    }
    tg = _table_ddl(render_schema_sql(tables), "title_genres")
    assert tg.count("PRIMARY KEY") == 1, tg              # exactly one PK (the composite), not two
    assert "PRIMARY KEY (" in tg                          # table-level composite constraint
    assert "SERIAL" not in tg                             # FK cols stay plain int (no auto-increment)
    assert "NOT NULL" in tg                               # composite-PK cols implicitly NOT NULL


def test_single_pk_unchanged():
    tables = {"users2": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}]}}
    u = _table_ddl(render_schema_sql(tables), "users2")
    assert u.count("PRIMARY KEY") == 1
    assert "SERIAL PRIMARY KEY" in u                      # single int PK still promoted to SERIAL


def test_id_plus_mismarked_fks_demoted():
    tables = {"xref": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "title_id", "type": "integer", "primary_key": True, "references": "titles.id"},
        {"name": "genre_id", "type": "integer", "primary_key": True, "references": "genres.id"}]}}
    x = _table_ddl(render_schema_sql(tables), "xref")
    assert x.count("PRIMARY KEY") == 1                    # only id's PK
    assert "SERIAL PRIMARY KEY" in x                      # id stays the sole promoted PK
    assert "PRIMARY KEY (" not in x                       # no composite — id is the sole PK


def test_col_is_pk():
    assert _col_is_pk({"name": "a", "type": "int", "primary_key": True})
    assert _col_is_pk({"name": "a", "type": "integer primary key"})
    assert _col_is_pk({"name": "a", "type": "int", "pk": True})
    assert not _col_is_pk({"name": "a", "type": "integer"})


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
