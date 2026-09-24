"""Re-merging an already-integrated branch must SUCCEED, not fail.

Regression for smoke #8/#11: ``resolve_merge_conflict_via_strategy`` (and
``merge_agent_branch_to_main``) committed the squash result with ``git commit
-q``. When the agent branch was already integrated (squash nets no change), the
commit exits 1 and ``-q`` SUPPRESSES the "nothing to commit" text the code keyed
on — so a benign no-op was misreported as ``git commit exit 1`` and the
orchestrator blocked delivery on an already-merged frontend. The fix detects the
empty index explicitly (``git diff --cached --quiet``).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))

from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    merge_agent_branch_to_main,
    resolve_merge_conflict_via_strategy,
)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def _init_repo_with_merged_branch(repo: Path):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "integration")
    # agent branch with a change
    _git(repo, "checkout", "-q", "-b", "agent/frontend")
    (repo / "app.txt").write_text("frontend\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "frontend work")
    # integrate it once (the real first merge)
    ok, _info = merge_agent_branch_to_main(
        repo_root=repo, agent_branch="agent/frontend",
        main_branch="integration", agent_id="frontend")
    assert ok, _info


class AlreadyIntegratedNoOp(unittest.TestCase):
    def test_strategy_remerge_of_integrated_branch_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_repo_with_merged_branch(repo)
            # Re-resolve the SAME (already-integrated) branch — nothing to commit.
            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo, agent_branch="agent/frontend",
                main_branch="integration", strategy="agent", agent_id="frontend")
            self.assertTrue(ok, f"already-integrated re-merge must succeed, got: {info}")
            self.assertNotIn("git commit exit", info)

    def test_regular_remerge_of_integrated_branch_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_repo_with_merged_branch(repo)
            ok, info = merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/frontend",
                main_branch="integration", agent_id="frontend")
            self.assertTrue(ok, f"already-integrated re-merge must succeed, got: {info}")
            self.assertNotIn("exit", info)


if __name__ == "__main__":
    unittest.main()
