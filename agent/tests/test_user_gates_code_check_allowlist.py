"""Adversarial tests for Phase 0.2 Fix 2 -- code_check allowlist.

Audit 3.1 critical #2 found that ``_eval_code_check`` used
``subprocess.run(command, shell=True, ...)`` with a caller-supplied command
string -- arbitrary shell execution available to anyone who could register a
user_gate. The fix replaces shell=True with an operator-managed allowlist
file. ``params.command`` is no longer a shell line; it is a KEY into the
allowlist. The allowlist maps key -> {command_argv: list[str],
timeout_seconds: int}, and execution uses
``subprocess.run(argv, shell=False, ...)``.

Phase 0.2 RE-FIX 1: the allowlist YAML now lives OUTSIDE the agent
workspace; its path is read from the env var
``ENVGEN_ALLOWED_CODE_CHECKS_FILE``. Agents cannot write to that path, so
even a future routing-table regression cannot re-open the RCE.

These tests verify that:
* commands not in the allowlist are rejected (no subprocess invoked)
* an unset env var or missing/malformed allowlist file rejects everything
  (no crash)
* shell metacharacters in an allowlisted argv are passed as literal args
* the per-entry timeout is honored
* the allowlist entry shape is validated (command_argv must be a list)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


def _abs(binary: str) -> str:
    """Resolve a binary to its absolute path. The argv hardening (fix #2)
    requires argv[0] be absolute, so tests must reference /usr/bin/echo
    etc., not bare names."""
    p = shutil.which(binary)
    if not p:
        raise RuntimeError(
            f"{binary!r} not found on PATH; required for test."
        )
    return p


ECHO = _abs("echo")
SLEEP = _abs("sleep")

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.user_gates import (  # noqa: E402
    ALLOWLIST_PATH_ENV,
    _eval_code_check,
    _load_allowed_code_checks,
)


class TestCodeCheckAllowlist(unittest.TestCase):
    def setUp(self):
        # Workspace -- the agent-writable area; cwd for the subprocess.
        self._workspace_tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._workspace_tmp.name)
        # Allowlist directory -- OUTSIDE the workspace. Simulates an
        # operator-owned location like /etc/envgen/.
        self._allowlist_tmp = tempfile.TemporaryDirectory()
        self.allowlist_dir = Path(self._allowlist_tmp.name)
        self.allowlist_path = self.allowlist_dir / "allowed_code_checks.yaml"
        # Each test installs its own env-var value via _set_env; capture any
        # pre-existing value and restore it on tearDown.
        self._prior_env = os.environ.get(ALLOWLIST_PATH_ENV)
        # Default: the env var points at our tempfile path. Tests that need
        # the var unset call _unset_env().
        os.environ[ALLOWLIST_PATH_ENV] = str(self.allowlist_path)

    def tearDown(self):
        if self._prior_env is None:
            os.environ.pop(ALLOWLIST_PATH_ENV, None)
        else:
            os.environ[ALLOWLIST_PATH_ENV] = self._prior_env
        self._workspace_tmp.cleanup()
        self._allowlist_tmp.cleanup()

    # ------ test helpers ------
    def _write_allowlist(self, mapping: dict) -> Path:
        """Write the allowlist YAML at the operator-owned path (NOT under
        the workspace)."""
        self.allowlist_path.write_text(yaml.safe_dump(mapping))
        return self.allowlist_path

    def _unset_env(self) -> None:
        os.environ.pop(ALLOWLIST_PATH_ENV, None)

    # 1. Arbitrary shell-string commands are no longer accepted.
    def test_command_not_in_allowlist_rejected(self):
        # Allowlist exists but does not contain this key. The classic
        # injection payload is being passed as the gate's "command" field.
        self._write_allowlist({
            "echo_hi": {"command_argv": [ECHO, "hi"], "timeout_seconds": 5},
        })
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "rm -rf /"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        # No subprocess call must happen for a non-allowlisted command.
        self.assertEqual(run.call_count, 0)

    # 2. An allowlisted key actually runs and reports success.
    def test_command_in_allowlist_runs(self):
        self._write_allowlist({
            "echo_hi": {"command_argv": [ECHO, "hi"], "timeout_seconds": 5},
        })
        result = _eval_code_check(
            {"command": "echo_hi"}, None, self.workspace,
        )
        self.assertTrue(result["passed"], result)
        # Output tail should contain the literal stdout.
        self.assertIn("hi", result["details"]["output_tail"])
        # Exit code matched the default expect_exit=0.
        self.assertEqual(result["details"]["exit_code"], 0)
        # argv is preserved verbatim in details for observability.
        self.assertEqual(result["details"]["argv"], [ECHO, "hi"])

    # 3. No allowlist env var / no file -> every command rejected.
    def test_no_allowlist_file_rejects_all(self):
        # Two flavors: (a) env var unset entirely, (b) env var set but path
        # does not exist. Both must fail-closed without crashing.
        # (a)
        self._unset_env()
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "echo_hi"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)
        self.assertEqual(_load_allowed_code_checks(self.workspace), {})

        # (b) env var points at a non-existent file.
        bogus = self.allowlist_dir / "does_not_exist.yaml"
        self.assertFalse(bogus.exists())
        os.environ[ALLOWLIST_PATH_ENV] = str(bogus)
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "echo_hi"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)
        self.assertEqual(_load_allowed_code_checks(self.workspace), {})

    # 4. Malformed YAML -> graceful rejection, no crash.
    def test_malformed_allowlist_rejects_all(self):
        # Invalid YAML -- unbalanced brackets and stray colons.
        self.allowlist_path.write_text(
            "this: is: not: valid: yaml: [unclosed\n"
        )
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "echo_hi"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)
        # Loader itself returns {} without raising.
        self.assertEqual(_load_allowed_code_checks(self.workspace), {})

    # 5. shell=False -> argv elements are passed as literal strings; shell
    # metacharacters like $(...), backticks, semicolons are NOT expanded.
    def test_no_shell_injection(self):
        injected = "$(rm -rf /)"
        self._write_allowlist({
            "literal_dollar": {
                "command_argv": [ECHO, injected],
                "timeout_seconds": 5,
            },
        })
        result = _eval_code_check(
            {"command": "literal_dollar"}, None, self.workspace,
        )
        self.assertTrue(result["passed"], result)
        # The literal "$(rm -rf /)" must appear in the captured output --
        # which proves echo received it as a single literal argument and the
        # shell did NOT command-substitute it.
        self.assertIn(injected, result["details"]["output_tail"])

    # 6. Per-entry timeout is honored.
    def test_command_timeout_honored(self):
        self._write_allowlist({
            "slow_sleep": {
                "command_argv": [SLEEP, "5"],
                "timeout_seconds": 1,
            },
        })
        result = _eval_code_check(
            {"command": "slow_sleep"}, None, self.workspace,
        )
        self.assertFalse(result["passed"])
        self.assertIn("timed out", result["message"])
        # The timeout reported in the message/details should be the
        # allowlist value (1), not some caller-supplied number.
        self.assertIn("1s", result["message"])
        self.assertEqual(result["details"]["timeout"], 1)

    # 7. (bonus) command_argv must be a list -- a string-shaped value is dropped.
    def test_argv_must_be_list(self):
        # command_argv is a single string -- this must NOT be accepted, even
        # though loading the YAML produces a dict entry. If it were accepted
        # the runner would pass a single str to subprocess and re-introduce
        # the shell-string behavior the fix is meant to forbid.
        self.allowlist_path.write_text(yaml.safe_dump({
            "string_argv": {
                "command_argv": "echo hi; rm -rf /",
                "timeout_seconds": 5,
            },
        }))
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("string_argv", loaded)

        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "string_argv"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)

    # 8. (bonus) Empty command key still rejected with the original message.
    def test_empty_command_key_rejected(self):
        self._write_allowlist({
            "echo_hi": {"command_argv": [ECHO, "hi"], "timeout_seconds": 5},
        })
        result = _eval_code_check(
            {"command": ""}, None, self.workspace,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["message"], "params.command required")

    # 9. (bonus) timeout_seconds out of range -> entry dropped.
    def test_timeout_seconds_out_of_range_drops_entry(self):
        self.allowlist_path.write_text(yaml.safe_dump({
            "too_long": {
                "command_argv": [ECHO, "hi"],
                "timeout_seconds": 9999,  # > 600
            },
            "ok": {
                "command_argv": [ECHO, "ok"],
                "timeout_seconds": 5,
            },
        }))
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertNotIn("too_long", loaded)
        self.assertIn("ok", loaded)

    # 10. (bonus) subprocess receives argv directly (not as a shell string),
    # AND shell=False is the call we make. Mock-level evidence.
    def test_subprocess_invoked_with_shell_false_and_argv_list(self):
        self._write_allowlist({
            "echo_hi": {"command_argv": [ECHO, "hi"], "timeout_seconds": 5},
        })
        with mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="hi\n", stderr=""),
        ) as run:
            _eval_code_check({"command": "echo_hi"}, None, self.workspace)
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        # First positional arg is the argv list -- NOT a single string.
        self.assertEqual(args[0], [ECHO, "hi"])
        # shell=False explicitly.
        self.assertIs(kwargs.get("shell"), False)
        # cwd pinned to the workspace.
        self.assertEqual(kwargs.get("cwd"), str(self.workspace))


if __name__ == "__main__":
    unittest.main()
