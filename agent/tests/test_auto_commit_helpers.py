"""auto_commit helpers: stage_file + commit_worktree."""
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


def _init_repo_with_worktree(tmpdir: Path) -> tuple:
    """Init a bare-ish repo with one initial commit + a worktree for tests."""
    repo = tmpdir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    wt = tmpdir / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "agent/backend", str(wt)],
        cwd=repo, check=True,
    )
    return repo, wt


class TestStageFile(unittest.TestCase):
    def test_stage_file_runs_git_add_in_worktree(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            target = wt / "app/server.js"
            target.write_text("console.log('hi');\n")
            ok, err = stage_file(wt, target)
            self.assertTrue(ok, f"stage_file failed: {err}")
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=wt, capture_output=True, text=True,
            )
            self.assertIn("A  app/server.js", r.stdout)

    def test_stage_file_silent_on_missing_path(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            ok, err = stage_file(wt, wt / "does/not/exist.txt")
            self.assertFalse(ok)
            self.assertIn("does/not/exist", err)

    def test_stage_file_outside_worktree_refused(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            outside = Path(tmp) / "outside.txt"
            outside.write_text("x")
            ok, err = stage_file(wt, outside)
            self.assertFalse(ok)
            self.assertIn("outside", err.lower())


class TestCommitWorktree(unittest.TestCase):
    def test_commit_records_change_with_agent_author(self):
        from multi_agent.agents.runtime.auto_commit import stage_file, commit_worktree
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            f = wt / "app/server.js"
            f.write_text("x\n")
            stage_file(wt, f)
            ok, info = commit_worktree(
                worktree_dir=wt,
                branch="agent/backend",
                author="backend",
                message="[backend] finish: scaffolding",
            )
            self.assertTrue(ok, f"commit failed: {info}")
            log = subprocess.run(
                ["git", "log", "-1", "--format=%an|%s"],
                cwd=wt, capture_output=True, text=True,
            )
            line = log.stdout.strip()
            self.assertTrue(line.startswith("backend|"), f"author wrong: {line}")
            self.assertIn("[backend] finish: scaffolding", line)

    def test_commit_no_op_when_nothing_staged(self):
        from multi_agent.agents.runtime.auto_commit import commit_worktree
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            ok, info = commit_worktree(
                worktree_dir=wt, branch="agent/backend",
                author="backend", message="empty",
            )
            self.assertTrue(ok)
            self.assertIn("nothing to commit", info.lower())


if __name__ == "__main__":
    unittest.main()
