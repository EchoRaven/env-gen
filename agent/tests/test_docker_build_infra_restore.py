"""#450 (netflix r37: visual gate 0.069 across ALL 13 screens — a blank app, not a
fidelity signal). ROOT: the framework-owned backend/frontend Dockerfiles are
(re)written into the integration tree and committed each tick, but a concurrent
lane->integration merge can transiently DROP an uncommitted Dockerfile (stash-drop
/ `git clean -fd -- app`) exactly when docker_up reads the build context -> compose
reports 'no Dockerfile yet' / the build fails -> the image never builds -> every
screenshot is blank. FIX: ensure_build_infra_staged_for_build restores a dropped,
git-tracked Dockerfile from HEAD (else the staged index) AT the build entry (wired
into both _run_compose and the deterministic validation runner). Idempotent, no-op
when present, git-based (generalizable, no contract). Locks it in."""
import subprocess
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    ensure_build_infra_staged_for_build)


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


def _repo_with_dockerfiles(tmp_path) -> Path:
    root = tmp_path / "out"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "frontend" / "src").mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "app" / "backend" / "Dockerfile").write_text("FROM python:3.10\n# backend\n")
    (root / "app" / "backend" / "main.py").write_text("# main\n")  # #462 core marker
    (root / "app" / "frontend" / "Dockerfile").write_text("FROM node:20\n# frontend\n")
    (root / "app" / "frontend" / "src" / "App.jsx").write_text("export default function A(){}\n")
    (root / "docker" / "docker-compose.yml").write_text("services: {}\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_restores_both_dropped_dockerfiles_from_head(tmp_path):
    root = _repo_with_dockerfiles(tmp_path)
    be = root / "app" / "backend" / "Dockerfile"
    fe = root / "app" / "frontend" / "Dockerfile"
    # simulate the merge drop: remove both from the working tree
    be.unlink(); fe.unlink()
    assert not be.exists() and not fe.exists()
    restored = ensure_build_infra_staged_for_build(root / "docker" / "docker-compose.yml")
    assert be.exists() and fe.exists(), "both Dockerfiles restored"
    assert "# backend" in be.read_text() and "# frontend" in fe.read_text()
    assert set(restored) == {"app/backend/Dockerfile", "app/frontend/Dockerfile"}


def test_noop_when_present(tmp_path):
    root = _repo_with_dockerfiles(tmp_path)
    orig = (root / "app" / "backend" / "Dockerfile").read_text()
    restored = ensure_build_infra_staged_for_build(root / "docker")
    assert restored == [], "nothing to restore when both present"
    assert (root / "app" / "backend" / "Dockerfile").read_text() == orig, "untouched"


def test_restores_from_index_when_not_committed(tmp_path):
    # a Dockerfile staged (git add) but not yet committed, then dropped from disk,
    # is restored from the index (the never-committed-first-tick edge is narrower
    # but the staged copy still covers a merge that dropped a staged write).
    root = tmp_path / "out2"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "frontend").mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "app" / "backend" / "Dockerfile").write_text("FROM python:3.10\n# idx-be\n")
    (root / "app" / "frontend" / "Dockerfile").write_text("FROM node:20\n# idx-fe\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")  # staged, NOT committed
    (root / "app" / "backend" / "Dockerfile").unlink()
    restored = ensure_build_infra_staged_for_build(root / "docker" / "docker-compose.yml")
    assert (root / "app" / "backend" / "Dockerfile").exists()
    assert "# idx-be" in (root / "app" / "backend" / "Dockerfile").read_text()
    assert "app/backend/Dockerfile" in restored


def test_noop_outside_git_repo(tmp_path):
    root = tmp_path / "nogit"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "docker").mkdir()
    restored = ensure_build_infra_staged_for_build(root / "docker")
    assert restored == [], "no git repo → graceful no-op"


def test_never_raises_on_bad_anchor():
    assert ensure_build_infra_staged_for_build("/nonexistent/path/x.yml") == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── #462: restore a WHOLE dropped framework app dir (not just the Dockerfile) ──
def _repo_with_app_dirs(tmp_path):
    root = tmp_path / "out462"
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "frontend" / "src").mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "app" / "backend" / "Dockerfile").write_text("FROM python:3.10\n")
    (root / "app" / "backend" / "main.py").write_text("# backend main\n")
    (root / "app" / "frontend" / "Dockerfile").write_text("FROM node:20\n")
    (root / "app" / "frontend" / "src" / "App.jsx").write_text("export default function App(){}\n")
    (root / "docker" / "docker-compose.yml").write_text("services: {}\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_restores_whole_dropped_frontend_dir(tmp_path):
    import shutil as _sh
    root = _repo_with_app_dirs(tmp_path)
    _sh.rmtree(root / "app" / "frontend")  # lane-merge dropped the WHOLE frontend dir
    assert not (root / "app" / "frontend").exists()
    restored = ensure_build_infra_staged_for_build(root / "docker" / "docker-compose.yml")
    assert (root / "app" / "frontend" / "src" / "App.jsx").exists(), "whole frontend dir restored"
    assert (root / "app" / "frontend" / "Dockerfile").exists()
    assert any("frontend" in r for r in restored)


def test_intact_dir_with_wip_not_overwritten(tmp_path):
    # a dir whose core (src/) is present must NOT be git-checked-out (preserve lane WIP)
    root = _repo_with_app_dirs(tmp_path)
    (root / "app" / "frontend" / "src" / "App.jsx").write_text("// LANE WIP uncommitted\n")
    ensure_build_infra_staged_for_build(root / "docker")
    assert "LANE WIP" in (root / "app" / "frontend" / "src" / "App.jsx").read_text(), \
        "intact dir's uncommitted WIP must be preserved (not overwritten from HEAD)"


def test_restores_dir_when_core_marker_missing(tmp_path):
    import shutil as _sh
    root = _repo_with_app_dirs(tmp_path)
    _sh.rmtree(root / "app" / "frontend" / "src")  # core src/ dropped (whole-dir-core drop)
    restored = ensure_build_infra_staged_for_build(root / "docker")
    assert (root / "app" / "frontend" / "src" / "App.jsx").exists(), "src restored from HEAD"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
