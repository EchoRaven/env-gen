"""Phase 0.2 RE-FIX 5: auto-stage path filter — don't stage dotfiles
or other non-app paths into the agent worktree.

The propagation chain we close here:
    agent writes ``.gates/allowed_code_checks.yaml`` in worktree
    → auto-stage on agent finish: ``git add`` everything in worktree
    → auto-commit
    → squash-merge worktree → base_dir
    → user_gates reads ``.gates/allowed_code_checks.yaml`` from base_dir

Even with the allowlist relocated out-of-workspace (RE-FIX 1), the
auto-stage propagation is its own escalation surface: any agent-authored
dotfile would otherwise ride into the shared ``integration`` branch.

This suite asserts that:
  * dotfiles are refused unless in ``ALLOWED_DOTFILES``
  * dotted directories (``.gates/``, ``.secrets/``) are refused on any
    path component
  * regular ``app/...`` paths are allowed
  * rejections produce a warning log entry
  * end-to-end through ``stage_file``: a worktree with mixed legitimate
    + dotfile content only stages the legitimate paths
"""
from __future__ import annotations

import logging
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
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    wt = tmpdir / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "agent/backend", str(wt)],
        cwd=repo, check=True,
    )
    return repo, wt


def _staged_files(wt: Path) -> list:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=wt, capture_output=True, text=True,
    )
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


class TestShouldStagePath(unittest.TestCase):
    def test_dotfile_not_staged(self):
        """Agent writes .gates/foo.yaml → not stageable."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertFalse(_should_stage_path(".gates/allowed_code_checks.yaml"))
        self.assertFalse(_should_stage_path(".gates/foo.yaml"))

    def test_allowed_dotfile_staged(self):
        """Agent writes .gitignore / .gitattributes → IS stageable."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertTrue(_should_stage_path(".gitignore"))
        self.assertTrue(_should_stage_path(".gitattributes"))
        self.assertTrue(_should_stage_path(".gitkeep"))
        self.assertTrue(_should_stage_path(".env.example"))

    def test_dotdir_not_staged(self):
        """Any path component starting with '.' rejects (e.g. .secrets/x)."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertFalse(_should_stage_path(".secrets/x"))
        self.assertFalse(_should_stage_path(".github/workflows/ci.yml"))
        self.assertFalse(_should_stage_path("app/.env"))
        self.assertFalse(_should_stage_path("app/backend/.hidden/file.py"))

    def test_app_file_staged(self):
        """Regular app paths pass the filter."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertTrue(_should_stage_path("app/backend/main.py"))
        self.assertTrue(_should_stage_path("app/frontend/src/index.tsx"))
        self.assertTrue(_should_stage_path("tasks/T_001.yaml"))
        self.assertTrue(_should_stage_path("tests/test_x.py"))
        self.assertTrue(_should_stage_path("README.md"))

    def test_pycache_and_pyc_never_staged(self):
        """instagram MM run #9: committed __pycache__/*.pyc caused 'Cannot merge binary
        files' conflicts on agent→integration, so backend fixes never reached the
        validated tree. Compiled artifacts must never stage."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertFalse(_should_stage_path("app/backend/__pycache__/main.cpython-314.pyc"))
        self.assertFalse(_should_stage_path("__pycache__/x.pyc"))
        self.assertFalse(_should_stage_path("app/backend/models.pyc"))
        self.assertFalse(_should_stage_path("app/backend/foo.pyo"))
        # real source under a normal dir still stages
        self.assertTrue(_should_stage_path("app/backend/models.py"))

    def test_filter_logs_rejection(self):
        """Rejected file produces a warning entry naming the agent."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        with self.assertLogs(
            "multi_agent.agents.runtime.auto_commit", level="WARNING",
        ) as cm:
            _should_stage_path(".gates/x.yaml", agent_id="backend")
        joined = "\n".join(cm.output)
        self.assertIn("auto-stage refused", joined)
        self.assertIn(".gates/x.yaml", joined)
        self.assertIn("backend", joined)

    def test_filter_applied_per_path(self):
        """Mixed allowed + dotfile list filters to only the allowed paths."""
        from multi_agent.agents.runtime.auto_commit import _filter_paths_for_staging
        candidates = [
            "app/backend/main.py",
            ".gates/allowed_code_checks.yaml",
            "app/frontend/index.tsx",
            ".secrets/x",
            "tasks/T1.yaml",
            ".gitignore",          # ALLOWED dotfile — must stay
            "tests/.hidden/x.py",  # dotted component anywhere → drop
        ]
        kept = _filter_paths_for_staging(candidates, agent_id="backend")
        self.assertEqual(
            kept,
            [
                "app/backend/main.py",
                "app/frontend/index.tsx",
                "tasks/T1.yaml",
                ".gitignore",
            ],
        )

    def test_backslash_separated_paths_normalized(self):
        """Windows-style separators still get filtered correctly."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertFalse(_should_stage_path(".gates\\foo.yaml"))
        self.assertTrue(_should_stage_path("app\\backend\\main.py"))

    def test_empty_or_absolute_path_refused(self):
        """Defensive: empty / absolute paths refused (callers should never pass these)."""
        from multi_agent.agents.runtime.auto_commit import _should_stage_path
        self.assertFalse(_should_stage_path(""))
        self.assertFalse(_should_stage_path("/abs/path/foo.py"))


class TestStageFileFilter(unittest.TestCase):
    """End-to-end through stage_file in a real git worktree."""

    def test_stage_file_refuses_dotfile_under_hidden_dir(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / ".gates").mkdir()
            target = wt / ".gates" / "allowed_code_checks.yaml"
            target.write_text("- whoami\n")
            ok, msg = stage_file(wt, target, agent_id="backend")
            self.assertFalse(ok)
            self.assertIn("dotfile not in allowlist", msg)
            # And critically: NOT staged.
            self.assertNotIn(".gates/allowed_code_checks.yaml", _staged_files(wt))

    def test_stage_file_allows_gitignore(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            target = wt / ".gitignore"
            target.write_text("*.pyc\n")
            ok, info = stage_file(wt, target, agent_id="backend")
            self.assertTrue(ok, f"stage_file rejected .gitignore: {info}")
            self.assertIn(".gitignore", _staged_files(wt))

    def test_stage_file_allows_app_path(self):
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            (wt / "app" / "backend").mkdir(parents=True)
            target = wt / "app" / "backend" / "main.py"
            target.write_text("print('hi')\n")
            ok, info = stage_file(wt, target, agent_id="backend")
            self.assertTrue(ok, f"stage_file failed on app path: {info}")
            self.assertIn("app/backend/main.py", _staged_files(wt))

    def test_stage_deletion_refuses_dotfile(self):
        from multi_agent.agents.runtime.auto_commit import stage_deletion
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            phantom = wt / ".secrets" / "x"
            ok, msg = stage_deletion(wt, phantom, agent_id="backend")
            self.assertFalse(ok)
            self.assertIn("dotfile not in allowlist", msg)

    def test_mixed_worktree_only_allowed_paths_staged(self):
        """A worktree with mixed allowed + dotfile content — only allowed
        paths end up in the final staged set."""
        from multi_agent.agents.runtime.auto_commit import stage_file
        with tempfile.TemporaryDirectory() as tmp:
            _, wt = _init_repo_with_worktree(Path(tmp))
            # Allowed.
            (wt / "app" / "backend").mkdir(parents=True)
            ok_path = wt / "app" / "backend" / "main.py"
            ok_path.write_text("print('hi')\n")
            # Disallowed: dotted directory.
            (wt / ".gates").mkdir()
            bad_path = wt / ".gates" / "allowed_code_checks.yaml"
            bad_path.write_text("- whoami\n")
            # Disallowed: dotfile leaf at root.
            bad_env = wt / ".env"
            bad_env.write_text("SECRET=1\n")
            # Allowed-dotfile.
            gi = wt / ".gitignore"
            gi.write_text("__pycache__/\n")

            for p in [ok_path, bad_path, bad_env, gi]:
                stage_file(wt, p, agent_id="backend")

            staged = sorted(_staged_files(wt))
            self.assertIn("app/backend/main.py", staged)
            self.assertIn(".gitignore", staged)
            self.assertNotIn(".gates/allowed_code_checks.yaml", staged)
            self.assertNotIn(".env", staged)


if __name__ == "__main__":
    unittest.main()
