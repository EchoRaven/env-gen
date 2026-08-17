r"""#808: the staged dataset's ids never matched the PK TYPE the lane declared.

Root-cause half of #807/#807b. The staging pipeline already aligns dataset field **names** to the
model's columns (#483) and fills a declared ranking column (#552). Nothing checked the PK's
**type**.

design-prep emits integer ids. r145 declared `titles.id TEXT PRIMARY KEY`, with every dependent
`title_id TEXT NOT NULL REFERENCES titles(id)`. So the framework wrote integer ids into a text
column and left 93 rows across 5 tables pointing at an id space that no longer existed.

#807b refuses the whole swap when a majority of dependents would be orphaned — which protects the
app but throws away the real domain data the dataset exists to provide. #808 is the other half:
get the type right at staging, so the two sources can agree wherever the values would.

**Deliberately narrow**, because a seed corrupted by an over-eager coercion is worse than a typed
mismatch:
  * only columns the schema marks `pk`, plus `<singular>_id` columns naming a table whose PK was
    coerced — never a free-form data column (a `year` of `"2019"` stays a string if that is what
    the model says);
  * only int↔str, the one mismatch design-prep can actually produce;
  * unknown table / unknown column / unparsable schema → untouched.
"""
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    align_dataset_id_types, model_schema_from_models_py)


_GENERATED = pathlib.Path(__file__).resolve().parents[1] / "generated"

_TEXT_PK = {"titles": {"id": {"type": "text", "nullable": False, "pk": True},
                       "name": {"type": "text", "nullable": False, "pk": False},
                       "year": {"type": "integer", "nullable": True, "pk": False}},
            "episodes": {"id": {"type": "text", "pk": True},
                         "title_id": {"type": "text", "pk": False}}}
_INT_PK = {"titles": {"id": {"type": "integer", "nullable": False, "pk": True},
                      "name": {"type": "text", "pk": False}}}


def test_an_integer_id_becomes_text_for_a_text_pk():
    out = align_dataset_id_types({"titles": [{"id": 1, "name": "A"}]}, _TEXT_PK)
    assert out["titles"][0]["id"] == "1"


def test_a_text_id_becomes_integer_for_an_integer_pk():
    out = align_dataset_id_types({"titles": [{"id": "7", "name": "A"}]}, _INT_PK)
    assert out["titles"][0]["id"] == 7


def test_a_matching_type_is_left_alone():
    """Non-vacuity in the other direction: the common case must be byte-identical."""
    src = {"titles": [{"id": 1, "name": "A"}]}
    assert align_dataset_id_types(src, _INT_PK) == src


def test_a_foreign_key_follows_its_parents_pk():
    out = align_dataset_id_types({"episodes": [{"id": 5, "title_id": 1}]}, _TEXT_PK)
    assert out["episodes"][0]["title_id"] == "1"


def test_a_plain_data_column_is_never_coerced():
    """★ The narrowness is the safety. `year` is an integer column holding an integer; a
    blanket coercion would be the #264 mistake again — repairing one field by corrupting others."""
    out = align_dataset_id_types({"titles": [{"id": 1, "name": "A", "year": 2019}]}, _TEXT_PK)
    assert out["titles"][0]["year"] == 2019
    assert out["titles"][0]["name"] == "A"


def test_a_non_numeric_string_is_not_forced_into_an_integer():
    out = align_dataset_id_types({"titles": [{"id": "tv-stranger-signals"}]}, _INT_PK)
    assert out["titles"][0]["id"] == "tv-stranger-signals"


def test_a_bool_is_not_treated_as_an_integer():
    out = align_dataset_id_types({"titles": [{"id": True}]}, _TEXT_PK)
    assert out["titles"][0]["id"] is True


def test_it_is_idempotent():
    once = align_dataset_id_types({"titles": [{"id": 1}]}, _TEXT_PK)
    assert align_dataset_id_types(once, _TEXT_PK) == once


@pytest.mark.parametrize("dataset,schema", [
    (None, _TEXT_PK), ({"titles": [{"id": 1}]}, None), ("nope", _TEXT_PK),
    ({"titles": "nope"}, _TEXT_PK), ({"other": [{"id": 1}]}, _TEXT_PK),
    ({"titles": [None, 3]}, _TEXT_PK),
])
def test_malformed_input_never_raises_and_never_drops_rows(dataset, schema):
    out = align_dataset_id_types(dataset, schema)
    if isinstance(dataset, dict) and isinstance(out, dict):
        for k, v in dataset.items():
            if isinstance(v, list):
                assert len(out.get(k) or []) == len(v), k


# --- against the real corpus --------------------------------------------------------------------

def _backend(suffix):
    if not _GENERATED.is_dir():
        return None
    for p in sorted(_GENERATED.iterdir()):
        be = p / "app" / "backend"
        if p.name.endswith(suffix) and (be / "models.py").is_file() \
                and (be / "seed_dataset.json").is_file():
            return be
    return None


@pytest.mark.parametrize("suffix,pk,before,after", [
    ("r145", "text", 1, "1"),
    ("r151", "integer", 1, 1),
])
def test_the_real_runs_behave_as_measured(suffix, pk, before, after):
    be = _backend(suffix)
    if be is None:
        pytest.skip(f"{suffix} not present")
    schema = model_schema_from_models_py(be / "models.py")
    assert schema["titles"]["id"]["type"] == pk, "non-vacuity: the two runs really do differ"
    ds = json.loads((be / "seed_dataset.json").read_text(encoding="utf-8"))
    assert ds["titles"][0]["id"] == before
    out = align_dataset_id_types(ds, schema)
    assert out["titles"][0]["id"] == after
    assert len(out["titles"]) == len(ds["titles"]), "no row may be lost"


def test_it_is_wired_into_staging():
    """A correct helper nobody calls is #786's defect — the one this session committed four
    times."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs
    src = inspect.getsource(bs._ensure_seed_dataset)
    assert "align_dataset_id_types" in src
    assert src.index("enrich_ranking_seed(real") < src.index("align_dataset_id_types(real")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
