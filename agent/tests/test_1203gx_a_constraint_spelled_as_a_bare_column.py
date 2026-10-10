"""#1203gx: a third spelling of "table constraint modelled as a column", and the first
one that did not crash.

#32 handled `{"name": "unique(a,b)", "type": "constraint"}` and #1031 handled
`{"name": "__unique__", "type": "(a, b)"}`; both abort postgres initdb, so both were found
the hard way. r171 produced `{"name": "unique", "type": "comment_id,user_id"}` -- keyword as
the whole name, column list in the type, no parens anywhere. Postgres accepts the quoted
reserved word, so nothing crashed: `01_init.sql` simply carried `"unique" TEXT` in
`comment_likes` and `follows`, `models.py` carried `unique = Column(String)` twice, and the
UNIQUE the contract asked for did not exist -- the delivered app accepts duplicate likes and
duplicate follows, and its follower counts are wrong by construction.

The TYPE is the guard: a column legitimately named `check` or `index` carries a SQL type
there, never `a,b`. The negative controls below are what make the keyword test safe.
"""
import ast
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _is_constraint_pseudo_column as _pseudo,
    _render_table_constraint as _render,
)

SKEL = (Path(__file__).resolve().parents[1]
        / "env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py")

# The two rows r171 actually produced, verbatim from its registryhub_tables.json.
R171_ROWS = (
    ({"name": "unique", "type": "comment_id,user_id"}, 'UNIQUE ("comment_id", "user_id")'),
    ({"name": "unique", "type": "follower_id,following_id"},
     'UNIQUE ("follower_id", "following_id")'),
)


def test_the_bare_keyword_spelling_is_recognised():
    for col, _ in R171_ROWS:
        assert _pseudo(col), col


def test_it_is_rendered_as_a_real_constraint_not_dropped():
    """Honour the constraint. Dropping it is what left `follows` accepting duplicate rows."""
    for col, want in R171_ROWS:
        assert (_render(col) or "").strip() == want, col


def test_the_two_older_spellings_still_work():
    """#32 and #1031 are regression surface, not history."""
    assert _pseudo({"name": "unique(a,b)", "type": "constraint"})
    assert (_render({"name": "unique(a,b)", "type": "constraint"}) or "").strip() \
        == 'UNIQUE ("a", "b")'
    assert _pseudo({"name": "__unique__", "type": "(email, tenant_id)"})
    assert (_render({"name": "__unique__", "type": "(email, tenant_id)"}) or "").strip() \
        == 'UNIQUE ("email", "tenant_id")'


def test_a_real_column_whose_name_is_a_keyword_is_left_alone():
    """The TYPE guard. Without it, `{"name": "check", "type": "boolean"}` would be eaten."""
    for col in ({"name": "check", "type": "boolean"},
                {"name": "index", "type": "integer"},
                {"name": "unique", "type": "text"},
                {"name": "unique", "type": "varchar(64)"},
                {"name": "constraint", "type": "text"}):
        assert not _pseudo(col), col
        assert _render(col) is None, col


def test_an_ordinary_column_is_never_touched():
    for col in ({"name": "created_at", "type": "datetime not null"},
                {"name": "user_id", "type": "integer references users.id"},
                {"name": "id", "type": "integer primary key"}):
        assert not _pseudo(col), col


def test_a_single_name_in_the_type_is_not_a_column_list():
    """Requiring the comma is what makes acting on the name safe; a one-column UNIQUE is
    declared with the column's own flag, which #396 already promotes."""
    assert not _pseudo({"name": "unique", "type": "email"})


def test_both_emitters_read_this_one_predicate():
    """The ORM renderer and the DDL renderer must share it, or a fix lands in one output.

    r171 shipped the junk column in BOTH `01_init.sql` and `models.py` because the single
    predicate they share did not recognise the shape. AST, so a renderer that stops calling
    it turns this red.
    """
    tree = ast.parse(SKEL.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "render_models")
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert any("_is_constraint_pseudo_column" in c for c in calls), (
        "render_models no longer filters constraint pseudo-columns")


def test_unsupported_keywords_are_dropped_rather_than_mis_rendered():
    """FOREIGN KEY / CHECK composites are not rendered -- better a dropped constraint than
    broken DDL, which is #32's own stated rule. They must still be kept OUT of the columns."""
    for col in ({"name": "foreign key", "type": "user_id,tenant_id"},
                {"name": "check", "type": "a,b"}):
        assert _pseudo(col), col
        assert _render(col) is None, col
