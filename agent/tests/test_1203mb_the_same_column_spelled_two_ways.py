r"""#1203mb: the table detector compared declared type strings raw.

`detect_breaking_change` (endpoints) was taught by #1202om that `bool` and `boolean` are one
type. `detect_table_breaking_change`, in the same file, still compared
`old_schema[k] != new_schema[k]` on the raw strings.

MEASURED by replaying every table's schema history out of the `table_registered` events (they
fire on every registration and carry the full schema): across the 39 modern runs, 1703
consecutive registration pairs give 1712 raw declared-string differences -- 1061 (62%) real
and 651 (38%) pure spelling.

The equivalence is the framework's own: two declarations that render to the same DDL LINE are
the same column, because that line is what postgres gets. Two weaker versions were measured
first and both were wrong -- my own alias table claimed 92% noise by folding `bigint` into
`integer`, `serial` into `integer` and `date` into `timestamp` (hiding real changes), and
`_sql_type` alone leaves 67% because it only fires when the whole string is an alias key.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _changed(tmp_path, a, b, name="c"):
    rh = HubRegistry(tmp_path).hubs.registryhub
    return rh.detect_table_breaking_change(
        {"columns": [{"name": name, "type": a}]},
        {"columns": [{"name": name, "type": b}]})


@pytest.mark.parametrize("a,b", [
    ("text", "TEXT"), ("int", "integer"), ("string", "str"),
    ("timestamp", "datetime"), ("json", "jsonb"),
    ("integer primary key", "integer primary_key"),   # 36 occurrences, pure spelling
])
def test_a_spelling_difference_is_not_a_breaking_change(tmp_path, a, b):
    out = _changed(tmp_path, a, b)
    assert out["type_changed_columns"] == []
    assert out["is_breaking"] is False


@pytest.mark.parametrize("a,b", [
    ("text", "text not null"),        # 54 occurrences -- a writer can break on this
    ("integer", "bigint"),            # a narrowing the other way round
    ("serial", "integer"),            # loses the sequence
    ("timestamp", "date"),            # loses time of day
    ("integer", "integer references users.id"),   # 92+35+28
    ("integer", "integer default 0"),             # 59+35
    ("text", "integer"),
])
def test_a_real_change_is_still_breaking(tmp_path, a, b):
    out = _changed(tmp_path, a, b)
    assert out["type_changed_columns"] == ["c"]
    assert out["is_breaking"] is True


def test_a_removed_column_is_untouched(tmp_path):
    """The regression direction: the other half of the verdict must still fire."""
    rh = HubRegistry(tmp_path).hubs.registryhub
    out = rh.detect_table_breaking_change(
        {"columns": [{"name": "a", "type": "text"}, {"name": "b", "type": "int"}]},
        {"columns": [{"name": "a", "type": "text"}]})
    assert out["removed_columns"] == ["b"] and out["is_breaking"] is True


def test_identical_schemas_are_not_breaking(tmp_path):
    out = _changed(tmp_path, "text", "text")
    assert out["is_breaking"] is False


@pytest.mark.parametrize("a,b", [(None, "text"), ("text", None), ("", ""), (7, "text")])
def test_it_never_raises_on_odd_declarations(tmp_path, a, b):
    out = _changed(tmp_path, a, b)
    assert isinstance(out["type_changed_columns"], list)


def test_the_equivalence_is_delegated_not_reimplemented():
    """#1032: the renderer owns "what does this declaration become".

    Pinned by AST, not by source text -- the docstring names both helpers, so a substring
    assertion would be satisfied by the comment (the #1203m9 lesson).
    """
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(RegistryHub.detect_table_breaking_change)))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_r1203mb" in called, "the DDL renderer is no longer consulted"
    assert "_p1203mb" in called, "inline modifiers are no longer promoted first"
    # and no type table of its own appeared beside it
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict) and n.keys:
            keys = [k.value for k in n.keys if isinstance(k, ast.Constant)]
            assert not {"text", "integer", "varchar", "bool"} & set(map(str, keys)), \
                "a second type map appeared instead of delegating"


def test_the_caller_still_reaches_it(tmp_path):
    """`update_table_schema` is the only caller; the fix is worthless if it stopped calling."""
    src = inspect.getsource(RegistryHub.update_table_schema)
    tree = ast.parse(textwrap.dedent(src))
    assert any(isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "detect_table_breaking_change"
               for n in ast.walk(tree)), "nothing detects table breaking changes any more"


def test_a_fault_in_the_renderer_reports_the_change_rather_than_hiding_it(tmp_path,
                                                                          monkeypatch):
    """The fallback direction. A detector that cannot tell must say "changed", not "fine".

    Found by mutation: flipping `except Exception: return False` to `return True` survived,
    because nothing in the suite made the renderer raise. The iron rule is that a fallback
    must not mask a failure, so this pins the direction with the renderer forced to throw.
    """
    from env_generator.llm_generator.multi_agent.runtime import database_scaffold

    def _boom(*a, **k):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(database_scaffold, "_render_column", _boom)
    out = _changed(tmp_path, "text", "integer")
    assert out["type_changed_columns"] == ["c"], \
        "a renderer fault silently turned a real type change into 'no change'"
    assert out["is_breaking"] is True


def test_a_fault_does_not_invent_a_change_for_identical_declarations(tmp_path, monkeypatch):
    """The other side of the same fallback: equal strings short-circuit before the renderer."""
    from env_generator.llm_generator.multi_agent.runtime import database_scaffold

    def _boom(*a, **k):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(database_scaffold, "_render_column", _boom)
    out = _changed(tmp_path, "text", "text")
    assert out["type_changed_columns"] == [] and out["is_breaking"] is False
