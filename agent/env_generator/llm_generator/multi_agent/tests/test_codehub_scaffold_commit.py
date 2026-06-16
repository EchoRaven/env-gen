"""CodeHub.commit_runtime_scaffold — the consistency-by-construction substrate.

Fixed, runtime-owned files (the embedded OAuth2 AS modules) must be committed to
the BASE branch BEFORE any agent worktree is created, so every ``agent/<id>``
worktree branched off HEAD physically inherits them. This proves the inheritance
end-to-end with a real git repo: commit to base → register a worktree → the file
is present (and tracked) inside that worktree.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hubs.codehub.service import CodeHub  # noqa: E402


_HAS_GIT = shutil.which("git") is not None


@unittest.skipUnless(_HAS_GIT, "git not available")
class CommitRuntimeScaffoldTests(unittest.TestCase):
    def _codehub(self, td: Path) -> CodeHub:
        repo = td / "project"
        hub = td / "hubs"
        repo.mkdir(parents=True, exist_ok=True)
        hub.mkdir(parents=True, exist_ok=True)
        return CodeHub(repo_root=repo, hub_dir=hub, eventhub=None)

    def _write(self, repo: Path, rel: str, text: str):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_commits_to_base_and_tracks_the_files(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            ch = self._codehub(td)
            self._write(ch.repo_root, "app/backend/jwt_manager.py", "# AS module\n")
            sha = ch.commit_runtime_scaffold(["app/backend/jwt_manager.py"], "bootstrap: AS")
            self.assertTrue(sha)
            tracked = subprocess.run(
                ["git", "ls-files"], cwd=ch.repo_root, capture_output=True, text=True,
            ).stdout
            self.assertIn("app/backend/jwt_manager.py", tracked)

    def test_worktree_created_after_commit_inherits_the_files(self):
        # The decisive property: a lane worktree branched off base HEAD must
        # physically contain the committed scaffold.
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            ch = self._codehub(td)
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                self._write(ch.repo_root, f"app/backend/{mod}", f"# {mod}\n")
            ch.commit_runtime_scaffold(
                [f"app/backend/{m}" for m in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py")],
                "bootstrap: embedded OAuth2 AS",
            )
            wt = ch.register_agent_worktree("backend")
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                self.assertTrue(
                    (wt / "app" / "backend" / mod).is_file(),
                    f"worktree missing inherited {mod}",
                )

    def test_idempotent_recommit_is_noop(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            ch = self._codehub(td)
            self._write(ch.repo_root, "app/backend/jwt_manager.py", "# AS\n")
            first = ch.commit_runtime_scaffold(["app/backend/jwt_manager.py"], "bootstrap")
            second = ch.commit_runtime_scaffold(["app/backend/jwt_manager.py"], "bootstrap")
            self.assertTrue(first)
            self.assertIsNone(second)  # nothing staged → no second commit

    def test_missing_path_raises(self):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            ch = self._codehub(td)
            with self.assertRaises(FileNotFoundError):
                ch.commit_runtime_scaffold(["app/backend/does_not_exist.py"], "bootstrap")


if __name__ == "__main__":
    unittest.main()
