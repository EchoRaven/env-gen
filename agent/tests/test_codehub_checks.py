"""
Tests for CodeHub.list_checks and get_check_summary (Task 11).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hubs.codehub.service import CodeHub  # noqa: E402


def _make_hub(td: str) -> CodeHub:
    base = Path(td)
    crdt_dir = base / "shared" / "crdt"
    crdt_dir.mkdir(parents=True, exist_ok=True)
    hub = CodeHub(base, crdt_dir)
    hub.ensure_repo()
    return hub


class TestCodeHubListChecks(unittest.TestCase):
    def _setup_prs_with_checks(self, hub: CodeHub):
        """Create two PRs with checks and return their ids."""
        # Use synthetic PR ids — record_check works without a real PR
        pr_a = "pr_test_aaa"
        pr_b = "pr_test_bbb"
        hub.record_check(pr_a, "lint", "passed")
        hub.record_check(pr_a, "tests", "passed")
        hub.record_check(pr_a, "coverage", "failed")
        hub.record_check(pr_b, "lint", "passed")
        hub.record_check(pr_b, "security", "warning")
        return pr_a, pr_b

    def test_list_checks_filter_by_pr_id(self):
        """list_checks(pr_id=...) returns only checks for that PR."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr_a, pr_b = self._setup_prs_with_checks(hub)

            checks_a = hub.list_checks(pr_id=pr_a)
            self.assertEqual(len(checks_a), 3)
            self.assertTrue(all(c["pr_id"] == pr_a for c in checks_a))

            checks_b = hub.list_checks(pr_id=pr_b)
            self.assertEqual(len(checks_b), 2)
            self.assertTrue(all(c["pr_id"] == pr_b for c in checks_b))

    def test_list_checks_filter_by_name(self):
        """list_checks(name='lint') returns only checks named 'lint' across all PRs."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr_a, pr_b = self._setup_prs_with_checks(hub)

            lint_checks = hub.list_checks(name="lint")
            self.assertEqual(len(lint_checks), 2)
            self.assertTrue(all(c["name"] == "lint" for c in lint_checks))

            security_checks = hub.list_checks(name="security")
            self.assertEqual(len(security_checks), 1)
            self.assertEqual(security_checks[0]["pr_id"], pr_b)

    def test_get_check_summary_computes_counts(self):
        """get_check_summary returns correct total and by_status breakdown."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            pr_a, _ = self._setup_prs_with_checks(hub)

            summary = hub.get_check_summary(pr_a)
            self.assertEqual(summary["pr_id"], pr_a)
            self.assertEqual(summary["total"], 3)
            by_status = summary["by_status"]
            self.assertEqual(by_status.get("passed"), 2)
            self.assertEqual(by_status.get("failed"), 1)
            self.assertNotIn("warning", by_status)

    def test_get_check_summary_empty_pr(self):
        """get_check_summary returns total=0 for a PR with no checks."""
        with tempfile.TemporaryDirectory() as td:
            hub = _make_hub(td)
            summary = hub.get_check_summary("pr_no_checks")
            self.assertEqual(summary["total"], 0)
            self.assertEqual(summary["by_status"], {})


if __name__ == "__main__":
    unittest.main()
