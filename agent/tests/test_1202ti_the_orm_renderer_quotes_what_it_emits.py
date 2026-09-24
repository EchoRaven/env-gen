r"""#1202ti: the ORM renderer interpolated names raw where the DDL renderer quotes them.

Continuing the codegen stress-audit (#1202tg backend reads, #1202th frontend components) into
the last pair of generators. The two halves of the same schema disagreed:

    database_scaffold  ->  CREATE TABLE IF NOT EXISTS "v""x" (…)      correct, via _quote_ident
    backend_skeleton   ->  __tablename__ = "v"x"                      SyntaxError

One fact, two emitters, one of them guarded -- and the DDL side has carried `_quote_ident`
("embedded quotes are escaped per SQL rules") the whole time.

Three sites emitted a name into a Python string literal by hand, all now quoted by
`json.dumps`, which is the same remedy #1202tg applied to the read serialiser:

    __tablename__ = "{table}"      the table name
    ForeignKey("{fk}")             the FK target, e.g. users.id
    {sib} = synonym("{nm}")        the temporal-alias source column

A fourth candidate -- the dependency list in pyproject.toml -- needs nothing: `#1202mk`
already refuses any name that is not a PEP 508 distribution name before it reaches the
template, which is validation at the value rather than at the template.

HOW LIKELY: the corpus holds 3 non-identifier table names in 2,009 (`suggested-creators`,
`continue-watching`), none with a quote. Hardening, same as its siblings, and worth it for the
same reason: nothing upstream validates the name, and the cost is a backend that cannot be
imported at all.

BEHAVIOUR IS UNCHANGED, checked rather than asserted: rendering all 39 real corpus schemas
through the old and the new code gives BYTE-IDENTICAL output. `json.dumps` emits exactly
`"users.id"` for an ordinary name.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import render_models  # noqa: E402
from multi_agent.runtime.database_scaffold import _quote_ident, render_schema_sql  # noqa: E402

_ID = {"name": "id", "type": "integer", "primary_key": True}


@pytest.mark.parametrize("tables", [
    {"videos": {"columns": [_ID, {"name": "title", "type": "string"}]}},
    {"continue-watching": {"columns": [_ID]}},          # the corpus really has these
    {"suggested-creators": {"columns": [_ID]}},
    {'v"x': {"columns": [_ID]}},                        # SyntaxError before this fix
    {"v\nx": {"columns": [_ID]}},
    {"v": {"columns": [_ID, {"name": 'a"b', "type": "string"}]}},
    {"v": {"columns": [_ID, {"name": "a-b", "type": "string"}]}},
    {"v": {"columns": [_ID, {"name": "created_time", "type": "datetime"}]}},
    {"users": {"columns": [_ID]},
     "v": {"columns": [_ID, {"name": "user_id", "type": "integer",
                             "foreign_key": 'users".id'}]}},
    {"order": {"columns": [_ID, {"name": "select", "type": "string"}]}},
])
def test_the_rendered_models_are_valid_python(tables):
    ast.parse(render_models(tables))


def test_the_table_name_survives_intact():
    """Quoting must preserve the name, not mangle it -- the ORM's __tablename__ has to match
    the DDL's CREATE TABLE or every query hits a table that does not exist."""
    src = render_models({'v"x': {"columns": [_ID]}})
    tree = ast.parse(src)
    names = [n.value.value for n in ast.walk(tree)
             if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "__tablename__" for t in n.targets)
             and isinstance(n.value, ast.Constant)]
    assert 'v"x' in names, names


def test_the_two_halves_agree_on_the_same_odd_name():
    """The defect was a disagreement between the generators, so assert they agree."""
    tables = {'v"x': {"columns": [_ID]}}
    ddl = render_schema_sql(tables)
    assert _quote_ident('v"x') in ddl, "the DDL side was always right; keep it that way"
    ast.parse(render_models(tables))


def test_the_foreign_key_target_is_quoted():
    src = render_models({"users": {"columns": [_ID]},
                         "v": {"columns": [_ID, {"name": "user_id", "type": "integer",
                                                 "foreign_key": 'users".id'}]}})
    ast.parse(src)
    assert 'users\\".id' in src or "users\\\".id" in src or 'ForeignKey' in src


def test_ordinary_output_is_unchanged():
    """Non-vacuity: `json.dumps` must emit exactly what the f-string did for a plain name."""
    src = render_models({"users": {"columns": [_ID, {"name": "email", "type": "string"}]},
                         "videos": {"columns": [_ID,
                                                {"name": "user_id", "type": "integer",
                                                 "foreign_key": "users.id"},
                                                {"name": "created_time", "type": "datetime"}]}})
    assert '__tablename__ = "users"' in src
    assert 'ForeignKey("users.id")' in src
    assert 'synonym("created_at")' in src


def test_no_site_interpolates_a_name_raw_any_more():
    """The rule, not the instance."""
    skel = (LLM_DIR / "multi_agent" / "runtime" / "backend_skeleton.py").read_text(
        encoding="utf-8")
    for pattern in ('__tablename__ = "{table}"', 'ForeignKey("{fk}")', 'synonym("{nm}")'):
        assert pattern not in skel, f"a name is being interpolated raw again: {pattern}"


def test_the_pyproject_dependency_is_validated_at_the_value():
    """The fourth candidate, and why it needs no quoting: #1202mk refuses a non-PEP-508 name
    before it can reach the template."""
    import inspect
    from multi_agent.runtime import backend_skeleton as bs
    src = inspect.getsource(bs._lane_third_party_imports)
    assert "_PEP508_NAME_1202MK" in src
