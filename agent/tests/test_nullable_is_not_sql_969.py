"""#969: `nullable` is a contract word, not SQL — it must never reach the DDL.

Kickoff/ORM contracts describe an optional column as `{"logo_url": "string nullable"}`.
Postgres has no such keyword: nullability is the default, expressed by the ABSENCE of
NOT NULL. Left inside the type string it defeated the alias lookup — `"string nullable"`
missed the entry that maps `string` -> TEXT — so BOTH tokens were emitted verbatim:

    "logo_url" string nullable,

which is `syntax error at or near "nullable"`, initdb fails, the db container dies, and
docker_up FAILS. netflix r157 hit it 6 times across its validation retries, each costing a
full down/build/up cycle.

Same class as the inline `check` already stripped in `_sql_type` and the four modifiers
already promoted by `_promote_inline_modifiers`; this is the missing sibling.

The load-bearing constraint on the fix: only this known modifier word may be removed.
Legitimate SQL types are multi-token (`double precision`, `timestamp with time zone`,
`character varying`), so a "first token wins" normalization would corrupt them — that is
what `test_multi_token_types_survive` pins.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _promote_inline_modifiers, _sql_type, render_schema_sql)


@pytest.mark.parametrize("spec,expected", [
    ("string nullable", "TEXT"),
    ("integer nullable", "INTEGER"),
    ("text NULLABLE", "TEXT"),
    ("bool nullable", "BOOLEAN"),
])
def test_nullable_is_stripped_and_the_type_still_resolves(spec, expected):
    assert _sql_type(spec) == expected, (
        "the marker must be removed BEFORE the alias lookup, otherwise the whole string "
        "misses the table and reaches the DDL verbatim")


@pytest.mark.parametrize("spec", [
    "double precision", "timestamp with time zone", "character varying",
    "varchar(255)", "numeric(10,2)", "text[]",
])
def test_multi_token_types_survive(spec):
    """Only the known modifier word may be dropped. Real SQL types have multiple tokens."""
    assert _sql_type(spec) == spec, (
        f"{spec!r} is valid SQL and must pass through untouched — a first-token-wins "
        "normalization would silently change the column's type")


def test_nullable_becomes_a_structured_flag():
    """The ORM renderer keys off structured flags, so it must agree with the DDL (#393)."""
    out = _promote_inline_modifiers({"name": "logo_url", "type": "string nullable"})
    assert out.get("nullable") is True


def test_not_null_wins_over_a_contradictory_nullable():
    out = _promote_inline_modifiers({"name": "c", "type": "text not null nullable"})
    assert out.get("not_null") is True
    assert out.get("nullable") is not True, (
        "a contradictory spec must keep the stricter reading, not silently widen the column")


def test_the_rendered_ddl_is_valid():
    """End-to-end through the real renderer — `_sql_type` alone would not prove the token
    stays out of the emitted SQL."""
    sql = render_schema_sql({
        "titles": {"columns": [
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "logo_url", "type": "string nullable"},
            {"name": "rank", "type": "integer nullable"},
            {"name": "name", "type": "text not null"},
        ]},
    })
    assert "nullable" not in sql.lower(), (
        f"the contract marker reached the DDL:\n{sql}")
    assert '"logo_url" TEXT' in sql or "logo_url TEXT" in sql
    assert "NOT NULL" in sql, "the unrelated not-null column must still be constrained"


def test_the_control_emits_the_broken_ddl():
    """Planted control: the PRE-FIX shape — alias lookup on the raw string, no stripping —
    must still produce the invalid token. Synthetic, so fixing the real renderer can never
    turn this red."""
    from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
        _TYPE_ALIASES)

    def _pre_fix_sql_type(raw):
        t = (raw or "").strip()
        return _TYPE_ALIASES.get(t.lower(), t)

    assert _pre_fix_sql_type("string nullable") == "string nullable", (
        "the control was supposed to pass the marker through; if it no longer does, the "
        "main assertions prove nothing")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
