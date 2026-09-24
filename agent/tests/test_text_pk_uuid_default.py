"""A TEXT/UUID primary key gets a Python-side UUID default (outlook run-24, 2026-07-01).

An Integer PK autoincrements (SERIAL); a TEXT/UUID PK has NO auto-generator, so the projected
create handler's ``Model(**valid)`` (which never sets id — id isn't a body field) inserts a NULL
id → ``NotNullViolation: null value in column "id"`` → EVERY POST create 500s. Runs 21/23/24 all
used text ids and died on creates here. render_models now gives a text/uuid PK
``default=lambda: str(_uuid.uuid4())`` so the ORM generates the id on insert, by construction;
Integer PKs are untouched. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_models  # noqa: E402


def _class_block(src, name):
    assert f"class {name}" in src, name
    return src.split(f"class {name}")[1].split("\nclass ")[0]


def _id_line(block):
    return next(l.strip() for l in block.splitlines() if l.strip().startswith("id = Column"))


def test_text_pk_gets_uuid_default_integer_pk_does_not():
    src = render_models({
        "messages": {"columns": [{"name": "id", "type": "text", "primary_key": True},
                                 {"name": "subject", "type": "text"}]},
        "notes":    {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                                 {"name": "body", "type": "text"}]},
    })
    compile(src, "models.py", "exec")
    assert "import uuid as _uuid" in src
    msg = _id_line(_class_block(src, "Message"))
    note = _id_line(_class_block(src, "Note"))
    assert "default=lambda: str(_uuid.uuid4())" in msg, msg    # text PK → uuid default
    assert "Text" in msg
    assert "default=lambda: str(_uuid.uuid4())" not in note, note  # int PK → autoincrement, no default
    assert "Integer" in note


def test_varchar_and_uuid_typed_pk_also_get_default():
    src = render_models({
        "a": {"columns": [{"name": "id", "type": "varchar", "primary_key": True}]},
        "b": {"columns": [{"name": "id", "type": "uuid", "primary_key": True}]},
    })
    for cls in ("A", "B"):
        assert "default=lambda: str(_uuid.uuid4())" in _id_line(_class_block(src, cls))


def test_default_generates_a_real_uuid_on_orm_insert():
    """Exec the generated models against in-memory sqlite and confirm a text-PK row gets a
    non-null generated id when inserted WITHOUT one (the projected create path)."""
    src = render_models({
        "widgets": {"columns": [{"name": "id", "type": "text", "primary_key": True},
                                {"name": "name", "type": "text"}]},
    })
    ns = {}
    # database.Base backed by in-memory sqlite so create_all + a real insert work
    from sqlalchemy.orm import declarative_base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    Base = declarative_base()
    eng = create_engine("sqlite://")
    import types
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    sys.modules["database"] = db_mod
    try:
        exec(compile(src, "models.py", "exec"), ns)
        Base.metadata.create_all(eng)
        Widget = ns["Widget"]
        s = sessionmaker(bind=eng)()
        w = Widget(name="hi")             # NO id supplied — the create-handler path
        s.add(w); s.commit(); s.refresh(w)
        assert w.id and isinstance(w.id, str) and len(w.id) >= 32   # a real uuid was generated
    finally:
        sys.modules.pop("database", None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
