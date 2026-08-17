"""#552 — deterministic Top-N ranking seed enrichment.

The generated projector already emits Netflix-signature Top-10 rank numerals /
"#N in X Today" badges + a data-derived Top-10 rail (frontend_scaffold #455/#531),
but they gate on a row's ``top10_rank``/``rank`` being non-null and the REAL
design-prep dataset (design/dataset/*.json → seed_dataset.json) leaves those declared
columns NULL — so every ranked treatment renders NOTHING (verified live: GET
/api/titles → top10_rank null, trending_score null). ``enrich_ranking_seed`` fills a
DECLARED-but-unseeded ranking column at authoring time so the delivered DB carries
real ranks. Keyed off the SCHEMA (not the table/product name), deterministic, and
byte-identical when the column isn't declared or is already author-populated.
"""
import copy
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    enrich_ranking_seed,
    model_schema_from_models_py,
)

# a schema that DECLARES an int/nullable rank column + a float trending column
_SCHEMA = {
    "titles": {
        "id": {"type": "integer", "nullable": False, "pk": True},
        "name": {"type": "string", "nullable": False, "pk": False},
        "top10_rank": {"type": "integer", "nullable": True, "pk": False},
        "trending_score": {"type": "float", "nullable": True, "pk": False},
    }
}


def _titles(n):
    return {"titles": [{"id": i, "name": "T%d" % i} for i in range(1, n + 1)]}


def test_declared_null_rank_assigns_1_to_n():
    ds = _titles(15)  # 15 rows, ranks null, ordered by id
    out = enrich_ranking_seed(ds, _SCHEMA)
    ranks = [r.get("top10_rank") for r in out["titles"]]
    assert ranks[:10] == list(range(1, 11)), ranks
    assert all(r is None for r in ranks[10:]), "only the first N≈10 rows get a rank"


def test_deterministic_across_two_calls():
    a = enrich_ranking_seed(_titles(12), copy.deepcopy(_SCHEMA))
    b = enrich_ranking_seed(_titles(12), copy.deepcopy(_SCHEMA))
    assert a == b, "same input → same ranks (no clock/random)"


def test_idempotent_when_reapplied():
    ds = _titles(12)
    once = copy.deepcopy(enrich_ranking_seed(ds, _SCHEMA))
    twice = enrich_ranking_seed(ds, _SCHEMA)  # re-run over the already-enriched dict
    assert once == twice, "re-running preserves the ranks it set (author-safe path)"


def test_no_rank_column_is_byte_identical_noop():
    schema = {"titles": {
        "id": {"type": "integer", "nullable": False, "pk": True},
        "name": {"type": "string", "nullable": False, "pk": False},
    }}
    ds = _titles(5)
    before = copy.deepcopy(ds)
    out = enrich_ranking_seed(ds, schema)
    assert out == before, "no declared rank column → byte-identical"


def test_unknown_table_schema_is_noop():
    ds = _titles(5)
    before = copy.deepcopy(ds)
    out = enrich_ranking_seed(ds, {})  # no schema at all
    assert out == before


def test_non_int_rank_column_is_skipped():
    # a rank must be an integer ordinal — a String "rank" is not enriched
    schema = {"titles": {"id": {"type": "integer", "nullable": False, "pk": True},
                         "rank": {"type": "string", "nullable": True, "pk": False}}}
    ds = _titles(3)
    before = copy.deepcopy(ds)
    assert enrich_ranking_seed(ds, schema) == before


def test_author_provided_ranks_are_preserved():
    ds = {"titles": [{"id": 1, "top10_rank": 5}, {"id": 2}, {"id": 3}]}
    before = copy.deepcopy(ds)
    out = enrich_ranking_seed(ds, _SCHEMA)
    assert out == before, "any non-null rank → whole table preserved, never overwritten"


def test_trending_score_populated_descending_when_null():
    out = enrich_ranking_seed(_titles(4), _SCHEMA)
    ts = [r.get("trending_score") for r in out["titles"]]
    # rank r → trending = top_n - r + 1 = 10, 9, 8, 7 (descending, matches rank order)
    assert ts == [10.0, 9.0, 8.0, 7.0], ts
    assert all(isinstance(v, float) for v in ts), "float column → float values"


def test_trending_desc_is_the_order_signal_when_present():
    # when trending is already populated it drives the rank order (desc), and is not clobbered
    ds = {"titles": [
        {"id": 1, "trending_score": 10.0},
        {"id": 2, "trending_score": 90.0},
        {"id": 3, "trending_score": 50.0},
    ]}
    out = enrich_ranking_seed(ds, _SCHEMA)
    by_id = {r["id"]: r["top10_rank"] for r in out["titles"]}
    assert by_id == {2: 1, 3: 2, 1: 3}, by_id
    kept = {r["id"]: r["trending_score"] for r in out["titles"]}
    assert kept == {1: 10.0, 2: 90.0, 3: 50.0}, "existing trending values preserved"


def test_generalizes_to_any_table_and_rank_name():
    # keys off the DECLARED column, not "titles"/"netflix": any table + *_rank column
    schema = {"leaderboard": {
        "id": {"type": "integer", "nullable": False, "pk": True},
        "player_rank": {"type": "integer", "nullable": True, "pk": False},
    }}
    ds = {"leaderboard": [{"id": i} for i in range(1, 4)]}
    out = enrich_ranking_seed(ds, schema)
    assert [r["player_rank"] for r in out["leaderboard"]] == [1, 2, 3]


def test_model_schema_parser_extracts_types(tmp_path):
    models_py = tmp_path / "models.py"
    models_py.write_text(
        "from sqlalchemy import Column, Integer, String, Float, Text\n"
        "from database import Base\n\n\n"
        "class Title(Base):\n"
        "    __tablename__ = \"titles\"\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    name = Column(String, nullable=False)\n"
        "    top10_rank = Column(Integer)\n"
        "    trending_score = Column(Float, default=0)\n",
        encoding="utf-8",
    )
    schema = model_schema_from_models_py(models_py)
    t = schema["titles"]
    assert t["id"]["type"] == "integer" and t["id"]["pk"] is True
    assert t["name"]["nullable"] is False
    assert t["top10_rank"]["type"] == "integer" and t["top10_rank"]["nullable"] is True
    assert t["top10_rank"]["pk"] is False
    assert t["trending_score"]["type"] == "float"


def test_end_to_end_seed_dataset_enrichment(tmp_path):
    """Wiring: _ensure_seed_dataset(design/dataset + models.py) → enriched seed_dataset.json."""
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
        _ensure_seed_dataset,
    )
    out_dir = tmp_path / "app_out"
    ds_dir = out_dir / "design" / "dataset"
    ds_dir.mkdir(parents=True)
    (ds_dir / "titles.json").write_text(
        json.dumps([{"id": i, "name": "T%d" % i} for i in range(1, 13)]),
        encoding="utf-8",
    )
    be = out_dir / "app" / "backend"
    be.mkdir(parents=True)
    (be / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String, Float\n"
        "from database import Base\n\n\n"
        "class Title(Base):\n"
        "    __tablename__ = \"titles\"\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    name = Column(String, nullable=False)\n"
        "    top10_rank = Column(Integer)\n"
        "    trending_score = Column(Float, default=0)\n",
        encoding="utf-8",
    )
    assert _ensure_seed_dataset(be, out_dir) is True
    seeded = json.loads((be / "seed_dataset.json").read_text(encoding="utf-8"))
    ranks = [r.get("top10_rank") for r in seeded["titles"]]
    assert ranks[:10] == list(range(1, 11)), ranks
    assert all(r is None for r in ranks[10:])
    assert seeded["titles"][0]["trending_score"] == 10.0
    # re-running is byte-identical (stable fingerprint → no re-seed loop)
    _ensure_seed_dataset(be, out_dir)
    seeded2 = json.loads((be / "seed_dataset.json").read_text(encoding="utf-8"))
    assert seeded2 == seeded


def test_backend_skeleton_imports():
    import importlib
    mod = importlib.import_module(
        "env_generator.llm_generator.multi_agent.runtime.backend_skeleton")
    assert hasattr(mod, "_ensure_seed_dataset")
