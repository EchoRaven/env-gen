"""restage_written_files — commit backstop (2026-06-05).

Root cause: per-write ``_auto_stage`` can silently skip (e.g.
``workspace.resolve`` returns None), leaving an agent's written files
UNTRACKED in its worktree. ``commit_worktree`` only commits PRE-STAGED
changes, so the agent's whole deliverable then never reaches its branch
(observed in smoke #2: backend wrote app/backend/* but they stayed
untracked → ``agent/backend`` had only the initial commit → nothing
merged → output app/backend absent → docker_up impossible).

``restage_written_files`` is the backstop ``_auto_stage``'s own docstring
already promises ("the next codehub_commit will pick the file up"): right
before the finish-commit, re-stage every file the agent wrote this
session. Precise (only agent-written paths, not memory-bank), dotfile-
filtered (reuses stage_file), and robust to the resolve→None failure mode
(resolves paths as worktree/<rel>, not via workspace).
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


def _init_repo_with_worktree(tmpdir: Path) -> tuple:
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


def _staged(wt: Path) -> str:
    return subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=wt, capture_output=True, text=True,
    ).stdout


class RestageWrittenFilesTests(unittest.TestCase):
    def test_stages_unstaged_written_files(self):
        from multi_agent.agents.runtime.auto_commit import restage_written_files
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            # Agent wrote these but they were NEVER staged (the bug).
            (wt / "app/backend").mkdir(parents=True)
            (wt / "app/backend/Dockerfile").write_text("FROM node:20\n")
            (wt / "app/backend/package.json").write_text("{}\n")
            self.assertEqual(_staged(wt).strip(), "")  # precondition: nothing staged

            staged = restage_written_files(
                wt, ["app/backend/Dockerfile", "app/backend/package.json"],
                agent_id="backend",
            )
            self.assertEqual(
                sorted(staged),
                ["app/backend/Dockerfile", "app/backend/package.json"],
            )
            out = _staged(wt)
            self.assertIn("app/backend/Dockerfile", out)
            self.assertIn("app/backend/package.json", out)

    def test_idempotent_when_already_staged(self):
        from multi_agent.agents.runtime.auto_commit import (
            restage_written_files, stage_file,
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            (wt / "app/server.js").write_text("x\n")
            stage_file(wt, wt / "app/server.js")  # already staged
            staged = restage_written_files(wt, ["app/server.js"], agent_id="backend")
            self.assertEqual(staged, ["app/server.js"])
            self.assertIn("app/server.js", _staged(wt))

    def test_respects_dotfile_filter(self):
        from multi_agent.agents.runtime.auto_commit import restage_written_files
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / ".gates").mkdir()
            (wt / ".gates/allowed.yaml").write_text("x\n")
            staged = restage_written_files(wt, [".gates/allowed.yaml"], agent_id="backend")
            self.assertEqual(staged, [])  # dotfile refused
            self.assertEqual(_staged(wt).strip(), "")

    def test_skips_missing_and_duplicate_paths(self):
        from multi_agent.agents.runtime.auto_commit import restage_written_files
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app").mkdir()
            (wt / "app/real.js").write_text("x\n")
            staged = restage_written_files(
                wt,
                ["app/real.js", "app/real.js", "app/ghost.js", "", None],
                agent_id="backend",
            )
            self.assertEqual(staged, ["app/real.js"])  # deduped, ghost skipped


if __name__ == "__main__":
    unittest.main()
