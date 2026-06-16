"""
Parity tests: validation API migrated from CRDTWorkspace to CodeHub.checks.

Contract under test (Task 16 implements this):
  workspace.record_validation_result(task_id, status, agent, summary, execution_mode, metadata)
  →  codehub.record_check(pr_id="main", name=f"validation:{task_id}", status=status,
                           evidence={"summary": summary, "execution_mode": execution_mode, **metadata},
                           agent=agent)

  get_validation_results()  →  codehub.list_checks() filtered on name.startswith("validation:")
  get_validation_summary()  →  computed from codehub.list_checks(), same shape as the old dict
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _ws(td: str) -> HubRegistry:
    return HubRegistry(Path(td))


class TestValidationMigratedToCodeHub(unittest.TestCase):
    """After Task 16: record_validation_result writes to CodeHub.checks."""

    def test_record_validation_result_visible_via_codehub_list_checks(self):
        """record_validation_result stores a check accessible via codehub.list_checks."""
        with tempfile.TemporaryDirectory() as td:
            ws = _ws(td)
            ws.record_validation_result(
                task_id="api_smoke",
                status="passed",
                agent="task_runner",
                summary="OK",
                execution_mode="api",
                metadata={"check": "api_smoke"},
            )
            checks = ws.hubs.codehub.list_checks(name="validation:api_smoke")
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["pr_id"], "main")
            self.assertEqual(checks[0]["name"], "validation:api_smoke")
            self.assertEqual(checks[0]["status"], "passed")

    def test_record_validation_check_evidence_contains_summary_and_metadata(self):
        """The evidence dict includes summary, execution_mode, and metadata fields."""
        with tempfile.TemporaryDirectory() as td:
            ws = _ws(td)
            ws.record_validation_result(
                task_id="ui_smoke",
                status="failed",
                agent="verifier",
                summary="page not found",
                execution_mode="browser",
                metadata={"check": "ui_smoke", "domain": "frontend"},
            )
            checks = ws.hubs.codehub.list_checks(name="validation:ui_smoke")
            self.assertEqual(len(checks), 1)
            ev = checks[0].get("evidence", {})
            self.assertEqual(ev.get("summary"), "page not found")
            self.assertEqual(ev.get("execution_mode"), "browser")
            self.assertEqual(ev.get("check"), "ui_smoke")
            self.assertEqual(ev.get("domain"), "frontend")

    def test_get_validation_summary_maps_to_codehub_check_summary(self):
        """get_validation_summary() returns total and by_status matching CodeHub checks."""
        with tempfile.TemporaryDirectory() as td:
            ws = _ws(td)
            ws.record_validation_result(
                task_id="api_smoke",
                status="passed",
                agent="runner",
                summary="OK",
                execution_mode="api",
                metadata={"check": "api_smoke"},
            )
            ws.record_validation_result(
                task_id="ui_smoke",
                status="failed",
                agent="runner",
                summary="boom",
                execution_mode="browser",
                metadata={"check": "ui_smoke"},
            )
            summary = ws.get_validation_summary()
            self.assertIn("total", summary)
            self.assertIn("by_status", summary)
            self.assertIn("all_passed", summary)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["by_status"].get("passed", 0), 1)
            self.assertEqual(summary["by_status"].get("failed", 0), 1)
            self.assertFalse(summary["all_passed"])

    def test_get_validation_results_returns_only_validation_checks(self):
        """get_validation_results() returns only checks whose name starts with 'validation:'."""
        with tempfile.TemporaryDirectory() as td:
            ws = _ws(td)
            ws.record_validation_result(
                task_id="api_smoke",
                status="passed",
                agent="runner",
                summary="OK",
                execution_mode="api",
                metadata={"check": "api_smoke"},
            )
            # A non-validation check should not appear in results
            ws.hubs.codehub.record_check(
                pr_id="main",
                name="build:backend",
                status="success",
                evidence={"output": "compiled"},
                agent="builder",
            )
            results = ws.get_validation_results(limit=50)
            names = [r.get("name", r.get("task_id", "")) for r in results]
            self.assertTrue(
                all("validation:" in n or n == "api_smoke" for n in names),
                f"Non-validation check leaked into results: {names}",
            )
            # Only the validation check should be in results
            validation_only = [r for r in results if r.get("name", "").startswith("validation:") or r.get("task_id") == "api_smoke"]
            self.assertGreaterEqual(len(validation_only), 1)


if __name__ == "__main__":
    unittest.main()
