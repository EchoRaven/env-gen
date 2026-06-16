"""Parity tests for dev_task family — WorkHub (Phase B Task 9, updated Task 11).

After CRDTDevTaskMixin deletion, all dev_task operations go through WorkHub
directly.  These tests exercise the WorkHub dev: namespace lifecycle.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402


def _workhub() -> WorkHub:
    tmp = tempfile.mkdtemp()
    return WorkHub(Path(tmp))


class TestPublishDevTaskViaWorkhub(unittest.TestCase):
    """create_task with dev: prefix is the canonical publish path."""

    def test_publish_creates_workhub_task_with_dev_prefix(self):
        hub = _workhub()
        task = hub.create_task(
            title="X",
            task_id="dev:t1",
            description="",
            assignee="backend",
            agent="orchestrator",
            domain="backend",
        )
        self.assertNotIn("error", task)
        self.assertEqual(task["id"], "dev:t1")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["title"], "X")

    def test_get_task_returns_published_task(self):
        hub = _workhub()
        hub.create_task(title="X", task_id="dev:t1", agent="orchestrator")
        retrieved = hub.get_task("dev:t1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["id"], "dev:t1")


class TestClaimDevTaskViaWorkhub(unittest.TestCase):
    """claim_task on dev: tasks flips status to in_progress."""

    def _published_hub(self):
        hub = _workhub()
        hub.create_task(
            title="X",
            task_id="dev:t1",
            assignee="backend",
            agent="orchestrator",
        )
        return hub

    def test_claim_sets_in_progress(self):
        hub = self._published_hub()
        result = hub.claim_task("dev:t1", "backend")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["claimed_by"], "backend")

    def test_claim_is_reflected_in_get_task(self):
        hub = self._published_hub()
        hub.claim_task("dev:t1", "backend")
        stored = hub.get_task("dev:t1")
        self.assertEqual(stored["status"], "in_progress")
        self.assertEqual(stored["claimed_by"], "backend")


class TestCompleteDevTaskViaWorkhub(unittest.TestCase):
    """complete_task on dev: tasks sets status to completed."""

    def _claimed_hub(self):
        hub = _workhub()
        hub.create_task(title="X", task_id="dev:t1", assignee="backend", agent="orchestrator")
        hub.claim_task("dev:t1", "backend")
        return hub

    def test_complete_sets_completed(self):
        hub = self._claimed_hub()
        result = hub.complete_task("dev:t1", "backend", result={"files": ["api.py"], "success": True})
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "completed")

    def test_complete_is_reflected_in_get_task(self):
        hub = self._claimed_hub()
        hub.complete_task("dev:t1", "backend", result={"success": True})
        stored = hub.get_task("dev:t1")
        self.assertEqual(stored["status"], "completed")


class TestCancelDevTaskViaWorkhub(unittest.TestCase):
    """cancel_task on dev: tasks sets status to cancelled."""

    def _published_hub(self):
        hub = _workhub()
        hub.create_task(title="X", task_id="dev:t1", assignee="backend", agent="orchestrator")
        return hub

    def test_cancel_sets_cancelled(self):
        hub = self._published_hub()
        result = hub.cancel_task("dev:t1", "orchestrator")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "cancelled")

    def test_cancel_is_reflected_in_get_task(self):
        hub = self._published_hub()
        hub.cancel_task("dev:t1", "orchestrator")
        stored = hub.get_task("dev:t1")
        self.assertEqual(stored["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
