"""#1129: the build-failure report threw away the stream that held the error.

#972 made a failing spawn emit its transcript. It still did not carry the reason, for two
independent reasons in the same two lines:

    _tail = stderr + ("\\n" + stdout if stderr is blank else "")   # stderr is never blank
    _tail = _tail.strip()[-600:]                                   # ...so slice the banner

compose v2 writes progress to STDERR and the classic builder writes "The command ...
returned a non-zero code: 1" there too, while the compile diagnostic that names the file and
the symbol goes to STDOUT -- which was appended only when stderr was empty, i.e. never.

Measured on the two runs built by the current code: 24 of 24 build-failure reports carried no
error line at all. In netflix-local-r1 the frontend build broke at 13:29 and never came back,
so :8080 stopped answering and the visual judge burned its three remaining attempts on
"capture unavailable -- 0 of 13 screen(s) photographed"; its verdict stayed frozen at the
13:21 score for the last 1h42m of the run.
"""
from __future__ import annotations

import logging
import subprocess
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

from multi_agent.runtime import validation_runner  # noqa: E402

# What a real classic-builder frontend failure looks like on the two streams.
_VITE_ERROR = (
    "x Build failed in 3.41s\n"
    "error during build:\n"
    "[vite:esbuild] Transform failed with 1 error:\n"
    "/app/src/pages/LoginPage.jsx:27:0: ERROR: The symbol \"LoginPage\" has already "
    "been declared\n"
)
_STDOUT = (
    "Step 6/9 : RUN npm ci\n ---> Running in 1a2b3c\n"
    + ("added 431 packages in 22s\n" * 20)
    + "Step 7/9 : RUN npm run build\n ---> Running in 4d5e6f\n"
    + "> frontend@0.0.0 build\n> vite build\n"
    + _VITE_ERROR
)
_STDERR = (
    'time="2026-08-27T13:29:26-05:00" level=warning msg="docker-compose.yml: version is '
    'obsolete"\n'
    " Service backend  Building\n Service backend  Built\n Service frontend  Building\n"
    "The command '/bin/sh -c npm run build' returned a non-zero code: 1\n"
)


class _FakeRun:
    def __init__(self, stdout, stderr, rc=1):
        self.cp = subprocess.CompletedProcess(
            args=["docker"], returncode=rc, stdout=stdout, stderr=stderr)

    def __call__(self, *a, **kw):
        return self.cp


def _spawn_and_capture(testcase, stdout, stderr):
    tmp = Path(tempfile.mkdtemp())
    cf = tmp / "docker-compose.yml"
    cf.write_text("services: {}\n")
    real = validation_runner.subprocess.run
    validation_runner.subprocess.run = _FakeRun(stdout, stderr)
    try:
        with testcase.assertLogs(logging.getLogger(), level="WARNING") as caught:
            validation_runner._compose(cf, "build", cwd=tmp)
        return "\n".join(caught.output)
    finally:
        validation_runner.subprocess.run = real


class TheReasonSurvivesTheReport(unittest.TestCase):

    def test_the_compile_error_reaches_the_log(self):
        out = _spawn_and_capture(self, _STDOUT, _STDERR)
        self.assertIn("LoginPage", out)
        self.assertIn("already been declared", out)

    def test_the_premise_the_old_formula_would_have_lost_it(self):
        """Exactly what the replaced two lines computed, on the same input."""
        old = (_STDERR + ("\n" + _STDOUT if not _STDERR.strip() else "")).strip()[-600:]
        self.assertNotIn("LoginPage", old)
        self.assertIn("non-zero code", old)

    def test_a_backend_only_failure_still_reports(self):
        """stdout empty, everything on stderr -- must not regress to silence."""
        out = _spawn_and_capture(
            self, "", "ERROR: relation \"titles\" does not exist\nrc=1\n")
        self.assertIn("titles", out)

    def test_a_silent_command_says_so_rather_than_nothing(self):
        out = _spawn_and_capture(self, "", "")
        self.assertIn("no output", out)

    def test_a_success_logs_no_warning(self):
        tmp = Path(tempfile.mkdtemp())
        cf = tmp / "docker-compose.yml"
        cf.write_text("services: {}\n")
        real = validation_runner.subprocess.run
        validation_runner.subprocess.run = _FakeRun("built\n", "", rc=0)
        try:
            with self.assertLogs(logging.getLogger(), level="INFO") as caught:
                validation_runner._compose(cf, "build", cwd=tmp)
            self.assertFalse([m for m in caught.output if m.startswith("WARNING")])
        finally:
            validation_runner.subprocess.run = real


if __name__ == "__main__":
    unittest.main()
