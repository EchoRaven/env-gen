"""Phase 0.2 RE-FIX C: env-var cache hardening for the code_check allowlist.

Reviewer 1 reframed the env-var concern correctly: the bypass is INERT in
production because process-isolation prevents an agent's child-process
``os.environ`` from propagating back to the parent monitor process. Phase
0.2's win is the process trust boundary itself. BUT defense in depth is
cheap, so the monitor process now reads
``ENVGEN_ALLOWED_CODE_CHECKS_FILE`` ONCE at startup
(``freeze_allowlist_path()``), caches it, and ignores later changes to
``os.environ``. That closes the hypothetical scenario where some OTHER
in-process bug lets an attacker mutate ``os.environ`` in the monitor's
address space.

These tests verify:
* PRE-FREEZE behavior: tests that mutate ``os.environ`` still see the live
  value (this preserves the existing unit-test contract).
* POST-FREEZE behavior: subsequent ``os.environ`` mutations are ignored;
  the value captured at freeze time is what the loader uses.
* ``freeze_allowlist_path()`` is idempotent and emits a warning if called
  more than once.
* Freezing with the env var UNSET caches an empty path -> all code_check
  invocations are rejected (fail-closed preserved).

IMPORTANT: each test that calls ``freeze_allowlist_path()`` must reset the
module-level cache in ``tearDown`` so it does not leak into other tests.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


def _abs(binary: str) -> str:
    p = shutil.which(binary)
    if not p:
        raise RuntimeError(f"{binary!r} not found on PATH; required for test.")
    return p


ECHO = _abs("echo")

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime import user_gates  # noqa: E402
from multi_agent.runtime.user_gates import (  # noqa: E402
    ALLOWLIST_PATH_ENV,
    _eval_code_check,
    _load_allowed_code_checks,
    freeze_allowlist_path,
)


class _FreezeCacheTestBase(unittest.TestCase):
    """Shared setUp/tearDown for tests that interact with the freeze cache."""

    def setUp(self):
        # Stash and reset the module-level freeze cache so each test starts
        # PRE-FREEZE. Tests that call freeze_allowlist_path() will mutate it
        # back, and we restore the original values in tearDown.
        self._prior_cache = user_gates._ALLOWLIST_PATH_CACHE
        self._prior_initialized = user_gates._ALLOWLIST_PATH_INITIALIZED
        user_gates._ALLOWLIST_PATH_CACHE = None
        user_gates._ALLOWLIST_PATH_INITIALIZED = False

        self._workspace_tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._workspace_tmp.name)
        self._allowlist_tmp = tempfile.TemporaryDirectory()
        self.allowlist_dir = Path(self._allowlist_tmp.name)

        self._prior_env = os.environ.get(ALLOWLIST_PATH_ENV)

    def tearDown(self):
        # Restore env var.
        if self._prior_env is None:
            os.environ.pop(ALLOWLIST_PATH_ENV, None)
        else:
            os.environ[ALLOWLIST_PATH_ENV] = self._prior_env
        # Restore freeze cache.
        user_gates._ALLOWLIST_PATH_CACHE = self._prior_cache
        user_gates._ALLOWLIST_PATH_INITIALIZED = self._prior_initialized
        self._workspace_tmp.cleanup()
        self._allowlist_tmp.cleanup()

    # helpers
    def _write_allowlist(self, path: Path, mapping: dict) -> Path:
        path.write_text(yaml.safe_dump(mapping))
        return path


class TestPreFreezeReadsLiveEnvVar(_FreezeCacheTestBase):
    """Before freeze_allowlist_path() has been called, ``_load_allowed_
    code_checks`` must continue to read the LIVE env var. This is the
    test-mode contract that lets the existing per-test env-var fixtures in
    ``test_user_gates_code_check_allowlist.py`` keep working."""

    def test_pre_freeze_reads_live_env_var(self):
        # Two distinct allowlist files, each with its own unique key.
        a_path = self.allowlist_dir / "a.yaml"
        b_path = self.allowlist_dir / "b.yaml"
        self._write_allowlist(a_path, {
            "key_a": {"command_argv": [ECHO, "from_a"], "timeout_seconds": 5},
        })
        self._write_allowlist(b_path, {
            "key_b": {"command_argv": [ECHO, "from_b"], "timeout_seconds": 5},
        })

        # Sanity: freeze has NOT been called.
        self.assertFalse(user_gates._ALLOWLIST_PATH_INITIALIZED)

        # Point env var at A -> loader should see key_a only.
        os.environ[ALLOWLIST_PATH_ENV] = str(a_path)
        loaded_a = _load_allowed_code_checks(self.workspace)
        self.assertIn("key_a", loaded_a)
        self.assertNotIn("key_b", loaded_a)

        # Repoint env var at B -> loader should now see key_b only.
        # (This is the LIVE-env-var behavior under test.)
        os.environ[ALLOWLIST_PATH_ENV] = str(b_path)
        loaded_b = _load_allowed_code_checks(self.workspace)
        self.assertIn("key_b", loaded_b)
        self.assertNotIn("key_a", loaded_b)


class TestFreezePinsPath(_FreezeCacheTestBase):
    """After freeze_allowlist_path() runs, subsequent os.environ overrides
    must be ignored: the cached path is what the loader uses."""

    def test_freeze_pins_path(self):
        a_path = self.allowlist_dir / "a.yaml"
        b_path = self.allowlist_dir / "b.yaml"
        self._write_allowlist(a_path, {
            "key_a": {"command_argv": [ECHO, "from_a"], "timeout_seconds": 5},
        })
        self._write_allowlist(b_path, {
            "key_b": {"command_argv": [ECHO, "from_b"], "timeout_seconds": 5},
        })

        # Step 1: set env to A, freeze.
        os.environ[ALLOWLIST_PATH_ENV] = str(a_path)
        freeze_allowlist_path()
        self.assertTrue(user_gates._ALLOWLIST_PATH_INITIALIZED)
        self.assertEqual(user_gates._ALLOWLIST_PATH_CACHE, str(a_path))

        # Step 2: attacker repoints env to B AFTER freeze.
        os.environ[ALLOWLIST_PATH_ENV] = str(b_path)

        # Step 3: loader must still serve from A's allowlist -- the B override
        # is ignored because the cache is pinned.
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertIn("key_a", loaded)
        self.assertNotIn("key_b", loaded)

        # And _eval_code_check using a B-only key must reject it.
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "key_b"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)


class TestFreezeIdempotentWithWarning(_FreezeCacheTestBase):
    """freeze_allowlist_path() must be idempotent: the FIRST call wins and
    subsequent calls are a no-op that logs a warning. This matters because
    accidental double-init (e.g. test bootstrap + real startup) must not
    silently rebind to an attacker-controlled value."""

    def test_freeze_idempotent_with_warning(self):
        a_path = self.allowlist_dir / "a.yaml"
        b_path = self.allowlist_dir / "b.yaml"
        self._write_allowlist(a_path, {
            "key_a": {"command_argv": [ECHO, "from_a"], "timeout_seconds": 5},
        })
        self._write_allowlist(b_path, {
            "key_b": {"command_argv": [ECHO, "from_b"], "timeout_seconds": 5},
        })

        # First freeze pins A.
        os.environ[ALLOWLIST_PATH_ENV] = str(a_path)
        freeze_allowlist_path()
        self.assertEqual(user_gates._ALLOWLIST_PATH_CACHE, str(a_path))

        # Attacker (or buggy startup code) tries to repoint+refreeze to B.
        os.environ[ALLOWLIST_PATH_ENV] = str(b_path)
        with self.assertLogs(user_gates.__name__, level=logging.WARNING) as cm:
            freeze_allowlist_path()
        # Cache must STILL be A, not B.
        self.assertEqual(user_gates._ALLOWLIST_PATH_CACHE, str(a_path))
        # And the second call logged a warning.
        self.assertTrue(
            any("freeze_allowlist_path called twice" in m for m in cm.output),
            cm.output,
        )

        # Loader still serves A's allowlist.
        loaded = _load_allowed_code_checks(self.workspace)
        self.assertIn("key_a", loaded)
        self.assertNotIn("key_b", loaded)


class TestFreezeWithUnsetEnv(_FreezeCacheTestBase):
    """If the operator forgot to wire up the env var BEFORE freezing, the
    cache must capture the empty value. From that point forward every
    code_check is rejected (fail-closed) -- and crucially, an attacker who
    later sets the env var to point at a malicious allowlist gets IGNORED."""

    def test_freeze_with_unset_env(self):
        # No env var at freeze time.
        os.environ.pop(ALLOWLIST_PATH_ENV, None)
        freeze_allowlist_path()
        self.assertTrue(user_gates._ALLOWLIST_PATH_INITIALIZED)
        self.assertEqual(user_gates._ALLOWLIST_PATH_CACHE, "")

        # Loader returns {} -- no checks ever runnable.
        self.assertEqual(_load_allowed_code_checks(self.workspace), {})

        # Now an attacker writes a malicious allowlist and points env at it.
        evil_path = self.allowlist_dir / "evil.yaml"
        self._write_allowlist(evil_path, {
            "evil": {"command_argv": [ECHO, "pwned"], "timeout_seconds": 5},
        })
        os.environ[ALLOWLIST_PATH_ENV] = str(evil_path)

        # Cache still says "unset"; the evil allowlist is NOT consulted.
        self.assertEqual(_load_allowed_code_checks(self.workspace), {})

        # _eval_code_check on the supposedly-allowlisted key still rejects.
        with mock.patch("subprocess.run") as run:
            result = _eval_code_check(
                {"command": "evil"}, None, self.workspace,
            )
        self.assertFalse(result["passed"])
        self.assertIn("not in workspace allowlist", result["message"])
        self.assertEqual(run.call_count, 0)


if __name__ == "__main__":
    unittest.main()
