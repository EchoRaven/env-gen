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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class OpenPRGatesTests(unittest.TestCase):
    def _setup(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        return hubs, ch

    def test_open_pr_requires_non_empty_linked_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["orchestrator", "frontend"],
                linked_tasks=[],  # empty
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_tasks_required")

    def test_open_pr_requires_two_reviewers_after_author_exclusion(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="Build feed", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["backend"],  # author is sole reviewer -> 0 distinct -> fails
                linked_tasks=[task["id"]],
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "insufficient_reviewers")
            self.assertEqual(result.get("required"), 2)

    def test_open_pr_auto_injects_orchestrator_when_author_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend"],  # only 1 explicit; orchestrator injected -> 2 distinct
                linked_tasks=[task["id"]],
                title="Feed API",
                author="backend",
            )
            self.assertNotIn("error", result)
            self.assertIn("orchestrator", result["reviewers"])
            self.assertIn("frontend", result["reviewers"])

    def test_open_pr_orchestrator_author_does_not_self_inject(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "verifier"],
                linked_tasks=[task["id"]],
                title="Cleanup",
                author="orchestrator",
            )
            self.assertNotIn("error", result)
            # author=orchestrator -> no auto-injection
            self.assertNotIn("orchestrator", result["reviewers"])

    def test_open_pr_linked_api_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_apis=["GET /api/ghost"],  # not in RegistryHub
                title="Feed API",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_apis_unknown")
            self.assertIn("GET /api/ghost", result.get("unknown", []))

    def test_open_pr_linked_pages_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup(td)
            task = hubs.workhub.create_task(title="x", assignee="frontend",
                                            agent="orchestrator")
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["backend", "orchestrator"],
                linked_tasks=[task["id"]],
                linked_pages=["page_does_not_exist"],
                title="UI",
                author="frontend",
            )
            self.assertEqual(result.get("error"), "linked_pages_unknown")

    def test_open_pr_linked_tasks_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup(td)
            result = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=["task_ghost"],
                title="x",
                author="backend",
            )
            self.assertEqual(result.get("error"), "linked_tasks_unknown")
            self.assertIn("task_ghost", result.get("unknown", []))


if __name__ == "__main__":
    unittest.main()
