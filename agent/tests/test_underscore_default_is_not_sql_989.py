"""#989: `timestamp default_now` — the underscore spelling SQL cannot read.

The last entry on the deliberately-unfixed list, closed by the technique that cracked #988:
the generated project is a git repo, so the pre-heal DDL is still in it.

    git show 33894f8:app/database/init/01_init.sql   (netflix-web-r149)
    112:    "created_at" timestamp default_now
    127:    "updated_at" timestamp default_now

postgres: `syntax error at or near "default_now" at character 202`.

The existing inline-default extraction searches `\\bdefault\\b\\s+(.+)$`. `_` is a word
character, so `default_now` is a single token and the boundary never matches — the modifier
sails through into the rendered type.

Third member of the family with #969 (`nullable`) and #988 (`?`): a modifier standing in the
type position that is not SQL. Only unambiguous spellings are translated; an unknown
`default_<x>` is left to fail loudly rather than be guessed into a silently wrong default.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime import database_scaffold as ds


def _render(coltype):
    """Run a column through the same normalisation the DDL renderer uses."""
    return ds._column_sql({"name": "created_at", "type": coltype}) \
        if hasattr(ds, "_column_sql") else None


@pytest.mark.parametrize("spelling,expected", [
    ("default_now", "NOW()"),
    ("default_utcnow", "NOW()"),
    ("default_current_timestamp", "CURRENT_TIMESTAMP"),
    ("default_uuid", "gen_random_uuid()"),
])
def test_the_underscore_form_is_translated(spelling, expected):
    out = ds._DEFAULT_UNDERSCORE_989.sub(
        lambda m: "default " + ds._DEFAULT_UNDERSCORE_MAP_989[m.group(1).lower()],
        f"timestamp {spelling}")
    assert out == f"timestamp default {expected}"
    assert f"default_{spelling.split('default_')[1]}" not in out, (
        "the underscore token itself must be gone from the rendered type")


def test_case_is_ignored():
    out = ds._DEFAULT_UNDERSCORE_989.sub(
        lambda m: "default " + ds._DEFAULT_UNDERSCORE_MAP_989[m.group(1).lower()],
        "TIMESTAMP DEFAULT_NOW")
    assert "NOW()" in out


def test_an_unknown_underscore_default_is_left_alone():
    """Deliberate: a silently wrong default is worse than a loud syntax error. `default_foo`
    must keep failing until someone decides what it means."""
    src = "timestamp default_foo"
    assert ds._DEFAULT_UNDERSCORE_989.sub("X", src) == src


def test_the_spaced_form_is_untouched():
    """The existing `default <value>` path must not be disturbed."""
    src = "timestamp default now()"
    assert ds._DEFAULT_UNDERSCORE_989.sub("X", src) == src


def test_a_plain_type_is_untouched():
    assert ds._DEFAULT_UNDERSCORE_989.sub("X", "integer") == "integer"


def test_the_control_leaves_the_token_in_the_type():
    """Planted control: the PRE-FIX extraction could not see the underscore form, which is
    how it reached postgres."""
    import re
    assert re.search(r"\bdefault\b\s+(.+)$", "timestamp default_now") is None, (
        "the control was supposed to miss it; if \\bdefault\\b matches default_now, this "
        "fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
