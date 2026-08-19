"""#997: assert #969/#988/#989's invariants where the DDL is written.

Three defects, three sessions, one accident in three spellings — a token that means something
to a contract author and nothing to postgres, left standing in a column's TYPE position:

    #969   "duration" integer nullable        nullable is a flag, not a type
    #988   "duration" integer?                the optional marker
    #989   "created_at" timestamp default_now the underscore spelling of DEFAULT NOW()

Each cost a run. initdb refuses the file, the database never starts, docker_up fails, and the
run stalls in validation behind an error naming a character offset inside a statement the log
had already truncated — which is why they took three sessions to find.

The fixes strip each spelling at the source. This is the net underneath them: a FOURTH
spelling gets caught when the DDL is rendered, not by a container failing to boot an hour
later. The first three were found one at a time over months; there is no reason to think the
list is complete.
"""

import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _ddl_invariants_997, render_schema_sql)

GOOD = 'CREATE TABLE IF NOT EXISTS "titles" (\n    "id" SERIAL PRIMARY KEY,\n' \
       '    "duration_minutes" INTEGER,\n    "created_at" TIMESTAMP DEFAULT NOW()\n);\n'


def test_valid_ddl_passes():
    _ddl_invariants_997(GOOD)


@pytest.mark.parametrize("bad,tag", [
    ('CREATE TABLE "t" (\n    "duration" integer?\n);', "988"),
    ('CREATE TABLE "t" (\n    "duration" integer nullable\n);', "969"),
    ('CREATE TABLE "t" (\n    "created_at" timestamp default_now\n);', "989"),
])
def test_each_known_spelling_is_refused(bad, tag):
    with pytest.raises(ValueError) as e:
        _ddl_invariants_997(bad)
    assert tag in str(e.value), "the message must name the fix that owns the spelling"


def test_the_message_names_the_line():
    """An offset with no line number is what made these expensive to find."""
    bad = 'CREATE TABLE "t" (\n    "a" TEXT,\n    "b" integer?\n);'
    with pytest.raises(ValueError) as e:
        _ddl_invariants_997(bad)
    assert "line 3" in str(e.value)


def test_a_legitimate_question_mark_is_not_flagged():
    """Only a `?` in TYPE POSITION is the optional marker. One inside a default string or a
    comment is not ours to reject."""
    _ddl_invariants_997("CREATE TABLE \"t\" (\n    \"label\" TEXT DEFAULT 'why?'\n);")


def test_a_column_named_like_a_default_is_not_flagged():
    _ddl_invariants_997('CREATE TABLE "t" (\n    "is_nullable" BOOLEAN\n);')


def test_the_real_renderer_produces_clean_ddl():
    """End to end: whatever render_schema_sql emits for an ordinary contract must satisfy the
    invariants, or the guard would block every run."""
    tables = {"titles": {
        "name": "titles",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "duration_minutes", "type": "integer?"},
            {"name": "created_at", "type": "timestamp default_now"},
            {"name": "title", "type": "string", "nullable": False},
        ],
    }}
    ddl = render_schema_sql(tables)
    _ddl_invariants_997(ddl)          # must not raise
    assert "?" not in re.sub(r"'[^']*'", "", ddl)


def test_the_control_would_have_shipped():
    """Planted control: a plain write accepts the broken DDL, which is how #988 reached
    postgres four times in r160."""
    bad = 'CREATE TABLE "t" (\n    "duration" integer?\n);'
    assert "integer?" in bad, (
        "the control was supposed to contain the marker; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
