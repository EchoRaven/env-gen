"""FIX #156 (§6-4) — nested list/dict dataset values vs String columns (gmrun3: routes 0 rows).

gmrun3's real dataset shipped ``routes.json`` whose ``steps`` field is a nested
list-of-dict; the contract typed the column ``text`` → ``Column(Text)``. At seed time the
driver cannot adapt a Python list to a String parameter, the INSERT dies at the per-table
commit, and the rollback drops EVERY row of that table — routes shipped 0/8 while all
flat tables landed. The loader must JSON-serialize a nested value ONLY when the target
column is String/Text; a native JSON column keeps the structured value (danger list:
don't touch what belongs structured). LOCAL-ONLY (agent/tests/ gitignored).
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
    # the gmrun3 shape: steps is a nested list-of-dict, the column is TEXT
    "routes": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"},
        {"name": "steps", "type": "text"}]},
    # the danger-list shape: a NATIVE JSON column must keep the structured value
    "layers": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"},
        {"name": "meta", "type": "json"}]},
}

_STEPS_1 = [{"instruction": "Head north on Market St", "distance_m": 120},
            {"instruction": "Turn left onto Valencia St", "distance_m": 480}]
_STEPS_2 = [{"instruction": "Board the N Judah", "stops": [{"id": 5}, {"id": 9}]}]

_DATASET = {
    "routes": [
        {"id": 1, "name": "Market to Valencia", "steps": _STEPS_1},
        {"id": 2, "name": "N Judah leg", "steps": _STEPS_2},
    ],
    "layers": [
        {"id": 1, "name": "transit", "meta": {"kind": "overlay", "zooms": [10, 12]}},
    ],
}


def _boot(tmp_path):
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
    src = render_seed_data(_TABLES)
    loader = seed_dir / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    # the F2 dual-source REAL-dataset channel — exactly how gmrun3's routes arrived
    (seed_dir / "seed_dataset.json").write_text(json.dumps(_DATASET), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    ns["seed_if_empty"]()
    s = db_mod.SessionLocal()
    try:
        routes = [(r.id, r.name, r.steps) for r in s.query(models_mod.Route).order_by(
            models_mod.Route.id).all()]
        layers = [(r.id, r.meta) for r in s.query(models_mod.Layer).all()]
    finally:
        s.close()
        for m in ("database", "models"):
            sys.modules.pop(m, None)
    return routes, layers


def test_nested_list_of_dict_rows_insert_into_text_column(tmp_path):
    routes, _ = _boot(tmp_path)
    # gmrun3 shipped 0/8 here: the whole-table commit rolled back on the first
    # unadaptable nested value. Both rows must land.
    assert len(routes) == 2, f"routes rows lost (gmrun3 class): {routes}"


def test_text_column_value_is_roundtrippable_json(tmp_path):
    routes, _ = _boot(tmp_path)
    by_id = {r[0]: r for r in routes}
    assert isinstance(by_id[1][2], str)
    assert json.loads(by_id[1][2]) == _STEPS_1
    assert json.loads(by_id[2][2]) == _STEPS_2


def test_native_json_column_keeps_structured_value(tmp_path):
    _, layers = _boot(tmp_path)
    assert len(layers) == 1
    meta = layers[0][1]
    # the ORM JSON type round-trips a dict — the loader must NOT pre-stringify it
    assert isinstance(meta, dict) and meta == {"kind": "overlay", "zooms": [10, 12]}


def test_scalar_values_untouched(tmp_path):
    routes, _ = _boot(tmp_path)
    assert routes and routes[0][1] == "Market to Valencia"


# --------------------------- real-archive empiricism ---------------------------

_GM3_SEED = (ROOT.parent / "generated" /
             "googlemaps-core-di.SUCCESS-gmrun3-3milestones-realdata" /
             "app" / "backend" / "seed_dataset.json")


def test_gmrun3_real_routes_dataset_all_rows_insert(tmp_path):
    """The ACTUAL gmrun3 dataset (8 OSM routes, steps = list-of-dict) through the real
    rendered loader against the run-3 column shape (steps TEXT) — 0/8 landed live; all
    8 must land now, JSON round-trippable."""
    import pytest as _pytest
    if not _GM3_SEED.exists():
        _pytest.skip("gmrun3 archive not on this host")
    real_routes = json.loads(_GM3_SEED.read_text(encoding="utf-8")).get("routes") or []
    assert len(real_routes) == 8

    tables = {
        "users": _TABLES["users"],
        "routes": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "origin_place_id", "type": "integer"},
            {"name": "dest_place_id", "type": "integer"},
            {"name": "mode", "type": "text"},
            {"name": "duration_min", "type": "integer"},
            {"name": "distance_km", "type": "float"},
            {"name": "steps", "type": "text"}]},
    }
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod
    models_mod = types.ModuleType("models")
    exec(compile(render_models(tables), "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    Base.metadata.create_all(eng)
    seed_dir = tmp_path / "backend"
    seed_dir.mkdir(exist_ok=True)
    src = render_seed_data(tables)
    loader = seed_dir / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    (seed_dir / "seed_dataset.json").write_text(
        json.dumps({"routes": real_routes}), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    try:
        ns["seed_if_empty"]()
        s = db_mod.SessionLocal()
        try:
            rows = s.query(models_mod.Route).all()
            assert len(rows) == 8, f"expected all 8 real routes, got {len(rows)}"
            for r in rows:
                assert isinstance(r.steps, str) and isinstance(json.loads(r.steps), list)
        finally:
            s.close()
    finally:
        for m in ("database", "models"):
            sys.modules.pop(m, None)
