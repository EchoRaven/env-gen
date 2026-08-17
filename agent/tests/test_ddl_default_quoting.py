"""#404 (DDL bare-word default quoting — initdb-failure prevention, the #372/#382/#383 class):
the DDL renderer emitted a column DEFAULT value VERBATIM, so a bare-word text default
(``status text default active`` / ``{"default": "active"}``) rendered ``DEFAULT active`` —
postgres reads ``active`` as an identifier (``column "active" does not exist``) → CREATE TABLE
fails → initdb exit 3 → docker_up wedge → the whole run stalls. The fix single-quotes a
bare-word text default while passing through numbers / already-quoted / boolean-NULL keywords /
SQL functions / known keywords. This locks it.
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


def _default_clause(col):
    line = _ds._render_column("t", dict(col))
    # return the "DEFAULT ..." tail if present
    idx = line.upper().find("DEFAULT ")
    return line[idx:].strip() if idx >= 0 else ""


def test_bare_word_default_is_quoted():
    assert _default_clause({"name": "status", "type": "text", "default": "active"}) == "DEFAULT 'active'"
    assert _default_clause({"name": "role", "type": "text", "default": "user"}) == "DEFAULT 'user'"


def test_embedded_bare_word_default_is_quoted():
    # default carried inside the type string
    assert _default_clause({"name": "status", "type": "text default active"}) == "DEFAULT 'active'"


def test_numeric_default_unquoted():
    assert _default_clause({"name": "cnt", "type": "integer", "default": 0}) == "DEFAULT 0"
    assert _default_clause({"name": "cnt", "type": "integer", "default": "5"}) == "DEFAULT 5"
    assert _default_clause({"name": "amt", "type": "numeric", "default": "1.50"}) == "DEFAULT 1.50"


def test_already_quoted_default_unchanged():
    assert _default_clause({"name": "st", "type": "text", "default": "'active'"}) == "DEFAULT 'active'"


def test_boolean_and_null_keywords_unquoted():
    assert _default_clause({"name": "flag", "type": "boolean", "default": "true"}) == "DEFAULT true"
    assert _default_clause({"name": "flag", "type": "boolean", "default": False}) == "DEFAULT false"


def test_sql_function_and_keyword_defaults_unquoted():
    assert _default_clause({"name": "ts", "type": "timestamp", "default": "now()"}) == "DEFAULT now()"
    assert _default_clause({"name": "id", "type": "uuid", "default": "gen_random_uuid()"}) == "DEFAULT gen_random_uuid()"
    out = _default_clause({"name": "ts", "type": "timestamp", "default": "current_timestamp"})
    assert out.lower() == "default current_timestamp"


def test_quote_escaping_for_apostrophe():
    # a value containing a single quote is SQL-escaped ('' ) so the DDL stays valid
    assert _ds._quote_default("O'Brien") == "'O''Brien'"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
