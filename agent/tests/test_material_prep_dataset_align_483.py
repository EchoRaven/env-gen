"""#483 — dataset↔contract field-name alignment (r55 wedge, live). design-prep's REAL
dataset uses domain field names (name/synopsis/kind/year/poster/backdrop/rating), but the
contract-projected ORM model's column names are NON-DETERMINISTIC across runs (netflix r54:
titles.`name` → CONVERGED 10/10; r55: titles.`title` → 0 titles seeded from a 60-title
dataset → title chains 404 → 0 release). ROOT: the seed loader keeps only fields that are
model columns (`hasattr(cls,k)`), so a diverged name leaves the NOT-NULL column unset → every
row silently fails its per-row insert → empty table. FIX: before staging seed_dataset.json,
map dataset fields onto the model's column names via synonym groups — ADDITIVE + best-effort
(fills an UNSET model column from a droppable synonym; a run whose names already match is
byte-identical; worst case is a no-op, never a regression)."""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    model_columns_from_models_py, align_dataset_field_names)


_R55_MODELS = '''\
from sqlalchemy import Column, Integer, String, Text
from db import Base

class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    type = Column(String)
    release_year = Column(Integer)
    poster_url = Column(String)
    backdrop_url = Column(String)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
'''


def _cols(tmp):
    p = Path(tmp) / "models.py"
    p.write_text(_R55_MODELS, encoding="utf-8")
    return model_columns_from_models_py(p)


def test_model_columns_parse():
    with tempfile.TemporaryDirectory() as tmp:
        cols = _cols(tmp)
        assert cols.get("titles") == {"id", "title", "description", "type",
                                      "release_year", "poster_url", "backdrop_url"}, cols
        assert cols.get("users") == {"id", "email"}


def test_r55_style_remaps_dataset_names_to_contract_columns():
    # dataset uses domain names; model uses contract names → remap so the row carries `title`
    cols = {"titles": {"id", "title", "description", "type", "release_year",
                       "poster_url", "backdrop_url"}}
    ds = {"titles": [{"id": 11, "name": "Inception", "synopsis": "A heist.",
                      "kind": "movie", "year": 2010, "poster": "/p/11.jpg",
                      "backdrop": "/b/11.jpg"}]}
    out = align_dataset_field_names(ds, cols)
    r = out["titles"][0]
    assert r["title"] == "Inception", "#483: titles.title (NOT-NULL) filled from dataset `name` → row no longer dropped"
    assert r["description"] == "A heist." and r["type"] == "movie"
    assert r["release_year"] == 2010 and r["poster_url"] == "/p/11.jpg" and r["backdrop_url"] == "/b/11.jpg"


def test_r54_style_matching_names_is_byte_identical():
    # model already uses the dataset's `name`/`kind` → NOTHING to remap (no regression)
    cols = {"titles": {"id", "name", "kind", "synopsis", "year", "poster", "backdrop"}}
    ds = {"titles": [{"id": 1, "name": "Dune", "kind": "movie", "synopsis": "Sand."}]}
    import copy
    before = copy.deepcopy(ds)
    out = align_dataset_field_names(ds, cols)
    assert out == before, "#483: matching names → byte-identical (additive fix never touches a working seed)"


def test_never_overwrites_a_set_target_or_cannibalizes_own_column():
    # target already set → keep it; and a synonym that IS its own column is never moved
    cols = {"titles": {"id", "title", "name"}}  # BOTH title and name are real columns
    ds = {"titles": [{"id": 1, "title": "Real", "name": "AltName"}]}
    out = align_dataset_field_names(ds, cols)
    r = out["titles"][0]
    assert r["title"] == "Real", "#483: never overwrite an already-set target"
    assert r["name"] == "AltName", "#483: never cannibalize a field that is its own model column"


def test_best_effort_on_bad_input():
    assert align_dataset_field_names(None, {}) is None
    assert align_dataset_field_names({"t": "notalist"}, {"t": {"a"}}) == {"t": "notalist"}
    assert model_columns_from_models_py("/nonexistent/models.py") == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
