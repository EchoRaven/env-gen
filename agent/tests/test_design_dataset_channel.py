"""F1 — design-prep FOURTH channel: dataset/ (real structured data rows).

Google Maps needs REAL POI/review/transit data seeded deterministically (not LLM-synthesized),
and it must survive the backend lane's from-scratch seed authoring. This first piece is the
INGEST + DISCOVERY half: a design_input's optional dataset/ subfolder (JSON/CSV/NDJSON) is
resolved, staged into design/dataset/, and manifested onto design_system["dataset"] — exactly
parallel to how assets/ is ingested. Absent dataset/ → everything behaves as today (zero
regression for IG/outlook). LOCAL-ONLY (agent/tests/ gitignored).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import resolve_design_input, build_skeleton_design_system  # noqa: E402
from multi_agent.runtime.material_prep import ingest_dataset  # noqa: E402


def _mk_design_input(tmp_path, with_dataset=True):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "references" / "home.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # not a real image; ingest tolerates
    if with_dataset:
        ds = di / "dataset"
        ds.mkdir()
        (ds / "places.json").write_text(json.dumps(
            [{"id": "mels", "name": "Mel's Drive-in", "lat": 37.79, "lng": -122.43}]))
        (ds / "reviews.json").write_text(json.dumps(
            [{"id": "r1", "place_id": "mels", "text": "great diner"},
             {"id": "r2", "place_id": "mels", "text": "ok"}]))
    return di


def test_resolve_discovers_dataset_dir(tmp_path):
    di = _mk_design_input(tmp_path)
    res = resolve_design_input(str(di), None, None)
    assert res.get("dataset_dir") == str(di / "dataset")


def test_resolve_dataset_dir_absent_is_none(tmp_path):
    di = _mk_design_input(tmp_path, with_dataset=False)
    res = resolve_design_input(str(di), None, None)
    assert res.get("dataset_dir") is None
    # back-compat branch (no design_input) also carries the key as None
    res2 = resolve_design_input(None, None, ["/some/ref.png"])
    assert res2.get("dataset_dir") is None


def test_ingest_dataset_manifest_and_staging(tmp_path):
    di = _mk_design_input(tmp_path)
    stage = tmp_path / "out" / "design" / "dataset"
    manifest = ingest_dataset(str(di / "dataset"), str(stage))
    by = {m["id"]: m for m in manifest}
    assert set(by) == {"places", "reviews"}
    assert by["places"]["type"] == "json"
    assert by["places"]["records"] == 1
    assert by["reviews"]["records"] == 2
    assert by["places"]["staged_path"] == "backend/dataset/places.json"
    # physically staged
    assert (stage / "places.json").is_file()
    assert json.loads((stage / "places.json").read_text())[0]["name"] == "Mel's Drive-in"


def test_ingest_dataset_missing_dir_is_empty(tmp_path):
    assert ingest_dataset(str(tmp_path / "nope"), str(tmp_path / "stage")) == []


def test_skeleton_carries_dataset_manifest(tmp_path):
    di = _mk_design_input(tmp_path)
    res = resolve_design_input(str(di), None, None)
    out = tmp_path / "out"
    skel = build_skeleton_design_system(res, out)
    ids = {m["id"] for m in (skel.get("dataset") or [])}
    assert ids == {"places", "reviews"}
    assert (out / "design" / "dataset" / "places.json").is_file()


def test_skeleton_without_dataset_has_empty_list(tmp_path):
    di = _mk_design_input(tmp_path, with_dataset=False)
    res = resolve_design_input(str(di), None, None)
    skel = build_skeleton_design_system(res, tmp_path / "out")
    assert skel.get("dataset") == []  # key present, empty — zero regression


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
