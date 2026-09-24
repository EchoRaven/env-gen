"""Bug 1 guard (youtube run, observed 6×): strategic merge must not abort
on a dirty working tree.

Observed failure: ``resolve_merge_conflict_via_strategy`` did
``checkout main_branch`` while repo_root had UNCOMMITTED agent edits to a
tracked file (``app/backend/main.py``) that also differed on the target
branch. git refused the checkout:

    error: Your local changes to the following files would be overwritten
    by merge: app/backend/main.py
    Please commit your changes or stash them before you merge. Aborting

so no conflict resolution ever ran (it returned "strategic merge still
conflicts: ..." / a checkout failure).

Fix: before ``checkout main_branch`` + merge, COMMIT the agent's
uncommitted edits onto the AGENT branch (never onto main_branch, never a
bare stash-drop), then integrate. This test pins that the strategic merge
SUCCEEDS and the agent's uncommitted edit is PRESERVED (committed, not
lost).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


def _git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)


class TestStrategicMergeDirtyTree(unittest.TestCase):
    def _init_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "checkout", "-qb", "main")
        (repo / "app").mkdir()
        (repo / "app" / "main.py").write_text("# base\nVERSION = 0\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        return repo

    def test_strategic_merge_succeeds_with_uncommitted_agent_edit(self):
        from multi_agent.agents.runtime.auto_commit import (
            resolve_merge_conflict_via_strategy,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))

            # Bootstrap an ``integration`` branch that DIFFERS on app/main.py,
            # so a later ``checkout integration`` would clobber a dirty
            # working-tree edit to the same path.
            _git(repo, "checkout", "-qb", "integration")
            (repo / "app" / "main.py").write_text("# integration\nVERSION = 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "integration change")

            # Agent branch off the base, with a committed change.
            _git(repo, "checkout", "-q", "main")
            _git(repo, "checkout", "-qb", "agent/backend")
            (repo / "app" / "feature.py").write_text("def feature():\n    return 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "[backend] feature")

            # Leave the agent on agent/backend and dirty the SAME tracked
            # file that differs on integration — reproduces the abort.
            self.assertEqual(
                _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                "agent/backend",
            )
            (repo / "app" / "main.py").write_text(
                "# AGENT UNCOMMITTED EDIT\nVERSION = 99\n"
            )
            self.assertTrue(_git(repo, "status", "--porcelain").stdout.strip())

            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                strategy="agent",
                agent_id="backend",
            )
            self.assertTrue(ok, f"strategic merge aborted on dirty tree: {info}")
            self.assertNotIn("would be overwritten", info)
            self.assertNotIn("still conflicts", info)

            # The agent's uncommitted edit must be PRESERVED — it was
            # committed onto agent/backend, so it rides the strategic merge
            # into integration (strategy='agent' → agent wins).
            r = _git(repo, "show", "integration:app/main.py")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("AGENT UNCOMMITTED EDIT", r.stdout)
            self.assertIn("VERSION = 99", r.stdout)
            # The committed feature also reached integration.
            r2 = _git(repo, "show", "integration:app/feature.py")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("def feature", r2.stdout)

            # The WIP must NOT have been committed onto main_branch
            # (integration) directly as a separate WIP commit; it belongs
            # to the agent branch. Verify agent/backend carries the edit.
            r3 = _git(repo, "show", "agent/backend:app/main.py")
            self.assertEqual(r3.returncode, 0, r3.stderr)
            self.assertIn("AGENT UNCOMMITTED EDIT", r3.stdout)

    def test_clean_tree_strategic_merge_still_works(self):
        """Regression guard: the dirty-tree handling must not disturb the
        existing clean-tree strategic-merge behavior."""
        from multi_agent.agents.runtime.auto_commit import (
            resolve_merge_conflict_via_strategy,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            _git(repo, "checkout", "-qb", "integration")
            (repo / "app" / "main.py").write_text("# integration\nVERSION = 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "integration change")

            _git(repo, "checkout", "-q", "main")
            _git(repo, "checkout", "-qb", "agent/backend")
            (repo / "app" / "main.py").write_text("# agent\nVERSION = 2\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "[backend] agent change")
            # Land repo on integration, clean, to mirror post-abort state.
            _git(repo, "checkout", "-q", "integration")

            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                strategy="agent",
                agent_id="backend",
            )
            self.assertTrue(ok, f"clean strategic merge failed: {info}")
            r = _git(repo, "show", "integration:app/main.py")
            self.assertIn("VERSION = 2", r.stdout)


if __name__ == "__main__":
    unittest.main()
