"""#1075 — the central git runner had no timeout and no prompt guard.

`GitOps._run` is the subprocess wrapper every CodeHub git operation goes through —
commit, merge, stash, branch, worktree. It called `subprocess.run(...)` with
`capture_output=True` and no `timeout`, so a git that blocks blocks forever, with
no line in the log and no ceiling to hit.

That is a deviation from this package's own standard: of 54 subprocess call sites,
52 pass a timeout. This one and a bundled test are the exceptions.

Two ways git blocks here:

  * an operation waiting on `index.lock` left by a crashed process — and the git
    pain in this corpus is documented, "could not write index" 187 times, feeding
    #623's 70.8x conflict storm;
  * an operation that wants credentials. `GIT_TERMINAL_PROMPT` is set nowhere in
    the package, so git waits on stdin that will never arrive.

A timeout is raised as `GitOpsError`, which is what every caller already handles —
a hang must become a legible failure, not a new exception type nobody catches.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hubs.codehub.git_ops import GitOps, GitOpsError  # noqa: E402


class EveryGitCallIsBounded(unittest.TestCase):

    def test_a_timeout_is_passed(self):
        g = GitOps(Path("/tmp"))
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            g._run("status")
        self.assertIn("timeout", run.call_args.kwargs)
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_a_hang_becomes_the_error_callers_already_catch(self):
        g = GitOps(Path("/tmp"))
        with mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired(["git"], 1)):
            with self.assertRaises(GitOpsError) as ctx:
                g._run("merge", "main")
        msg = str(ctx.exception)
        self.assertIn("merge", msg, "the failing command must be named")
        self.assertIn("timed out", msg.lower())

    def test_the_timeout_comes_from_the_module_constant(self):
        """Not hardcoded at the call site — deliberately NOT via importlib.reload,
        which rebinds GitOpsError and leaves every other test in this file holding
        a stale class."""
        from multi_agent.runtime.hubs.codehub import git_ops as m
        g = GitOps(Path("/tmp"))
        with mock.patch.object(m, "_GIT_TIMEOUT_1075", 7), mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            g._run("status")
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_the_constant_reads_the_env_override(self):
        import inspect
        from multi_agent.runtime.hubs.codehub import git_ops as m
        src = inspect.getsource(m)
        self.assertIn("ENVGEN_GIT_TIMEOUT", src)
        self.assertGreaterEqual(m._GIT_TIMEOUT_1075, 1)


class GitNeverWaitsOnStdin(unittest.TestCase):

    def test_terminal_prompt_is_disabled(self):
        g = GitOps(Path("/tmp"))
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            g._run("status")
        env = run.call_args.kwargs.get("env") or {}
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0",
                         "without this, a credential prompt blocks on stdin forever")

    def test_the_inherited_environment_is_preserved(self):
        """Passing `env` replaces it wholesale — PATH must survive or git is gone."""
        g = GitOps(Path("/tmp"))
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            g._run("status")
        env = run.call_args.kwargs.get("env") or {}
        import os
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))


class TheOrdinaryPathIsUnchanged(unittest.TestCase):

    def test_a_clean_call_returns_the_completed_process(self):
        g = GitOps(Path("/tmp"))
        cp = subprocess.CompletedProcess(["git"], 0, "out", "")
        with mock.patch("subprocess.run", return_value=cp):
            self.assertIs(g._run("status"), cp)

    def test_a_nonzero_exit_still_raises_with_stderr(self):
        g = GitOps(Path("/tmp"))
        cp = subprocess.CompletedProcess(["git"], 1, "", "fatal: not a repo")
        with mock.patch("subprocess.run", return_value=cp):
            with self.assertRaises(GitOpsError) as ctx:
                g._run("status")
        self.assertIn("not a repo", str(ctx.exception))

    def test_check_false_returns_instead_of_raising(self):
        g = GitOps(Path("/tmp"))
        cp = subprocess.CompletedProcess(["git"], 1, "", "nope")
        with mock.patch("subprocess.run", return_value=cp):
            self.assertIs(g._run("status", check=False), cp)


if __name__ == "__main__":
    unittest.main()
