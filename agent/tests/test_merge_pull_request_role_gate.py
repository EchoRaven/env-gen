"""Phase 2 Fix C: merge_pull_request role-gate.

Reviewer 2 (NEW HIGH): ``CodeHub.merge_pull_request`` (service.py:500)
had NO role-gate at all. The default ``agent="codehub"`` and the runtime
tool's ``agent=self._agent_id`` plumbing let any agent merge ANY PR,
short-circuiting the very reason ``force_merge_pull_request`` is
orchestrator-only. The L2 premerge verifier gate guards *content*; this
gate guards *who* may push the button.

The fix mirrors the existing ``force_merge_pull_request`` /
``resolve_conflict`` role-gates: orchestrator is always allowed,
otherwise the caller must be the PR's own author or assignee.

These three tests pin that gate.
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

# Cutover 13: substantive approve requires inline_comments +
# considered_alternatives.
_SUBST_INLINE = [{"file": "feat.py", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


def _make_hub(td: str) -> CodeHub:
    base = Path(td)
    crdt_dir = base / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    hub = CodeHub(base, crdt_dir)
    hub.ensure_repo()
    return hub


def _commit_file(hub: CodeHub, agent_id: str, filename: str, content: str) -> str:
    wt_path = hub.register_agent_worktree(agent_id)
    (wt_path / filename).write_text(content, encoding="utf-8")
    result = hub.commit(agent_id, f"Add {filename}", files=[filename])
    return result["sha"]


def _open_ready_pr(hub: CodeHub, author: str = "agent-feat") -> dict:
    """Create a PR and approve it so merge_state == 'ready'."""
    _commit_file(hub, author, "feat.py", "x = 1\n")
    pr = hub.open_pull_request(
        branch=f"agent/{author}",
        target="master",
        author=author,
        reviewers=["reviewer1"],
        linked_tasks=["synthetic_task_1"],
    )
    if "error" in pr:
        raise AssertionError(f"open_pull_request failed: {pr}")
    # reviewers present -> merge_state is blocked; approve all to unblock.
    hub.submit_review(pr["id"], "reviewer1", "approve",
                      inline_comments=_SUBST_INLINE,
                      considered_alternatives=_SUBST_ALTS)
    hub.submit_review(pr["id"], "orchestrator", "approve",
                      inline_comments=_SUBST_INLINE,
                      considered_alternatives=_SUBST_ALTS)
    ready = hub.stores.pull_requests.get(pr["id"])
    if ready.get("merge_state") != "ready":
        raise AssertionError(
            f"expected merge_state=ready, got {ready.get('merge_state')!r}"
        )
    return ready


class TestMergePullRequestRoleGate(unittest.TestCase):
    def test_random_agent_cannot_merge_others_pr(self):
        """A random agent (not author, not assignee, not orchestrator)
        is denied — and the PR is NOT merged."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _open_ready_pr(hub, author="agent-feat")

            result = hub.merge_pull_request(
                pr["id"], strategy="squash", agent="random_agent",
            )
            self.assertIn("error", result, result)
            self.assertEqual(result["error"], "merge_pr_role_denied")
            # PR must remain open — no side effects on denial.
            stored = hub.stores.pull_requests.get(pr["id"])
            self.assertEqual(stored["status"], "open", stored)
            self.assertNotEqual(stored.get("status"), "merged")

    def test_pr_author_can_merge_own_pr(self):
        """The PR's own author may merge — documented intended path."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _open_ready_pr(hub, author="agent-feat")

            result = hub.merge_pull_request(
                pr["id"], strategy="squash", agent="agent-feat",
            )
            self.assertNotIn("error", result, result)
            self.assertEqual(result["status"], "merged", result)

    def test_orchestrator_can_merge_any_pr(self):
        """The orchestrator is always allowed (mirrors force_merge_pr)."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _open_ready_pr(hub, author="agent-feat")

            result = hub.merge_pull_request(
                pr["id"], strategy="squash", agent="orchestrator",
            )
            self.assertNotIn("error", result, result)
            self.assertEqual(result["status"], "merged", result)


if __name__ == "__main__":
    unittest.main()
