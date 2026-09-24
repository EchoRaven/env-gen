"""#1202fl / #1202fm -- drive the REAL ownership resolver against REAL git repos.

r96 stalled for its final 18 minutes on

    checkout --theirs app/frontend/src/pages/LoginPage.jsx failed:
      error: path '...' does not have their version

which is a MODIFY/DELETE conflict: the index has no stage for the side ownership picked,
so `git checkout --ours/--theirs` cannot work and the whole resolution aborts -- every
retry, forever. These tests build that exact conflict with real git so the assertion is
about BEHAVIOUR, not about how the fix is spelled.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime import auto_commit as AC  # noqa: E402

PAGE = "app/frontend/src/pages/LoginPage.jsx"   # lane-owned (src/pages/ prefix)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def _repo(tmp_path):
    r = tmp_path / "repo"
    (r / "app/frontend/src/pages").mkdir(parents=True)
    _git(r.parent, "init", "-q", "repo")
    _git(r, "config", "user.email", "t@t.local")
    _git(r, "config", "user.name", "t")
    (r / PAGE).write_text("export default function Login(){return <div/>}\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _modify_delete(tmp_path, *, deleted_on_branch: bool):
    """Return a repo mid-merge with a real modify/delete conflict on PAGE.

    deleted_on_branch=True  -> the incoming branch deleted it, HEAD modified it
    deleted_on_branch=False -> HEAD deleted it, the incoming branch modified it
    """
    r = _repo(tmp_path)
    _git(r, "checkout", "-q", "-b", "feature")
    if deleted_on_branch:
        _git(r, "rm", "-q", PAGE)
    else:
        (r / PAGE).write_text("// branch edit\n")
        _git(r, "add", "-A")
    _git(r, "commit", "-qm", "feature side")
    _git(r, "checkout", "-q", "master" if _git(r, "rev-parse", "--verify",
                                               "master").returncode == 0 else "main")
    if deleted_on_branch:
        (r / PAGE).write_text("// head edit\n")
        _git(r, "add", "-A")
    else:
        _git(r, "rm", "-q", PAGE)
    _git(r, "commit", "-qm", "head side")
    m = _git(r, "merge", "feature")
    assert m.returncode != 0, "expected a merge conflict"
    unmerged = _git(r, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert PAGE in unmerged, f"expected {PAGE} unmerged, got {unmerged}"
    return r


@pytest.mark.parametrize("deleted_on_branch", [True, False])
@pytest.mark.parametrize("framework_side", ["--ours", "--theirs"])
def test_modify_delete_resolves_instead_of_aborting(
        tmp_path, deleted_on_branch, framework_side):
    """#1202fl: every direction/side combination must RESOLVE, not abort.

    Before the fix, whichever combination asked for the missing stage returned
    False and the merge stayed conflicted forever."""
    r = _modify_delete(tmp_path, deleted_on_branch=deleted_on_branch)
    ok, msg = AC._resolve_conflict_by_ownership(
        r, lane="frontend", framework_side=framework_side)
    assert ok, f"resolver aborted on a modify/delete conflict: {msg}"
    # The property that matters: git no longer considers anything unmerged.
    left = _git(r, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert left == [], f"paths still unmerged after a successful resolve: {left}"
    # And the resolution is committable -- a stuck merge is exactly what blocked r96.
    c = _git(r, "commit", "-qm", "resolved")
    assert c.returncode == 0, f"resolved tree would not commit: {c.stderr}"


def test_deletion_side_actually_removes_the_file(tmp_path):
    """When the winning side's version IS absence, the path must end up deleted --
    not silently resurrected from the other side."""
    # branch deleted it; ownership sends lane-owned pages to the LANE side, and with
    # framework_side="--ours" the lane side is "--theirs" == the branch == deletion.
    r = _modify_delete(tmp_path, deleted_on_branch=True)
    ok, msg = AC._resolve_conflict_by_ownership(
        r, lane="frontend", framework_side="--ours")
    assert ok, msg
    assert not (r / PAGE).exists(), "the deleting side won but the file survived"
    assert "deleted" in msg, f"resolution should say it deleted the path: {msg}"


def test_ordinary_content_conflict_still_takes_the_checkout_path(tmp_path):
    """Guard the untouched majority case: both sides modified -> content is kept,
    nothing is deleted."""
    r = _repo(tmp_path)
    head = _git(r, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    _git(r, "checkout", "-q", "-b", "feature")
    (r / PAGE).write_text("// branch content\n")
    _git(r, "commit", "-qam", "branch")
    _git(r, "checkout", "-q", head)
    (r / PAGE).write_text("// head content\n")
    _git(r, "commit", "-qam", "head")
    assert _git(r, "merge", "feature").returncode != 0
    ok, msg = AC._resolve_conflict_by_ownership(
        r, lane="frontend", framework_side="--ours")
    assert ok, msg
    assert (r / PAGE).exists(), "a content conflict must not delete the file"
    assert _git(r, "diff", "--name-only", "--diff-filter=U").stdout.split() == []


def test_stage_probe_reports_what_the_index_holds(tmp_path):
    """#1202fl's probe is the decision input -- it must distinguish the two cases."""
    r = _modify_delete(tmp_path, deleted_on_branch=True)
    stages = AC._conflict_stages_1202fl(r, PAGE)
    assert 3 not in stages, "branch deleted it, so there is no 'theirs' stage"
    assert 2 in stages, "HEAD modified it, so an 'ours' stage must exist"


def test_unconflicted_path_probes_as_no_stages(tmp_path):
    r = _repo(tmp_path)
    assert AC._conflict_stages_1202fl(r, PAGE) == set()


def test_strategic_merge_failure_names_the_paths(tmp_path):
    """#1202fm: the caller used to be handed 'strategic merge still conflicts: ' with
    NOTHING after the colon -- git writes its CONFLICT lines to stdout while the code
    reported stderr, and `merge --abort` erased the index that named the paths before
    they were read. Six such empty failures in r96 told the orchestrator and the lane
    nothing they could act on."""
    r = _repo(tmp_path)
    head = _git(r, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    # A conflict that -X strategy genuinely cannot settle: modify/delete.
    _git(r, "checkout", "-q", "-b", "feature")
    _git(r, "rm", "-q", PAGE)
    _git(r, "commit", "-qm", "branch deletes")
    _git(r, "checkout", "-q", head)
    (r / PAGE).write_text("// head edit\n")
    _git(r, "commit", "-qam", "head edits")
    _git(r, "branch", "-q", "integration", head)

    ok, msg = AC.resolve_merge_conflict_via_strategy(
        repo_root=r, agent_branch="feature", main_branch=head,
        strategy="agent", agent_id="frontend")
    if ok:
        pytest.skip("this git settles modify/delete under -X; nothing to report on")
    assert msg.rstrip().rstrip(":") != "strategic merge still conflicts", (
        "conflict reported with no detail at all")
    assert PAGE in msg or "CONFLICT" in msg, (
        f"failure names neither a path nor a git CONFLICT line: {msg!r}")
