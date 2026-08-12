r"""#623: a stash failure is not a merge conflict.

`pull_main_into_worktree` returned False when `git stash` could not save a dirty worktree, and
the caller turns False into a `merge_conflict` event plus a P0 task titled "Resolve step-start
merge conflict … resolve the conflicting files in your worktree". No merge was attempted, so
there were no conflicting files to resolve.

That false label ignited the #622 storm. In r124 the first four events — inside one minute, before
any real conflict existed — were all this stash failure. The orchestrator then did the one thing
that makes a dirty tree stashable:

    codehub_commit("chore(orchestrator): clear worktree — commit stray BrowseHomePage.jsx …")

which is a sound response to the message it was handed, and produced 394 real conflicts over the
next 70 minutes.

187 occurrences across 6+ runs. A concurrency cause was tested and REJECTED (stash failures within
±2s of another agent's commit: 2.1%, vs 2.1% for a random-time control), so this fixes the LABEL,
which is what the evidence supports — not a guessed cause of git's "could not write index".
"""
import os
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env={**os.environ, **_ENV})
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture()
def worktree(tmp_path):
    """A lane worktree that is behind integration AND dirty, so the pull must stash."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    (root / "f.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "agent/frontend", str(wt))
    (root / "f.txt").write_text("moved on\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "integration moves")
    (wt / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")   # forces the stash
    return wt


def _fail_stash(monkeypatch):
    """Make only `git stash push` fail, exactly as the runs did."""
    real = ac._run_git

    def fake(args, cwd=None, **kw):
        if args[:2] == ["stash", "push"]:
            return 1, "", "error: could not write index"
        return real(args, cwd=cwd, **kw)

    monkeypatch.setattr(ac, "_run_git", fake)


# --- the label -------------------------------------------------------------------------------

def test_a_stash_failure_no_longer_reports_a_conflict(worktree, monkeypatch):
    _fail_stash(monkeypatch)
    ok, info = ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert ok is True, "False is published as a merge_conflict event + P0 task"
    assert "stash_failed_no_conflict" in info


def test_the_message_says_what_actually_happened(worktree, monkeypatch):
    _fail_stash(monkeypatch)
    _ok, info = ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert "SKIPPED" in info and "no conflict" in info
    assert "retries next step" in info


def test_it_warns_against_the_repair_that_caused_the_storm(worktree, monkeypatch):
    _fail_stash(monkeypatch)
    _ok, info = ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert "do NOT commit files your lane does not own" in info


def test_the_underlying_git_error_is_still_reported(worktree, monkeypatch):
    """Relabelling must not hide the cause from whoever debugs it next."""
    _fail_stash(monkeypatch)
    _ok, info = ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert "could not write index" in info


# --- it must not paper over real state ---------------------------------------------------------

def test_the_agents_uncommitted_work_is_untouched(worktree, monkeypatch):
    _fail_stash(monkeypatch)
    ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert (worktree / "dirty.txt").read_text(encoding="utf-8") == "uncommitted\n"


def test_nothing_was_merged(worktree, monkeypatch):
    """`ok=True` means 'no problem to escalate', NOT 'the pull happened'."""
    _fail_stash(monkeypatch)
    ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert (worktree / "f.txt").read_text(encoding="utf-8") == "base\n"


def test_a_REAL_conflict_still_reports_False(tmp_path):
    """The relabelling is scoped to the stash path; a genuine unresolvable conflict must still
    reach the orchestrator."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    (root / "docs").mkdir()
    (root / "docs" / "n.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "agent/orchestrator", str(wt))
    (wt / "docs" / "n.md").write_text("lane\n", encoding="utf-8")
    _git(wt, "add", "-A"); _git(wt, "commit", "-q", "-m", "lane")
    (root / "docs" / "n.md").write_text("integration\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "integration")

    ok, info = ac.pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
    assert ok is False and "conflict pulling" in info      # docs/ is nobody's territory


def test_a_clean_pull_is_unaffected(worktree):
    ok, info = ac.pull_main_into_worktree(worktree_dir=worktree, main_branch="integration")
    assert ok and "_no_conflict" not in info
    assert (worktree / "f.txt").read_text(encoding="utf-8") == "moved on\n"


# --- the skip must stay visible ------------------------------------------------------------

def test_the_caller_logs_the_skip_rather_than_swallowing_it():
    """Trading a false alarm for silence would hide all 187 measured cases."""
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import step_runner
    src = inspect.getsource(step_runner)
    i = src.index("#623: the pull was skipped")
    block = src[src.rindex("if pulled_ok", 0, i):src.index("if pulled_ok and _superseded:", i)]
    assert '"_no_conflict" in (pulled_info or "")' in block
    assert "_logger.warning" in block


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(ac).replace("#", " ").split())
    assert "187 times across 6+ runs" in flat
    assert "2.1% vs a 2.1% random-time control" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
