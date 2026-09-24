"""FIX #218 — one bad seed row must not nuke a whole table.

The loader adds a table's rows then does ONE per-TABLE commit; a single row that
violates a constraint at commit (a FK to a missing parent — the code comment
cites posts_user_id_fkey; a duplicate PK; a NOT NULL that coercion/backfill can't
reach) fails the whole commit → rollback → 0 rows → that surface is empty forever
(business_chain 404 wedge / 'No data yet'). #213 (type coercion) and #217
(user email/name backfill) fix the KNOWN causes, but any UNFORESEEN per-row
violation still empties the table. Isolate each insert in a SAVEPOINT
(begin_nested + flush) so only the offending row is dropped and every valid row
lands. Seed analog of #210's robust staging. Env-agnostic.
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
    "items": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "label", "type": "text"}]},
}

# items has a DUPLICATE pk (id=1 twice) — a stand-in for any per-row constraint
# violation. Today the whole-table commit fails on it → 0 items. Valid rows (1, 2)
# must survive; only the duplicate is dropped.
_SEED = {
    "users": [{"id": 1, "email": "a@x.com", "name": "A"}],
    "items": [
        {"id": 1, "label": "first"},
        {"id": 1, "label": "dup — must be dropped, not nuke the table"},
        {"id": 2, "label": "second"},
    ],
}


def _seed_items(tmp_path):
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
        labels = sorted(x.label for x in s.query(models_mod.Item).all())
    finally:
        s.close()
        for m in ("database", "models"):
            sys.modules.pop(m, None)
    return labels


def test_valid_rows_survive_a_bad_sibling(tmp_path):
    labels = _seed_items(tmp_path)
    # today: 0 items (dup PK failed the whole-table commit). Must be the 2 valid rows.
    assert len(labels) == 2, f"the bad row nuked the whole table: {labels}"
    assert "first" in labels and "second" in labels
