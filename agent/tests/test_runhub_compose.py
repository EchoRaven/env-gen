"""Tests for RunHub docker compose wrapper (mocked subprocess)."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.runhub.compose import (  # noqa: E402
    ComposeLifecycle, ComposeResult, HealthcheckProbe, HealthcheckResult,
)


def _make_completed(returncode=0, stdout="", stderr=""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class ComposeLifecycleTests(unittest.TestCase):
    def test_up_calls_docker_compose_up_with_d_flag(self) -> None:
        runner = MagicMock(return_value=_make_completed())
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.up()
        self.assertIsInstance(result, ComposeResult)
        self.assertEqual(result.returncode, 0)
        runner.assert_called_once()
        args, kwargs = runner.call_args
        self.assertEqual(list(args[0])[:3], ["docker", "compose", "up"])
        self.assertIn("-d", args[0])
        self.assertEqual(kwargs.get("cwd"), "/tmp/gen")

    def test_up_failure_returncode_propagates(self) -> None:
        runner = MagicMock(return_value=_make_completed(returncode=1, stderr="boom"))
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.up()
        self.assertEqual(result.returncode, 1)
        self.assertIn("boom", result.stderr)

    def test_down_calls_docker_compose_down(self) -> None:
        runner = MagicMock(return_value=_make_completed())
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        lc.down()
        args, _ = runner.call_args
        self.assertEqual(list(args[0])[:3], ["docker", "compose", "down"])

    def test_down_swallows_nonzero_returncode(self) -> None:
        # down() must not raise on failure — caller always calls it in finally
        runner = MagicMock(return_value=_make_completed(returncode=2, stderr="already down"))
        lc = ComposeLifecycle(cwd="/tmp/gen", runner=runner)
        result = lc.down()
        self.assertEqual(result.returncode, 2)  # we return it but don't raise


class HealthcheckProbeTests(unittest.TestCase):
    def test_healthy_when_first_attempt_returns_2xx(self) -> None:
        def fake_get(url, timeout):
            return MagicMock(status_code=200)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=1, getter=fake_get)
        result = hc.wait()
        self.assertIsInstance(result, HealthcheckResult)
        self.assertTrue(result.healthy)
        self.assertEqual(result.status_code, 200)
        self.assertGreaterEqual(result.attempts, 1)

    def test_unhealthy_when_timeout_reached(self) -> None:
        def fake_get(url, timeout):
            return MagicMock(status_code=503)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=0.1, getter=fake_get)
        result = hc.wait()
        self.assertFalse(result.healthy)
        self.assertEqual(result.status_code, 503)

    def test_unhealthy_when_connection_refused_throughout(self) -> None:
        class _Refused(Exception):
            pass
        def fake_get(url, timeout):
            raise _Refused("connection refused")
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=0.05, getter=fake_get)
        result = hc.wait()
        self.assertFalse(result.healthy)
        self.assertIn("connection", result.last_error.lower())

    def test_healthy_after_initial_failures(self) -> None:
        attempts = {"n": 0}
        def fake_get(url, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("not yet")
            return MagicMock(status_code=200)
        hc = HealthcheckProbe(url="http://localhost:8000/health",
                              poll_interval_s=0, timeout_s=5, getter=fake_get)
        result = hc.wait()
        self.assertTrue(result.healthy)
        self.assertGreaterEqual(result.attempts, 3)


if __name__ == "__main__":
    unittest.main()
