"""Tests for observability LLM tool + CLI (Cutover 17)."""

import asyncio
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_PYTHON = "/home/haibotong/miniconda3/envs/dt/bin/python"


def _make_logs(tmp: Path) -> Path:
    logs = tmp / "logs"
    agent_dir = logs / "Agent A"
    agent_dir.mkdir(parents=True)
    with (agent_dir / "session.jsonl").open("w") as f:
        f.write(json.dumps({
            "timestamp": "2026-05-20T18:00:00",
            "event_type": "prompt", "content": "sys", "metadata": {},
        }) + "\n")
        f.write(json.dumps({
            "timestamp": "2026-05-20T18:00:05",
            "event_type": "tool_call",
            "content": "query_knowledge({'q': 'x'})",
            "metadata": {},
        }) + "\n")
    return logs


class ObservabilityToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="obs_tool_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tool_renders_dashboard_to_path(self) -> None:
        from tools.observability_tools import ObservabilityDashboardTool
        logs = _make_logs(self.tmp)
        out = self.tmp / "dashboard.html"
        tool = ObservabilityDashboardTool()
        result = _run_async(tool.execute(logs_dir=str(logs),
                                          output_path=str(out)))
        self.assertTrue(result.success, f"failed: {result.error_message}")
        self.assertTrue(out.exists())
        content = out.read_text()
        self.assertIn("Agent A", content)
        self.assertIn("query_knowledge", content)

    def test_tool_returns_stats_summary(self) -> None:
        from tools.observability_tools import ObservabilityDashboardTool
        logs = _make_logs(self.tmp)
        out = self.tmp / "dashboard.html"
        tool = ObservabilityDashboardTool()
        result = _run_async(tool.execute(logs_dir=str(logs),
                                          output_path=str(out)))
        self.assertEqual(result.data["total_agents"], 1)
        self.assertEqual(result.data["total_events"], 2)


class ObservabilityCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="obs_cli_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_renders_dashboard(self) -> None:
        logs = _make_logs(self.tmp)
        out = self.tmp / "dashboard.html"
        env = {"PYTHONPATH": str(AGENT_DIR / "env_generator" / "llm_generator")}
        result = subprocess.run(
            [_PYTHON, "-m", "multi_agent.runtime.observability",
             "--logs-dir", str(logs), "--output", str(out)],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertTrue(out.exists())
        self.assertIn("Agent A", out.read_text())


if __name__ == "__main__":
    unittest.main()
