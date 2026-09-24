"""R1 round-4 condition #2 + R2 round-4 condition #2: monitor bind guard.

Both reviewers required this as the safety counterpart of deferring the
~54 monitor-layer ``*_call`` gating items from Phase 0.2 to Phase
0.2-EXT.

R1: "monitor binds 127.0.0.1 by default (line 5491) and the threat model
is single-trusted-local-user, so deferring the ~54 monitor mutators is
defensible. Add a one-line bind guard: refuse --host != loopback unless
ENVGEN_AUTH_TOKEN is set."

R2: "best to add a deployment guard - refuse non-loopback binding when
the monitor invariant is RED."

The guard is implemented as ``_enforce_bind_guard(host)`` in
``live_monitor_server`` so it runs BEFORE any socket is opened. It
exits with status 2 (argparse-style misuse code) on refusal.

Acceptance:

  * loopback literal (127.0.0.1 / ::1) + no auth  -> proceeds
  * the name ``localhost`` + no auth              -> sys.exit(2)
    (attempt-6 HARDENING A / R1 round-5 FIX C: ``localhost`` is
    resolved via /etc/hosts + nsswitch, which a root-poisoned
    /etc/hosts can re-point to a non-loopback address. The bind
    guard now accepts only the literal IP loopbacks.)
  * non-loopback (e.g. 0.0.0.0) + no auth         -> sys.exit(2)
  * non-loopback + ENVGEN_AUTH_TOKEN set          -> proceeds
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class MonitorBindGuardRefusesNonLoopbackWithoutAuth(unittest.TestCase):
    """R1 round-4 condition #2 + R2 round-4 condition #2: defensive bind guard."""

    def setUp(self) -> None:
        # Stash and clear ENVGEN_AUTH_TOKEN so each test sets the precise
        # environment it needs without leaking from the harness.
        self._saved_token = os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    def tearDown(self) -> None:
        if self._saved_token is not None:
            os.environ["ENVGEN_AUTH_TOKEN"] = self._saved_token
        else:
            os.environ.pop("ENVGEN_AUTH_TOKEN", None)

    # ---------------- loopback hosts: must always proceed ----------------

    def test_loopback_ipv4_default_proceeds(self) -> None:
        """127.0.0.1 + no auth -> proceeds (single-user local dev default)."""
        from live_monitor_server import _enforce_bind_guard
        # Should NOT raise SystemExit.
        _enforce_bind_guard("127.0.0.1")

    def test_loopback_name_localhost_refused(self) -> None:
        """attempt-6 HARDENING A / R1 round-5 FIX C: the *name*
        ``localhost`` is no longer in the literal loopback set. It
        resolves via /etc/hosts + nsswitch, and a root-poisoned
        /etc/hosts can re-point it to a non-loopback address while
        the string-equality gate would still treat the input as
        safe. The hardened set contains only the literal IP
        loopbacks (``127.0.0.1`` and ``::1``); ``localhost`` now
        falls through to the auth-required branch and, with no
        ENVGEN_AUTH_TOKEN set, must ``sys.exit(2)``."""
        from live_monitor_server import _enforce_bind_guard
        self.assertNotIn("ENVGEN_AUTH_TOKEN", os.environ)
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
            _enforce_bind_guard("localhost")
        self.assertEqual(cm.exception.code, 2)
        msg = buf.getvalue()
        self.assertIn("localhost", msg)
        self.assertIn("REFUSING", msg)

    def test_loopback_ipv6_proceeds(self) -> None:
        from live_monitor_server import _enforce_bind_guard
        _enforce_bind_guard("::1")

    # ------------- non-loopback without auth: must refuse ----------------

    def test_nonloopback_without_auth_refuses(self) -> None:
        """0.0.0.0 + no ENVGEN_AUTH_TOKEN -> sys.exit(2)."""
        from live_monitor_server import _enforce_bind_guard
        # Belt-and-suspenders: ensure the env var really is gone.
        self.assertNotIn("ENVGEN_AUTH_TOKEN", os.environ)
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
            _enforce_bind_guard("0.0.0.0")
        self.assertEqual(cm.exception.code, 2)
        # The diagnostic should name the offending host and the env var
        # so operators can self-remediate.
        msg = buf.getvalue()
        self.assertIn("0.0.0.0", msg)
        self.assertIn("ENVGEN_AUTH_TOKEN", msg)
        self.assertIn("REFUSING", msg)

    def test_nonloopback_with_empty_auth_refuses(self) -> None:
        """Whitespace-only token does NOT count as auth."""
        from live_monitor_server import _enforce_bind_guard
        with mock.patch.dict(os.environ, {"ENVGEN_AUTH_TOKEN": "   "}):
            with self.assertRaises(SystemExit) as cm, redirect_stderr(io.StringIO()):
                _enforce_bind_guard("192.168.1.10")
            self.assertEqual(cm.exception.code, 2)

    # ---------------- non-loopback WITH auth: must proceed ---------------

    def test_nonloopback_with_auth_proceeds(self) -> None:
        """0.0.0.0 + ENVGEN_AUTH_TOKEN set -> proceeds (no SystemExit)."""
        from live_monitor_server import _enforce_bind_guard
        with mock.patch.dict(os.environ, {"ENVGEN_AUTH_TOKEN": "test-token"}):
            # Should NOT raise SystemExit. If it does, the test fails.
            _enforce_bind_guard("0.0.0.0")

    def test_public_iface_with_auth_proceeds(self) -> None:
        from live_monitor_server import _enforce_bind_guard
        with mock.patch.dict(os.environ, {"ENVGEN_AUTH_TOKEN": "x" * 32}):
            _enforce_bind_guard("10.0.0.5")


if __name__ == "__main__":
    unittest.main()
