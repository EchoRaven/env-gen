"""#322 — the backend authors app/backend/seed_data.json in its WORKTREE, but it did
not reliably reach the INTEGRATION tree the delivery gate reads → integration kept the
{} placeholder → deliverability chronically 'authored seed missing'-blocked delivery
(r86 + r91: ~50 tasks; r91 burned the full 6h wall-clock). reconcile_integration_seed
copies the most-populated lane-worktree seed onto integration when integration's is
empty — never overwriting a populated integration seed.
"""
import json
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.heal_pipeline import reconcile_integration_seed  # noqa: E402


def _repo(integ_seed, lane_seeds):
    root = Path(tempfile.mkdtemp(prefix="seed322_"))
    ib = root / "app" / "backend"; ib.mkdir(parents=True)
    if integ_seed is not None:
        (ib / "seed_data.json").write_text(json.dumps(integ_seed), encoding="utf-8")
    for lane, seed in lane_seeds.items():
        wb = root / "worktrees" / lane / "app" / "backend"; wb.mkdir(parents=True)
        if seed is not None:
            (wb / "seed_data.json").write_text(json.dumps(seed), encoding="utf-8")
    return root


def _integ(root):
    p = root / "app" / "backend" / "seed_data.json"
    return json.loads(p.read_text()) if p.exists() else None


def test_empty_integration_filled_from_lane_worktree():
    root = _repo({}, {"backend": {"users": [1, 2, 3], "videos": [1, 2]}})
    out = reconcile_integration_seed(root)
    assert out.get("rows") == 5
    assert _integ(root) == {"users": [1, 2, 3], "videos": [1, 2]}   # integration now populated


def test_absent_integration_seed_filled():
    root = _repo(None, {"backend": {"users": [1]}})
    reconcile_integration_seed(root)
    assert _integ(root) == {"users": [1]}


def test_populated_integration_not_clobbered():
    root = _repo({"users": [9, 9]}, {"backend": {"users": [1, 2, 3, 4, 5, 6]}})
    out = reconcile_integration_seed(root)
    assert out == {}                                   # nothing to do
    assert _integ(root) == {"users": [9, 9]}           # real integration seed preserved


def test_picks_most_populated_lane():
    root = _repo({}, {"backend": {"users": [1] * 10, "videos": [1] * 8},   # 18 rows
                      "frontend": {"users": [1] * 2}})                     # 2 rows
    out = reconcile_integration_seed(root)
    assert out.get("rows") == 18
    assert len(_integ(root)["users"]) == 10


def test_no_populated_lane_seed_is_noop():
    root = _repo({}, {"backend": {}, "frontend": {"users": []}})
    out = reconcile_integration_seed(root)
    assert out == {}
    assert _integ(root) == {}                          # left as-is (SOFT gate handles empty)
