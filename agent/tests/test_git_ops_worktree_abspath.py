"""Lane-merge wedge fix (netflix r2 landing-flow deadlock): CodeHub builds a lane's
worktree path as ``repo_root / "worktrees" / <agent>`` and ``repo_root`` is routinely
RELATIVE (``generated/<name>``). GitOps._run sets ``cwd=repo_root``, so ``git worktree add
<relative-path>`` was re-resolved by git AGAINST the repo dir → the worktree landed at
``generated/<name>/generated/<name>/worktrees/<agent>`` (doubly nested). That does NOT match
where path_routed_workspace + heal_pipeline read/write the lane's files (resolved against the
PROCESS cwd) → the lane wrote into a plain dir in the main checkout, its work never reached
agent/<lane>, never merged to integration, and the build/audit shipped a stale tree. The fix
resolves the worktree path to ABSOLUTE before ``git worktree add``. This locks it in against
a real temp git repo: with a RELATIVE repo_root, the worktree is created at the single,
canonical absolute location — never doubly nested.
"""
import importlib.util
import os
import sys
import subprocess
from pathlib import Path

import pytest

_GIT = "/usr/bin/git"
_GIT_OPS = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" /
            "multi_agent" / "runtime" / "hubs" / "codehub" / "git_ops.py")


def _load_git_ops():
    spec = importlib.util.spec_from_file_location("_gitops_under_test", _GIT_OPS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass machinery looks the module up by name
    spec.loader.exec_module(mod)
    return mod


def _git(*args, cwd):
    subprocess.run([_GIT, *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "generated" / "app-r2"          # mimic generated/<name>
    r.mkdir(parents=True)
    _git("init", "-q", cwd=r)
    _git("config", "user.email", "t@t.t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "README.md").write_text("x")
    _git("add", "-A", cwd=r)
    _git("commit", "-qm", "init", cwd=r)
    saved = os.getcwd()
    os.chdir(tmp_path)                              # process cwd = parent of the repo
    try:
        yield r, tmp_path
    finally:
        os.chdir(saved)


def _worktree_paths(mod, repo_abs):
    go = mod.GitOps(repo_abs)
    return {wt["path"] for wt in go.list_worktrees()}


def test_relative_repo_root_worktree_is_not_doubly_nested(repo):
    repo_abs, root = repo
    mod = _load_git_ops()
    # RELATIVE repo_root, exactly like CodeHub(output_dir="generated/<name>")
    rel_repo = Path("generated") / "app-r2"
    go = mod.GitOps(rel_repo)
    # relative worktree path, exactly like service.py: repo_root / "worktrees" / agent
    wt_rel = rel_repo / "worktrees" / "frontend"
    go.add_worktree(wt_rel, "agent/frontend")

    expected = (root / "generated" / "app-r2" / "worktrees" / "frontend").resolve()
    doubled = (root / "generated" / "app-r2" / "generated" / "app-r2" /
               "worktrees" / "frontend").resolve()
    assert expected.is_dir(), "worktree not created at the canonical single-nested path"
    assert not doubled.exists(), "worktree was created at the DOUBLY-nested path (the bug)"

    # git agrees: the registered worktree is the single-nested absolute path
    paths = {Path(p).resolve() for p in _worktree_paths(mod, repo_abs)}
    assert expected in paths
    assert doubled not in paths


def test_worktree_path_matches_where_workspace_would_read(repo):
    # path_routed_workspace / heal_pipeline resolve `repo_root/worktrees/<lane>` against the
    # PROCESS cwd; the created worktree must live exactly there so lane writes land IN it.
    repo_abs, root = repo
    mod = _load_git_ops()
    rel_repo = Path("generated") / "app-r2"
    go = mod.GitOps(rel_repo)
    created = go.add_worktree(rel_repo / "worktrees" / "backend", "agent/backend")
    workspace_view = (rel_repo / "worktrees" / "backend").resolve()  # reader's resolution
    assert Path(created).resolve() == workspace_view


def test_app_file_written_to_worktree_lands_in_agent_branch(repo):
    # end-to-end of the fix: a file the lane writes into its worktree is committable to the
    # lane branch (i.e. the worktree is real + on agent/<lane>), so a later merge can surface
    # it — the exact chain that was broken when writes hit a plain dir on the main checkout.
    repo_abs, root = repo
    mod = _load_git_ops()
    rel_repo = Path("generated") / "app-r2"
    go = mod.GitOps(rel_repo)
    wt = Path(go.add_worktree(rel_repo / "worktrees" / "frontend", "agent/frontend")).resolve()
    comp = wt / "app" / "frontend" / "src" / "components"
    comp.mkdir(parents=True)
    (comp / "LandingTopBar.jsx").write_text("export default function LandingTopBar(){return null}")
    _git("add", "-A", cwd=wt)
    _git("commit", "-qm", "feat(frontend): landing top bar", cwd=wt)
    # the commit is on agent/frontend and carries the component
    out = subprocess.run([_GIT, "ls-tree", "-r", "--name-only", "agent/frontend"],
                         cwd=str(repo_abs), capture_output=True, text=True).stdout
    assert "app/frontend/src/components/LandingTopBar.jsx" in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
