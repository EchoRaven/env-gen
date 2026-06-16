"""Tests for WorkHub coverage_allowlist helpers (Cutover 19)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CoverageAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_allow_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_allowlist_returns_empty(self) -> None:
        self.assertEqual(self.reg.gate_registry.list_coverage_allowlist(), [])

    def test_mark_intentionally_dead_creates_entry(self) -> None:
        entry = self.reg.gate_registry.mark_path_intentionally_dead(
            "file:frontend/src/UpcomingFeature.tsx",
            reason="behind FEATURE_FLAG_X",
            agent="orchestrator")
        self.assertEqual(entry["path"], "file:frontend/src/UpcomingFeature.tsx")
        self.assertEqual(entry["reason"], "behind FEATURE_FLAG_X")

    def test_list_after_mark_returns_entry(self) -> None:
        self.reg.gate_registry.mark_path_intentionally_dead(
            "endpoint:GET /api/v1/legacy",
            reason="kept for v0 clients", agent="orchestrator")
        entries = self.reg.gate_registry.list_coverage_allowlist()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "kept for v0 clients")

    def test_multiple_marks_append_to_same_page(self) -> None:
        for i in range(3):
            self.reg.gate_registry.mark_path_intentionally_dead(
                f"file:dead{i}.tsx", reason=f"r{i}", agent="orchestrator")
        entries = self.reg.gate_registry.list_coverage_allowlist()
        self.assertEqual(len(entries), 3)

    def test_mark_with_empty_reason_is_rejected(self) -> None:
        result = self.reg.gate_registry.mark_path_intentionally_dead(
            "file:x.tsx", reason="", agent="orchestrator")
        self.assertIn("error", result)

    def test_mark_with_empty_path_is_rejected(self) -> None:
        result = self.reg.gate_registry.mark_path_intentionally_dead(
            "", reason="r", agent="orchestrator")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
