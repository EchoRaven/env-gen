"""#403 (ORM/DDL type-map parity, extends #396's #393-root fix): the ORM renderer
(backend_skeleton._sa_type -> SQLAlchemy type) and the DDL renderer
(database_scaffold._sql_type -> SQL type) must agree on a column's type, or the generated
ORM Column mismatches the physical column (the #393 class: inserts/reads misbehave). This
locks the COMMON types in agreement and pins the #403 fix (money -> NUMERIC on both sides,
instead of ORM Numeric vs the native postgres MONEY type).

It also DOCUMENTS the remaining exotic-type divergences (bytea / interval / arrays / citext)
as known gaps — deferred, to be fixed when a live run actually needs them (per the iron law:
don't build speculative taxonomies; validate generalizations against a live run).
"""
import importlib
import sys
import types

# load the two runtime modules without dragging in the httpx-heavy package __init__
_RT = "env_generator/llm_generator/multi_agent/runtime"
for _pkg in ("env_generator", "env_generator.llm_generator",
             "env_generator.llm_generator.multi_agent",
             "env_generator.llm_generator.multi_agent.runtime"):
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        _m.__path__ = []
        sys.modules[_pkg] = _m
sys.modules["env_generator.llm_generator.multi_agent.runtime"].__path__ = [_RT]
_bs = importlib.import_module("env_generator.llm_generator.multi_agent.runtime.backend_skeleton")
_ds = importlib.import_module("env_generator.llm_generator.multi_agent.runtime.database_scaffold")

# SQLAlchemy type -> the family of SQL types it round-trips cleanly against.
_COMPATIBLE = {
    "Text": {"TEXT", "VARCHAR", "CHAR", "CITEXT"},
    "String": {"TEXT", "VARCHAR", "CHAR", "UUID", "INET"},
    "Integer": {"INTEGER", "SMALLINT", "SERIAL"},
    "BigInteger": {"BIGINT", "BIGSERIAL"},
    "Boolean": {"BOOLEAN"},
    "Numeric": {"NUMERIC", "DECIMAL"},
    "Float": {"DOUBLE PRECISION", "REAL", "FLOAT"},
    "DateTime": {"TIMESTAMP", "TIMESTAMPTZ", "DATETIME"},
    "Date": {"DATE"},
    "Time": {"TIME"},
    "JSON": {"JSON", "JSONB"},
}


def _agree(llm_type):
    orm = _bs._sa_type(llm_type)
    ddl = _ds._sql_type(llm_type).upper().strip()
    ok = ddl in _COMPATIBLE.get(orm, set())
    return orm, ddl, ok


# ---- COMMON types must agree (the invariant #396 established, extended here) -------------
def test_common_scalar_types_agree():
    for t in ["text", "varchar", "integer", "int", "bigint", "smallint", "boolean", "bool",
              "numeric", "decimal", "float", "real", "double precision",
              "timestamp", "datetime", "date", "time", "json", "jsonb"]:
        orm, ddl, ok = _agree(t)
        assert ok, "ORM/DDL diverge on %r: ORM=%s DDL=%s" % (t, orm, ddl)


def test_money_now_aligned_403():
    # the #403 fix: money -> NUMERIC on the DDL side, matching ORM Numeric
    orm, ddl, ok = _agree("money")
    assert orm == "Numeric" and ddl == "NUMERIC", "money not aligned: ORM=%s DDL=%s" % (orm, ddl)
    assert ok


def test_money_not_the_native_postgres_money_type():
    # native postgres MONEY is discouraged + was the divergent form; make sure it's gone
    assert _ds._sql_type("money").upper() == "NUMERIC"


def test_uuid_and_jsonb_tolerable():
    # String<->UUID and JSON<->JSONB round-trip via psycopg; assert they stay in the tolerated set
    assert _agree("uuid")[2], _agree("uuid")
    assert _agree("jsonb")[2], _agree("jsonb")


# ---- KNOWN, DEFERRED exotic divergences — documented so they're visible + regression-tracked
# (NOT asserted as "correct"; asserted as the CURRENT state so a future fix flips them here).
def test_known_exotic_divergences_are_documented():
    known = {}
    for t in ("bytea", "interval", "text[]", "integer[]", "citext"):
        orm, ddl, ok = _agree(t)
        known[t] = (orm, ddl, ok)
    # These currently diverge (ORM strips/mis-maps vs DDL's native type). This test PINS the
    # status quo so it's tracked; when a live run needs one, fix the renderer + flip its entry.
    assert known["bytea"][2] is False        # ORM String vs DDL bytea
    assert known["interval"][2] is False      # ORM Integer (startswith 'int') vs DDL interval
    assert known["text[]"][2] is False        # ORM Text vs DDL text[]
    assert known["integer[]"][2] is False     # ORM Integer vs DDL integer[]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
