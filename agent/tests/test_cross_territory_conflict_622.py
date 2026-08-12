r"""#622: a lane has no claim on another lane's territory.

The ownership resolver only ever fired for a lane IN the map, on paths under ITS OWN prefix.
Measured over 15 kept runs that is the minority case:

    2091 conflicted-file mentions
    1907 (91%) CROSS-territory — the lane has no claim on the path
     184       same-territory — all the old resolver could handle
       0       outside every known territory

`agent/orchestrator` is not in the map, so its step-start pull aborted and re-hit the identical
conflict forever: 394 times in r124, 306 in r129, 227 in r137, still failing in the last minute of
the run in 8 of 15 runs. `git merge-tree agent/orchestrator integration` on the kept r124 repo
still reproduces it.

What made it permanent was an agent REPAIRING ITSELF. Told by a P0 task to "resolve the
conflicting files in your worktree", the orchestrator ran

    codehub_commit("chore(orchestrator): clear worktree — commit stray BrowseHomePage.jsx …")

turning a stashable dirty file into a divergent commit on a branch that never merges:

    50 min BEFORE it:   4 conflicts, NONE on that file
    70 min AFTER it:  394 conflicts, ALL on that file      (70.8x)

Nothing told it that its repair was the cause. Ownership settles this without guessing — the
worktree cannot be authoritative about another lane's path, so the shared side wins.
"""
import subprocess

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import auto_commit as ac

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args, check=True):
    import os
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env={**os.environ, **_ENV})
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo_with_conflict(tmp_path, path, lane_branch):
    """integration and `lane_branch` both edit `path`; leave the index UNMERGED."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    _write(root, path, "base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")

    _git(root, "checkout", "-q", "-b", lane_branch)
    _write(root, path, "THE LANE'S OWN VERSION\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "lane edit")

    _git(root, "checkout", "-q", "integration")
    _write(root, path, "INTEGRATION VERSION\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "integration edit")

    # PULL direction: the lane's branch is checked out, integration is merged IN.
    _git(root, "checkout", "-q", lane_branch)
    subprocess.run(["git", "-C", str(root), "merge", "--no-edit", "integration"],
                   capture_output=True, text=True)
    assert _git(root, "diff", "--name-only", "--diff-filter=U").strip(), "expected an unmerged index"
    return root


_PAGE = "app/frontend/src/pages/BrowseHomePage.jsx"


# --- the defect: a lane that owns nothing --------------------------------------------------

def test_a_non_owner_lane_resolves_instead_of_aborting(tmp_path):
    root = _repo_with_conflict(tmp_path, _PAGE, "agent/orchestrator")
    ok, info = ac._resolve_conflict_by_ownership(root, lane="orchestrator",
                                                 framework_side="--theirs")
    assert ok, f"orchestrator still cannot resolve: {info}"


def test_the_shared_side_wins_not_the_lane_copy(tmp_path):
    root = _repo_with_conflict(tmp_path, _PAGE, "agent/orchestrator")
    ac._resolve_conflict_by_ownership(root, lane="orchestrator", framework_side="--theirs")
    assert (root / _PAGE).read_text(encoding="utf-8") == "INTEGRATION VERSION\n"


def test_the_path_is_staged_so_the_merge_can_commit(tmp_path):
    root = _repo_with_conflict(tmp_path, _PAGE, "agent/orchestrator")
    ac._resolve_conflict_by_ownership(root, lane="orchestrator", framework_side="--theirs")
    assert not _git(root, "diff", "--name-only", "--diff-filter=U").strip()


def test_the_lane_is_told_its_edit_was_superseded(tmp_path):
    """#26 N2's notice is the only way the orchestrator learns to stop re-editing."""
    root = _repo_with_conflict(tmp_path, _PAGE, "agent/orchestrator")
    out = []
    ac._resolve_conflict_by_ownership(root, lane="orchestrator", framework_side="--theirs",
                                      superseded_out=out)
    assert out == [_PAGE]


# --- the same rule for a lane that IS in the map -------------------------------------------

def test_an_owned_lane_also_has_no_claim_on_the_other_territory(tmp_path):
    """Measured 12 times: the frontend lane conflicting on app/backend/seed_data.json."""
    root = _repo_with_conflict(tmp_path, "app/backend/seed_data.json", "agent/frontend")
    ok, _ = ac._resolve_conflict_by_ownership(root, lane="frontend", framework_side="--theirs")
    assert ok
    assert (root / "app/backend/seed_data.json").read_text(encoding="utf-8") == "INTEGRATION VERSION\n"


def test_a_lane_keeps_its_OWN_authored_file(tmp_path):
    """The pre-#622 behaviour on a lane's own territory must not move."""
    root = _repo_with_conflict(tmp_path, "app/frontend/src/pages/X.jsx", "agent/frontend")
    ok, _ = ac._resolve_conflict_by_ownership(root, lane="frontend", framework_side="--theirs")
    assert ok
    assert (root / "app/frontend/src/pages/X.jsx").read_text(encoding="utf-8") == "THE LANE'S OWN VERSION\n"


# --- where it must still refuse -------------------------------------------------------------

def test_an_unidentifiable_lane_never_discards(tmp_path):
    """`_lane_of_worktree` returns '' on a detached HEAD. If we cannot say whose worktree this
    is, taking the shared side could throw away the real owner's work."""
    root = _repo_with_conflict(tmp_path, _PAGE, "agent/orchestrator")
    ok, info = ac._resolve_conflict_by_ownership(root, lane="", framework_side="--theirs")
    assert not ok and "identified" in info
    assert (root / _PAGE).read_text(encoding="utf-8") != "INTEGRATION VERSION\n"


def test_a_path_outside_every_territory_still_aborts(tmp_path):
    root = _repo_with_conflict(tmp_path, "docs/notes.md", "agent/orchestrator")
    ok, info = ac._resolve_conflict_by_ownership(root, lane="orchestrator",
                                                 framework_side="--theirs")
    assert not ok and "outside" in info


def test_it_never_raises_on_a_broken_repo(tmp_path):
    ok, _ = ac._resolve_conflict_by_ownership(tmp_path, lane="orchestrator",
                                              framework_side="--theirs")
    assert ok is False


# --- direction ------------------------------------------------------------------------------

def test_the_shared_side_is_correct_in_the_merge_direction(tmp_path):
    """MERGE has integration checked out, so the shared side is `--ours`; PULL has the lane
    checked out, so it is `--theirs`. Both must keep integration's content."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    _write(root, _PAGE, "base\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "agent/orchestrator")
    _write(root, _PAGE, "THE LANE'S OWN VERSION\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "lane")
    _git(root, "checkout", "-q", "integration")
    _write(root, _PAGE, "INTEGRATION VERSION\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "integration")
    subprocess.run(["git", "-C", str(root), "merge", "--no-edit", "agent/orchestrator"],
                   capture_output=True, text=True)
    ok, _ = ac._resolve_conflict_by_ownership(root, lane="orchestrator", framework_side="--ours")
    assert ok
    assert (root / _PAGE).read_text(encoding="utf-8") == "INTEGRATION VERSION\n"


# --- end to end: the r124 stall ---------------------------------------------------------------

def test_the_r124_stall_now_converges(tmp_path):
    """The whole path, through `pull_main_into_worktree` and `_lane_of_worktree`: an
    orchestrator worktree carrying a stray committed page pulls integration cleanly."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "integration")
    _write(root, _PAGE, "base\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "base")

    wt = tmp_path / "worktrees" / "orchestrator"
    _git(root, "worktree", "add", "-q", "-b", "agent/orchestrator", str(wt))
    # the self-heal that caused the storm: commit a page you do not own
    _write(wt, _PAGE, "STRAY COPY COMMITTED BY THE ORCHESTRATOR\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "chore(orchestrator): clear worktree")

    _write(root, _PAGE, "THE FRONTEND LANE'S REAL PAGE\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "frontend merge")

    superseded = []
    ok, info = ac.pull_main_into_worktree(worktree_dir=wt, main_branch="integration",
                                          superseded_out=superseded)
    assert ok, f"pull still fails: {info}"
    assert (wt / _PAGE).read_text(encoding="utf-8") == "THE FRONTEND LANE'S REAL PAGE\n"
    assert superseded == [_PAGE]

    # and it CONVERGES — the second pull has nothing left to do
    ok2, info2 = ac.pull_main_into_worktree(worktree_dir=wt, main_branch="integration")
    assert ok2 and "up to date" in info2


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(ac._resolve_conflict_by_ownership).replace("#", " ").split())
    assert "1907 (91%) are CROSS-TERRITORY" in flat
    assert "70.8x" in flat


def test_the_safety_argument_is_structural_not_statistical():
    """Corrected after the fix shipped. Lane merges are SQUASH merges, so
    `integration..agent/<lane>` lists commits whose content IS already in integration — the
    ancestry argument this comment first used cannot answer the question. What makes discarding
    safe is that no lane worktree is ever a docker build context."""
    import inspect
    flat = " ".join(inspect.getsource(ac._resolve_conflict_by_ownership).split())
    assert "No lane worktree is ever a build context" in flat
    assert "SQUASH merges" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
