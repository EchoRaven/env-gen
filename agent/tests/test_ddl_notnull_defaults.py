"""#407 (FW_DEBUG-surfaced on netflix r5): a NOT NULL column with no default is a landmine —
the agent seed / projected create / profile autocreate omit it -> NotNullViolation -> the row
is DROPPED (r5: 7 profiles + episodes dropped on null created_at -> no profiles -> per-profile
chains 404 -> business_chain wedge). The DDL now supplies a safe default BY CONSTRUCTION for the
unambiguous types: NOT NULL timestamp -> now(), date -> CURRENT_DATE, time -> CURRENT_TIME,
boolean -> false. Text/int/numeric are left required (no universal default). This locks it.
"""
import importlib
import sys
import types

_RT = "env_generator/llm_generator/multi_agent/runtime"
for _pkg in ("env_generator", "env_generator.llm_generator",
             "env_generator.llm_generator.multi_agent",
             "env_generator.llm_generator.multi_agent.runtime"):
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        _m.__path__ = []
        sys.modules[_pkg] = _m
sys.modules["env_generator.llm_generator.multi_agent.runtime"].__path__ = [_RT]
_ds = importlib.import_module("env_generator.llm_generator.multi_agent.runtime.database_scaffold")


def _col(**kw):
    return _ds._render_column("t", dict(kw))


def _default(line):
    i = line.upper().find("DEFAULT ")
    return line[i:].strip() if i >= 0 else ""


def test_notnull_timestamp_gets_now():
    for t in ("timestamp", "timestamptz", "datetime"):
        line = _col(name="created_at", type=t, not_null=True)
        assert "NOT NULL" in line.upper()
        assert _default(line).lower() == "default now()", (t, line)


def test_notnull_boolean_gets_false():
    line = _col(name="is_kids", type="boolean", not_null=True)
    assert _default(line).lower() == "default false", line


def test_notnull_date_and_time():
    assert _default(_col(name="d", type="date", not_null=True)).upper() == "DEFAULT CURRENT_DATE"
    assert _default(_col(name="tm", type="time", not_null=True)).upper() == "DEFAULT CURRENT_TIME"


def test_notnull_text_and_int_left_required():
    # no universal safe default — must stay required (don't invent a name/count)
    assert _default(_col(name="name", type="text", not_null=True)) == ""
    assert _default(_col(name="cnt", type="integer", not_null=True)) == ""


def test_nullable_timestamp_gets_no_default():
    # only NOT NULL columns get the by-construction default
    assert _default(_col(name="seen_at", type="timestamp")) == ""


def test_explicit_default_not_overridden():
    line = _col(name="created_at", type="timestamp", not_null=True, default="'2020-01-01'")
    assert _default(line) == "DEFAULT '2020-01-01'", line


def test_pk_timestamp_not_given_default():
    # a PK is never given the auto-default (PKs are handled separately)
    line = _col(name="id", type="timestamp", primary_key=True)
    assert "DEFAULT NOW()" not in line.upper()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
