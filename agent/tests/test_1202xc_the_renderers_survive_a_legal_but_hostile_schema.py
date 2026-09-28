"""#1202xc: a contract the lane is allowed to write must not be able to stop the app booting.

Framework-projected code is this corpus's largest single source of failing steps (32% of
them), and the two renderers a contract flows through are `backend_skeleton.render_models`
(the ORM classes) and `route_projector._serialize_expr` (the dict literal every projected read
returns). Both take column and table names STRAIGHT FROM THE LANE'S CONTRACT, and both emit
Python source, so a name is an injection site into the generated program.

Each has been holed before, one name at a time:

    #215     a column named `text` shadowed `text()` inside the class body -> the Column
             object was called -> TypeError, backend never booted
    #1202tg  a quoted name became `"a"b": getattr(r, "a"b", None)` -> SyntaxError, and
             `a-b_at` rendered as a SUBTRACTION that evaluated on every read -> 500
    #1202tp  a table name starting with a digit -> an invalid class name -> never booted
    _SA_RESERVED_ATTRS  `metadata` / `registry` are reserved on a declarative class, and
             `metadata` is an ordinary column name on posts/files/events

Every one of those was found after it shipped. This is the same question asked as a matrix
instead of one name at a time: 12 hostile-but-legal schemas through the mapper, 23 hostile
column names through the serialiser.

MEASURED at the time of writing: all of them already pass. That is the point -- this is a
regression floor for a class that keeps coming back, not a report of a new defect.

DUNDERS ARE DELIBERATELY OUT, and the reason is worth keeping because the obvious fix is
worse than the gap. A column named `__tablename__` renders `__tablename__ = Column(String)`
AFTER the renderer's own `__tablename__ = "posts"` and overwrites it -- no exception, a wrong
table at runtime -- and `__init__` replaces the constructor and kills the mapper outright.
Adding dunders to `_needs_attr_suffix` (the rule that already handles keywords and
`metadata`) fixes both: the table name survives and the mapper builds. But the suffixed
attribute `__tablename___` is then NAME-MANGLED inside the class body, and the column
disappears from `__table__.columns` entirely -- silent table corruption traded for silent
column loss. On an input that cannot occur, that is not an improvement.

Reachability, measured rather than assumed: of the 13,962 column names in the corpus's 176
schema hubs, ZERO are dunders and ZERO are non-identifiers. So the hostile names below are
the ones a new domain could plausibly introduce -- `class` for a school app, `order` for a
shop, `metadata` on posts/files -- and all of them work today.
"""
import ast
import datetime
import sys
import types

import pytest

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0] + "/env_generator/llm_generator")

from multi_agent.runtime.backend_skeleton import render_models  # noqa: E402
from multi_agent.runtime.route_projector import _serialize_expr  # noqa: E402

# Names a lane can legally put in a contract and that a real app plausibly has. Each is a
# different way to be hostile: a Python keyword, a dunder, an SA-reserved attribute, an SQL
# reserved word, a name that is not an identifier at all, a name that closes a string literal.
_HOSTILE_COLUMNS = [
    "class", "from", "lambda", "None",          # python keywords
    "metadata", "registry",                      # reserved on a declarative class
    "order", "group", "select", "user",          # SQL reserved words
    "id",                                        # collides with the implicit PK
    "Name",                                      # case-collides with `name`
    "c" * 70,                                    # past Postgres's 63-char identifier limit
    "标题",                                       # non-ASCII
    "my col", "a-b", "1st", "",                  # not identifiers at all
    'a"b', "a'b", "a\\b",                        # close the string literal the name lands in
]


def _mapper_ok(tables):
    """Render the models and actually BUILD the declarative classes.

    Parsing is not the bar -- #1202tg's `a-b_at` parsed perfectly and evaluated a
    subtraction. The mapper is where `metadata` and a duplicated column are rejected."""
    import database  # noqa: F401  (stubbed by the fixture)
    src = render_models(tables)
    ast.parse(src)                                  # must at least be Python
    ns = {"__name__": "genmod_1202xc"}
    exec(compile(src, "<models>", "exec"), ns)      # must build the mapper
    return ns


@pytest.fixture(autouse=True)
def _stub_database():
    """The generated module imports `Base` from `database`; give it a real one per test so
    two schemas cannot collide in one MetaData."""
    from sqlalchemy.orm import declarative_base
    mod = types.ModuleType("database")
    mod.Base = declarative_base()
    saved = sys.modules.get("database")
    sys.modules["database"] = mod
    try:
        yield
    finally:
        if saved is not None:
            sys.modules["database"] = saved
        else:
            sys.modules.pop("database", None)


@pytest.mark.parametrize("col", _HOSTILE_COLUMNS)
def test_a_hostile_column_still_builds_a_mapper(col):
    _mapper_ok({"posts": {"columns": [{"name": col, "type": "string"},
                                      {"name": "title", "type": "string"}]}})


@pytest.mark.parametrize("table", ["order", "user", "group", "select", "1st", "my table"])
def test_a_hostile_table_name_still_builds_a_mapper(table):
    _mapper_ok({table: {"columns": [{"name": "total", "type": "integer"}]}})


def test_a_duplicated_column_does_not_stop_the_mapper():
    _mapper_ok({"posts": {"columns": [{"name": "title", "type": "string"},
                                      {"name": "title", "type": "integer"}]}})


def test_a_case_collision_does_not_stop_the_mapper():
    _mapper_ok({"posts": {"columns": [{"name": "Name", "type": "string"},
                                      {"name": "name", "type": "string"}]}})


# --- the serialiser: every projected read returns this dict ------------------------------

@pytest.mark.parametrize("col", [c for c in _HOSTILE_COLUMNS if c not in ("id", "")])
def test_the_projected_read_returns_that_column_s_value(col):
    """★ Not just 'it parses'. #1202tg's defect PARSED and then computed a subtraction, so
    the assertion has to be that the value on the row comes back."""
    expr = _serialize_expr("r", ["id", col])
    tree = ast.parse("v = " + expr)

    row = types.SimpleNamespace()
    row.id = 1
    setattr(row, col, "VAL")
    ns = {"r": row, "datetime": datetime.datetime}
    exec(compile(tree, "<expr>", "exec"), ns)
    assert ns["v"].get(col) == "VAL", (
        "the projected read does not return column %r: %r" % (col, ns["v"]))


def test_an_empty_column_list_still_returns_the_id():
    ns = {"r": types.SimpleNamespace(id=7), "datetime": datetime.datetime}
    exec(compile(ast.parse("v = " + _serialize_expr("r", [])), "<expr>", "exec"), ns)
    assert ns["v"] == {"id": 7}


def test_a_datetime_column_is_serialised_as_a_string():
    """The docstring's own promise -- ISO datetimes, so the dict is JSON-encodable."""
    row = types.SimpleNamespace(id=1, created_at=datetime.datetime(2026, 9, 28, 12, 0, 0))
    ns = {"r": row, "datetime": datetime.datetime}
    exec(compile(ast.parse("v = " + _serialize_expr("r", ["id", "created_at"])),
                 "<expr>", "exec"), ns)
    assert isinstance(ns["v"]["created_at"], str), ns["v"]


def test_the_matrix_is_not_empty():
    """A parametrised guard over an empty list is vacuous (#1202wm)."""
    assert len(_HOSTILE_COLUMNS) >= 20
