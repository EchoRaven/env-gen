"""#1202ml: git must never own the live hub ledgers.

`shared/hubs/*.json` are the durable coordination state, read and written from
the run root while the lanes work. They were not in the generated `.gitignore`,
so a broad auto-commit could sweep them into the repository. Once that happens:

  * every later checkout / merge / reset of `integration` restores the COMMITTED
    snapshot over live state, and
  * every lane's git worktree carries a frozen checkout of it.

tiktok-r123 paid for it. A single commit — "auto-commit uncommitted work on
integration before strategic merge", 09-14 03:05 — put workhub_documents.json
into git at version 34. On the resume the orchestrator created a kickoff meeting
(`doc_1a7fc20a34`); the lanes answered `workhub_get_document FAILED: Document
not found`; the verifier wrote its predicates into the OLD meeting instead
(`doc_4400736584`, the one git knew about); the coordinator polled the meeting
nobody could see, counted three missing attendees for 245s, and abandoned. The
run died 11 minutes in, having just proved its build worked.

Three of the 162 generated runs on disk are in this state — netflix-local-r11,
netflix-local-r19 and tiktok-web-r123 — all from the same auto-commit. Rare, and
fatal to resume when it happens.

Two guards, because ignoring the path is not the same as refusing the value: the
scaffolder ignores `shared/`, and the stage filter refuses it even when named
explicitly.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.scaffolder import ensure_base_gitignore  # noqa: E402
from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    _should_stage_path, stage_file)


class TheScaffolderIgnoresTheLedger(unittest.TestCase):

    def test_shared_is_in_the_generated_gitignore(self):
        with tempfile.TemporaryDirectory() as d:
            ensure_base_gitignore(Path(d))
            gi = (Path(d) / ".gitignore").read_text(encoding="utf-8").split()
            self.assertIn("shared/", gi, gi)

    def test_git_does_not_see_the_ledger_as_untracked(self):
        """The real mechanism: `git add -A` can only sweep in what git lists."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "shared" / "hubs").mkdir(parents=True)
            (root / "shared" / "hubs" / "workhub_documents.json").write_text(
                '{"_meta": {"version": 34}}', encoding="utf-8")
            (root / "app").mkdir()
            (root / "app" / "main.py").write_text("X = 1\n", encoding="utf-8")
            ensure_base_gitignore(root)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            out = subprocess.run(["git", "status", "--porcelain", "-uall"],
                                 cwd=root, capture_output=True, text=True).stdout
            self.assertNotIn("shared/hubs", out, out)
            self.assertIn("app/main.py", out, "the app must still be tracked")

    def test_the_existing_entries_are_kept(self):
        """It must not become a way to drop the scratch-dir entries."""
        with tempfile.TemporaryDirectory() as d:
            ensure_base_gitignore(Path(d))
            gi = (Path(d) / ".gitignore").read_text(encoding="utf-8").split()
            for expected in ("memory-bank/", "worktrees/", "snapshots/"):
                self.assertIn(expected, gi)

    def test_it_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            ensure_base_gitignore(Path(d))
            first = (Path(d) / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(ensure_base_gitignore(Path(d)), [])
            self.assertEqual((Path(d) / ".gitignore").read_text(encoding="utf-8"),
                             first)


class TheStageFilterRefusesItAnyway(unittest.TestCase):
    """Guarding the entry is not guarding the value."""

    def test_a_ledger_path_is_refused(self):
        for p in ("shared/hubs/workhub_documents.json",
                  "shared/hubs/registryhub_endpoints.json",
                  "./shared/hubs/eventhub_events.json",
                  "shared/seed_live_counts.json"):
            self.assertFalse(_should_stage_path(p), p)

    def test_app_paths_are_unaffected(self):
        for p in ("app/backend/main.py", "app/frontend/src/App.jsx",
                  "docker/docker-compose.yml", "README.md"):
            self.assertTrue(_should_stage_path(p), p)

    def test_a_path_merely_containing_shared_is_not_refused(self):
        """The check is on the FIRST component, not a substring: an app file
        named `shared` is the lane's to commit."""
        for p in ("app/frontend/src/shared/utils.js",
                  "app/backend/shared_helpers.py"):
            self.assertTrue(_should_stage_path(p), p)

    def test_stage_file_declines_a_ledger_write(self):
        """End to end through the function the file tools actually call.

        In a REAL repository, so the refusal cannot come from `git add` failing
        for want of one — the first draft of this test passed with the guard
        removed, which made it worth nothing. The control below proves the same
        setup stages an app file.
        """
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d)
            subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=wt, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=wt, check=True)
            (wt / "shared" / "hubs").mkdir(parents=True)
            ledger = wt / "shared" / "hubs" / "workhub_documents.json"
            ledger.write_text("{}", encoding="utf-8")
            (wt / "app").mkdir()
            app = wt / "app" / "main.py"
            app.write_text("X = 1\n", encoding="utf-8")

            ok_app, msg_app = stage_file(wt, app)
            self.assertTrue(ok_app, "the control did not stage: %s" % msg_app)

            ok, msg = stage_file(wt, ledger)
            self.assertFalse(ok, msg)
            staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                    cwd=wt, capture_output=True, text=True).stdout
            self.assertIn("app/main.py", staged)
            self.assertNotIn("shared/hubs", staged, staged)


if __name__ == "__main__":
    unittest.main()
