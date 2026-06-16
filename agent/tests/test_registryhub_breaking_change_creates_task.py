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


class BreakingChangeCreatesTaskTests(unittest.TestCase):
    def test_breaking_change_auto_creates_workhub_task_per_consumer(self):
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs

            # backend publishes the endpoint, frontend registers as consumer
            hubs.registryhub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend",
            )
            hubs.registryhub.register_consumer(
                "GET /api/feed", "app/frontend/src/services/api.js", "frontend",
            )

            # backend pushes a breaking schema change
            hubs.registryhub.update_schema(
                "GET /api/feed",
                response={"items": []},   # removes `posts` and `total`
                agent="backend",
            )

            # there must be at least one WorkHub task whose assignee is the affected consumer
            tasks = list(hubs.workhub.snapshot()["tasks"].values())
            fix_tasks = [
                t for t in tasks
                if t.get("assignee") == "frontend"
                and t.get("metadata", {}).get("source") == "registryhub_breaking_change"
                and "GET /api/feed" in (t.get("metadata", {}).get("linked_apis") or [])
            ]
            self.assertEqual(len(fix_tasks), 1, f"expected exactly one frontend fix task, got: {fix_tasks}")
            task = fix_tasks[0]
            self.assertIn("/api/feed", task["title"])
            self.assertEqual(task["status"], "pending")


if __name__ == "__main__":
    unittest.main()
