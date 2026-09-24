"""FIX #158 (gmrun6 boot crash) — a dataset column named after a Python keyword.

gmrun6 died at backend boot: the real transit_lines dataset has a column ``from`` (OSM
line origin). F2b binds the backend to build the table with the dataset's exact columns,
so the SchemaHub carried a column literally named ``from``; ``_render_column`` emitted
``    from = Column(Text)`` → ``SyntaxError: invalid syntax`` in models.py → ``import
models`` fails → the backend crashes on every boot → backend_health never 200 → wedge.
(run-3/4 never bound ``from`` into their schema, so it never surfaced; F2b exposed it.)
Fifth real-dataset-landing lesson (after: ingest channel / dual-source survival / schema-
binding / integer id).

The whole pipeline must use ONE sanitize (backend_skeleton.safe_column_name): a Python
keyword or non-identifier column name → a safe identifier, applied at render (the
syntactic safety net, covers ANY source incl. a lane self-authored reserved-word column),
at the dataset→requirements binding, and at seed-dataset key assembly — so the ORM
attribute, the DB column, and the seed key stay equal and data still lands.
LOCAL-ONLY (agent/tests/ gitignored).
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

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    safe_column_name, render_models, render_seed_data)


# ------------------------------ safe_column_name ------------------------------

def test_keyword_columns_get_trailing_underscore():
    assert safe_column_name("from") == "from_"
    assert safe_column_name("class") == "class_"
    assert safe_column_name("import") == "import_"
    assert safe_column_name("return") == "return_"
    assert safe_column_name("global") == "global_"
    assert safe_column_name("None") == "None_"


def test_ordinary_names_untouched():
    for n in ("name", "user_id", "from_stop", "to", "created_at", "id", "type", "steps"):
        assert safe_column_name(n) == n, n


def test_idempotent():
    for n in ("from", "class", "2way", "a-b"):
        once = safe_column_name(n)
        assert safe_column_name(once) == once, n


def test_invalid_identifiers_become_valid():
    assert safe_column_name("2way").isidentifier()
    assert safe_column_name("a-b") == "a_b"
    assert safe_column_name("name!") .isidentifier()
    assert safe_column_name("") == "col"


# ------------------------------ render_models ------------------------------

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]},
    # the gmrun6 shape: a keyword column `from` alongside an ordinary `to`
    "transit_lines": {"columns": [
        {"name": "id", "type": "text", "primary_key": True},
        {"name": "from", "type": "text"},
        {"name": "to", "type": "text"},
        {"name": "name", "type": "text"}]},
}


def test_render_models_with_keyword_column_is_valid_python():
    src = render_models(_TABLES)
    # gmrun6 died exactly here — compile must NOT raise SyntaxError
    compile(src, "models.py", "exec")
    assert "from = Column" not in src  # the raw keyword form is gone
    assert "from_ = Column" in src     # replaced by the safe attribute


def test_render_models_keeps_ordinary_neighbor():
    src = render_models(_TABLES)
    assert "\n    to = Column" in src  # `to` is not a keyword — untouched


# ------------------------- seed loader round-trip -------------------------

def test_keyword_column_seed_data_lands_via_dataset(tmp_path):
    """End-to-end: a seed_dataset row whose key is the (sanitized) attribute name
    inserts into the DB — the attribute the ORM exposes is `from_`, so the seed key
    must be `from_` and the value must be readable back."""
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
    # assemble_seed_dataset sanitizes the key → `from_` (== the ORM attribute)
    (seed_dir / "seed_dataset.json").write_text(json.dumps({
        "transit_lines": [{"id": "L1", "from_": "Powell St", "to": "Embarcadero",
                           "name": "N Judah"}]}), encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    try:
        ns["seed_if_empty"]()
        s = db_mod.SessionLocal()
        try:
            rows = s.query(models_mod.TransitLine).all()
            assert len(rows) == 1, "the keyword-column row must land"
            assert getattr(rows[0], "from_") == "Powell St"
            assert rows[0].to == "Embarcadero"
        finally:
            s.close()
    finally:
        for m in ("database", "models"):
            sys.modules.pop(m, None)


# ------------------------- material_prep uses the SAME sanitize -------------------------

def test_material_prep_shares_the_sanitize():
    from multi_agent.runtime import material_prep as mp
    # the dataset column list (feeds the requirements binding block) is sanitized
    dpath = tmp = Path
    d = tmp_path_json = None  # noqa
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "transit_lines.json"
        p.write_text(json.dumps([{"id": "L1", "from": "A", "to": "B", "name": "N"}]))
        cols = mp._dataset_columns(p, "json")
        assert "from_" in cols and "from" not in cols
        assert "to" in cols  # neighbor untouched
        # assemble sanitizes the row keys of the emitted seed dict
        (Path(td) / "d").mkdir()
        p2 = Path(td) / "d" / "transit_lines.json"
        p2.write_text(json.dumps([{"id": "L1", "from": "A", "to": "B"}]))
        out = mp.assemble_seed_dataset(Path(td) / "d")
        assert out["transit_lines"][0].get("from_") == "A"
        assert "from" not in out["transit_lines"][0]


# ------------------------- real gmrun6 archive empiricism -------------------------

_GM6_DS = (ROOT.parent / "generated" /
           "googlemaps-core-di.run6-killed-modelsfromkeyword-syntaxerror" /
           "app" / "backend" / "seed_dataset.json")


def test_gmrun6_archive_transit_lines_renders_valid_after_sanitize():
    import pytest as _pytest
    if not _GM6_DS.exists():
        _pytest.skip("gmrun6 archive not on this host")
    ds = json.loads(_GM6_DS.read_text(encoding="utf-8"))
    tl = ds.get("transit_lines") or []
    assert tl and "from" in tl[0], "the archive's transit_lines carried the raw `from`"
    # build the same-shape contract and prove render is valid now
    cols = [{"name": k, "type": "text"} for k in tl[0].keys()]
    tables = {"users": _TABLES["users"], "transit_lines": {"columns": cols}}
    compile(render_models(tables), "models.py", "exec")
