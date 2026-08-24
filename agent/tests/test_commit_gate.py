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


def _base_gitignore(ch):
    """Mirror the scaffold before any worktree exists.

    #624 has the framework ignore its own scratch dirs (.agents, .agent_logs,
    worktrees, .memory): git listing them as untracked is what makes a worktree
    DIRTY, and "42 of the 89 dirty worktrees across 15 runs are dirty for no other
    reason". Without it a FRESH worktree is dirty on `.agents/`, so every
    clean-state assertion here fails for a reason production does not have.
    """
    import subprocess as _sp
    from multi_agent.runtime.scaffolder import ensure_base_gitignore
    from pathlib import Path as _P
    ensure_base_gitignore(_P(ch.repo_root))
    _sp.run(["git", "-C", str(ch.repo_root), "add", ".gitignore"],
            check=True, capture_output=True)
    _sp.run(["git", "-C", str(ch.repo_root), "commit", "-qm", "base gitignore"],
            check=True, capture_output=True)


class CommitGateCollectTests(unittest.TestCase):
    def test_collect_clean_state_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            _base_gitignore(hubs.codehub)
            hubs.codehub.register_agent_worktree("backend")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            for value in loose.values():
                self.assertFalse(value)

    def test_collect_detects_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            _base_gitignore(hubs.codehub)
            hubs.codehub.register_agent_worktree("backend")
            wt = hubs.codehub.repo_root / "worktrees" / "backend"
            (wt / "f.py").write_text("x=1\n")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=1, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("dirty_worktree"))

    def test_commit_no_pr_is_NOT_a_loose_end(self):
        # #35: commit-only pipeline — a branch ahead with no PR is the NORMAL complete
        # state (auto-integrates). It must NOT be flagged as a loose end (was a
        # "NO open PR -> open a PR" nag that confused agents in run #34).
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
            self.assertFalse(loose.get("unpushed_commits"))  # key retired
            self.assertNotIn("unpushed_commits", loose)      # five-category dict now

    def test_collect_detects_stale_claimed_task(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            _base_gitignore(hubs.codehub)
            hubs.codehub.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            hubs.workhub.claim_task(task["id"], "backend")
            # #642 — AGE THE TASK, NOT THE AGENT. This used to assert staleness
            # from `step_num=10 >= 5`, which never looked at the task: from an
            # agent's 5th step on, EVERY in-progress task it held was reported
            # stale, including one claimed a second earlier. That fired in 65% of
            # 1961 integrity checks across 41 runs. Staleness is now the age of
            # `claimed_at` against `stale_task_seconds` (default 1800 — over 3992
            # completed tasks claim->finish is p50 2.7 min, p95 29.1). So age the
            # claim instead of the step counter.
            loose = collect_loose_ends(
                hubs, agent_id="backend", step_num=10,
                thresholds={**THRESHOLDS, "stale_task_seconds": 0})
            self.assertTrue(loose.get("stale_claimed_tasks"))

    def test_a_freshly_claimed_task_is_not_stale_642(self):
        """The regression #642 fixed: a just-claimed task must not be flagged."""
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            _base_gitignore(hubs.codehub)
            hubs.codehub.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            hubs.workhub.claim_task(task["id"], "backend")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            self.assertFalse(loose.get("stale_claimed_tasks"))

    def test_collect_detects_forgotten_review(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            _base_gitignore(hubs.codehub)
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

    def test_build_prompt_does_NOT_nag_to_open_pr(self):
        # #35: even if an (old) unpushed_commits flag leaks through, the renderer must
        # never emit a "NO open PR -> codehub_open_pr" nag (commit-only auto-integration).
        loose = {"dirty_worktree": False, "unpushed_commits": True,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        details = {"ahead": 3, "branch": "agent/backend"}
        prompt = build_commit_gate_prompt(loose, details=details)
        # no loose ends render -> None; and crucially never advises a PR
        self.assertIsNone(prompt)

    def test_build_prompt_never_mentions_open_pr(self):
        loose = {"dirty_worktree": True, "stale_claimed_tasks": False,
                 "forgotten_reviews": False, "unhandled_breaking_changes": False,
                 "conflict_prs_unresolved": False}
        prompt = build_commit_gate_prompt(loose, details={"dirty_files": ["a.py"]})
        self.assertIsNotNone(prompt)
        self.assertNotIn("open_pr", prompt)
        self.assertNotIn("NO open PR", prompt)


if __name__ == "__main__":
    unittest.main()
