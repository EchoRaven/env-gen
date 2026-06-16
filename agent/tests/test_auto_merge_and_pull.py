"""Phase 0b: auto-merge agent branches to ``agent`` main; auto-pull
``agent`` main into each agent's worktree before reading."""
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


def _init_repo_with_worktree(tmpdir: Path, agent_id: str = "backend") -> tuple:
    repo = tmpdir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-qb", "main"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    wt = tmpdir / f"wt_{agent_id}"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", f"agent/{agent_id}", str(wt)],
        cwd=repo, check=True,
    )
    return repo, wt


class TestMergeAgentBranchToMain(unittest.TestCase):
    def test_first_merge_bootstraps_agent_main(self):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            (wt / "app").mkdir()
            f = wt / "app/server.js"
            f.write_text("x\n")
            stage_file(wt, f)
            commit_worktree(
                worktree_dir=wt, branch="agent/backend",
                author="backend", message="[backend] finish: ok",
            )
            # No ``agent`` branch yet — first merge bootstraps it.
            ok, info = merge_agent_branch_to_main(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                agent_id="backend",
            )
            self.assertTrue(ok, f"merge failed: {info}")
            # Verify ``agent`` branch now exists and has the file.
            r = subprocess.run(
                ["git", "show", "integration:app/server.js"],
                cwd=repo, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("x", r.stdout)

    def test_second_merge_squashes_new_changes(self):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            (wt / "app").mkdir()
            f1 = wt / "app/a.js"
            f1.write_text("a\n")
            stage_file(wt, f1)
            commit_worktree(worktree_dir=wt, branch="agent/backend",
                            author="backend", message="[backend] a")
            merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )

            # Second round on the same branch.
            f2 = wt / "app/b.js"
            f2.write_text("b\n")
            stage_file(wt, f2)
            commit_worktree(worktree_dir=wt, branch="agent/backend",
                            author="backend", message="[backend] b")
            ok, info = merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )
            self.assertTrue(ok, f"second merge failed: {info}")
            # ``agent`` branch must have BOTH files.
            for name in ("a", "b"):
                r = subprocess.run(
                    ["git", "show", f"integration:app/{name}.js"],
                    cwd=repo, capture_output=True, text=True,
                )
                self.assertEqual(r.returncode, 0, f"missing app/{name}.js: {r.stderr}")

    def test_merge_with_nothing_new_is_a_noop(self):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            (wt / "app").mkdir()
            f = wt / "app/a.js"
            f.write_text("a\n")
            stage_file(wt, f)
            commit_worktree(worktree_dir=wt, branch="agent/backend",
                            author="backend", message="[backend] a")
            ok1, _ = merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )
            self.assertTrue(ok1)
            # Second merge with no new commits.
            ok2, info = merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )
            self.assertTrue(ok2)
            self.assertIn("nothing to merge", info)


class TestPullMainIntoWorktree(unittest.TestCase):
    def test_pull_brings_other_agents_files_into_my_worktree(self):
        """Backend commits + merges; verifier pulls main → verifier
        sees backend's files in its worktree."""
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
            pull_main_into_worktree,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt_backend = _init_repo_with_worktree(Path(tmp), "backend")
            # Also create verifier's worktree on agent/verifier.
            wt_verifier = Path(tmp) / "wt_verifier"
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "agent/verifier", str(wt_verifier)],
                cwd=repo, check=True,
            )

            # Backend writes, commits, merges to main.
            (wt_backend / "app").mkdir()
            (wt_backend / "app/server.js").write_text("server!\n")
            stage_file(wt_backend, wt_backend / "app/server.js")
            commit_worktree(worktree_dir=wt_backend, branch="agent/backend",
                            author="backend", message="[backend] server")
            merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )

            # Before pull: verifier's worktree has NO app/server.js.
            self.assertFalse((wt_verifier / "app" / "server.js").exists())

            # Verifier pulls main → sees backend's file.
            ok, info = pull_main_into_worktree(
                worktree_dir=wt_verifier, main_branch="integration",
            )
            self.assertTrue(ok, f"pull failed: {info}")
            self.assertTrue(
                (wt_verifier / "app" / "server.js").exists(),
                "verifier worktree did not receive backend's file after pull",
            )

    def test_pull_when_main_missing_skips_quietly(self):
        from multi_agent.agents.runtime.auto_commit import pull_main_into_worktree
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            # No agent branch exists yet — pull should silently skip.
            ok, info = pull_main_into_worktree(
                worktree_dir=wt, main_branch="integration",
            )
            self.assertTrue(ok)
            self.assertIn("does not exist", info)

    def test_pull_handles_dirty_worktree_via_stash(self):
        """If the worktree has uncommitted changes that DON'T conflict,
        the pull stashes them, merges, and restores them — agent's
        in-progress work is preserved."""
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
            pull_main_into_worktree,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt_backend = _init_repo_with_worktree(Path(tmp), "backend")
            wt_verifier = Path(tmp) / "wt_verifier"
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "agent/verifier", str(wt_verifier)],
                cwd=repo, check=True,
            )
            # Backend creates a file in app/ and merges to integration.
            (wt_backend / "app").mkdir()
            (wt_backend / "app/server.js").write_text("server\n")
            stage_file(wt_backend, wt_backend / "app/server.js")
            commit_worktree(worktree_dir=wt_backend, branch="agent/backend",
                            author="backend", message="[backend] server")
            merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )
            # Verifier has in-progress uncommitted work in a *different* path.
            (wt_verifier / "notes").mkdir()
            (wt_verifier / "notes" / "scratch.md").write_text("draft\n")
            ok, info = pull_main_into_worktree(
                worktree_dir=wt_verifier, main_branch="integration",
            )
            self.assertTrue(ok, f"pull failed unexpectedly: {info}")
            # Both must now coexist.
            self.assertTrue((wt_verifier / "app" / "server.js").exists(),
                            "merged file from integration is missing")
            self.assertTrue((wt_verifier / "notes" / "scratch.md").exists(),
                            "agent's in-progress file was lost by the pull")

    def test_pull_idempotent_when_up_to_date(self):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
            pull_main_into_worktree,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            (wt / "app").mkdir()
            (wt / "app/a.js").write_text("a\n")
            stage_file(wt, wt / "app/a.js")
            commit_worktree(worktree_dir=wt, branch="agent/backend",
                            author="backend", message="[backend] a")
            merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )
            # Now pull into the SAME worktree (which already has the change
            # via its own commit). Should be a no-op.
            ok, info = pull_main_into_worktree(
                worktree_dir=wt, main_branch="integration",
            )
            self.assertTrue(ok)
            self.assertIn("up to date", info.lower())


class TestResolveMergeConflict(unittest.TestCase):
    def _setup_two_agents_conflicting(self, tmp: Path):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
        )
        repo, wt_backend = _init_repo_with_worktree(tmp, "backend")
        wt_frontend = tmp / "wt_frontend"
        subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "agent/frontend", str(wt_frontend)],
            cwd=repo, check=True,
        )
        # Backend commits + merges first → integration has "backend version".
        (wt_backend / "app").mkdir()
        (wt_backend / "app/shared.js").write_text("// from backend\nmodule.exports = 'backend';\n")
        stage_file(wt_backend, wt_backend / "app/shared.js")
        commit_worktree(worktree_dir=wt_backend, branch="agent/backend",
                        author="backend", message="[backend] shared.js")
        merge_agent_branch_to_main(
            repo_root=repo, agent_branch="agent/backend",
            main_branch="integration", agent_id="backend",
        )
        # Frontend writes a different version of the SAME file, commits.
        (wt_frontend / "app").mkdir()
        (wt_frontend / "app/shared.js").write_text("// from frontend\nmodule.exports = 'frontend';\n")
        stage_file(wt_frontend, wt_frontend / "app/shared.js")
        commit_worktree(worktree_dir=wt_frontend, branch="agent/frontend",
                        author="frontend", message="[frontend] shared.js")
        # First merge attempt → CONFLICT (returns False).
        ok, info = merge_agent_branch_to_main(
            repo_root=repo, agent_branch="agent/frontend",
            main_branch="integration", agent_id="frontend",
        )
        self.assertFalse(ok)
        self.assertIn("conflict", info.lower())
        return repo

    def test_strategy_agent_lets_incoming_win(self):
        from multi_agent.agents.runtime.auto_commit import resolve_merge_conflict_via_strategy
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._setup_two_agents_conflicting(Path(tmp))
            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo, agent_branch="agent/frontend",
                main_branch="integration", strategy="agent",
                agent_id="frontend",
            )
            self.assertTrue(ok, f"resolve failed: {info}")
            # integration must now contain the FRONTEND version.
            r = subprocess.run(
                ["git", "show", "integration:app/shared.js"],
                cwd=repo, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("from frontend", r.stdout)
            self.assertNotIn("from backend", r.stdout)

    def test_strategy_integration_keeps_existing_version(self):
        from multi_agent.agents.runtime.auto_commit import resolve_merge_conflict_via_strategy
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._setup_two_agents_conflicting(Path(tmp))
            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo, agent_branch="agent/frontend",
                main_branch="integration", strategy="integration",
                agent_id="frontend",
            )
            self.assertTrue(ok, f"resolve failed: {info}")
            r = subprocess.run(
                ["git", "show", "integration:app/shared.js"],
                cwd=repo, capture_output=True, text=True,
            )
            self.assertIn("from backend", r.stdout)
            self.assertNotIn("from frontend", r.stdout)

    def test_unknown_strategy_returns_error(self):
        from multi_agent.agents.runtime.auto_commit import resolve_merge_conflict_via_strategy
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._setup_two_agents_conflicting(Path(tmp))
            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=repo, agent_branch="agent/frontend",
                main_branch="integration", strategy="best-effort",
            )
            self.assertFalse(ok)
            self.assertIn("unknown strategy", info)


class TestRevertCommitOnBranch(unittest.TestCase):
    def test_revert_undoes_change_with_new_commit(self):
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
            revert_commit_on_branch,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt = _init_repo_with_worktree(Path(tmp), "backend")
            (wt / "app").mkdir()
            (wt / "app/bad.js").write_text("// broken\n")
            stage_file(wt, wt / "app/bad.js")
            commit_worktree(worktree_dir=wt, branch="agent/backend",
                            author="backend", message="[backend] bad")
            merge_agent_branch_to_main(
                repo_root=repo, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )

            # integration HEAD now contains app/bad.js. Capture its SHA.
            head_sha = subprocess.run(
                ["git", "rev-parse", "integration"],
                cwd=repo, capture_output=True, text=True,
            ).stdout.strip()

            # Revert.
            ok, new_sha = revert_commit_on_branch(
                repo_root=repo, branch="integration",
                commit_sha=head_sha, actor="orchestrator",
            )
            self.assertTrue(ok, f"revert failed: {new_sha}")

            # File should no longer be in the tree.
            r = subprocess.run(
                ["git", "show", "integration:app/bad.js"],
                cwd=repo, capture_output=True, text=True,
            )
            self.assertNotEqual(r.returncode, 0,
                                "app/bad.js still in tree after revert")

    def test_revert_unknown_commit_returns_error(self):
        from multi_agent.agents.runtime.auto_commit import revert_commit_on_branch
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = _init_repo_with_worktree(Path(tmp), "backend")
            ok, info = revert_commit_on_branch(
                repo_root=repo, branch="main",
                commit_sha="deadbeefdeadbeef",
            )
            self.assertFalse(ok)
            self.assertIn("commit not found", info)


if __name__ == "__main__":
    unittest.main()
