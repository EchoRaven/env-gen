"""Fix #63 — physical generated mirror columns for the _at<->_time raw-SQL drift
(outlook run-47, live 2026-07-02).

#61's ORM synonym makes event.start_time work in ORM code, but a lane also wrote
RAW SQL against the _time naming (SELECT * / WHERE start_time / ORDER BY
start_time in get_events) while the contract column is start_at ->
'psycopg.errors.UndefinedColumn: column "start_time" does not exist' -> every
such raw read 500'd (a synonym cannot reach a SQL string). The generated main.py
now runs _ensure_temporal_alias_columns() after create_all: for each temporal
_at/_time column whose sibling name is not physically present, it adds a Postgres
GENERATED-ALWAYS-STORED mirror so the lane's raw SQL works as-written. Postgres-
only, idempotent, best-effort, and coexists with the ORM synonym (a DB column
outside the ORM model). LOCAL-ONLY (agent/tests/ gitignored).
"""

import ast
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_EVENTS = {"events": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
    {"name": "title", "type": "text"},
    {"name": "start_at", "type": "timestamp"},
    {"name": "end_at", "type": "timestamp"},
    {"name": "created_at", "type": "timestamp"}]}}


def test_main_renders_valid_and_routine_before_seed():
    src = render_skeleton_main([{"method": "GET", "path": "/api/events"}], _EVENTS)
    ast.parse(src)
    assert "_ensure_temporal_alias_columns()" in src
    assert "GENERATED ALWAYS AS" in src
    assert "ADD COLUMN IF NOT EXISTS" in src
    # must run AFTER create_all and BEFORE seeding (seed reads the columns)
    assert src.index("create_all") < src.index("_ensure_temporal_alias_columns()")
    assert src.index("_ensure_temporal_alias_columns()") < src.index("seed_if_empty()")


class _RecordingConn:
    def __init__(self, rows):
        self._rows = rows
        self.ddl = []

    def execute(self, stmt, *a, **k):
        s = str(stmt)
        if "information_schema.columns" in s:
            return types.SimpleNamespace(fetchall=lambda: self._rows)
        if "ALTER TABLE" in s:
            self.ddl.append(s)
        return types.SimpleNamespace(fetchall=lambda: [])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Engine:
    def __init__(self, rows, dialect="postgresql"):
        self._conn = _RecordingConn(rows)
        self.dialect = types.SimpleNamespace(name=dialect)

    def begin(self):
        return self._conn


def _run_routine(engine):
    """Extract _ensure_temporal_alias_columns from the rendered main and run it
    against a mock engine (exec the def with `engine` + a text() shim in scope)."""
    src = render_skeleton_main([{"method": "GET", "path": "/api/events"}], _EVENTS)
    start = src.index("def _ensure_temporal_alias_columns():")
    end = src.index("_ensure_temporal_alias_columns()\n", start)
    fn_src = src[start:end]
    ns = {"engine": engine}

    def _text(s):
        return s
    # the function imports `from sqlalchemy import text as _text` — shim the module
    sa = types.ModuleType("sqlalchemy")
    sa.text = _text
    # RESTORE IT. This replaced the real sqlalchemy in sys.modules for the rest of
    # the session: any later test doing `from sqlalchemy import create_engine` got
    # "cannot import name 'create_engine' from 'sqlalchemy' (unknown location)" —
    # unknown because the stub has no __file__. test_temporal_synonym and
    # test_text_pk_uuid_default pass alone and failed in-suite for exactly this,
    # and the blast radius was however many tests happened to run after.
    _prev = sys.modules.get("sqlalchemy")
    sys.modules["sqlalchemy"] = sa
    try:
        exec(compile(fn_src, "main_fragment.py", "exec"), ns)
        ns["_ensure_temporal_alias_columns"]()
    finally:
        if _prev is not None:
            sys.modules["sqlalchemy"] = _prev
        else:
            sys.modules.pop("sqlalchemy", None)
    return engine._conn.ddl


def test_postgres_adds_mirror_for_at_columns_without_sibling():
    rows = [("events", "start_at", "timestamp without time zone"),
            ("events", "end_at", "timestamp without time zone"),
            ("events", "created_at", "timestamp without time zone"),
            ("events", "title", "text")]
    ddl = _run_routine(_Engine(rows))
    joined = "\n".join(ddl)
    assert 'ADD COLUMN IF NOT EXISTS "start_time"' in joined
    assert 'GENERATED ALWAYS AS ("start_at") STORED' in joined
    assert 'ADD COLUMN IF NOT EXISTS "end_time"' in joined
    assert 'ADD COLUMN IF NOT EXISTS "created_time"' in joined
    assert "title" not in joined              # non-temporal untouched


def test_no_mirror_when_sibling_already_present():
    rows = [("events", "start_at", "timestamp without time zone"),
            ("events", "start_time", "timestamp without time zone")]  # both exist
    ddl = _run_routine(_Engine(rows))
    assert ddl == []


def test_reverse_direction_time_to_at():
    rows = [("logs", "logged_time", "timestamp without time zone")]
    ddl = _run_routine(_Engine(rows))
    assert 'ADD COLUMN IF NOT EXISTS "logged_at"' in "\n".join(ddl)
    assert 'GENERATED ALWAYS AS ("logged_time") STORED' in "\n".join(ddl)


def test_sqlite_noops():
    rows = [("events", "start_at", "datetime")]
    ddl = _run_routine(_Engine(rows, dialect="sqlite"))
    assert ddl == []


def test_non_temporal_at_suffix_ignored():
    rows = [("orders", "shipped_at", "integer"),      # not a temporal type
            ("orders", "flat_rate", "numeric")]
    ddl = _run_routine(_Engine(rows))
    assert ddl == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
