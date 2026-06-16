"""
Tests for CodeHub.merge_pull_request (Task 12) and resolve_conflict (Task 13).
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
from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402

# Cutover 13: substantive approve requires inline_comments + considered_alternatives
_SUBST_INLINE = [{"file": "feat.py", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


def _make_hub(td: str) -> CodeHub:
    base = Path(td)
    crdt_dir = base / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    hub = CodeHub(base, crdt_dir)
    hub.ensure_repo()
    return hub


def _make_workhub(td: str) -> WorkHub:
    crdt_dir = Path(td) / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    return WorkHub(crdt_dir)


def _commit_file(hub: CodeHub, agent_id: str, filename: str, content: str) -> str:
    """Register worktree for agent, write file, commit; return SHA."""
    wt_path = hub.register_agent_worktree(agent_id)
    (wt_path / filename).write_text(content, encoding="utf-8")
    result = hub.commit(agent_id, f"Add {filename}", files=[filename])
    return result["sha"]


# ---------------------------------------------------------------------------
# Task 12 — merge_pull_request (happy path, conflict, not-ready guard)
# ---------------------------------------------------------------------------

class TestMergePullRequestSquashHappy(unittest.TestCase):
    """Happy-path squash merge → status=merged, conflict_files=[]."""

    def test_squash_merge_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            _commit_file(hub, "agent-feat", "feat.py", "x = 1\n")

            # No workhub attached -> task existence gate skipped; provide synthetic linked_tasks
            pr = hub.open_pull_request(
                branch="agent/agent-feat",
                target="master",
                author="agent-feat",
                reviewers=["reviewer1"],
                linked_tasks=["synthetic_task_1"],
            )
            self.assertNotIn("error", pr, pr)
            # reviewers present -> merge_state is blocked; approve all to unblock
            self.assertEqual(pr["merge_state"], "blocked")
            hub.submit_review(pr["id"], "reviewer1", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)
            hub.submit_review(pr["id"], "orchestrator", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)
            pr_ready = hub.stores.pull_requests.get(pr["id"])
            self.assertEqual(pr_ready["merge_state"], "ready")

            merged = hub.merge_pull_request(pr["id"], strategy="squash", agent="orchestrator")
            self.assertNotIn("error", merged, merged)
            self.assertEqual(merged["status"], "merged")
            self.assertEqual(merged.get("conflict_files", []), [])
            self.assertEqual(merged.get("merge_mode"), "real_git")


class TestMergePullRequestConflict(unittest.TestCase):
    """Conflict path → status=conflict, conflict_files non-empty, WorkHub task created."""

    def _create_conflicting_pr(self, hub: CodeHub, workhub=None) -> dict:
        """
        Create two divergent commits on different branches modifying the same line,
        then open a PR from the feature branch into master.

        main: initial commit with shared.txt = 'base\n'
        master branch: modifies shared.txt = 'from master\n'
        feature branch: modifies shared.txt = 'from feature\n'
        """
        # Step 1: initial commit on master with the shared file
        hub.git.add(".")
        # Write initial file in the main worktree
        shared_file = hub.repo_root / "shared.txt"
        shared_file.write_text("base\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Initial commit with shared.txt")

        # Step 2: create feature branch from master
        hub.git.checkout("feature-conflict", create=True)
        shared_file.write_text("from feature\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Feature changes shared.txt")

        # Step 3: go back to master and commit a conflicting change
        hub.git.checkout("master")
        shared_file.write_text("from master\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Master changes shared.txt")

        # Register the feature branch in codehub so open_pull_request can find it
        hub.stores.branches.update(
            lambda m: m.set(
                "main:feature-conflict",
                {"id": "main:feature-conflict", "name": "feature-conflict", "repo_id": "main",
                 "base": "master", "owner": "feat-agent", "status": "active"},
                "test",
            )
        )
        # Create a real WorkHub task when workhub is attached (Gate 5 validates task existence)
        if workhub is not None:
            task = workhub.create_task(title="Conflict PR task", assignee="feat-agent",
                                       agent="orchestrator")
            # Complete the task to satisfy the premerge gate (linked_task_incomplete check)
            workhub.claim_task(task["id"], "feat-agent")
            workhub.complete_task(task["id"], "feat-agent", result={"ok": True})
            task_ids = [task["id"]]
        else:
            task_ids = ["synthetic_task_1"]
        # open_pull_request for a branch that exists in git
        pr = hub.open_pull_request(
            branch="feature-conflict",
            target="master",
            author="feat-agent",
            reviewers=["reviewer1"],
            linked_tasks=task_ids,
        )
        return pr

    def test_conflict_sets_status_and_populates_conflict_files(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            workhub = _make_workhub(td)
            hub.attach_workhub(workhub)

            pr = self._create_conflicting_pr(hub, workhub=workhub)
            self.assertNotIn("error", pr, pr)

            # Submit approvals so merge_state becomes ready (all reviewers must approve)
            hub.submit_review(pr["id"], "reviewer1", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)
            hub.submit_review(pr["id"], "orchestrator", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)

            merged = hub.merge_pull_request(pr["id"], strategy="squash", agent="orchestrator")
            self.assertEqual(merged["status"], "conflict", merged)
            self.assertIsInstance(merged.get("conflict_files"), list)

    def test_conflict_creates_workhub_task(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            workhub = _make_workhub(td)
            hub.attach_workhub(workhub)

            pr = self._create_conflicting_pr(hub, workhub=workhub)
            self.assertNotIn("error", pr, pr)

            # Submit approvals so merge_state becomes ready (all reviewers must approve)
            hub.submit_review(pr["id"], "reviewer1", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)
            hub.submit_review(pr["id"], "orchestrator", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)

            hub.merge_pull_request(pr["id"], strategy="squash", agent="orchestrator")

            # WorkHub should have a task with source="codehub_merge_conflict"
            all_tasks = workhub.list_tasks()
            conflict_tasks = [
                t for t in all_tasks
                if t.get("metadata", {}).get("source") == "codehub_merge_conflict"
            ]
            self.assertGreater(len(conflict_tasks), 0, "Expected a conflict resolution task")
            task = conflict_tasks[0]
            self.assertEqual(task.get("assignee"), "feat-agent")


class TestMergePullRequestNotReady(unittest.TestCase):
    """PR not ready → returns error without attempting merge."""

    def test_merge_blocked_pr_returns_error(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            _commit_file(hub, "agent-blk", "blk.py", "y = 2\n")

            # No workhub attached -> task existence gate skipped; provide synthetic linked_tasks
            pr = hub.open_pull_request(
                branch="agent/agent-blk",
                target="master",
                author="agent-blk",
                reviewers=["reviewer-alice", "reviewer-bob"],  # makes merge_state=blocked
                linked_tasks=["synthetic_task_1"],
            )
            self.assertEqual(pr["merge_state"], "blocked")

            result = hub.merge_pull_request(pr["id"], strategy="squash")
            self.assertIn("error", result)
            # PR status must remain open, not merged
            stored = hub.stores.pull_requests.get(pr["id"])
            self.assertEqual(stored["status"], "open")


# ---------------------------------------------------------------------------
# Task 13 — resolve_conflict
# ---------------------------------------------------------------------------

class TestResolveConflict(unittest.TestCase):
    """conflict → resolve_conflict with file contents → PR status flips to merged."""

    def _create_conflicting_pr(self, hub: CodeHub) -> dict:
        # Same setup as above
        shared_file = hub.repo_root / "shared.txt"
        shared_file.write_text("base\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Initial commit with shared.txt")

        hub.git.checkout("resolve-feature", create=True)
        shared_file.write_text("from resolve-feature\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Resolve-feature changes shared.txt")

        hub.git.checkout("master")
        shared_file.write_text("from master resolve\n", encoding="utf-8")
        hub.git.add("shared.txt")
        hub.git.commit("Master changes shared.txt for resolve test")

        hub.stores.branches.update(
            lambda m: m.set(
                "main:resolve-feature",
                {"id": "main:resolve-feature", "name": "resolve-feature", "repo_id": "main",
                 "base": "master", "owner": "resolve-agent", "status": "active"},
                "test",
            )
        )
        # No workhub attached -> task existence gate skipped; provide synthetic linked_tasks
        pr = hub.open_pull_request(
            branch="resolve-feature",
            target="master",
            author="resolve-agent",
            reviewers=["reviewer1"],
            linked_tasks=["synthetic_task_1"],
        )
        return pr

    def test_resolve_conflict_flips_pr_to_merged(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)

            pr = self._create_conflicting_pr(hub)
            self.assertNotIn("error", pr, pr)

            # Submit approvals from all reviewers so merge_state becomes ready
            hub.submit_review(pr["id"], "reviewer1", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)
            hub.submit_review(pr["id"], "orchestrator", "approve",
                              inline_comments=_SUBST_INLINE,
                              considered_alternatives=_SUBST_ALTS)

            # Trigger conflict
            conflicted = hub.merge_pull_request(pr["id"], strategy="squash", agent="orchestrator")
            self.assertEqual(conflicted["status"], "conflict", conflicted)

            # Resolve by providing the resolved content. Phase 0.2 attempt-3
            # Fix B added a role-gate to ``resolve_conflict`` mirroring
            # ``force_merge_pull_request``: only the orchestrator or the
            # PR's author/assignee may resolve a conflict. The PR author
            # here is ``resolve-agent`` (see ``_create_conflicting_pr``).
            resolved = hub.resolve_conflict(
                pr["id"],
                resolution_files={"shared.txt": "resolved content\n"},
                agent="resolve-agent",
            )
            self.assertNotIn("error", resolved, resolved)
            self.assertEqual(resolved["status"], "merged")
            self.assertEqual(resolved.get("conflict_resolved_by"), "resolve-agent")
            self.assertIn("resolution_sha", resolved)

            # Verify persisted
            stored = hub.stores.pull_requests.get(pr["id"])
            self.assertEqual(stored["status"], "merged")


if __name__ == "__main__":
    unittest.main()
