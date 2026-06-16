"""Adversarial tests for Phase 0.2 RE-FIX 2 -- code_check argv hardening.

Reviewer's audit required-fix #2: even with ``subprocess.run(..., shell=False)``,
an allowlist entry whose ``command_argv`` is ``["/bin/sh", "-c", "<payload>"]``
or ``["/usr/bin/python", "-c", "<payload>"]`` re-introduces full code execution.
We therefore harden ``command_argv``:

  * argv[0] must be an absolute path,
  * argv[0]'s basename must NOT be a known interpreter/shell (versions
    stripped: ``python3.11`` -> ``python``),
  * no component of argv[0]'s path may be an interpreter name either.

The validator runs at ALLOWLIST LOAD time (drops bad entries with a warning),
AND a second time at EXEC time as defense in depth.

These tests verify each of those rules with a representative adversarial
payload, plus three legitimate-binary cases that must still be allowed
through.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.user_gates import (  # noqa: E402
    ALLOWLIST_PATH_ENV,
    _eval_code_check,
    _is_interpreter,
    _load_allowed_code_checks,
    _validate_code_check_argv,
)


def _write_allowlist(dir_: Path, mapping: dict) -> Path:
    """Write an allowlist YAML and return its path."""
    path = dir_ / "allowed_code_checks.yaml"
    path.write_text(yaml.safe_dump(mapping))
    return path


class _ArgvHardeningBase(unittest.TestCase):
    """Base: create an allowlist file outside the workspace and point the
    env var at it; tests then write allowlists into ``self.allowlist_dir``.
    """

    def setUp(self):
        # Workspace -- where subprocess cwd would land.
        self._ws = tempfile.TemporaryDirectory()
        self.workspace = Path(self._ws.name)
        # Operator allowlist directory -- intentionally OUTSIDE workspace.
        self._ald = tempfile.TemporaryDirectory()
        self.allowlist_dir = Path(self._ald.name)
        self.allowlist_path = self.allowlist_dir / "allowed_code_checks.yaml"
        self._env_patch = mock.patch.dict(
            os.environ,
            {ALLOWLIST_PATH_ENV: str(self.allowlist_path)},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._ws.cleanup()
        self._ald.cleanup()


class TestArgvDeniedAtLoad(_ArgvHardeningBase):
    """Bad ``command_argv`` entries are dropped at allowlist-load time."""

    # 1. /bin/sh -c "..." -- the canonical shell-eval bypass.
    def test_shell_sh_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "shell_sh": {
                "command_argv": ["/bin/sh", "-c", "rm -rf /"],
                "timeout_seconds": 5,
            },
            "ok": {  # control: should be kept
                "command_argv": ["/usr/bin/grep", "-r", "TODO", "."],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("shell_sh", loaded)
        self.assertIn("ok", loaded)
        # And invoking the gate must refuse too (key not in allowlist).
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "shell_sh"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)

    # 2. /usr/bin/bash payload.
    def test_shell_bash_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "shell_bash": {
                "command_argv": ["/usr/bin/bash", "evil.sh"],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("shell_bash", loaded)

    # 3. /usr/bin/python -c "<payload>"
    def test_python_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "py_eval": {
                "command_argv": ["/usr/bin/python", "-c", "import os; os.system('id')"],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("py_eval", loaded)

    # 4. Versioned python (python3.11) must collapse to "python" and reject.
    def test_python_versioned_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "py311": {
                "command_argv": ["/usr/bin/python3.11", "script.py"],
                "timeout_seconds": 5,
            },
            "py3": {
                "command_argv": ["/usr/bin/python3", "script.py"],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("py311", loaded)
        self.assertNotIn("py3", loaded)

    # 5. /usr/bin/node -e "<payload>"
    def test_node_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "node_eval": {
                "command_argv": ["/usr/bin/node", "-e", "require('child_process').exec('id')"],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("node_eval", loaded)

    # 6. Relative paths must be rejected -- "bash" relies on PATH lookup,
    # which is agent-controllable.
    def test_relative_path_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "rel_bash": {
                "command_argv": ["bash", "-c", "id"],
                "timeout_seconds": 5,
            },
            "rel_grep": {  # also rejected -- "grep" is relative
                "command_argv": ["grep", "TODO", "."],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("rel_bash", loaded)
        self.assertNotIn("rel_grep", loaded)

    # 7. Even a non-interpreter binary whose PATH contains "python" must be
    # rejected -- the operator may not realize a wrapper script execs an
    # interpreter; reject as defense in depth.
    def test_interpreter_path_component_rejected(self):
        _write_allowlist(self.allowlist_dir, {
            "wrap_runner": {
                "command_argv": ["/opt/python/bin/runner"],
                "timeout_seconds": 5,
            },
            "wrap_bash": {
                "command_argv": ["/var/opt/bash/run-stuff"],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("wrap_runner", loaded)
        self.assertNotIn("wrap_bash", loaded)


class TestArgvLegitimateAccepted(_ArgvHardeningBase):
    """Legitimate non-interpreter binaries must still be allowed."""

    # 8. /usr/bin/grep is a real lint-style use case.
    def test_legitimate_lint_accepted(self):
        _write_allowlist(self.allowlist_dir, {
            "lint_todo": {
                "command_argv": ["/usr/bin/grep", "-r", "TODO", "."],
                "timeout_seconds": 5,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertIn("lint_todo", loaded)
        self.assertEqual(
            loaded["lint_todo"]["command_argv"],
            ["/usr/bin/grep", "-r", "TODO", "."],
        )
        # And actually invocable (mocked so we don't depend on grep behavior).
        with mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ) as run:
            result = _eval_code_check(
                {"command": "lint_todo"}, None, self.workspace,
            )
        self.assertTrue(result["passed"], result)
        self.assertEqual(run.call_count, 1)
        # subprocess received argv, shell=False.
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/grep", "-r", "TODO", "."])
        self.assertIs(kwargs.get("shell"), False)

    # 9. /usr/bin/docker compose ps -- real CI/operator use.
    def test_legitimate_docker_accepted(self):
        _write_allowlist(self.allowlist_dir, {
            "docker_ps": {
                "command_argv": ["/usr/bin/docker", "compose", "ps"],
                "timeout_seconds": 30,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertIn("docker_ps", loaded)
        self.assertEqual(loaded["docker_ps"]["timeout_seconds"], 30)

    # 10. /usr/local/bin/pytest tests/  -- real test runner use.
    def test_legitimate_pytest_accepted(self):
        _write_allowlist(self.allowlist_dir, {
            "run_pytest": {
                "command_argv": ["/usr/local/bin/pytest", "tests/"],
                "timeout_seconds": 120,
            },
        })
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertIn("run_pytest", loaded)


class TestArgvDefenseInDepth(_ArgvHardeningBase):
    """``_eval_code_check`` re-validates argv even if _load lets something
    through -- defense in depth against future refactors."""

    def test_eval_revalidates_after_lookup(self):
        # Construct a tainted allowlist DIRECTLY in memory and force
        # ``_load_allowed_code_checks`` to return it. This simulates a
        # future bug where someone weakens the load-time validator.
        tainted = {
            "shell_sh": {
                "command_argv": ["/bin/sh", "-c", "id"],
                "timeout_seconds": 5,
                "description": None,
                "allowed_in_cwd_pattern": None,
            }
        }
        with mock.patch(
            "multi_agent.runtime.user_gates._load_allowed_code_checks",
            return_value=tainted,
        ), mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "shell_sh"}, None, self.workspace,
            )
        # The eval-time gate refuses to invoke.
        self.assertFalse(result["passed"])
        self.assertIn("failed argv validation", result["message"])
        self.assertEqual(run.call_count, 0)

    def test_eval_revalidates_relative_argv0(self):
        tainted = {
            "rel": {
                "command_argv": ["grep", "TODO"],
                "timeout_seconds": 5,
                "description": None,
                "allowed_in_cwd_pattern": None,
            }
        }
        with mock.patch(
            "multi_agent.runtime.user_gates._load_allowed_code_checks",
            return_value=tainted,
        ), mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "rel"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("failed argv validation", result["message"])
        self.assertEqual(run.call_count, 0)


class TestValidatorUnit(unittest.TestCase):
    """Unit tests for the validator function itself."""

    def test_returns_none_for_valid_argv(self):
        self.assertIsNone(
            _validate_code_check_argv(["/usr/bin/grep", "-r", "TODO"])
        )

    def test_rejects_empty(self):
        self.assertIsNotNone(_validate_code_check_argv([]))
        self.assertIsNotNone(_validate_code_check_argv(None))

    def test_rejects_non_string_argv0(self):
        self.assertIsNotNone(_validate_code_check_argv([42, "x"]))

    def test_rejects_relative_argv0(self):
        err = _validate_code_check_argv(["bash", "-c", "id"])
        self.assertIsNotNone(err)
        self.assertIn("absolute path", err)

    def test_rejects_interpreter_basename(self):
        err = _validate_code_check_argv(["/bin/sh", "-c", "id"])
        self.assertIsNotNone(err)
        self.assertIn("interpreter", err)

    def test_is_interpreter_version_stripping(self):
        # Versioned names should reduce to base interpreter names.
        self.assertTrue(_is_interpreter("python3.11"))
        self.assertTrue(_is_interpreter("python3"))
        self.assertTrue(_is_interpreter("python"))
        self.assertTrue(_is_interpreter("PYTHON"))  # case-insensitive
        # Not interpreters.
        self.assertFalse(_is_interpreter("grep"))
        self.assertFalse(_is_interpreter("docker"))
        self.assertFalse(_is_interpreter("pytest"))


if __name__ == "__main__":
    unittest.main()
