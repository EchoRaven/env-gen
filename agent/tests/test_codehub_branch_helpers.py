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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CodeHubBranchHelpersTests(unittest.TestCase):
    def _setup_repo(self, td):
        """Real git repo with one agent worktree."""
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.ensure_repo()
        # Mirror the scaffold: #624 has the framework write a .gitignore covering
        # its own scratch dirs (.agents, .agent_logs, worktrees, .memory) because
        # git listing them as untracked is what makes a worktree DIRTY — "42 of the
        # 89 dirty worktrees across 15 runs are dirty for no other reason". Without
        # it here, a FRESH worktree reports clean=False on `.agents/` and the two
        # cleanliness assertions below can never hold.
        from multi_agent.runtime.scaffolder import ensure_base_gitignore
        import subprocess as _sp
        ensure_base_gitignore(Path(ch.repo_root))
        _sp.run(["git", "-C", str(ch.repo_root), "add", ".gitignore"], check=True,
                capture_output=True)
        _sp.run(["git", "-C", str(ch.repo_root), "commit", "-qm", "base gitignore"],
                check=True, capture_output=True)
        # committed on the main repo BEFORE the worktree exists, so the worktree
        # inherits it (a .gitignore is a tracked file, shared by every worktree)
        ch.register_agent_worktree("backend")
        return hubs, ch

    def test_get_branch_status_returns_clean_for_fresh_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            status = ch.get_branch_status("backend")
            self.assertTrue(status["clean"])
            self.assertEqual(status["dirty_files"], [])
            self.assertEqual(status["commits_ahead_of_main"], 0)

    def test_get_branch_status_detects_dirty(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            wt = ch.repo_root / "worktrees" / "backend"
            (wt / "feature.py").write_text("x = 1\n")
            status = ch.get_branch_status("backend")
            self.assertFalse(status["clean"])
            self.assertIn("feature.py", status["dirty_files"])

    def test_get_branch_status_ignores_python_bytecode(self):
        """Python bytecode/cache (regenerated whenever the framework imports the
        backend to api_smoke-test it) must NEVER count as a dirty tree — else it
        wedges delivery in an infinite loop (outlook 2026-06-30)."""
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            wt = ch.repo_root / "worktrees" / "backend"
            # app/backend/ is TRACKED (the committed backend), as in a real run —
            # so git reports the NEW bytecode as individual .pyc paths, not a
            # collapsed untracked dir.
            be = wt / "app" / "backend"
            be.mkdir(parents=True)
            (be / "models.py").write_text("X = 1\n")
            ch.git._run("add", "-A", cwd=wt)
            ch.git._run("-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "backend", cwd=wt)
            cache = be / "__pycache__"
            cache.mkdir()
            (cache / "models.cpython-311.pyc").write_bytes(b"\x00\x01")
            (cache / "database.cpython-311.pyc").write_bytes(b"\x00\x02")
            # bytecode alone → clean
            status = ch.get_branch_status("backend")
            self.assertTrue(status["clean"], status["dirty_files"])
            self.assertEqual(status["dirty_files"], [])
            # real source change still detected, bytecode still excluded
            (wt / "real_change.py").write_text("y = 2\n")
            status2 = ch.get_branch_status("backend")
            self.assertFalse(status2["clean"])
            self.assertIn("real_change.py", status2["dirty_files"])
            self.assertFalse(any("__pycache__" in f or f.endswith(".pyc")
                                 for f in status2["dirty_files"]))

    def test_get_branch_status_detects_ahead_count(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            wt = ch.repo_root / "worktrees" / "backend"
            (wt / "f1.py").write_text("x=1\n")
            ch.commit("backend", message="add f1", files=["f1.py"])
            (wt / "f2.py").write_text("x=2\n")
            ch.commit("backend", message="add f2", files=["f2.py"])
            status = ch.get_branch_status("backend")
            self.assertGreaterEqual(status["commits_ahead_of_main"], 2)
            self.assertTrue(status["clean"])

    def test_get_branch_status_handles_no_repo_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            # No ensure_repo, no worktree
            status = hubs.codehub.get_branch_status("backend")
            self.assertIsInstance(status, dict)
            self.assertIn("clean", status)
            # When no repo, treat as clean / 0 ahead (defensive default)
            self.assertTrue(status["clean"])

    def test_list_prs_needing_review_filters_by_reviewer(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            need_fe = ch.list_prs_needing_review("frontend")
            self.assertEqual(len(need_fe), 1)
            self.assertEqual(need_fe[0]["id"], pr["id"])
            need_db = ch.list_prs_needing_review("database")
            self.assertEqual(need_db, [])

    def test_list_prs_needing_review_excludes_already_decided(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            ch.submit_review(
                pr["id"], "frontend", "approve",
                inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}],
                considered_alternatives=["considered alt approach; not needed"],
            )
            # frontend already decided
            need_fe = ch.list_prs_needing_review("frontend")
            self.assertEqual(need_fe, [])
            need_orch = ch.list_prs_needing_review("orchestrator")
            self.assertEqual(len(need_orch), 1)

    def test_get_pending_reviews_for_with_step_age(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            result = ch.get_pending_reviews_for("frontend", since_steps=0)
            self.assertEqual(len(result), 1)
            self.assertIn("pr_id", result[0])

    def test_get_my_branch_loose_ends_aggregates_state(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            wt = ch.repo_root / "worktrees" / "backend"
            (wt / "f1.py").write_text("x=1\n")
            ch.commit("backend", message="add f1", files=["f1.py"])
            loose = ch.get_my_branch_loose_ends("backend")
            self.assertIn("dirty", loose)
            self.assertIn("ahead", loose)
            self.assertIn("has_open_pr", loose)
            self.assertIn("conflict_prs", loose)
            self.assertGreaterEqual(loose["ahead"], 1)
            self.assertFalse(loose["has_open_pr"])


if __name__ == "__main__":
    unittest.main()
