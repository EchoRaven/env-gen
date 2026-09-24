"""Tests for observability HTML dashboard renderer (Cutover 17)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.observability.log_parser import (  # noqa: E402
    LogStats, AgentStats,
)
from multi_agent.runtime.observability.dashboard import render_dashboard  # noqa: E402


def _stats():
    a = AgentStats(name="Agent A", total_events=10, prompt_count=2,
                    tool_call_count=5, top_tools=[("query_knowledge", 3),
                                                    ("store_knowledge", 2)],
                    first_event_ts=1716552000.0, last_event_ts=1716552600.0,
                    span_seconds=600.0,
                    event_type_counts=[("tool_call", 5), ("prompt", 2),
                                         ("tool_result", 3)])
    b = AgentStats(name="Agent B", total_events=3, prompt_count=1,
                    tool_call_count=1, top_tools=[("query_knowledge", 1)],
                    first_event_ts=1716552100.0, last_event_ts=1716552200.0,
                    span_seconds=100.0,
                    event_type_counts=[("tool_call", 1), ("prompt", 1),
                                         ("tool_result", 1)])
    return LogStats(
        per_agent={"Agent A": a, "Agent B": b},
        top_tools_across_agents=[("query_knowledge", 4), ("store_knowledge", 2)],
        event_type_counts=[("tool_call", 6), ("prompt", 3), ("tool_result", 4)],
        total_agents=2, total_events=13,
    )


class DashboardRenderTests(unittest.TestCase):
    def test_render_returns_html_string(self) -> None:
        html = render_dashboard(_stats())
        self.assertIsInstance(html, str)
        self.assertIn("<html", html.lower())
        self.assertIn("</html>", html.lower())

    def test_render_includes_summary_counts(self) -> None:
        html = render_dashboard(_stats())
        self.assertIn("2", html)  # total agents
        self.assertIn("13", html)  # total events

    def test_render_includes_each_agent_name(self) -> None:
        html = render_dashboard(_stats())
        self.assertIn("Agent A", html)
        self.assertIn("Agent B", html)

    def test_render_includes_top_tools_across_agents(self) -> None:
        html = render_dashboard(_stats())
        self.assertIn("query_knowledge", html)
        self.assertIn("store_knowledge", html)

    def test_render_includes_event_type_breakdown(self) -> None:
        html = render_dashboard(_stats())
        for et in ("tool_call", "prompt", "tool_result"):
            self.assertIn(et, html)

    def test_render_empty_stats_returns_valid_html(self) -> None:
        html = render_dashboard(LogStats())
        self.assertIn("<html", html.lower())
        # "No agents" or "0" summary line should appear
        self.assertTrue("0" in html or "no agents" in html.lower())

    def test_render_includes_inline_css(self) -> None:
        html = render_dashboard(_stats())
        self.assertIn("<style", html.lower())

    def test_render_no_emojis(self) -> None:
        html = render_dashboard(_stats())
        # Check absence of common emoji ranges (very rough heuristic)
        self.assertTrue(all(ord(c) < 0x1F300 or ord(c) > 0x1FAFF for c in html))

    def test_render_writes_when_output_path_given(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="obs_render_"))
        try:
            out = tmp / "dashboard.html"
            html = render_dashboard(_stats(), output_path=out)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_text(), html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
