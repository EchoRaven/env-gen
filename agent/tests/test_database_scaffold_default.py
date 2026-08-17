"""Framework DDL projection must not emit a duplicate DEFAULT (netflix docker_up killer).

A counter column (view_count/likes_count…) gets a forced `default: 0` by _counter_default,
and a column may ALSO carry a default in its type string ("integer default 0"). Before the
fix, both were emitted → `"view_count" INTEGER DEFAULT 0 DEFAULT 0` → postgres "multiple
default values specified" → db init fails → docker_up wedge on every validation cycle.
"""
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import _render_column

def test_embedded_default_plus_flag_not_doubled():
    out = _render_column("titles", {"name": "view_count", "type": "INTEGER DEFAULT 0", "default": 0})
    assert out.upper().count("DEFAULT") == 1 and "DEFAULT 0" in out.upper()

def test_type_only_default_preserved():
    out = _render_column("t", {"name": "c", "type": "integer default 5"})
    assert out.upper().count("DEFAULT") == 1 and "DEFAULT 5" in out.upper()

def test_quoted_empty_string_default():
    out = _render_column("t", {"name": "s", "type": "text default ''"})
    assert out.count("DEFAULT") == 1 and "DEFAULT ''" in out

def test_plain_default_flag_unaffected():
    out = _render_column("t", {"name": "n", "type": "integer", "default": 0})
    assert out.upper().count("DEFAULT") == 1

def test_no_default_no_clause():
    assert "DEFAULT" not in _render_column("t", {"name": "p", "type": "text"}).upper()

def test_counter_default_still_applied():
    # _counter_default forces 0 for a counter col with no default and no embedded one
    out = _render_column("t", {"name": "like_count", "type": "integer"})
    assert out.upper().count("DEFAULT") == 1

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))


# ---- #378: ORM/underscore shorthand type strings normalize to valid SQL ----
def test_primary_key_underscore_shorthand():
    out = _render_column("profiles", {"name": "id", "type": "int primary_key"})
    assert "PRIMARY KEY" in out.upper() and "PRIMARY_KEY" not in out.upper()
    assert out.strip().startswith('"id" SERIAL')  # bare int PK -> SERIAL

def test_fk_shorthand_becomes_references():
    out = _render_column("my_list", {"name": "title_id", "type": "int fk titles.id"})
    assert "REFERENCES" in out.upper() and " fk " not in out.lower()
    assert '"titles"' in out and '"id"' in out

def test_not_null_underscore_shorthand():
    out = _render_column("t", {"name": "n", "type": "text not_null"})
    assert "NOT NULL" in out.upper() and "NOT_NULL" not in out.upper()

def test_space_and_structured_forms_unregressed():
    assert "PRIMARY KEY" in _render_column("t", {"name": "id", "type": "integer primary key"}).upper()
    assert "PRIMARY KEY" in _render_column("t", {"name": "id", "type": "int", "primary_key": True}).upper()
    assert "REFERENCES" in _render_column("t", {"name": "u", "type": "int", "fk": "users.id"}).upper()


# ---- #382: "PK" abbreviation shorthand normalizes to PRIMARY KEY ----
def test_pk_abbreviation():
    out = _render_column("t", {"name": "id", "type": "Integer PK"})
    assert "PRIMARY KEY" in out.upper() and out.strip().startswith('"id" SERIAL')

def test_pk_lowercase_abbrev():
    assert "PRIMARY KEY" in _render_column("t", {"name": "id", "type": "int pk"}).upper()

def test_pk_no_false_positive():
    # a plain type with no standalone 'pk' token must NOT become a PK
    assert "PRIMARY KEY" not in _render_column("t", {"name": "n", "type": "integer"}).upper()


# ---- #383: base type re-aliased AFTER constraint strip (generic type + modifier) ----
def test_string_with_not_null_realiased():
    out = _render_column("t", {"name": "name", "type": "string NOT NULL"})
    assert out.strip().upper().startswith('"NAME" TEXT') and "NOT NULL" in out.upper() and "STRING" not in out.upper()

def test_str_unique_realiased():
    out = _render_column("t", {"name": "e", "type": "str unique"})
    assert "TEXT" in out.upper() and "UNIQUE" in out.upper()

def test_string_primary_key_realiased():
    out = _render_column("t", {"name": "id", "type": "string primary_key"})
    assert "TEXT PRIMARY KEY" in out.upper()

def test_valid_multiword_type_unregressed():
    assert "double precision" in _render_column("t", {"name": "d", "type": "double precision"}).lower()
    assert "varchar(255)" in _render_column("t", {"name": "v", "type": "varchar(255)"}).lower()
