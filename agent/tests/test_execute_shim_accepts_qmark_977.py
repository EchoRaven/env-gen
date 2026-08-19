"""#977: the execute() shim must accept the qmark style too.

`syntax error at or near "?"` — 4 occurrences in r158, 1 in r157, 1 in r149, each failing
`docker_up`. Written off twice as unlocalizable because the `?` never survives in any
artifact: the app source gets healed, and the log printed the postgres ERROR without the
STATEMENT beside it (that is what #973 fixed).

Found by enumerating the framework's SQL-execution surface instead of grepping for `?`. The
generated `database.py` carries a compatibility shim (FIX #86) that coerces a raw-string
statement to `text()` and rewrites psycopg's `%s` positional params into named binds. It
never learned the OTHER habit: `execute("... WHERE id = ?", (v,))`. That string reaches
postgres verbatim.

`%s` keeps priority, so behaviour is byte-identical on every statement that already worked.
"""

import ast

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _DATABASE_PY


def test_the_generated_module_still_parses():
    """This is a TEMPLATE — a syntax error here breaks every generated app, and the
    framework's own py_compile would not notice."""
    ast.parse(_DATABASE_PY)


def test_the_shim_handles_qmark():
    assert '"?" in statement' in _DATABASE_PY, (
        "a lane writing the sqlite habit `execute(sql, (v,))` with ? placeholders sends the "
        "literal ? to postgres")


def test_percent_s_keeps_priority():
    """Existing statements must be rewritten exactly as before."""
    assert 'marker = "%s" if "%s" in statement else "?"' in _DATABASE_PY


# The shim's logic, lifted verbatim, so the rewrite can be exercised without a database.
def _rewrite(statement, params):
    if isinstance(params, (list, tuple)) and ("%s" in statement or "?" in statement):
        marker = "%s" if "%s" in statement else "?"
        parts = statement.split(marker)
        stmt = parts[0]
        bound = {}
        for i, chunk in enumerate(parts[1:]):
            stmt += f":p{i}" + chunk
            if i < len(params):
                bound[f"p{i}"] = params[i]
        return stmt, bound
    return statement, params


@pytest.mark.parametrize("sql,params,expected", [
    ("SELECT * FROM t WHERE id = ?", (7,), "SELECT * FROM t WHERE id = :p0"),
    ("SELECT * FROM t WHERE a = ? AND b = ?", (1, 2),
     "SELECT * FROM t WHERE a = :p0 AND b = :p1"),
    ("INSERT INTO t (a, b) VALUES (?, ?)", ("x", "y"),
     "INSERT INTO t (a, b) VALUES (:p0, :p1)"),
])
def test_qmark_becomes_named_binds(sql, params, expected):
    stmt, bound = _rewrite(sql, params)
    assert stmt == expected
    assert list(bound.values()) == list(params)


def test_percent_s_is_unchanged():
    stmt, bound = _rewrite("SELECT * FROM t WHERE id = %s", (7,))
    assert stmt == "SELECT * FROM t WHERE id = :p0"
    assert bound == {"p0": 7}


def test_a_bare_question_mark_without_params_is_left_alone():
    """Only a positional-params call is a placeholder call. A `?` inside a literal must not
    be rewritten into a bind that has nothing to bind."""
    sql = "SELECT * FROM t WHERE label = 'why?'"
    assert _rewrite(sql, None) == (sql, None)


def test_the_control_sends_the_literal_qmark():
    """Planted control: the PRE-FIX condition only fired on %s, so a qmark statement went
    through untouched — which is the postgres syntax error."""
    def _pre_fix(statement, params):
        if isinstance(params, (list, tuple)) and "%s" in statement:
            return "rewritten"
        return statement

    assert _pre_fix("SELECT * FROM t WHERE id = ?", (7,)) == "SELECT * FROM t WHERE id = ?", (
        "the control was supposed to pass the ? through; if it does not, the fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
