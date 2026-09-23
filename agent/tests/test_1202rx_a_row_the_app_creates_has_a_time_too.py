r"""#1202rx: a projected created_at fills itself, so a row the APP creates has a time too.

`#1202rw` fixed the seed. That leaves the sharper half of the same tell: the column is emitted
as a bare `Column(DateTime)` with no default, and in 129 of the 149 corpus runs carrying such
a column NO handler assigns one either. A comment a test user posts therefore lands with
created_at NULL and renders as "None" (r131, r115) or as 1/1/1970 (instagram-run77) right
beside seeded rows that now DO carry a date -- so the seed fix makes this contrast more
visible, not less. The two belong together.

This is `#97`'s construction (a `*_count` integer defaults to 0 so handler code can never meet
a NULL counter) applied to the other column family that has an unambiguous safe default, and
it reuses the rendering path `#407` already proved: `default="now()"` becomes
`default=datetime.utcnow` + `server_default=_sa_text('now()')` in models.py and `DEFAULT now()`
in the DDL. `#407` itself only fires for a NOT NULL column, and every corpus occurrence of
created_at is nullable -- so it never fired on the ones that matter.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _render_column as orm
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _record_timestamp_default_1202rx, _render_column as ddl)


# --- the ORM side --------------------------------------------------------------------

@pytest.mark.parametrize("name", ["created_at", "updated_at"])
def test_a_lifecycle_timestamp_fills_itself(name):
    line = orm({"name": name, "type": "timestamp"})
    assert "default=datetime.utcnow" in line
    assert "server_default=_sa_text('now()')" in line


def test_the_emitted_module_already_imports_what_that_default_needs():
    """`default=datetime.utcnow` is a NameError at import time without this line, and a
    models.py that cannot import takes the whole backend with it."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton

    assert "from datetime import datetime" in inspect.getsource(backend_skeleton)


def test_an_author_supplied_default_is_never_replaced():
    line = orm({"name": "created_at", "type": "timestamp", "default": "2020-01-01"})
    assert "datetime.utcnow" not in line and "2020-01-01" in line


# --- the DDL side --------------------------------------------------------------------

def test_the_ddl_carries_the_same_default():
    """A raw INSERT that omits the column must get a time too -- an ORM-side default never
    reaches the DDL."""
    assert 'DEFAULT now()' in ddl("t", {"name": "created_at", "type": "timestamp"})


def test_the_function_default_is_not_quoted_into_a_string():
    """`DEFAULT 'now()'` on a timestamp column is a type error Postgres rejects at CREATE
    TABLE, which wedges docker_up for the whole run."""
    assert "'now()'" not in ddl("t", {"name": "created_at", "type": "timestamp"})


def test_an_embedded_default_is_not_doubled():
    """`"created_at" TIMESTAMPTZ DEFAULT now() DEFAULT now()` is 'multiple default values
    specified for column' -- the netflix docker_up killer the #97 path already guards."""
    line = ddl("t", {"name": "created_at", "type": "timestamp default now()"})
    assert line.count("DEFAULT") == 1, line


# --- what it refuses -----------------------------------------------------------------

@pytest.mark.parametrize("name", ["read_at", "ended_at", "started_at", "last_message_at",
                                  "deleted_at", "expires_at", "last_watched_at"])
def test_a_null_that_carries_meaning_gets_no_default(name):
    """read_at null means unread, ended_at null means still live, deleted_at null means the
    row is alive. A default here seeds every notification already read.

    Corpus counts for these: last_message_at on 36 tables, started_at 16, read_at 16.
    """
    assert "datetime.utcnow" not in orm({"name": name, "type": "timestamp"})
    assert "DEFAULT" not in ddl("t", {"name": name, "type": "timestamp"})


def test_a_content_date_gets_no_default():
    assert "DEFAULT" not in ddl("t", {"name": "release_date", "type": "date"})


def test_a_non_temporal_column_is_untouched():
    assert _record_timestamp_default_1202rx({"name": "created_at", "type": "text"}) == {
        "name": "created_at", "type": "text"}


def test_a_primary_key_or_foreign_key_is_untouched():
    for extra in ({"primary_key": True}, {"references": "users.id"}, {"fk": "users.id"}):
        col = dict({"name": "created_at", "type": "timestamp"}, **extra)
        assert _record_timestamp_default_1202rx(col) == col


def test_malformed_input_passes_through():
    assert _record_timestamp_default_1202rx(None) is None
    assert _record_timestamp_default_1202rx("x") == "x"
    assert _record_timestamp_default_1202rx({}) == {}


# --- one list, two renderers ---------------------------------------------------------

def test_both_sides_read_the_same_list_as_the_seed_fix():
    """One fact, many emitters: the seed pass and both renderers must agree on which
    columns are lifecycle timestamps, or a column gets a default whose seed stays null.
    """
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import database_scaffold
    from env_generator.llm_generator.multi_agent.runtime.material_prep import (
        _RECORD_TIME_NAMES_1202RW)

    src = inspect.getsource(database_scaffold._record_timestamp_default_1202rx)
    assert "_RECORD_TIME_NAMES_1202RW" in src, "the list was copied instead of imported"
    for name in _RECORD_TIME_NAMES_1202RW:
        assert "datetime.utcnow" in orm({"name": name, "type": "timestamp"})
