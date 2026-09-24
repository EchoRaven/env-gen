"""PROPOSAL #36 CLASS C — strategic merge must not wedge on a worktree-held agent branch.

Run #34 (validation-wedge): the orchestrator called codehub_resolve_merge_conflict; repo_root
was on ``integration`` with tracked-dirty FRAMEWORK residue (scaffold/heal writes awaiting
commit_framework_delivery). The old code assumed that dirt was the AGENT's WIP and did
``git checkout agent_branch`` in repo_root to move it there — but ``agent/<id>`` is checked
out in ``worktrees/<id>``, so git refused:

    fatal: 'agent/orchestrator' is already checked out at '.../worktrees/orchestrator'

→ returned "strategic merge blocked …" and the #22/#23 ownership resolver never ran → the
conflict (the lane-edited Dockerfile) was unresolvable → validation wedged → no create_release.

Fix: when current_branch != agent_branch (the normal worktree case), the repo_root dirt is
transient framework residue → STASH it (mirrors merge_agent_branch_to_main), never
``checkout agent_branch``. This pins that the strategic merge SUCCEEDS in that topology.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


class TestStrategicMergeWorktreeCollision(unittest.TestCase):
    def test_succeeds_when_agent_branch_is_checked_out_in_a_worktree(self):
        from multi_agent.agents.runtime.auto_commit import (
            resolve_merge_conflict_via_strategy,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "t@e.com")
            _git(repo, "config", "user.name", "T")
            _git(repo, "checkout", "-qb", "main")
            (repo / "app").mkdir()
            (repo / "app" / "Dockerfile").write_text("FROM base\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")

            # integration branch with its own Dockerfile (framework version).
            _git(repo, "checkout", "-qb", "integration")
            (repo / "app" / "Dockerfile").write_text("FROM framework-clean\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "integration framework Dockerfile")

            # agent/backend off main, with a committed lane change (custom_routes).
            _git(repo, "checkout", "-q", "main")
            _git(repo, "checkout", "-qb", "agent/backend")
            (repo / "app" / "custom_routes.py").write_text("def routes():\n    return 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "[backend] custom routes")

            # ★ Put agent/backend into a WORKTREE (the real topology) and return
            #   repo_root to integration — so a `git checkout agent/backend` in
            #   repo_root is now IMPOSSIBLE (already checked out in the worktree).
            _git(repo, "checkout", "-q", "integration")
            wt = Path(tmp) / "worktrees" / "backend"
            wt.parent.mkdir(parents=True, exist_ok=True)
            rc_wt = _git(repo, "worktree", "add", str(wt), "agent/backend")
            self.assertEqual(rc_wt.returncode, 0, rc_wt.stderr)

            # repo_root on integration, tracked-dirty with FRAMEWORK residue
            # (the scaffold re-wrote the Dockerfile, awaiting commit).
            (repo / "app" / "Dockerfile").write_text("FROM framework-clean\n# regenerated\n")
            self.assertTrue(_git(repo, "status", "--porcelain").stdout.strip())
            self.assertEqual(
                _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                "integration",
            )

            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                strategy="agent",
                agent_id="backend",
            )
            # The fix: must NOT fail with the worktree-collision message.
            self.assertNotIn("already checked out", info)
            self.assertNotIn("strategic merge blocked", info)
            self.assertTrue(ok, f"strategic merge wedged on worktree topology: {info}")

            # The lane's committed work integrated.
            r = _git(repo, "show", "integration:app/custom_routes.py")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("def routes", r.stdout)

            # The worktree was never corrupted (agent/backend still checked out there).
            r2 = _git(repo, "worktree", "list", "--porcelain")
            self.assertIn("backend", r2.stdout)


if __name__ == "__main__":
    unittest.main()
