"""F2 — dual-source seed loader: real design-prep dataset survives the lane's from-scratch seed.

seed_data.json is backend-lane-owned and authored FROM SCRATCH, so a design-prep real
dataset written there would be clobbered (last-writer-wins). Instead the design-prep
dataset is assembled into a SEPARATE app/backend/seed_dataset.json — a framework-owned
file the lane never touches — and the generated loader merges it OVER the lane's
seed_data.json (dataset tables authoritative). Absent seed_dataset.json → the loader and
build-infra behave exactly as today (zero regression for every existing env). LOCAL-ONLY.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.material_prep import assemble_seed_dataset  # noqa: E402
from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    write_backend_build_infra, render_seed_data)


def _mk_design_dataset(tmp_path):
    dd = tmp_path / "design" / "dataset"
    dd.mkdir(parents=True)
    (dd / "places.json").write_text(json.dumps([
        {"id": "mels", "name": "Mel's Drive-in", "rating": 4.1},
        {"id": "johns", "name": "John's Grill", "rating": 4.3}]))
    (dd / "reviews.json").write_text(json.dumps([
        {"id": "r1", "place_id": "mels", "text": "classic diner"}]))
    (dd / "MANIFEST.md").write_text("# not a table")  # non-json, skipped
    (dd / "notes.json").write_text(json.dumps({"meta": "not a row array"}))  # non-array, skipped
    return tmp_path


def test_assemble_maps_files_to_tables(tmp_path):
    _mk_design_dataset(tmp_path)
    seed = assemble_seed_dataset(tmp_path / "design" / "dataset")
    assert set(seed) == {"places", "reviews"}, "one table per JSON-array file; non-arrays skipped"
    assert len(seed["places"]) == 2 and seed["places"][0]["name"] == "Mel's Drive-in"
    assert len(seed["reviews"]) == 1


def test_assemble_missing_dir_is_empty(tmp_path):
    assert assemble_seed_dataset(tmp_path / "nope") == {}


def test_build_infra_writes_seed_dataset_from_design(tmp_path):
    _mk_design_dataset(tmp_path)
    write_backend_build_infra(tmp_path)
    sd = tmp_path / "app" / "backend" / "seed_dataset.json"
    assert sd.is_file(), "assembled real dataset must be staged next to seed_data.json"
    data = json.loads(sd.read_text())
    assert set(data) == {"places", "reviews"}
    # and the lane's seed_data.json stub still exists untouched
    assert (tmp_path / "app" / "backend" / "seed_data.json").read_text().strip() == "{}"


def test_build_infra_without_dataset_writes_no_seed_dataset(tmp_path):
    write_backend_build_infra(tmp_path)  # no design/dataset/
    assert not (tmp_path / "app" / "backend" / "seed_dataset.json").exists(), \
        "no dataset → no seed_dataset.json → zero regression for existing envs"


def test_loader_merges_dual_sources():
    src = render_seed_data({"users": {"columns": {"id": "int", "email": "str"}}})
    # the generated loader must read the framework dataset file and merge it OVER the lane file
    assert "seed_dataset.json" in src
    assert "_load_rows" in src
    # dataset tables win: the merge must apply dataset AFTER base (base then dataset spread)
    assert "seed_data.json" in src


def _exec_load_rows(src, seed_py_path, base_seed):
    """Extract just the generated _load_rows def and run it in a minimal namespace
    with __file__ pointing at a real seed_data.py so Path(__file__).with_name works."""
    import re as _re
    body = _re.search(r"def _load_rows\(\):.*?(?=\ndef |\Z)", src, _re.S).group(0)
    ns = {"json": json, "Path": Path, "_SEED": base_seed, "__file__": str(seed_py_path)}
    exec(body, ns)
    return ns["_load_rows"]()


def test_loader_merge_semantics_executable(tmp_path):
    """Run the generated _load_rows against real files: dataset tables override the
    lane's, lane-only tables survive, and absent dataset == lane-only behavior."""
    src = render_seed_data({"users": {"columns": {"id": "int"}},
                            "places": {"columns": {"id": "str"}}})
    be = tmp_path / "backend"
    be.mkdir()
    seed_py = be / "seed_data.py"
    seed_py.write_text("# placeholder")
    (be / "seed_data.json").write_text(json.dumps({
        "users": [{"id": 1, "email": "demo@x.com"}],
        "places": [{"id": "fake", "name": "LLM-made"}]}))

    # (a) with a framework dataset present → its places override the lane's
    (be / "seed_dataset.json").write_text(json.dumps({
        "places": [{"id": "mels", "name": "Mel's Drive-in"}]}))
    result = _exec_load_rows(src, seed_py, {})
    assert {p["id"] for p in result["places"]} == {"mels"}, "dataset overrides the lane's places"
    assert result["users"][0]["email"] == "demo@x.com", "lane-only table survives"

    # (b) no dataset file → pure lane behavior (zero regression)
    (be / "seed_dataset.json").unlink()
    result2 = _exec_load_rows(src, seed_py, {})
    assert {p["id"] for p in result2["places"]} == {"fake"}
    assert result2["users"][0]["email"] == "demo@x.com"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── F2 gate double-read: the framework real dataset satisfies the authored-seed gate ──
def test_framework_dataset_satisfies_seed_gate(tmp_path):
    """A run whose real rows live in the framework seed_dataset.json must NOT trip the
    authored-seed-missing / thin-quality gate even if the lane's seed_data.json is empty."""
    from multi_agent.runtime.deliverability import compute_deliverability
    from multi_agent.runtime.hub_registry import HubRegistry
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend" / "seed_data.json").write_text("{}")  # lane authored nothing
    (app / "backend" / "seed_dataset.json").write_text(json.dumps({
        "places": [{"id": f"p{i}", "name": f"Real Place {i}", "rating": 4.0}
                   for i in range(15)]}))  # 15 real rows > floor
    hr = HubRegistry(tmp_path / "hubs")
    rep = compute_deliverability(hr, app, session_start_ts=0.0)
    seed_blockers = [b for b in (rep.blockers or [])
                     if "authored seed" in b]
    assert seed_blockers == [], f"real dataset must satisfy the seed gate, got {seed_blockers}"


def test_empty_both_sources_still_blocks(tmp_path):
    """Zero regression: no lane seed AND no framework dataset → the gate still fires."""
    from multi_agent.runtime.deliverability import compute_deliverability
    from multi_agent.runtime.hub_registry import HubRegistry
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend" / "seed_data.json").write_text("{}")
    hr = HubRegistry(tmp_path / "hubs")
    rep = compute_deliverability(hr, app, session_start_ts=0.0)
    assert any("authored seed missing" in b for b in (rep.blockers or [])), \
        "empty everywhere must still block (existing behavior preserved)"


# ── F2b robust assembly: per-milestone skeleton also stages seed_dataset.json ──
def test_ensure_seed_dataset_helper(tmp_path):
    from multi_agent.runtime.backend_skeleton import _ensure_seed_dataset
    dd = tmp_path / "design" / "dataset"
    dd.mkdir(parents=True)
    (dd / "places.json").write_text(json.dumps([{"id": "a", "name": "A"}]))
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    wrote = _ensure_seed_dataset(be, tmp_path)
    assert wrote is True
    assert json.loads((be / "seed_dataset.json").read_text())["places"][0]["name"] == "A"
    # absent design/dataset → no-op, no file
    be2 = tmp_path / "empty" / "backend"
    be2.mkdir(parents=True)
    assert _ensure_seed_dataset(be2, tmp_path / "empty") is False
    assert not (be2 / "seed_dataset.json").exists()


def test_build_infra_and_skeleton_both_call_ensure_seed_dataset():
    import inspect
    from multi_agent.runtime import backend_skeleton as bs
    assert "_ensure_seed_dataset(be, output_dir)" in inspect.getsource(bs.write_backend_build_infra)
    assert "_ensure_seed_dataset(be, output_dir)" in inspect.getsource(bs.write_backend_skeleton)
