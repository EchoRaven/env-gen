"""Tests for runtime/retro_aggregator.py (Cutover 16)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.retro_aggregator import (  # noqa: E402
    RetroStats, compute_retro_stats,
)


class RetroAggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_agg_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_registry_returns_zero_stats(self) -> None:
        stats = compute_retro_stats(self.reg)
        self.assertIsInstance(stats, RetroStats)
        self.assertEqual(stats.bug_stats["total_bugs"], 0)
        self.assertEqual(stats.run_stats["total_runs"], 0)
        self.assertEqual(stats.review_stats["total_prs"], 0)

    def test_bug_stats_counts_by_severity_and_state(self) -> None:
        self.reg.workhub.create_task(title="b1", agent="orch", kind="bug",
                                       severity="P0", bug_state="closed")
        self.reg.workhub.create_task(title="b2", agent="orch", kind="bug",
                                       severity="P1", bug_state="open")
        self.reg.workhub.create_task(title="b3", agent="orch", kind="bug",
                                       severity="P1", bug_state="escalated")
        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.bug_stats["total_bugs"], 3)
        self.assertEqual(stats.bug_stats["by_severity"]["P0"], 1)
        self.assertEqual(stats.bug_stats["by_severity"]["P1"], 2)
        self.assertEqual(stats.bug_stats["closed"], 1)
        self.assertEqual(stats.bug_stats["escalated"], 1)

    def test_run_stats_counts_passes_and_failures(self) -> None:
        r1 = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r1["id"], "completed", agent="r", fail_count=0)
        r2 = self.reg.runhub.record_run(branch="y", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r2["id"], "failed", agent="r", fail_count=3)
        r3 = self.reg.runhub.record_run(branch="z", generated_dir="/tmp/g", agent="o")
        self.reg.runhub.update_run_status(r3["id"], "completed", agent="r", fail_count=0)
        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.run_stats["total_runs"], 3)
        self.assertEqual(stats.run_stats["passed"], 2)
        self.assertEqual(stats.run_stats["failed"], 1)
        self.assertAlmostEqual(stats.run_stats["failure_rate"], 1 / 3, places=3)

    def test_review_stats_counts_prs_and_force_merges(self) -> None:
        # Wire 2 PRs; one normal merge, one force_merge audit entry
        task = self.reg.workhub.create_task(title="t", agent="backend", kind="feature")
        pr1 = self.reg.codehub.open_pull_request(
            branch="agent/backend", target="main", title="t1", author="backend",
            reviewers=["frontend", "orchestrator"], linked_tasks=[task["id"]])
        pr2 = self.reg.codehub.open_pull_request(
            branch="agent/backend2", target="main", title="t2", author="backend",
            reviewers=["frontend", "orchestrator"], linked_tasks=[task["id"]])
        # Tag pr2 as force-merged by stamping metadata directly (force_merge would do this in real flow)
        p2_full = self.reg.codehub.stores.pull_requests.get(pr2["id"])
        p2_full["force_merged"] = True
        self.reg.codehub.stores.pull_requests.update(
            lambda m: m.set(pr2["id"], p2_full, "orchestrator"),
            change_info={"agent": "orchestrator"})

        stats = compute_retro_stats(self.reg)
        self.assertEqual(stats.review_stats["total_prs"], 2)
        self.assertEqual(stats.review_stats["force_merged"], 1)


if __name__ == "__main__":
    unittest.main()
