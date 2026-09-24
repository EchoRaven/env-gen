"""FIX #217 — the seed loader must backfill the spine-required NOT NULL user
columns (email, name), or a dataset that omits them loads ZERO users.

r18 live "No data yet" ROOT CAUSE: the real TikTok dataset (seed_dataset.json)
carried users with only username/display_name/avatar — NO `email`, NO `name`.
The spine `users` table types both `NOT NULL`. The loader backfills password_hash
+ tenant_id but not email/name, and the per-TABLE commit means one NOT NULL
violation rolls back EVERY user → 0 users. In postgres every FK child then fails
(videos.author_id → users) → the whole app reads empty AND login is impossible.
Backfill email (from username, else user<id>@seed.local) and name (from
display_name/username/id), deterministic + unique-friendly. Env-agnostic: the
spine is fixed, and real datasets/agent seeds routinely omit these internal cols.
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

# a minimal contract; render adds the spine user cols (email/name/... NOT NULL).
_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "username", "type": "text"},
        {"name": "display_name", "type": "text"}]},
    "videos": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "author_id", "type": "integer", "references": "users.id"},
        {"name": "caption", "type": "text"}]},
}

# the r18 shape: users WITHOUT email/name (only username/display_name).
_SEED = {
    "users": [
        {"id": 1, "username": "@alice", "display_name": "Alice"},
        {"id": 2, "username": "@bob", "display_name": "Bob"},
    ],
    "videos": [{"id": 1, "author_id": 1, "caption": "hi"}],
}


def _seed_and_count(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod
    models_mod = types.ModuleType("models")
    exec(compile(render_models(_TABLES), "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    Base.metadata.create_all(eng)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    loader = seed_dir / "seed_data.py"
    loader.write_text(render_seed_data(_TABLES), encoding="utf-8")
    (seed_dir / "seed_data.json").write_text(json.dumps(_SEED), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(loader.read_text(), str(loader), "exec"), ns)
    ns["seed_if_empty"]()
    s = db_mod.SessionLocal()
    try:
        users = s.query(models_mod.User).all()
        rows = [(u.email, u.name, getattr(u, "username", None)) for u in users]
    finally:
        s.close()
        for m in ("database", "models"):
            sys.modules.pop(m, None)
    return rows


def test_users_without_email_name_still_load(tmp_path):
    rows = _seed_and_count(tmp_path)
    # r18 loaded 0 here (NOT NULL email → whole-table rollback). Both must land.
    assert len(rows) == 2, f"users lost to NOT NULL email/name: {rows}"


def test_backfilled_email_is_present_and_unique(tmp_path):
    rows = _seed_and_count(tmp_path)
    emails = [r[0] for r in rows]
    assert all(e for e in emails), f"email not backfilled: {emails}"
    assert len(set(emails)) == len(emails), f"emails not unique: {emails}"


def test_backfilled_name_present(tmp_path):
    rows = _seed_and_count(tmp_path)
    assert all(n for _, n, _ in rows), f"name not backfilled: {rows}"
    # name derives from display_name when available
    names = {r[2]: r[1] for r in rows}  # username -> name
    assert names.get("@alice") == "Alice"
