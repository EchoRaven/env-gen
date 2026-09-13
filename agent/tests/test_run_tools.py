"""Tests for RunHub LLM tools (Cutover 11)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.run_tools import (  # noqa: E402
    RunStartTool, RunStatusTool, RunListTool, RunGetTool,
)


def _run_async(coro):
    """Ephemeral event loop per call (matches Cutover-10 bug_tools test pattern)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RunToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="run_tools_"))
        # #1202ln: run_start resolves the backend host port from the env root's own compose
        # file rather than defaulting to :8000 (r121's database). A real env root has one.
        (self.tmp / "docker").mkdir(parents=True, exist_ok=True)
        (self.tmp / "docker" / "docker-compose.yml").write_text(
            "services:\n  backend:\n    ports:\n      - \"3001:8000\"\n", encoding="utf-8")
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_list_empty(self) -> None:
        tool = RunListTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run())
        self.assertTrue(result.success)
        self.assertEqual(result.data["runs"], [])

    def test_run_status_for_recorded_run(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        tool = RunStatusTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id=run["id"]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["run"]["status"], "starting")

    def test_run_get_returns_full_run(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        tool = RunGetTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id=run["id"]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["run"]["id"], run["id"])

    def test_run_get_unknown_returns_error(self) -> None:
        tool = RunGetTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(run_id="run_missing"))
        self.assertFalse(result.success)

    def test_run_start_invokes_runhub_start_run(self) -> None:
        # Wire up a minimal endpoint so the run has something to probe
        self.reg.registryhub.register_endpoint("GET", "/api/health", schema={},
                                          provider="backend", agent="backend",
                                          status="defined")
        # Use the inject-friendly start_run by replacing it on the runhub instance.
        # The tool calls runhub.start_run(...) — we monkey-patch to verify args.
        called = {}
        def _fake_start_run(*, branch, generated_dir, base_url, agent, **kwargs):
            called["kwargs"] = {"branch": branch, "generated_dir": generated_dir,
                                 "base_url": base_url, "agent": agent}
            return {"id": "run_fake", "status": "completed", "fail_count": 0}
        self.reg.runhub.start_run = _fake_start_run
        tool = RunStartTool(agent_id="orch", hub_workspace=self.reg)
        result = _run_async(tool._run(branch="feature/x",
                                       generated_dir="/tmp/gen",
                                       base_url="http://localhost:8000"))
        self.assertTrue(result.success)
        self.assertEqual(called["kwargs"]["branch"], "feature/x")
        self.assertEqual(called["kwargs"]["agent"], "orch")
        # #1202ln: the model's :8000 guess is discarded for the compose file's real port.
        self.assertEqual(called["kwargs"]["base_url"], "http://localhost:3001")


if __name__ == "__main__":
    unittest.main()
