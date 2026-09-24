"""FIX #130 — the seed loader re-seeds when a seed-PROVIDED content table is EMPTY,
even if ANOTHER business table still has rows (instagram-core-di run-49 M3, live).

The #99 guard skipped re-seeding when ANY seed-managed business table had rows. A
PARTIAL state fools that: a child write-handler that does NOT validate its parent FK
(POST /api/posts/{id}/like → 201 on a NON-EXISTENT post) leaves ORPHAN child rows, so
`likes` is non-empty while `posts` was wiped → seed skipped → posts stays EMPTY → the
repost/like verification chain 404s forever (business_chain wedge; live DB observed
posts=0, comments=0, likes=3). The loader now re-seeds when ANY seed-provided content
table is empty (incomplete), not only when ALL are.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
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

from multi_agent.runtime.backend_skeleton import render_seed_data, render_models  # noqa: E402

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]},
    "posts": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
        {"name": "caption", "type": "text"}]},
    "likes": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "post_id", "type": "integer", "foreign_key": "posts.id"},
        {"name": "user_id", "type": "integer", "foreign_key": "users.id"}]},
}

_AUTHORED = {
    "users": [{"email": "alice@example.com", "name": "Alice"},
              {"email": "bob@example.com", "name": "Bob"}],
    "posts": [{"user_id": 1, "caption": f"Post {i}"} for i in range(4)],
    "likes": [{"post_id": 1, "user_id": 1}, {"post_id": 2, "user_id": 2}],
}


def _make_env(tmp_path):
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
    return eng, db_mod, models_mod


def _boot(tmp_path):
    """One app boot against the SAME sqlite file: render + run the loader."""
    eng, db_mod, models_mod = _make_env(tmp_path)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    src = render_seed_data(_TABLES)
    loader = seed_dir / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    (seed_dir / "seed_data.json").write_text(json.dumps(_AUTHORED), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    ns["seed_if_empty"]()
    s = db_mod.SessionLocal()
    counts = {"users": s.query(models_mod.User).count(),
              "posts": s.query(models_mod.Post).count(),
              "likes": s.query(models_mod.Like).count()}
    s.close()
    for m in ("database", "models"):
        sys.modules.pop(m, None)
    return counts


def _wipe_posts_keep_likes(tmp_path):
    """Simulate the live pollution: posts emptied (reset), likes left as orphans."""
    eng, db_mod, models_mod = _make_env(tmp_path)
    s = db_mod.SessionLocal()
    s.query(models_mod.Post).delete()
    s.commit()
    remaining = {"posts": s.query(models_mod.Post).count(),
                 "likes": s.query(models_mod.Like).count()}
    s.close()
    for m in ("database", "models"):
        sys.modules.pop(m, None)
    return remaining


def test_partial_wipe_reseeds_the_empty_content_table(tmp_path):
    c1 = _boot(tmp_path)
    assert c1["posts"] == 4 and c1["likes"] == 2, c1

    rem = _wipe_posts_keep_likes(tmp_path)
    assert rem["posts"] == 0 and rem["likes"] == 2, rem  # posts empty, likes orphaned

    # boot again (SAME seed source → fingerprint matches). Old _any_rows saw likes!=0
    # → skipped → posts stayed 0. #130 must detect posts empty → re-seed.
    c2 = _boot(tmp_path)
    assert c2["posts"] == 4, f"posts must be RE-SEEDED after partial wipe, got {c2}"


def test_fully_seeded_same_source_is_still_a_noop(tmp_path):
    c1 = _boot(tmp_path)
    c2 = _boot(tmp_path)  # nothing wiped → must NOT duplicate
    assert c2 == c1, (c1, c2)


# ── FIX #135: partial wipe with SURVIVING non-seed rows (instagram run-58) ──

_AUTHORED_IDS = {
    "users": [{"id": 1, "email": "alice@example.com", "name": "Alice"},
              {"id": 2, "email": "bob@example.com", "name": "Bob"}],
    "posts": [{"id": i, "user_id": (i % 2) + 1, "caption": f"Post {i}"}
              for i in range(1, 5)],
    "likes": [{"id": 1, "post_id": 1, "user_id": 1}],
}


def _boot_ids(tmp_path):
    eng, db_mod, models_mod = _make_env(tmp_path)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    src = render_seed_data(_TABLES)
    loader = seed_dir / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    (seed_dir / "seed_data.json").write_text(json.dumps(_AUTHORED_IDS), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    ns["seed_if_empty"]()
    s = db_mod.SessionLocal()
    out = {"user_ids": sorted(u.id for u in s.query(models_mod.User).all()),
           "posts": s.query(models_mod.Post).count()}
    s.close()
    for m in ("database", "models"):
        sys.modules.pop(m, None)
    return out


def test_surviving_test_user_does_not_block_seed_row_restore(tmp_path):
    """run-58 live: after a wipe, TEST-REGISTERED users survive (users non-empty,
    WITHOUT the seed ids) while posts is empty. The old 'table non-empty -> skip'
    skipped users wholesale, so every posts row (user_id=1) died on the FK ->
    silently swallowed -> posts stayed 0 forever. #135 upserts missing seed rows
    BY PK, restoring users 1/2 so the posts re-seed succeeds."""
    c1 = _boot_ids(tmp_path)
    # #74 demo-concentration may clone extra posts onto the demo user (floor=8),
    # so assert the seed CORE, not an exact count.
    assert c1["user_ids"] == [1, 2] and c1["posts"] >= 4, c1

    # wipe: seed users + all posts gone; a test-registered user (id=99) survives
    eng, db_mod, models_mod = _make_env(tmp_path)
    s = db_mod.SessionLocal()
    s.query(models_mod.Post).delete()
    s.query(models_mod.User).filter(models_mod.User.id.in_([1, 2])).delete(
        synchronize_session=False)
    s.add(models_mod.User(id=99, email="test99@x.local", name="T",
                          password_hash="x", tenant_id="default"))
    s.commit()
    # drop the fingerprint too: applied=None -> the loader takes the NO-RESET path
    # (exactly the live shape where _reset_seeded_tables failed/was unavailable and
    # non-seed rows survived) -> the #135 per-row upsert branch is what must save us.
    from sqlalchemy import text as _text
    try:
        s.execute(_text("DELETE FROM _seed_meta"))
        s.commit()
    except Exception:
        s.rollback()
    s.close()
    for m in ("database", "models"):
        sys.modules.pop(m, None)

    c2 = _boot_ids(tmp_path)   # same fingerprint; posts empty -> #130 re-seed path
    assert 1 in c2["user_ids"] and 2 in c2["user_ids"], \
        f"missing seed users must be restored BY PK, got {c2}"
    assert 99 in c2["user_ids"], "surviving test user must NOT be destroyed"
    assert c2["posts"] >= 4, f"posts must re-seed once parents exist, got {c2}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
