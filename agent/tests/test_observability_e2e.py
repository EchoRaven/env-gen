"""E2E: run aggregator + renderer against the real agent/.agent_logs/ directory."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

REAL_LOGS = AGENT_DIR / ".agent_logs"


class ObservabilityE2ETests(unittest.TestCase):
    @unittest.skipUnless(REAL_LOGS.exists() and any(REAL_LOGS.rglob("*.jsonl")),
                          "no real .agent_logs/ event files (*.jsonl) present")
    def test_aggregate_real_logs_produces_nontrivial_stats(self) -> None:
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        stats = aggregate_logs(REAL_LOGS)
        # We've shipped 17 cutovers worth of generations - expect substantial data
        self.assertGreater(stats.total_agents, 0)
        self.assertGreater(stats.total_events, 0)

    @unittest.skipUnless(REAL_LOGS.exists() and any(REAL_LOGS.rglob("*.jsonl")),
                          "no real .agent_logs/ event files (*.jsonl) present")
    def test_render_real_dashboard_produces_valid_html(self) -> None:
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        from multi_agent.runtime.observability.dashboard import render_dashboard
        tmp = Path(tempfile.mkdtemp(prefix="obs_e2e_"))
        try:
            stats = aggregate_logs(REAL_LOGS)
            out = tmp / "dashboard.html"
            html = render_dashboard(stats, output_path=out)
            self.assertTrue(out.exists())
            self.assertIn("<html", html.lower())
            self.assertIn("Agent Observability Dashboard", html)
            # File should be at least somewhat substantial
            self.assertGreater(out.stat().st_size, 500)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
