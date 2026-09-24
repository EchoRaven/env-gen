"""Phase 0.2 attempt-3 Fix B: resolve_conflict triple-bypass closure.

These tests pin the three defenses Reviewer 2 found missing on
``CodeHub.resolve_conflict`` at HEAD ``e1280b24``:

  1. **Role-gate.** ``resolve_conflict`` had ``agent="codehub"`` as its
     default and no role check at all, while its peers
     ``force_merge_pull_request`` (orchestrator-only) and
     ``create_release`` (orchestrator-only) DO gate. Any agent could
     therefore resolve a PR they did not own and ship arbitrary content
     into the target branch.
  2. **Path containment.** The original code computed
     ``abs_path = repo_root / rel_path`` with no ``.resolve()`` and no
     ``is_relative_to`` check, so ``"../../etc/passwd"`` could escape
     ``repo_root``. Absolute paths supplied verbatim also need to be
     rejected (defense in depth — ``Path('/x') / '/etc/passwd'`` would
     return ``/etc/passwd`` because pathlib treats the absolute RHS as
     a reset).
  3. **Staging filter.** Even when the path stays in-repo,
     ``self.git.add(*keys)`` was called raw, so a dotfile path like
     ``.gates/allowed_code_checks.yaml`` was both *written* and
     *staged*. That dotfile, after a squash-merge to the integration
     branch, becomes the gate that ``user_gates`` consults — a clean
     RCE chain. ``_filter_paths_for_staging`` (Fix #5) refuses dotfile
     paths; ``resolve_conflict`` must call through it.

Each test below pins exactly one of these defenses.
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

# Cutover 13: substantive approve requires inline_comments + considered_alternatives
_SUBST_INLINE = [{"file": "shared.txt", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


def _make_hub(td: str) -> CodeHub:
    base = Path(td)
    crdt_dir = base / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    hub = CodeHub(base, crdt_dir)
    hub.ensure_repo()
    return hub


def _create_conflicting_pr(hub: CodeHub, author: str = "resolve-agent") -> dict:
    """Set up a PR in 'conflict' state and return its dict.

    The shape is the same as ``TestResolveConflict._create_conflicting_pr``
    in test_codehub_merge.py: divergent commits on ``main`` and
    ``resolve-feature``, then ``merge_pull_request`` runs and lands in
    conflict.
    """
    shared_file = hub.repo_root / "shared.txt"
    shared_file.write_text("base\n", encoding="utf-8")
    hub.git.add("shared.txt")
    hub.git.commit("Initial commit with shared.txt")

    hub.git.checkout("resolve-feature", create=True)
    shared_file.write_text("from feature\n", encoding="utf-8")
    hub.git.add("shared.txt")
    hub.git.commit("Feature changes shared.txt")

    hub.git.checkout("main")
    shared_file.write_text("from main\n", encoding="utf-8")
    hub.git.add("shared.txt")
    hub.git.commit("Main changes shared.txt for resolve test")

    hub.stores.branches.update(
        lambda m: m.set(
            "main:resolve-feature",
            {"id": "main:resolve-feature", "name": "resolve-feature",
             "repo_id": "main", "base": "main", "owner": author,
             "status": "active"},
            "test",
        )
    )

    pr = hub.open_pull_request(
        branch="resolve-feature",
        target="main",
        author=author,
        reviewers=["reviewer1"],
        linked_tasks=["synthetic_task_1"],
    )
    if "error" in pr:
        raise AssertionError(f"open_pull_request failed: {pr}")

    # Approvals to get merge_state=ready, then trigger the conflict path.
    hub.submit_review(pr["id"], "reviewer1", "approve",
                      inline_comments=_SUBST_INLINE,
                      considered_alternatives=_SUBST_ALTS)
    hub.submit_review(pr["id"], "orchestrator", "approve",
                      inline_comments=_SUBST_INLINE,
                      considered_alternatives=_SUBST_ALTS)

    conflicted = hub.merge_pull_request(pr["id"], strategy="squash",
                                         agent="orchestrator")
    if conflicted.get("status") != "conflict":
        raise AssertionError(
            f"PR did not land in conflict state as expected: {conflicted}"
        )
    return conflicted


# ---------------------------------------------------------------------------
# (1) Role-gate
# ---------------------------------------------------------------------------


class TestResolveConflictRoleGate(unittest.TestCase):
    def test_role_gate_non_orchestrator_rejected(self):
        """A random agent (not author / assignee / orchestrator) is denied."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"shared.txt": "resolved\n"},
                agent="random_agent",
            )
            self.assertIn("error", result, result)
            self.assertEqual(result["error"], "resolve_conflict_role_denied")
            # PR must remain in conflict state — no side effects on denial.
            stored = hub.stores.pull_requests.get(pr["id"])
            self.assertEqual(stored["status"], "conflict")

    def test_role_gate_orchestrator_accepted(self):
        """The orchestrator is always allowed (mirrors force_merge_pr)."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"shared.txt": "resolved by orch\n"},
                agent="orchestrator",
            )
            self.assertNotIn("error", result, result)
            self.assertEqual(result["status"], "merged")

    def test_role_gate_pr_author_accepted(self):
        """The PR's own author may resolve (the documented intended path)."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"shared.txt": "resolved by author\n"},
                agent="resolve-agent",
            )
            self.assertNotIn("error", result, result)
            self.assertEqual(result["status"], "merged")


# ---------------------------------------------------------------------------
# (2) Path containment
# ---------------------------------------------------------------------------


class TestResolveConflictPathContainment(unittest.TestCase):
    def test_path_traversal_dotdot_rejected(self):
        """``../../etc/passwd`` must not escape repo_root."""
        # Nest the temp dir 3 levels so the traversal target lands
        # inside our own tree, not the host's real /etc/passwd (which
        # exists on Linux and would make a 'must not exist' assertion
        # pass-or-fail based on environment).
        with tempfile.TemporaryDirectory() as outer:
            td = Path(outer) / "a" / "b" / "c"
            td.mkdir(parents=True)
            hub = _make_hub(str(td))
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"../../etc/passwd": "pwned\n"},
                agent="orchestrator",
            )
            self.assertIn("error", result, result)
            self.assertIn("escapes repo_root", result["error"])
            # The traversal target — relative to the hub's repo_root,
            # ../../etc/passwd resolves under ``outer/a/etc/passwd``.
            self.assertFalse(
                (Path(outer) / "a" / "etc" / "passwd").exists(),
                "../../etc/passwd should not have been written",
            )

    def test_absolute_path_rejected(self):
        """An absolute path (``/etc/passwd``) is rejected outright."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"/etc/passwd": "pwned\n"},
                agent="orchestrator",
            )
            self.assertIn("error", result, result)
            self.assertIn("absolute paths not allowed", result["error"])


# ---------------------------------------------------------------------------
# (3) Staging filter
# ---------------------------------------------------------------------------


class TestResolveConflictStagingFilter(unittest.TestCase):
    def test_dotfile_filtered_at_staging(self):
        """``.gates/x.yaml`` is in-repo (containment OK) but the staging
        filter must refuse it, so the dotfile is NOT staged and the
        resolution commit does NOT include it.

        This is Reviewer 2's RCE chain: agent writes
        ``.gates/allowed_code_checks.yaml`` via resolve_conflict →
        squash-merge to base → ``user_gates`` reads the dotfile →
        arbitrary execution. The staging filter is the propagation-layer
        defense that breaks the chain.
        """
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={
                    ".gates/allowed_code_checks.yaml": "evil: true\n",
                    "shared.txt": "safe content\n",
                },
                agent="orchestrator",
            )
            # The resolve itself succeeds (some content was staged).
            self.assertNotIn("error", result, result)

            # The dotfile was NOT staged. Verify by inspecting the
            # resolution commit: ``shared.txt`` must be there;
            # ``.gates/allowed_code_checks.yaml`` must NOT be.
            sha = result.get("resolution_sha")
            self.assertTrue(sha, "expected a resolution_sha")
            p = subprocess.run(
                ["git", "show", "--name-only", "--pretty=format:", sha],
                cwd=str(hub.repo_root),
                capture_output=True, text=True,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            committed = {line.strip() for line in p.stdout.splitlines() if line.strip()}
            self.assertIn("shared.txt", committed)
            self.assertNotIn(
                ".gates/allowed_code_checks.yaml", committed,
                f"dotfile must be refused by staging filter; "
                f"commit contained: {committed}",
            )

    def test_legit_resolve_succeeds(self):
        """The straight-line good path: orchestrator + in-repo non-dotfile
        path → success, file is staged and committed."""
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr = _create_conflicting_pr(hub, author="resolve-agent")

            result = hub.resolve_conflict(
                pr["id"],
                resolution_files={"shared.txt": "legit resolved\n"},
                agent="orchestrator",
            )
            self.assertNotIn("error", result, result)
            self.assertEqual(result["status"], "merged")
            self.assertIn("resolution_sha", result)

            sha = result["resolution_sha"]
            p = subprocess.run(
                ["git", "show", "--name-only", "--pretty=format:", sha],
                cwd=str(hub.repo_root),
                capture_output=True, text=True,
            )
            self.assertIn("shared.txt", p.stdout)


if __name__ == "__main__":
    unittest.main()
