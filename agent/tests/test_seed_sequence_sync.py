"""Fix #56 — seed loader advances SERIAL sequences past explicit seeded ids
(outlook run-41, live 2026-07-02).

The authored seed inserts rows with EXPLICIT integer ids, but the Postgres
SERIAL sequence still sits at its start — and the fingerprint re-seed's
TRUNCATE ... RESTART IDENTITY resets it back to 1 — so every post-seed INSERT
collides with a seeded id: live run-41 wedged api_smoke 6/6 on
`/auth/register -> duplicate key value violates unique constraint "users_pkey"
Key (id)=(2) already exists`. The loader now calls _sync_sequences (setval to
MAX(col)+1 via pg_get_serial_sequence) after applying the seed AND on the
same-fingerprint early-return path (heals a pre-#56 database). sqlite no-ops
(its INTEGER PRIMARY KEY auto-assigns max+1 natively). LOCAL-ONLY
(agent/tests/ gitignored).
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_models, render_seed_data  # noqa: E402

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]},
    "messages": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
        {"name": "subject", "type": "text"}, {"name": "body", "type": "text"}]},
}

_SEED_JSON = {
    "users": [{"id": 1, "email": "demo@example.com", "name": "Demo"},
              {"id": 2, "email": "boss@example.com", "name": "Boss"}],
    "messages": [{"id": i, "user_id": 1, "subject": f"Weekly digest {i}"}
                 for i in range(1, 6)],
}


def _load_loader_module(tmp_path, seed_json, engine_url):
    """Exec the ACTUAL rendered loader against a real engine (sqlite here)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(engine_url)
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod

    models_mod = types.ModuleType("models")
    models_src = render_models(_TABLES)
    models_src = models_src.replace("from database import Base",
                                    "from database import Base")
    exec(compile(models_src, "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    Base.metadata.create_all(eng)

    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    (seed_dir / "seed_data.json").write_text(json.dumps(seed_json), encoding="utf-8")
    loader_path = seed_dir / "seed_data.py"
    loader_path.write_text(render_seed_data(_TABLES), encoding="utf-8")
    mod = types.ModuleType("seed_loader_under_test")
    mod.__file__ = str(loader_path)
    exec(compile(loader_path.read_text(encoding="utf-8"), str(loader_path), "exec"),
         mod.__dict__)
    return mod, eng


def test_rendered_loader_contains_sync_and_both_call_sites():
    src = render_seed_data(_TABLES)
    assert "def _sync_sequences" in src
    assert "pg_get_serial_sequence" in src
    # def-line + the two CALL sites (same-fingerprint early return, post-apply)
    assert src.count("_sync_sequences(db)") == 3, \
        "must run on the same-fingerprint early return AND after a fresh apply"
    # early-return heal must come BEFORE the `return`
    early = src.index("if applied == fp:")
    assert src.index("_sync_sequences(db)", early) < src.index("return", early + 20)


def test_sqlite_apply_and_restart_no_op_cleanly(tmp_path):
    """The whole loader (incl. _sync_sequences on both paths) runs green on
    sqlite — the dialect guard no-ops; inserts after seeding get fresh ids."""
    mod, eng = _load_loader_module(tmp_path, _SEED_JSON, f"sqlite:///{tmp_path}/app.db")
    mod.seed_if_empty()          # fresh apply path (sync after apply)
    mod.seed_if_empty()          # same-fingerprint path (sync on early return)
    import models as m
    db = sys.modules["database"].SessionLocal()
    try:
        db.add(m.User(email="new@example.com", name="N", password_hash="x",
                      tenant_id="default"))
        db.commit()
        ids = [u.id for u in db.query(m.User).all()]
        assert len(ids) == 3 and len(set(ids)) == 3  # no collision, fresh id
    finally:
        db.close()


class _FakeDialectDB:
    """Records execute() SQL; pretends to be a postgresql session."""

    def __init__(self):
        self.sql = []

    def get_bind(self):
        class B:  # noqa: D401
            class dialect:  # noqa: N801
                name = "postgresql"
        return B()

    def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params))
        return types.SimpleNamespace(fetchall=lambda: [], fetchone=lambda: None)

    def commit(self):
        pass

    def rollback(self):
        pass


def test_postgres_path_emits_guarded_setval_per_table(tmp_path):
    mod, _ = _load_loader_module(tmp_path, _SEED_JSON, f"sqlite:///{tmp_path}/pg.db")
    fake = _FakeDialectDB()
    mod._sync_sequences(fake)
    joined = "\n".join(s for s, _ in fake.sql)
    assert 'FROM "users"' in joined and 'FROM "messages"' in joined
    assert "pg_get_serial_sequence" in joined
    assert "WHERE seq IS NOT NULL" in joined       # NULL-sequence (text/uuid PK) guarded
    assert "COALESCE(MAX(" in joined and "+ 1" in joined
    assert "false" in joined                        # is_called=false -> next nextval == max+1


def test_sync_failure_never_raises(tmp_path):
    mod, _ = _load_loader_module(tmp_path, _SEED_JSON, f"sqlite:///{tmp_path}/f.db")

    class _Boom(_FakeDialectDB):
        def execute(self, stmt, params=None):
            raise RuntimeError("db down")

    mod._sync_sequences(_Boom())   # must swallow


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
