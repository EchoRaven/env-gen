"""
Tests for tools/system_tools.py — SystemMetrics + LLM tool wrappers.
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure agent package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # agent/
sys.path.insert(0, str(Path(__file__).parent.parent / "env_generator" / "llm_generator"))


class TestSystemMetrics(unittest.TestCase):
    """Unit tests for SystemMetrics storage."""

    def setUp(self):
        from tools.system_tools import SystemMetrics
        self._td = tempfile.mkdtemp()
        self.metrics = SystemMetrics(Path(self._td))

    # ----------------------------------------------------------------
    # Token usage
    # ----------------------------------------------------------------

    def test_record_and_get_token_usage_single_agent(self):
        self.metrics.record_token_usage("backend", "gpt-4o", 1000, 500)
        usage = self.metrics.get_token_usage("backend")
        self.assertEqual(usage["total_input"], 1000)
        self.assertEqual(usage["total_output"], 500)
        self.assertEqual(usage["requests"], 1)

    def test_get_token_usage_totals(self):
        self.metrics.record_token_usage("a1", "gpt-4o-mini", 200, 100)
        self.metrics.record_token_usage("a2", "gpt-4o-mini", 300, 150)
        summary = self.metrics.get_token_usage()
        self.assertEqual(summary["total"]["input_tokens"], 500)
        self.assertEqual(summary["total"]["output_tokens"], 250)
        self.assertIn("by_agent", summary)

    def test_token_cost_calculated(self):
        self.metrics.record_token_usage("x", "gpt-4o", 1000, 1000)
        usage = self.metrics.get_token_usage("x")
        # gpt-4o: 1K in = 0.0025, 1K out = 0.01  => total 0.0125
        self.assertAlmostEqual(usage["total_cost"], 0.0125, places=5)

    def test_get_token_budget_status(self):
        self.metrics.record_token_usage("agent", "gpt-4o", 1000, 0)
        status = self.metrics.get_token_budget_status(budget_usd=10.0)
        self.assertIn("budget", status)
        self.assertIn("spent", status)
        self.assertFalse(status["over_budget"])

    # ----------------------------------------------------------------
    # Performance
    # ----------------------------------------------------------------

    def test_record_and_get_performance(self):
        self.metrics.record_operation_time("db_query", 50.0, agent_id="db")
        self.metrics.record_operation_time("db_query", 100.0, agent_id="db")
        stats = self.metrics.get_performance_stats("db_query")
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["min_ms"], 50.0)
        self.assertEqual(stats["max_ms"], 100.0)

    def test_get_performance_all(self):
        self.metrics.record_operation_time("op_a", 10.0)
        self.metrics.record_operation_time("op_b", 20.0)
        stats = self.metrics.get_performance_stats()
        self.assertIn("op_a", stats)
        self.assertIn("op_b", stats)

    # ----------------------------------------------------------------
    # Retries
    # ----------------------------------------------------------------

    def test_record_and_get_retries(self):
        self.metrics.record_retry("llm_call", agent_id="backend", reason="timeout")
        self.metrics.record_retry("llm_call", agent_id="backend", reason="rate_limit")
        stats = self.metrics.get_retry_stats("llm_call")
        self.assertEqual(stats["count"], 2)
        self.assertIn("backend", stats["by_agent"])
        self.assertIn("timeout", stats["reasons"])

if __name__ == "__main__":
    unittest.main()
