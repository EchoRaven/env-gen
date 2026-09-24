"""Tests for RunHub MCP probe step (Cutover 22)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402


class _FakeCompose:
    def __init__(self):
        self.up_called = False
        self.down_called = False
    def up(self, timeout=180.0):
        self.up_called = True
        return ComposeResult(returncode=0, stdout="up ok")
    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _FakeHealthyHC:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.05)


def _stdio_probe_factory(crash_servers=None):
    """Returns a fake stdio probe that crashes for any name in crash_servers."""
    crash_servers = crash_servers or set()
    def _probe(server):
        if server["name"] in crash_servers:
            return {"healthy": False, "detail": "process exited rc=1"}
        return {"healthy": True, "detail": "alive after 2s"}
    return _probe


def _http_probe_factory(unhealthy_servers=None):
    unhealthy_servers = unhealthy_servers or set()
    def _probe(server):
        if server["name"] in unhealthy_servers:
            return {"healthy": False, "detail": "connection refused"}
        return {"healthy": True, "detail": "HTTP 200"}
    return _probe


def _passing_http_probe(plan):
    return {"status_code": 200, "body_excerpt": "ok",
            "transport_error": None, "latency_ms": 5.0}


class RunHubMCPProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_mcp_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_mcp_servers_no_probes(self) -> None:
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe)
        # No MCP probes section in run record
        self.assertEqual(run.get("mcp_probes", []), [])

    def test_registered_stdio_server_probed_healthy(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["server"], "filesystem")
        self.assertEqual(mcp_probes[0]["verdict"], "pass")

    def test_crashed_stdio_server_publishes_run_failed(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(crash_servers={"filesystem"}),
            mcp_http_probe=_http_probe_factory())
        events = list(self.reg.eventhub.list_events_by_type("run_failed"))
        mcp_failures = [
            e for e in events
            if (e.get("payload") or {}).get("bug_artifacts", {}).get("affected_mcp_server")
        ]
        self.assertEqual(len(mcp_failures), 1)
        artifacts = mcp_failures[0]["payload"]["bug_artifacts"]
        self.assertEqual(artifacts["affected_mcp_server"], "filesystem")
        self.assertEqual(artifacts["transport"], "stdio")
        self.assertEqual(artifacts["owner_hint"], "backend")

    def test_http_transport_uses_http_probe(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["transport"], "http")
        self.assertEqual(mcp_probes[0]["verdict"], "pass")

    def test_websocket_transport_skipped(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="ws_server", transport="websocket", endpoint="ws://localhost:9001",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["verdict"], "skipped")

    def test_run_status_failed_when_mcp_fails(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(crash_servers={"filesystem"}),
            mcp_http_probe=_http_probe_factory())
        self.assertEqual(run["status"], "failed")
        self.assertGreaterEqual(run["fail_count"], 1)


if __name__ == "__main__":
    unittest.main()
