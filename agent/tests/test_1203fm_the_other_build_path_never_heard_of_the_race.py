r"""#1203fm: the agent-facing build path did not know about #1202iw.

#1202iw detects the docker build-context tar race and #1203fk makes the retry wait for the
tree to settle -- both inside `validation_runner._build_with_retry`. `_run_compose` in
tools/docker_tools.py is the OTHER build path: every `docker_up(build=true)`,
`DockerBuildTool` and `build --no-cache` an AGENT runs goes through it, and it carried
neither. The file contained zero occurrences of the ticket or the race signature.

r160, live, 10:21:25 -- the r110 failure #1202iw's own docstring describes, by almost the same
title. The verifier filed P0 `task_530d9958d1`:

    title:       Frontend Docker build fails while packaging build context: unexpected EOF
    stack_trace: Can't add file app/frontend/src/pages/MoreSettingsPage.jsx to tar:
                 archive/tar: missed writing 2342993 bytes ... Error processing tar
                 file(exit status 1): unexpected EOF

and the frontend lane closed it by adding a `.dockerignore` to "exclude the corrupt captured
media file ... identified in tar missed-write errors". The file was not corrupt and the app was
not wrong: a lane rewrote app configuration for a race in the framework's own packaging step --
the one thing `_RACE_NOTE_1202IW` exists to forbid.

What made it invisible to me: both of r160's `#1203f1` build transcripts carry ZERO race
signatures, because the race happened on the path that does not write them. Patching one build
path left the other one answering for it -- the "one fact, many emitters" shape.

The fix gives this path the same two things and no more: settle and retry ONCE on a race, and
when the retry still loses, append the diagnosis so whoever reads the failure is told not to
open a bug. A non-build compose call and any non-race failure are untouched.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools import docker_tools as DT  # noqa: E402

SRC = LLM_DIR / "tools" / "docker_tools.py"

# r160's own stderr, verbatim from task_530d9958d1's bug_artifacts.stack_trace.
RACE = ("Can't add file app/frontend/src/pages/MoreSettingsPage.jsx to tar: "
        "archive/tar: missed writing 2342993 bytes\n"
        "Can't close tar writer: archive/tar: missed writing 2342993 bytes\n"
        "Error response from daemon: Error processing tar file(exit status 1): unexpected EOF")
NOT_RACE = 'x Build failed in 793ms | Could not resolve "./pages/MoreSettingsPage"'


class _Runs:
    """A scripted `subprocess.run`: one entry per expected spawn."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        rc, err = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        return subprocess.CompletedProcess(cmd, rc, "", err)


class TheRacedBuildIsRetriedOnce(unittest.TestCase):
    def setUp(self):
        self._real_run = DT.subprocess.run
        self._settles = []

        def _settle(root, **kw):
            self._settles.append(str(root))
            return (True, 0.0)
        import multi_agent.runtime.validation_runner as VR
        self._real_settle = VR._settle_build_context_1203fk
        VR._settle_build_context_1203fk = _settle
        self._VR = VR

    def tearDown(self):
        DT.subprocess.run = self._real_run
        self._VR._settle_build_context_1203fk = self._real_settle

    def _call(self, runs, args):
        DT.subprocess.run = runs
        return DT._run_compose(Path("/nonexistent/docker/docker-compose.yml"), args,
                              cwd=Path("/nonexistent/docker"), timeout=5)

    def test_a_race_settles_and_the_retry_result_is_what_comes_back(self):
        runs = _Runs((1, RACE), (0, ""))
        cp = self._call(runs, ["build", "frontend"])
        self.assertEqual(cp.returncode, 0, "the recovered build was not returned")
        self.assertEqual(len(runs.calls), 2, "expected exactly one retry")
        self.assertTrue(self._settles, "it retried without settling")

    def test_only_one_retry_even_when_the_race_repeats(self):
        """Bounded: this sits inside an agent tool call with its own timeout."""
        runs = _Runs((1, RACE), (1, RACE), (0, ""))
        cp = self._call(runs, ["build"])
        self.assertEqual(len(runs.calls), 2)
        self.assertEqual(cp.returncode, 1)

    def test_when_the_retry_also_races_the_reader_is_told_not_to_file_a_bug(self):
        runs = _Runs((1, RACE), (1, RACE))
        cp = self._call(runs, ["build"])
        self.assertIn("#1202iw", cp.stderr)
        self.assertIn("NOT a defect in the application code", cp.stderr)
        self.assertIn("do not rewrite the file docker named", cp.stderr)
        self.assertIn("no retry left", cp.stderr)
        # the original evidence survives -- the note is appended, not substituted
        self.assertIn("missed writing 2342993 bytes", cp.stderr)

    def test_a_non_race_build_failure_is_untouched(self):
        runs = _Runs((1, NOT_RACE))
        cp = self._call(runs, ["build"])
        self.assertEqual(len(runs.calls), 1, "a real build failure bought itself a retry")
        self.assertEqual(cp.stderr, NOT_RACE)
        self.assertNotIn("#1202iw", cp.stderr)

    def test_a_successful_build_is_untouched(self):
        runs = _Runs((0, ""))
        cp = self._call(runs, ["build"])
        self.assertEqual(len(runs.calls), 1)
        self.assertEqual(self._settles, [])

    def test_a_non_build_compose_call_is_untouched_even_on_that_output(self):
        """`up`, `down`, `ps` must not grow a retry. The guard is the ARGS, not the output --
        the same `any(a in ("build", "--build") ...)` test the pre-build hooks already use."""
        runs = _Runs((1, RACE))
        cp = self._call(runs, ["down", "-v"])
        self.assertEqual(len(runs.calls), 1)
        self.assertNotIn("#1202iw", cp.stderr or "")

    def test_a_broken_helper_still_returns_the_build_result(self):
        """It must never turn a build result into an exception: the caller's own failure
        handling is strictly better than no result at all."""
        def _boom(*a, **k):
            raise RuntimeError("settle exploded")
        self._VR._settle_build_context_1203fk = _boom
        runs = _Runs((1, RACE))
        cp = self._call(runs, ["build"])
        self.assertEqual(cp.returncode, 1)
        self.assertIn("missed writing", cp.stderr)


class TheGuardIsStructural(unittest.TestCase):
    def _fn(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_compose":
                return node
        self.fail("_run_compose is gone")

    def test_the_race_branch_requires_both_a_failure_and_build_args(self):
        fn = self._fn()
        races = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_build_context_race_1202iw"]
        self.assertTrue(races, "the other build path still does not look for the race")
        guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and any(c is races[0] for c in ast.walk(n))]
        self.assertTrue(guards)
        src = ast.dump(guards[0].test)
        self.assertIn("returncode", src, "the branch is not gated on a FAILED build")
        self.assertIn("build", src, "the branch is not gated on a build-triggering call")

    def test_there_is_no_loop_around_the_respawn(self):
        """One retry is the contract; a loop here would re-enter an agent tool's timeout."""
        fn = self._fn()
        spawns = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_spawn_1203fm"]
        self.assertEqual(len(spawns), 2, "expected the first call plus exactly one retry")
        for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]:
            self.assertFalse(any(s in set(ast.walk(loop)) for s in spawns),
                             "a respawn sits inside a loop")

    def test_it_reuses_the_other_paths_helpers_rather_than_copying_them(self):
        """#906's rule: one criterion, one function. A second hand-written copy of the race
        regex is how #905/#906 diverged."""
        src = SRC.read_text(encoding="utf-8")
        self.assertIn("from multi_agent.runtime.validation_runner import", src)
        self.assertNotIn("archive/tar: missed writing", src.replace(
            "archive/tar: missed writing 2342993 bytes", ""))


if __name__ == "__main__":
    unittest.main()
