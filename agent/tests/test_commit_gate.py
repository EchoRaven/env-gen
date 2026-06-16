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
from multi_agent.agents.runtime.commit_gate import (  # noqa: E402
    collect_loose_ends,
    build_commit_gate_prompt,
)


THRESHOLDS = {"stale_task_steps": 5, "stale_review_steps": 3, "stale_pr_steps": 10}


class CommitGateCollectTests(unittest.TestCase):
    def test_collect_clean_state_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            for value in loose.values():
                self.assertFalse(value)

    def test_collect_detects_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            wt = hubs.codehub.repo_root / "worktrees" / "backend"
            (wt / "f.py").write_text("x=1\n")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=1, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("dirty_worktree"))

    def test_collect_detects_unpushed_commits_no_open_pr(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            wt = ch.repo_root / "worktrees" / "backend"
            (wt / "f.py").write_text("x=1\n")
            ch.commit("backend", message="add f", files=["f.py"])
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=1, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("unpushed_commits"))

    def test_collect_detects_stale_claimed_task(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            hubs.workhub.claim_task(task["id"], "backend")
            # step_num is 10 + threshold is 5 -> assume task is stale
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("stale_claimed_tasks"))

    def test_collect_detects_forgotten_review(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            hubs.codehub.register_agent_worktree("frontend")
            task = hubs.workhub.create_task(title="x", assignee="frontend",
                                            agent="orchestrator")
            hubs.codehub.open_pull_request(
                branch="agent/frontend",
                reviewers=["backend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="frontend",
            )
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=5, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("forgotten_reviews"))


class CommitGateBuildPromptTests(unittest.TestCase):
    def test_build_prompt_returns_none_when_no_loose_ends(self):
        loose = {"dirty_worktree": False, "unpushed_commits": False,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        self.assertIsNone(build_commit_gate_prompt(loose, details={}))

    def test_build_prompt_renders_dirty_worktree_section(self):
        loose = {"dirty_worktree": True, "unpushed_commits": False,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        details = {"dirty_files": ["src/feed.py"]}
        prompt = build_commit_gate_prompt(loose, details=details)
        self.assertIsNotNone(prompt)
        self.assertIn("INTEGRITY CHECK", prompt)
        self.assertIn("src/feed.py", prompt)

    def test_build_prompt_renders_unpushed_commits_section(self):
        loose = {"dirty_worktree": False, "unpushed_commits": True,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        details = {"ahead": 3, "branch": "agent/backend"}
        prompt = build_commit_gate_prompt(loose, details=details)
        self.assertIsNotNone(prompt)
        self.assertIn("3 commits", prompt)


if __name__ == "__main__":
    unittest.main()
