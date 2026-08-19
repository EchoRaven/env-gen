"""#988: `integer?` is a nullability marker, not a SQL type.

`syntax error at or near "?"` — six occurrences across r149, r157, r158, and four more in
r160. Written off twice as unlocalizable because the `?` never survives in an artifact: the
DDL is regenerated between validations, so by the time anyone looks the file is clean.

The chain that finally named it, all in this session:

    #973   print the STATEMENT beside the postgres ERROR
    #987   widen the cap to reach the offset the error names ("at character 255")
    here   count characters into `CREATE TABLE IF NOT EXISTS "titles" (` — 255 lands on
           the `duration_minutes` type position

Spec and TypeScript-ish contracts write `integer?` for optional. Rendered verbatim that is
`"duration_minutes" INTEGER?`, postgres initdb dies, docker_up fails, the run stalls.

Same family as #969's inline `nullable`, and it needs the same TWO halves: strip the marker
from the type AND promote it to `nullable`. Stripping alone renders valid SQL that says the
opposite of the contract.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _promote_inline_modifiers, _sql_type)


# The three shapes recovered from r160's git history (commit ea94bce, the pre-heal
# 01_init.sql that postgres rejected):
#     "duration_minutes" integer?,
#     "seasons_count"    integer? DEFAULT 0,
#     "logo_url"         string?,
@pytest.mark.parametrize("raw,expected", [
    ("integer?", "INTEGER"),
    ("text?", "TEXT"),
    ("integer ?", "INTEGER"),
    ("boolean?  ", "BOOLEAN"),
    ("string?", "TEXT"),
])
def test_the_marker_never_reaches_sql(raw, expected):
    assert "?" not in _sql_type(raw)
    assert _sql_type(raw).upper() == expected


def test_the_marker_can_terminate_a_token_mid_string():
    """r160 line 77: `integer? DEFAULT 0`. The first version of this fix only stripped a `?`
    at the END of the whole string and silently missed this one — caught by replaying the
    real DDL rather than the three shapes I had imagined."""
    assert "?" not in _sql_type("integer? DEFAULT 0")
    assert _promote_inline_modifiers(
        {"name": "seasons_count", "type": "integer? DEFAULT 0"}).get("nullable") is True


def test_a_plain_type_is_untouched():
    assert _sql_type("integer").upper() == "INTEGER"


def test_a_question_mark_inside_a_type_is_left_alone():
    """Only a TRAILING marker is nullability. Anything else is not ours to edit."""
    assert "?" in _sql_type("varchar(3?)")


def test_the_column_becomes_nullable():
    out = _promote_inline_modifiers({"name": "duration_minutes", "type": "integer?"})
    assert out.get("nullable") is True, (
        "stripping without promoting renders a NOT NULL column where the contract asked "
        "for an optional one — valid SQL that says the opposite")


def test_an_explicit_not_null_still_wins():
    """A contradictory `integer? not null` keeps the stricter read, matching #969."""
    out = _promote_inline_modifiers({"name": "d", "type": "integer? not null"})
    assert not out.get("nullable")


def test_a_stated_nullable_is_not_overwritten():
    out = _promote_inline_modifiers({"name": "d", "type": "integer?", "nullable": False})
    assert out["nullable"] is False


def test_the_control_emits_broken_ddl():
    """Planted control: the PRE-FIX type renderer passed the marker straight through, which
    is the postgres syntax error."""
    def _pre_fix(raw):
        return raw.strip()

    assert _pre_fix("integer?") == "integer?", (
        "the control was supposed to keep the ?; if it does not, this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
