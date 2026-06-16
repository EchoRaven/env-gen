"""Round 8h Patch A — closed-by-construction pin for the false-alarm
``merge_conflict`` event suppression in ``pull_main_into_worktree``.

Smoke #18 surfaced an EventHub poisoned by ~184 ``merge_conflict``
events (phase=step_start_pull) with NO matching unmerged paths in the
actual worktree. The orchestrator's coordination log diagnosed these
as "engine-level metadata drift" — the events fired but the worktree
was clean.

Root cause: ``git merge`` can exit non-zero for reasons OTHER than a
genuine code-level conflict — a pre-commit hook failing, a signing
requirement, transient I/O on the integration branch — and the
pre-fix code treated ALL non-zero exits as "conflict pulling".

This test pins the new behavior: ``pull_main_into_worktree`` now
captures ``git diff --name-only --diff-filter=U`` BEFORE the abort
and ONLY returns ``(False, ...)`` if there are real conflict files.
Other failure modes return ``(True, "merge_failed_no_conflict ...")``
so the step_runner does NOT publish a misleading event.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _init_repo_with_worktree(tmpdir: Path, agent_id: str = "backend") -> tuple:
    repo = tmpdir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True,
    )
    subprocess.run(["git", "checkout", "-qb", "main"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    # Create the integration branch so pull_main_into_worktree's
    # rev-parse check passes.
    subprocess.run(
        ["git", "branch", "integration"], cwd=repo, check=True,
    )
    wt = tmpdir / f"wt_{agent_id}"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", f"agent/{agent_id}", str(wt)],
        cwd=repo, check=True,
    )
    return repo, wt


class PullMainNonConflictFailureTests(unittest.TestCase):
    """Verify the new false-alarm suppression path in
    ``pull_main_into_worktree`` returns the right tuple under both
    real-conflict and non-conflict-failure scenarios."""

    def test_clean_pull_still_returns_true(self):
        """Baseline — a clean pull still works."""
        from multi_agent.agents.runtime.auto_commit import (
            pull_main_into_worktree,
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp), "backend")
            ok, info = pull_main_into_worktree(
                worktree_dir=wt, main_branch="integration",
            )
            # Either "up to date" or a clean merge — both succeed.
            self.assertTrue(ok, f"clean pull failed: {info}")
            self.assertNotIn("merge_failed_no_conflict", info)

    def test_real_conflict_returns_false_with_files_in_info(self):
        """When there ARE actual unmerged files, the function returns
        (False, "conflict pulling ... [files=...]") so the caller can
        emit a real merge_conflict event."""
        from multi_agent.agents.runtime.auto_commit import (
            pull_main_into_worktree,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            # Commit a file on integration with content A.
            subprocess.run(
                ["git", "checkout", "-q", "integration"], cwd=repo, check=True,
            )
            conflict_file = repo / "shared.txt"
            conflict_file.write_text("from integration\n")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=repo, check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "integration version"], cwd=repo,
                check=True,
            )
            # Switch back to main so the worktree's agent branch is
            # unaffected by the integration commit.
            subprocess.run(
                ["git", "checkout", "-q", "main"], cwd=repo, check=True,
            )
            # On the agent's worktree branch, commit the SAME file
            # with conflicting content.
            wt_conflict = wt / "shared.txt"
            wt_conflict.write_text("from agent backend\n")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=wt, check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "agent version"], cwd=wt, check=True,
            )

            ok, info = pull_main_into_worktree(
                worktree_dir=wt, main_branch="integration",
            )
            self.assertFalse(ok, f"expected conflict; got ok=True info={info!r}")
            self.assertIn("conflict pulling", info)
            self.assertIn("files=shared.txt", info)

    def test_non_conflict_merge_failure_returns_true_no_event(self):
        """Round 8h Patch A core pin: when `git merge` fails for a
        reason OTHER than a code conflict (no unmerged files in the
        diff), the function returns (True, "merge_failed_no_conflict
        ...") so the step_runner does NOT publish a misleading
        merge_conflict event."""
        from multi_agent.agents.runtime import auto_commit

        # Capture all _run_git invocations; selectively fail the merge.
        original_run_git = auto_commit._run_git
        merge_call_count = {"n": 0}

        def fake_run_git(args, cwd=None, **kw):
            # Pass everything through to the real implementation
            # EXCEPT the merge call — that one we replace with
            # an exit-1, no-stderr response (simulating a pre-commit
            # hook failure that left no unmerged paths). The
            # subsequent diff call returns empty (no unmerged paths).
            if list(args[:2]) == ["merge", "--no-edit"]:
                merge_call_count["n"] += 1
                return 1, "", "hook failed (simulated)"
            if list(args[:2]) == ["diff", "--name-only"]:
                # No unmerged paths.
                return 0, "", ""
            return original_run_git(args, cwd=cwd, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp), "backend")
            # Force the up-to-date check to NOT short-circuit: drop
            # a commit on integration so HEAD..integration is
            # non-empty when pull_main_into_worktree runs.
            subprocess.run(
                ["git", "-C", str(wt.parent / "repo"), "checkout", "-q",
                 "integration"],
                check=True,
            )
            (wt.parent / "repo" / "newfile.txt").write_text("new\n")
            subprocess.run(
                ["git", "-C", str(wt.parent / "repo"), "add", "newfile.txt"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(wt.parent / "repo"), "commit", "-qm",
                 "integration update"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(wt.parent / "repo"), "checkout", "-q", "main"],
                check=True,
            )

            with patch.object(auto_commit, "_run_git", side_effect=fake_run_git):
                ok, info = auto_commit.pull_main_into_worktree(
                    worktree_dir=wt, main_branch="integration",
                )

        # The fake merge fired exactly once.
        self.assertEqual(merge_call_count["n"], 1)
        # ok=True so step_runner SKIPS the merge_conflict emit.
        self.assertTrue(
            ok,
            f"non-conflict merge failure should suppress event; got ok=False info={info!r}",
        )
        # Info string starts with the dispositive marker so the
        # caller / log readers can distinguish this from a real
        # conflict at a glance.
        self.assertTrue(
            info.startswith("merge_failed_no_conflict"),
            f"info should start with the disambiguator; got {info!r}",
        )


if __name__ == "__main__":
    unittest.main()
