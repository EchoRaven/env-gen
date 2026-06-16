"""Tests for RunHub.last_successful_run_since (Cutover 24)."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class LastSuccessfulRunSinceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_last_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_runs_returns_none(self) -> None:
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_failed_run_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "failed", agent="runhub", fail_count=3)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_completed_run_with_zero_fail_count_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=0)
        result = self.reg.runhub.last_successful_run_since(0.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], run["id"])

    def test_completed_run_with_failures_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=2)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))

    def test_run_started_before_threshold_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "completed", agent="runhub", fail_count=0)
        future_ts = time.time() + 1000.0
        self.assertIsNone(self.reg.runhub.last_successful_run_since(future_ts))

    def test_returns_most_recent_when_multiple_qualify(self) -> None:
        r1 = self.reg.runhub.record_run(branch="a", generated_dir="/g", agent="o")
        self.reg.runhub.update_run_status(r1["id"], "completed", agent="runhub", fail_count=0)
        time.sleep(0.01)
        r2 = self.reg.runhub.record_run(branch="b", generated_dir="/g", agent="o")
        self.reg.runhub.update_run_status(r2["id"], "completed", agent="runhub", fail_count=0)
        result = self.reg.runhub.last_successful_run_since(0.0)
        self.assertEqual(result["id"], r2["id"])

    def test_aborted_run_not_returned(self) -> None:
        run = self.reg.runhub.record_run(
            branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(
            run["id"], "aborted", agent="runhub", fail_count=0)
        self.assertIsNone(self.reg.runhub.last_successful_run_since(0.0))


if __name__ == "__main__":
    unittest.main()
