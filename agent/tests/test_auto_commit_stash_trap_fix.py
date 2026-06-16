"""auto_commit step-start pull stash-trap fix verification.

The May 29 facebook-clone run audit (workflow w241o5bwn) diagnosed a
19-hour stall caused by stash-pop conflicts on untracked
``memory-bank/<role>/*.md`` files inside the step-start integration
pull (``auto_commit.pull_main_into_worktree``). Each of the 4 implementation
lanes + knowledge hit the same conflict in a clustered window and
re-hit it on every subsequent step.

Closed-by-construction fix: memory-bank is each agent's own scratch
subtree — commit memory-bank changes BEFORE the pull instead of
stashing them. The merge integrates the commit as an ancestor; no
stash → no pop → no conflict.

Recovery for non-memory-bank stash-pop conflicts: instead of leaving
the stash entry on the stack (which compounds every step), the
recovery now ``checkout --theirs`` + ``stash drop`` so the stack
doesn't grow + the loop is broken.

Tests construct real Git worktrees with the trap shape, run
pull_main_into_worktree, and assert the new behavior.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.auto_commit import pull_main_into_worktree  # noqa: E402


def _git(args, cwd, check=True):
    """Run git, return (rc, stdout)."""
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {args} failed in {cwd}: {proc.stderr}"
        )
    return proc.returncode, proc.stdout, proc.stderr


def _init_repo_with_main(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=repo_dir)
    _git(["config", "user.email", "t@t"], cwd=repo_dir)
    _git(["config", "user.name", "t"], cwd=repo_dir)
    _git(["checkout", "-q", "-b", "main"], cwd=repo_dir, check=False)
    (repo_dir / "README.md").write_text("seed\n")
    _git(["add", "README.md"], cwd=repo_dir)
    _git(["commit", "-q", "-m", "seed"], cwd=repo_dir)


class _StashTrapFixture(unittest.TestCase):
    """Builds the May 29 trap shape:
      - integration main has memory-bank/role-X/foo.md committed
      - agent's worktree has an UNTRACKED memory-bank/role-X/foo.md
      - pull_main_into_worktree must not stall
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auto_commit_stash_"))
        # Set up a bare-ish "integration" repo on main branch
        self.repo = self.tmp / "repo"
        _init_repo_with_main(self.repo)
        # Add a memory-bank file on main from another agent's perspective
        mb_dir = self.repo / "memory-bank" / "other-agent"
        mb_dir.mkdir(parents=True)
        (mb_dir / "notes.md").write_text("other agent's notes\n")
        _git(["add", "memory-bank/"], cwd=self.repo)
        _git(["commit", "-q", "-m", "other agent committed memory-bank"], cwd=self.repo)
        # Make agent worktree by cloning + checking out an agent branch
        self.wt = self.tmp / "agent_wt"
        _git(["clone", "-q", str(self.repo), str(self.wt)], cwd=self.tmp)
        _git(["config", "user.email", "a@a"], cwd=self.wt)
        _git(["config", "user.name", "a"], cwd=self.wt)
        _git(["checkout", "-q", "-b", "agent/backend"], cwd=self.wt)
        # Roll back agent's branch so main now has commits agent doesn't
        # (so the pull is non-empty).
        _git(["reset", "--hard", "HEAD~1"], cwd=self.wt)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class MemoryBankCommitFirstFix(_StashTrapFixture):
    """When dirty changes are ONLY in memory-bank/<id>/, the new path
    commits them onto the agent's branch BEFORE the merge."""

    def test_pull_succeeds_with_untracked_memory_bank(self) -> None:
        """Untracked memory-bank/backend/notes.md in the agent worktree
        + integration main bringing in memory-bank/other-agent/notes.md
        — the trap shape from the May 29 stall."""
        # Create an untracked memory-bank/backend/notes.md in worktree
        agent_mb = self.wt / "memory-bank" / "backend"
        agent_mb.mkdir(parents=True)
        (agent_mb / "notes.md").write_text("my own notes\n")
        # Pull integration — should NOT stall
        ok, info = pull_main_into_worktree(worktree_dir=self.wt, main_branch="main")
        self.assertTrue(ok, msg=f"pull failed: {info}")
        # The agent's own memory-bank file is preserved
        self.assertTrue((agent_mb / "notes.md").exists())
        # And the other agent's memory-bank file is now in the worktree
        self.assertTrue(
            (self.wt / "memory-bank" / "other-agent" / "notes.md").exists()
        )

    def test_memory_bank_committed_not_stashed(self) -> None:
        """After the fix runs, there should be NO stash entries
        (the May 29 trap left stash-after-stash; this test verifies
        the stack stays empty)."""
        agent_mb = self.wt / "memory-bank" / "backend"
        agent_mb.mkdir(parents=True)
        (agent_mb / "notes.md").write_text("my own notes\n")
        ok, _info = pull_main_into_worktree(worktree_dir=self.wt, main_branch="main")
        self.assertTrue(ok)
        rc, out, _ = _git(["stash", "list"], cwd=self.wt, check=False)
        self.assertEqual(out.strip(), "",
                         msg=f"stash stack should be empty, got: {out!r}")

    def test_repeated_pull_stays_stable(self) -> None:
        """The May 29 loop: re-pulling kept re-stashing + re-failing.
        Now repeated pulls with the same untracked memory-bank file
        should all succeed (idempotent)."""
        agent_mb = self.wt / "memory-bank" / "backend"
        agent_mb.mkdir(parents=True)
        (agent_mb / "notes.md").write_text("my own notes\n")
        # First pull
        ok1, _ = pull_main_into_worktree(worktree_dir=self.wt, main_branch="main")
        self.assertTrue(ok1)
        # No more updates to pull — should bail "already up to date"
        ok2, info2 = pull_main_into_worktree(worktree_dir=self.wt, main_branch="main")
        self.assertTrue(ok2)
        self.assertIn("up to date", info2)


class StashPopRecoveryDoesNotStall(_StashTrapFixture):
    """Even when stash IS used (mixed dirty content or non-memory-bank
    dirty content), the new stash-pop conflict recovery
    (checkout --theirs + stash drop) breaks the May 29 stall loop."""

    def test_mixed_dirty_uses_stash_and_recovers(self) -> None:
        """Mixed memory-bank + other dirty content forces the stash
        path. If pop conflicts, the recovery should NOT leave the
        stash on the stack (which would re-trip next pull)."""
        agent_mb = self.wt / "memory-bank" / "backend"
        agent_mb.mkdir(parents=True)
        (agent_mb / "notes.md").write_text("my own notes\n")
        # Add a non-memory-bank dirty file
        (self.wt / "other_dirty.txt").write_text("not memory-bank\n")
        ok, info = pull_main_into_worktree(worktree_dir=self.wt, main_branch="main")
        # Pull should succeed (or report stash-handled cleanly)
        self.assertTrue(ok, msg=f"pull failed: {info}")
        rc, out, _ = _git(["stash", "list"], cwd=self.wt, check=False)
        # Stack must be empty (no growing stash from the May 29 loop)
        self.assertEqual(
            out.strip(), "",
            msg=f"stash stack should be empty after recovery, got: {out!r}",
        )


if __name__ == "__main__":
    unittest.main()
