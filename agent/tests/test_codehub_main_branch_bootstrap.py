"""Bug 2 guard (youtube run): the integration branch ``main`` must exist.

Two failure modes were observed:

  * ``codehub_force_merge`` → ``Failed to checkout target branch 'main':
    git checkout main failed (exit 1): error: pathspec 'main' did not
    match any file(s) known to git``.

Root cause: ``GitOps.init()`` ran ``git init`` without pinning the default
branch, so on a host whose ``init.defaultBranch`` is ``master`` (git 2.25.1
default) the integration branch ``main`` never existed, and the
``self.git.checkout(target)`` in ``merge_pull_request`` /
``force_merge_pull_request`` (target defaults to ``main``) failed.

PRIMARY fix is pinned in ``test_codehub_git_ops.py``
(``test_init_pins_default_branch_to_main``). This module pins the DEFENSE:
even for a pre-existing repo created BEFORE the fix (default branch
``master``, ``main`` absent), ``merge_pull_request`` must bootstrap ``main``
at HEAD instead of erroring with ``pathspec 'main' did not match``.
"""
from __future__ import annotations

import subprocess
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

_SUBST_INLINE = [{"file": "feat.txt", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


class TestMainBranchBootstrapOnMerge(unittest.TestCase):
    def _make_master_default_repo(self, base: Path) -> CodeHub:
        """Construct a CodeHub over a repo that was ``git init``-ed the
        OLD way: default branch ``master``, no ``main`` branch. CodeHub's
        ``ensure_repo`` sees ``.git`` already present and does NOT re-init,
        so the fixed ``GitOps.init`` default-branch pin is bypassed —
        faithfully reproducing a repo created before the fix."""
        base.mkdir(parents=True, exist_ok=True)
        _git(base, "init", "-q")
        # Force the legacy ``master`` default and ensure ``main`` is absent.
        _git(base, "symbolic-ref", "HEAD", "refs/heads/master")
        _git(base, "config", "user.name", "GitOps Bot")
        _git(base, "config", "user.email", "gitops@codehub.local")
        # Base commit on master.
        (base / "README.md").write_text("init\n")
        _git(base, "add", "README.md")
        _git(base, "commit", "-qm", "init")

        crdt_dir = base / "shared" / "crdt"
        crdt_dir.mkdir(parents=True, exist_ok=True)
        hub = CodeHub(base, crdt_dir)
        hub.ensure_repo()  # no-op: .git already present
        # Sanity: main really does not exist on this repo.
        self.assertFalse(hub.git.branch_exists("main"))
        return hub

    def _ready_pr_targeting_main(self, hub: CodeHub) -> dict:
        # Feature branch off master with a new file.
        hub.git.checkout("feat-branch", create=True)
        (hub.repo_root / "feat.txt").write_text("feature work\n")
        hub.git.add("feat.txt")
        hub.git.commit("feature work")
        # Switch back so the worktree HEAD is the base (master).
        hub.git.checkout("master")
        hub.stores.branches.update(
            lambda m: m.set(
                "main:feat-branch",
                {"id": "main:feat-branch", "name": "feat-branch",
                 "repo_id": "main", "base": "main", "owner": "feat-agent",
                 "status": "active"},
                "test",
            )
        )
        pr = hub.open_pull_request(
            branch="feat-branch",
            target="main",  # integration branch that does NOT yet exist
            author="feat-agent",
            reviewers=["reviewer1"],
            linked_tasks=["synthetic_task_1"],
        )
        self.assertNotIn("error", pr, pr)
        hub.submit_review(pr["id"], "reviewer1", "approve",
                          inline_comments=_SUBST_INLINE,
                          considered_alternatives=_SUBST_ALTS)
        hub.submit_review(pr["id"], "orchestrator", "approve",
                          inline_comments=_SUBST_INLINE,
                          considered_alternatives=_SUBST_ALTS)
        ready = hub.stores.pull_requests.get(pr["id"])
        self.assertEqual(ready.get("merge_state"), "ready", ready)
        return ready

    def test_merge_bootstraps_missing_main_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_master_default_repo(Path(td) / "repo")
            pr = self._ready_pr_targeting_main(hub)

            merged = hub.merge_pull_request(
                pr["id"], strategy="squash", agent="orchestrator",
            )
            # Must NOT fail with "pathspec 'main' did not match".
            self.assertNotIn("error", merged, merged)
            err = str(merged.get("error", ""))
            self.assertNotIn("did not match", err)
            self.assertEqual(merged["status"], "merged", merged)
            # ``main`` now exists and carries the feature file.
            self.assertTrue(hub.git.branch_exists("main"))
            r = subprocess.run(
                ["git", "show", "main:feat.txt"],
                cwd=str(hub.repo_root), capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("feature work", r.stdout)

    def test_force_merge_bootstraps_missing_main(self):
        """force_merge_pull_request routes through merge_pull_request, so
        the same DEFENSE must apply (the observed ``codehub_force_merge``
        failure)."""
        with tempfile.TemporaryDirectory() as td:
            hub = self._make_master_default_repo(Path(td) / "repo")
            pr = self._ready_pr_targeting_main(hub)

            forced = hub.force_merge_pull_request(
                pr["id"],
                reason="youtube run repro: integration main never created",
                agent="orchestrator",
            )
            self.assertNotIn("error", forced, forced)
            self.assertNotIn("did not match", str(forced.get("error", "")))
            self.assertEqual(forced["status"], "merged", forced)
            self.assertTrue(hub.git.branch_exists("main"))


if __name__ == "__main__":
    unittest.main()
