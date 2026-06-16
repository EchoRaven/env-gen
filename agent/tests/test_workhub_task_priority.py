"""Tests for WorkHub task priority (Cutover 23)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CreateTaskPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_pri_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_priority_is_P2(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch")
        self.assertEqual((t.get("metadata") or {}).get("priority"), "P2")

    def test_explicit_priority_stored(self) -> None:
        t = self.reg.workhub.create_task(title="x", agent="orch", priority="P0")
        self.assertEqual((t.get("metadata") or {}).get("priority"), "P0")

    def test_invalid_priority_rejected(self) -> None:
        result = self.reg.workhub.create_task(
            title="x", agent="orch", priority="urgent")
        self.assertIn("error", result)
        self.assertIn("priority", result["error"].lower())

    def test_priority_round_trips_through_metadata(self) -> None:
        for p in ("P0", "P1", "P2", "P3"):
            t = self.reg.workhub.create_task(title=p, agent="orch", priority=p)
            self.assertEqual((t.get("metadata") or {}).get("priority"), p)


if __name__ == "__main__":
    unittest.main()
