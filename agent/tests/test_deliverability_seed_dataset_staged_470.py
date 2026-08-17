"""#470 (r46 = closest-ever delivery: seed 261 rows, api_smoke 13/13, ui_flow 10/10 —
yet fired 'authored seed missing' and never delivered). ROOT: the deliverability gate's
authored-seed check (deliverability.py:455) reads seed_data.json ∪ seed_dataset.json on
the gate's tree, but at check time NEITHER had landed there yet (the lane authors
seed_data.json late; the framework's seed_dataset.json — staged at skeleton-gen — hadn't
reached the gate's app_root). So the gate fired a SPURIOUS 'seed missing', driving the
remediation whack-a-mole that starved delivery convergence. FIX: before the authored-seed
read, (re)stage the framework's REAL dataset seed (design/dataset → app/backend/
seed_dataset.json) via _ensure_seed_dataset — best-effort, no-op without design/dataset,
so the gate sees the real rows on the FIRST poll. This test proves the staging flips the
authored-check from missing→authored. Generalizable to every app/env."""
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _ensure_seed_dataset)


def _authored(app_root: Path) -> bool:
    """Replicate the gate's authored-seed logic (deliverability.py ~432-455): merge
    seed_data.json with seed_dataset.json's non-empty list tables; authored iff any
    table has rows."""
    def _load(p):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    data = _load(app_root / "backend" / "seed_data.json")
    real = _load(app_root / "backend" / "seed_dataset.json")
    data = {**data, **{k: v for k, v in real.items() if isinstance(v, list) and v}}
    return any(isinstance(v, list) and v for v in data.values())


def _mk_run_root(tmp_path):
    root = tmp_path / "run"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "design" / "dataset").mkdir(parents=True)
    # framework REAL dataset (design/dataset/<table>.json = row array)
    (root / "design" / "dataset" / "titles.json").write_text(
        json.dumps([{"id": 1, "name": "The Hawk"}, {"id": 2, "name": "Worst Neighbor"}]),
        encoding="utf-8")
    (root / "design" / "dataset" / "genres.json").write_text(
        json.dumps([{"id": 1, "name": "Comedy"}]), encoding="utf-8")
    # lane's seed_data.json not authored yet (the {} placeholder the build-infra writes)
    (root / "app" / "backend" / "seed_data.json").write_text("{}\n", encoding="utf-8")
    return root


def test_before_fix_gate_would_report_seed_missing(tmp_path):
    root = _mk_run_root(tmp_path)
    # WITHOUT staging seed_dataset.json (the pre-#470 state at early gate time)
    assert not _authored(root / "app"), "empty seed_data.json + no dataset seed → 'missing'"


def test_470_staging_dataset_seed_makes_gate_authored(tmp_path):
    root = _mk_run_root(tmp_path)
    # #470: stage the dataset seed before the read (exactly what deliverability.py now does)
    wrote = _ensure_seed_dataset(root / "app" / "backend", root)
    assert wrote is True, "_ensure_seed_dataset should assemble+write from design/dataset"
    assert (root / "app" / "backend" / "seed_dataset.json").exists()
    assert _authored(root / "app"), "#470: gate now sees the framework's real rows → authored, no spurious 'seed missing'"


def test_470_noop_without_design_dataset(tmp_path):
    # no design/dataset → no-op → zero regression (still 'missing' until the lane authors)
    root = tmp_path / "run2"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "backend" / "seed_data.json").write_text("{}\n", encoding="utf-8")
    assert _ensure_seed_dataset(root / "app" / "backend", root) is False
    assert not (root / "app" / "backend" / "seed_dataset.json").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
