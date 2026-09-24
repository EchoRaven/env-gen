"""Smoke #21 + #22 root-cause regression pin.

Both smokes wedged on the SAME bug:
  * #21 (commit ac282498, 2026-06-03 17:21): kickoff meeting page
    `page_6363c52bb9` vanished from workhub_pages.json mid-kickoff.
    Orchestrator agent diagnosed "Meeting not found" at 17:23:34;
    timed out 20 min later.
  * #22 (instrumented, 2026-06-03 18:05): same pattern — workhub
    page/task/attendee/comments stores all DISAPPEARED from
    `shared/hubs/`. Kickoff finalized at 18:06:51 (lanes wrote
    decisions in memory), but persisted state was lost. Frontend
    + 3 others' agent_log dirs also gone.

Forensic finding: `auto_commit.merge_agent_branch_to_main` runs in
repo_root with ``git stash push -u`` to make ``git checkout
main_branch`` succeed even when the working tree is dirty. The
``-u`` flag captures **untracked files** into the stash. The
subsequent ``git stash drop`` (after a successful checkout)
**permanently destroys** the stashed untracked files.

`shared/hubs/*.json` is untracked by design (hub state owned by
HubRegistry, never committed). The auto-merge bug treated it as
"transient leftovers" and wiped it on every lane finish that
triggered auto-merge.

This regression test:
  1. Sets up a repo with two branches (main + agent/x) sharing
     history,
  2. Drops an untracked `shared/hubs/workhub_pages.json` in
     repo_root that mimics a real kickoff write,
  3. Calls ``merge_agent_branch_to_main``,
  4. Asserts the file SURVIVED the auto-merge.
"""

from __future__ import annotations

import json
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


def _init_repo_with_agent_branch(tmpdir: Path, agent_id: str = "backend") -> tuple:
    """Build a repo with main + agent/<id> branches, one commit each.

    Layout:
        tmpdir/repo/
            .git/
            README.md         (tracked, on main)
            agent_file.txt    (tracked, on agent/<id>)
            shared/hubs/      (untracked — kickoff state lives here)
                workhub_pages.json
    """
    repo = tmpdir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-qb", "main"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    # Create agent branch + commit ONE file on it.
    subprocess.run(
        ["git", "checkout", "-qb", f"agent/{agent_id}"], cwd=repo, check=True,
    )
    (repo / "agent_file.txt").write_text(f"by {agent_id}\n")
    subprocess.run(["git", "add", "agent_file.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", f"[{agent_id}] add agent_file"],
        cwd=repo, check=True,
    )
    return repo


class AutoMergePreservesUntrackedHubState(unittest.TestCase):
    """Smoke #21 + #22 regression pin."""

    def test_untracked_shared_hubs_survives_merge_to_main(self):
        """Smoke #21/#22 root cause: ``merge_agent_branch_to_main``
        used ``git stash -u`` which captured untracked hub state in
        ``shared/hubs/``, then ``git stash drop`` destroyed it.
        Pre-fix this test FAILED — workhub_pages.json disappeared
        after the merge. Post-fix it survives intact."""
        from multi_agent.agents.runtime.auto_commit import (
            merge_agent_branch_to_main,
        )
        with tempfile.TemporaryDirectory(prefix="auto_merge_") as tmp_str:
            tmp = Path(tmp_str)
            repo = _init_repo_with_agent_branch(tmp, "backend")
            # Switch BACK to main so the merge starts in a realistic
            # state (HEAD=main, agent_branch separate).
            subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

            # Plant an untracked file under shared/hubs/ — this is what
            # HubRegistry's WorkHub.ensure_documents + add_meeting_decision
            # write at runtime. NEVER tracked by git on purpose.
            hubs_dir = repo / "shared" / "hubs"
            hubs_dir.mkdir(parents=True)
            pages_path = hubs_dir / "workhub_pages.json"
            kickoff_meeting = {
                "_meta": {"version": 5, "last_modified_by": "orchestrator"},
                "page_6363c52bb9": {  # smoke #21's lost meeting id
                    "id": "page_6363c52bb9",
                    "kind": "kickoff",
                    "metadata": {
                        "decisions": [
                            {"section": "backend.proposal_v2", "agent": "backend"},
                            {"section": "frontend.proposal_v2", "agent": "frontend"},
                            {"section": "verifier.proposal_v2", "agent": "verifier"},
                        ],
                    },
                },
            }
            pages_path.write_text(json.dumps(kickoff_meeting, indent=2))

            # Sanity: git sees shared/ as untracked (`??` lines —
            # git collapses to dir level when nothing in shared/ is
            # tracked).
            status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo,
                capture_output=True, text=True,
            ).stdout
            self.assertTrue(
                "?? shared/" in status or "?? shared/hubs" in status,
                f"test fixture invalid — shared/ should be untracked; "
                f"git status output: {status!r}",
            )

            # Run the auto-merge that pre-fix destroyed our file.
            ok, info = merge_agent_branch_to_main(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                agent_id="backend",
            )
            self.assertTrue(ok, f"auto-merge failed: {info}")

            # Critical assertion: the untracked hub state SURVIVED.
            self.assertTrue(
                pages_path.exists(),
                f"workhub_pages.json was DESTROYED by the auto-merge "
                f"(smoke #21/#22 regression). Stash -u + stash drop wiped "
                f"untracked hub state. Files in shared/hubs/ now: "
                f"{[p.name for p in hubs_dir.iterdir()] if hubs_dir.exists() else 'dir gone'}",
            )
            # Content unchanged — not just file present but data intact.
            survived = json.loads(pages_path.read_text())
            self.assertIn("page_6363c52bb9", survived)
            self.assertEqual(
                len(survived["page_6363c52bb9"]["metadata"]["decisions"]), 3,
            )

    def test_tracked_dirty_files_still_get_stashed_for_checkout(self):
        """Regression: the fix removed `-u` but kept the
        tracked-dirty stash behavior. If a tracked file is modified
        in repo_root pre-merge, it MUST still be stashed +
        dropped so the checkout doesn't fail."""
        from multi_agent.agents.runtime.auto_commit import (
            merge_agent_branch_to_main,
        )
        with tempfile.TemporaryDirectory(prefix="auto_merge_dirty_") as tmp_str:
            tmp = Path(tmp_str)
            repo = _init_repo_with_agent_branch(tmp, "backend")
            subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

            # Modify a TRACKED file. Pre-fix this was the case the
            # stash was originally meant to handle.
            (repo / "README.md").write_text("locally modified\n")

            ok, info = merge_agent_branch_to_main(
                repo_root=repo,
                agent_branch="agent/backend",
                main_branch="integration",
                agent_id="backend",
            )
            self.assertTrue(
                ok, f"auto-merge of tracked-dirty repo failed: {info}",
            )


if __name__ == "__main__":
    unittest.main()
