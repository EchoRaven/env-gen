"""#473 SEED-VISIBILITY RACE — the chronic Part-B no-convergence blocker (r46/r47/r49).

r49 reached a fully deliver-ready state (verifier READY: 13/13 validation, 11 ui_flows,
0 bugs, business_chain green, 16/16 endpoints) yet fired DELIVER_PROJECT 22× with 0
releases — because the delivery gate's authored-seed check reads the WORKING-TREE
seed_data.json, which is transiently EMPTY on some ticks while the REAL seed is COMMITTED
to integration HEAD (git-proven: seed committed to integration at 07:17:48 with 223 rows;
the backend even force-resynced it 3× as the gate kept firing 'authored seed missing').
reconcile_integration_seed only scans worktree WORKING files (also transiently empty) and
never the committed HEAD, so it no-op'd → chronic false 'authored seed missing' → churn.

FIX (deliverability.py, in the authored-seed check): when the working-tree seed is empty,
restore it from the committed integration HEAD (the tree the delivery snapshot / docker
image actually ships). This test proves the core mechanism — `git show HEAD:...` recovers
the committed seed and repairs the working tree — on a real git fixture, exactly mirroring
the inline snippet. Activates ONLY when the working tree is empty (never regresses a
populated seed); no-ops when HEAD is also empty (genuine missing → still blocks). The
recovery reads what SHIPS, so it never masks a genuinely seedless app. Generalizable to
every app/env."""
import json
import subprocess
from pathlib import Path


def _rows(d) -> int:
    return (sum(len(v) for v in d.values() if isinstance(v, list))
            if isinstance(d, dict) else 0)


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=30)


def _mk_repo_with_committed_seed(tmp_path) -> Path:
    """integration checkout: a real seed COMMITTED to HEAD (what ships)."""
    root = tmp_path / "gen"
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t.io"], root)
    _git(["config", "user.name", "t"], root)
    real = {"users": [{"id": 1, "email": "a@b.io"}, {"id": 2, "email": "c@d.io"}],
            "titles": [{"id": 1, "name": "The Hawk"}]}
    (be / "seed_data.json").write_text(json.dumps(real, indent=2) + "\n", encoding="utf-8")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "seed: real rows"], root)
    return root


def _recover_from_head_like_the_fix(app_root: Path):
    """EXACT mirror of deliverability.py #473: read working-tree seed; if empty, restore
    from committed HEAD and repair the working tree. Returns the effective _data."""
    seed_path = app_root / "backend" / "seed_data.json"
    data = {}
    if seed_path.exists():
        try:
            data = json.loads(seed_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    if not any(isinstance(v, list) and v for v in data.values()):
        try:
            r = subprocess.run(["git", "show", "HEAD:app/backend/seed_data.json"],
                               cwd=str(app_root.parent), capture_output=True,
                               text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                head = json.loads(r.stdout)
                if isinstance(head, dict) and any(
                        isinstance(v, list) and v for v in head.values()):
                    data = head
                    seed_path.write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
    return data


def test_working_tree_empty_but_head_populated_recovers(tmp_path):
    root = _mk_repo_with_committed_seed(tmp_path)
    seed = root / "app" / "backend" / "seed_data.json"
    # RACE: the working-tree file is transiently clobbered to the {} placeholder
    seed.write_text("{}\n", encoding="utf-8")
    assert _rows(json.loads(seed.read_text())) == 0, "precondition: working tree empty"
    data = _recover_from_head_like_the_fix(root / "app")
    assert _rows(data) == 3, "#473: gate recovers the 3 committed rows from HEAD → authored"
    # and the working tree is REPAIRED so the docker build ships the real seed
    assert _rows(json.loads(seed.read_text())) == 3, "#473: working tree restored for the build"


def test_populated_working_tree_is_untouched(tmp_path):
    root = _mk_repo_with_committed_seed(tmp_path)
    seed = root / "app" / "backend" / "seed_data.json"
    # a DIFFERENT (thicker) working-tree seed must NOT be overwritten by HEAD
    thick = {"users": [{"id": i} for i in range(9)]}
    seed.write_text(json.dumps(thick), encoding="utf-8")
    data = _recover_from_head_like_the_fix(root / "app")
    assert _rows(data) == 9, "#473 no-ops on a populated working tree (never regresses)"
    assert _rows(json.loads(seed.read_text())) == 9, "working tree left as-is"


def test_head_also_empty_stays_missing(tmp_path):
    # genuine missing: working tree empty AND HEAD empty → no recovery → still blocks
    root = tmp_path / "gen2"
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t.io"], root)
    _git(["config", "user.name", "t"], root)
    (be / "seed_data.json").write_text("{}\n", encoding="utf-8")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "empty seed"], root)
    data = _recover_from_head_like_the_fix(root / "app")
    assert _rows(data) == 0, "#473: HEAD also empty → no false authored (genuine missing blocks)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
