"""Fix #61 — models tolerate the _at<->_time datetime naming drift (outlook run-46, live).

A lane authored custom_routes against event.start_time / Event(start_time=...) /
"end_time" while the framework-projected model (from the contract's start_at/
end_at) has start_at/end_at → 'AttributeError: Event object has no attribute
start_time' on read AND an invalid-kwarg error on construct → EVERY events
read/write 500'd → business_chain wedged on GET /api/events/{id} → 500 (run-46
STUCK-ABORT). render_models now emits a SQLAlchemy synonym for the sibling
temporal name (start_at -> start_time, start_time -> start_at) when the sibling
is not already a real column — aliasing read, write, and constructor kwargs.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _temporal_synonym_lines, render_models)


def _cols(*specs):
    return {"columns": [dict(name=n, type=t, **({"primary_key": True} if n == "id" else {}))
                        for n, t in specs]}


# --------------------------------------------------------------- unit
def test_at_gets_time_synonym_and_vice_versa():
    lines = _temporal_synonym_lines([
        {"name": "start_at", "type": "timestamp"},
        {"name": "deadline_time", "type": "datetime"},
    ])
    assert '    start_time = synonym("start_at")' in lines
    assert '    deadline_at = synonym("deadline_time")' in lines


def test_only_temporal_typed_columns():
    lines = _temporal_synonym_lines([
        {"name": "title_at", "type": "text"},      # not a datetime → no synonym
        {"name": "count_time", "type": "integer"},
    ])
    assert lines == []


def test_no_alias_when_sibling_is_a_real_column():
    lines = _temporal_synonym_lines([
        {"name": "start_at", "type": "timestamp"},
        {"name": "start_time", "type": "timestamp"},   # both declared → don't alias
    ])
    assert lines == []


def test_non_suffixed_temporal_column_untouched():
    assert _temporal_synonym_lines([{"name": "timestamp", "type": "datetime"}]) == []
    assert _temporal_synonym_lines([{"name": "created", "type": "datetime"}]) == []


# --------------------------------------------------------- render + exec
def _load_models(src):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine("sqlite://")
    Base = declarative_base()
    dbm = types.ModuleType("database")
    dbm.Base = Base
    dbm.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = dbm
    m = types.ModuleType("models")
    exec(compile(src, "models.py", "exec"), m.__dict__)
    Base.metadata.create_all(eng)
    return m, dbm.SessionLocal()


def test_construct_and_read_via_drift_names_the_run46_case():
    src = render_models({"events": _cols(
        ("id", "integer"), ("user_id", "integer"), ("title", "text"),
        ("start_at", "timestamp"), ("end_at", "timestamp"))})
    assert "from sqlalchemy.orm import synonym" in src
    m, db = _load_models(src)
    # the lane's exact drift: construct with start_time=, read event.start_time
    ev = m.Event(title="Standup", start_time=datetime(2026, 7, 3, 10),
                 end_time=datetime(2026, 7, 3, 11))
    db.add(ev)
    db.commit()
    got = db.query(m.Event).first()
    assert got.start_time == datetime(2026, 7, 3, 10)   # read via synonym
    assert got.start_at == got.start_time               # same underlying column
    assert got.end_time == datetime(2026, 7, 3, 11)
    # filter by the synonym works too (SQLAlchemy resolves it to the column)
    assert db.query(m.Event).filter(m.Event.start_time == datetime(2026, 7, 3, 10)).count() == 1


def test_models_import_clean_with_no_temporal_columns():
    src = render_models({"widgets": _cols(("id", "integer"), ("label", "text"))})
    m, db = _load_models(src)
    assert m.Widget is not None            # imports fine; synonym import unused is harmless


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
