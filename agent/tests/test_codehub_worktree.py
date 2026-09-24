"""
Tests for CodeHub.ensure_repo / register_agent_worktree / cleanup_worktree (Task 3).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hubs.codehub.service import CodeHub  # noqa: E402


class TestCodeHubWorktreeLifecycle(unittest.TestCase):
    def _make_hub(self, td: str) -> CodeHub:
        base = Path(td)
        crdt_dir = base / "shared" / "crdt"
        crdt_dir.mkdir(parents=True, exist_ok=True)
        return CodeHub(base, crdt_dir)

    def test_register_agent_worktree_creates_branch(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_hub(td)
            wt_path = hub.register_agent_worktree("backend")

            # Worktree directory was created
            self.assertTrue(wt_path.is_dir())
            # The correct branch is checked out
            from multi_agent.runtime.hubs.codehub.git_ops import GitOps
            wt_ops = GitOps(wt_path)
            self.assertEqual(wt_ops.current_branch(), "agent/backend")

    def test_cleanup_worktree_removes_directory(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_hub(td)
            wt_path = hub.register_agent_worktree("frontend")
            self.assertTrue(wt_path.is_dir())

            removed = hub.cleanup_worktree("frontend")
            self.assertTrue(removed)
            self.assertFalse(wt_path.exists())

            # Calling cleanup again returns False (idempotent)
            removed_again = hub.cleanup_worktree("frontend")
            self.assertFalse(removed_again)


if __name__ == "__main__":
    unittest.main()
