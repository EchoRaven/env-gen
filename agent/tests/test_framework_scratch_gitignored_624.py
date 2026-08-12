r"""#624: the framework's own scratch directories made every worktree dirty.

`.agents/` (injected skills), `.agent_logs/`, nested `worktrees/`, `.memory/` are created by the
FRAMEWORK. No lane authors them, none can ship, and `file_tools` already pruned them from
filename search — but git did not know, so `git status` listed them as untracked:

    89 dirty worktrees across 15 runs
    42 of them (47%) dirty for NO OTHER REASON

A dirty worktree is what forces `git stash -u` on the step-start pull, which is where "could not
write index" bites (187 times), and a failed stash used to be reported as a merge conflict — the
false label that ignited #623's 70.8x storm. Ignoring them removes the stash, so the ignition
cannot happen.

This is the reasoning already written down for `memory-bank/`, applied to the rest of the same
category: `git status` stops listing them AND `stash -u` SPARES ignored paths.
"""
import os
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.runtime.scaffolder import ensure_base_gitignore
from env_generator.llm_generator.tools.file_tools import FRAMEWORK_SCRATCH_DIRS

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env={**os.environ, **_ENV})
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


# --- the list ---------------------------------------------------------------------------------

def test_it_covers_the_directories_the_framework_creates():
    assert set(FRAMEWORK_SCRATCH_DIRS) == {".agents", ".agent_logs", "worktrees", ".memory"}


def test_build_artifacts_are_deliberately_excluded():
    """A different category with different delivery risk; nothing measured points at them."""
    for d in ("node_modules", "dist", "build", ".next", ".venv"):
        assert d not in FRAMEWORK_SCRATCH_DIRS


def test_the_search_prune_set_still_derives_from_the_same_list():
    """One source of truth — the ignore-list and the prune-set cannot drift."""
    import inspect
    from env_generator.llm_generator.tools import file_tools
    src = inspect.getsource(file_tools._workspace_filename_matches)
    assert "*FRAMEWORK_SCRATCH_DIRS" in src


# --- what gets written -------------------------------------------------------------------------

def test_every_scratch_dir_is_ignored(tmp_path):
    ensure_base_gitignore(tmp_path)
    body = (tmp_path / ".gitignore").read_text(encoding="utf-8").split()
    for d in FRAMEWORK_SCRATCH_DIRS:
        assert f"{d}/" in body


def test_memory_bank_is_still_ignored(tmp_path):
    ensure_base_gitignore(tmp_path)
    assert "memory-bank/" in (tmp_path / ".gitignore").read_text(encoding="utf-8").split()


def test_it_reports_the_file_for_committing(tmp_path):
    assert ensure_base_gitignore(tmp_path) == [".gitignore"]


def test_an_existing_gitignore_is_appended_to_not_replaced(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nsecrets.env\n", encoding="utf-8")
    ensure_base_gitignore(tmp_path)
    body = (tmp_path / ".gitignore").read_text(encoding="utf-8").split()
    assert "*.log" in body and "secrets.env" in body and ".agents/" in body


def test_running_twice_adds_nothing_and_commits_nothing(tmp_path):
    ensure_base_gitignore(tmp_path)
    first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ensure_base_gitignore(tmp_path) == []
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == first


# --- the behaviour that actually matters -------------------------------------------------------

def test_a_worktree_with_only_framework_scratch_is_CLEAN(tmp_path):
    """The whole point: clean → the step-start pull never has to stash."""
    _git(tmp_path, "init", "-q", "-b", "integration")
    ensure_base_gitignore(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    for d in FRAMEWORK_SCRATCH_DIRS:
        (tmp_path / d / "sub").mkdir(parents=True, exist_ok=True)
        (tmp_path / d / "sub" / "f.md").write_text("scratch\n", encoding="utf-8")
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


def test_CONTROL_the_pre_624_ignore_list_leaves_it_dirty(tmp_path):
    """The control for the test above: with only `memory-bank/` ignored — what the runs
    actually shipped — the very same tree is dirty. That is what forced the stash."""
    _git(tmp_path, "init", "-q", "-b", "integration")
    (tmp_path / ".gitignore").write_text("memory-bank/\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    for d in FRAMEWORK_SCRATCH_DIRS:
        (tmp_path / d / "sub").mkdir(parents=True, exist_ok=True)
        (tmp_path / d / "sub" / "f.md").write_text("scratch\n", encoding="utf-8")
    assert _git(tmp_path, "status", "--porcelain").strip() != ""


def test_real_app_edits_are_still_seen(tmp_path):
    """Ignoring scratch must not hide the lane's actual work."""
    _git(tmp_path, "init", "-q", "-b", "integration")
    ensure_base_gitignore(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "app" / "frontend").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "App.jsx").write_text("x\n", encoding="utf-8")
    # git collapses a wholly-untracked tree to its top dir — `?? app/`
    assert _git(tmp_path, "status", "--porcelain").strip() == "?? app/"


def test_the_pull_needs_no_stash_when_only_scratch_is_present(tmp_path):
    """End to end: the #623 ignition path is gone, because there is nothing to stash."""
    from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    ensure_base_gitignore(root)
    (root / "f.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "agent/orchestrator", str(wt))
    (root / "f.txt").write_text("moved on\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "integration moves")
    (wt / ".agents" / "skills").mkdir(parents=True)
    (wt / ".agents" / "skills" / "s.md").write_text("skill\n", encoding="utf-8")

    calls = []
    real = ac._run_git

    def spy(args, cwd=None, **kw):
        calls.append(args[0] if args else "")
        return real(args, cwd=cwd, **kw)

    ac._run_git, saved = spy, real
    try:
        ok, _info = ac.pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
    finally:
        ac._run_git = saved
    assert ok
    assert "stash" not in calls, "a clean worktree must not be stashed"
    assert (wt / "f.txt").read_text(encoding="utf-8") == "moved on\n"
    assert (wt / ".agents" / "skills" / "s.md").exists(), "scratch survives the pull"


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    flat = " ".join(inspect.getsource(scaffolder.ensure_base_gitignore).split())
    assert "42 of the 89 dirty worktrees across 15 runs" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
