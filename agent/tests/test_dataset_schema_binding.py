"""F2b — the real dataset AUTHORITATIVELY drives the contract schema.

googlemaps run-1 (live) shipped a DB whose places table had no `category`/`address`
columns: the backend lane built its own schema from the docs' entity model, never knowing
the real dataset existed, so the 171 real POI rows could not be inserted (column mismatch)
even once seed_dataset.json is present. Fix: design-prep tells every lane the EXACT tables
+ columns the real dataset defines, so the backend builds tables that match the data and
the loader inserts cleanly.

- ingest_dataset manifest carries `columns` (union of the row keys).
- design_system_summary_for_requirements emits a binding DATASET block (table -> columns +
  "build these tables with these EXACT columns; the framework seeds them; you only add
  users + associations").
LOCAL-ONLY (agent/tests/ gitignored).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.material_prep import ingest_dataset  # noqa: E402
from multi_agent.runtime.design_prep import (  # noqa: E402
    build_skeleton_design_system, resolve_design_input, design_system_summary_for_requirements)


def _mk(tmp_path):
    di = tmp_path / "di"
    (di / "references").mkdir(parents=True)
    (di / "references" / "home.png").write_bytes(b"x")
    dd = di / "dataset"
    dd.mkdir()
    (dd / "places.json").write_text(json.dumps([
        {"id": "mels", "name": "Mel's", "category": "restaurant", "lat": 37.8, "lng": -122.4,
         "rating": 4.1, "address": "3355 Geary Blvd"},
        {"id": "johns", "name": "John's", "category": "bar", "lat": 37.79, "lng": -122.41,
         "rating": 4.3, "price_level": 2}]))  # price_level only on row 2 → union
    (dd / "transit_stops.json").write_text(json.dumps([
        {"id": "s1", "name": "Mission & 24th", "lat": 37.75, "lng": -122.41, "mode": "bus"}]))
    return di


def test_manifest_carries_columns(tmp_path):
    di = _mk(tmp_path)
    manifest = ingest_dataset(str(di / "dataset"), str(tmp_path / "stage"))
    # key by file stem = the TABLE name (assemble_seed_dataset uses the stem verbatim);
    # the manifest 'id' is a slug (transit_stops -> transit-stops) for display only.
    by = {Path(m["file"]).stem: m for m in manifest}
    # columns = union of all row keys, order-stable (first-seen)
    assert by["places"]["columns"] == [
        "id", "name", "category", "lat", "lng", "rating", "address", "price_level"]
    assert by["transit_stops"]["columns"] == ["id", "name", "lat", "lng", "mode"]


def test_summary_emits_binding_dataset_schema(tmp_path):
    di = _mk(tmp_path)
    res = resolve_design_input(str(di), None, None)
    ds = build_skeleton_design_system(res, tmp_path / "out")
    summary = design_system_summary_for_requirements(ds)
    assert "DATASET" in summary
    # the exact table name + columns must be stated so the backend builds a matching schema
    assert "places" in summary and "category" in summary and "price_level" in summary
    assert "transit_stops" in summary and "mode" in summary
    # and the seeding contract: framework seeds it, lane must not fight it
    assert "seed_dataset.json" in summary
    assert "EXACT" in summary or "exact" in summary


def test_summary_no_dataset_is_silent(tmp_path):
    di = tmp_path / "di2"
    (di / "references").mkdir(parents=True)
    (di / "references" / "home.png").write_bytes(b"x")
    res = resolve_design_input(str(di), None, None)
    ds = build_skeleton_design_system(res, tmp_path / "out2")
    summary = design_system_summary_for_requirements(ds)
    assert "DATASET" not in summary  # zero regression for envs without a dataset


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
