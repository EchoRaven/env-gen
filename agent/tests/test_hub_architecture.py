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


class HubArchitectureTests(unittest.TestCase):
    def test_first_multi_hub_collaboration_loop(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))

            # WorkHub: Notion/Jira-like page + flat task lifecycle.
            # (Tier A retirement: ``create_plan`` retired; kickoff
            # publishes flat tasks via create_task directly. Mirrors
            # production: page for the design doc + standalone tasks
            # under it via create_task.)
            page = hubs.workhub.create_document("Implementation Plan", attendees=["backend", "frontend"], agent="orchestrator")
            task = hubs.workhub.create_task(
                title="Build feed API",
                task_id="build_feed_api",
                assignee="backend",
                agent="orchestrator",
            )
            task_id = task["id"]
            claimed = hubs.workhub.claim_task(task_id, "backend")
            self.assertEqual(claimed["claimed_by"], "backend")
            completed = hubs.workhub.complete_task(task_id, "backend", result={"endpoint": "GET /api/feed"})
            self.assertEqual(completed["status"], "completed")

            # RegistryHub: Apifox-like registry, consumer sync, and review event.
            endpoint = hubs.registryhub.register_endpoint(
                "GET",
                "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend",
                agent="backend",
            )
            self.assertEqual(endpoint["id"], "GET /api/feed")
            consumer = hubs.registryhub.register_consumer("GET /api/feed", "app/frontend/src/services/api.js", "frontend")
            self.assertEqual(consumer["agent"], "frontend")
            # Record passing contract test so the premerge gate is satisfied
            hubs.registryhub.record_api_test("GET /api/feed", {"passed": True},
                                        evidence={"trace": "ok"}, agent="verifier")
            review = hubs.registryhub.request_api_review("GET /api/feed", ["frontend"], agent="backend")
            self.assertEqual(review["status"], "pending")

            # CodeHub: GitHub-like branch/commit/PR/review/merge/release.
            hubs.codehub.register_agent_repo("backend", "/tmp/backend-worktree")
            commit = hubs.codehub.record_commit(
                "backend",
                "agent/backend",
                ["app/backend/src/routes/feed.js"],
                "Implement feed API",
            )
            pr = hubs.codehub.open_pull_request(
                "agent/backend",
                reviewers=["frontend"],
                linked_tasks=[task_id],
                linked_apis=["GET /api/feed"],
                title="Implement feed API",
                author="backend",
            )
            self.assertEqual(pr["merge_state"], "blocked")
            inbox = hubs.eventhub.list_inbox("frontend", unread_only=True)
            self.assertTrue(any(event["event_type"] == "pull_request_opened" for event in inbox))
            _inline = [{"file": "app/backend/src/routes/feed.js", "line": 1, "body": "ok"}]
            _alts = ["considered inlining the handler; rejected — keep route module thin"]
            hubs.codehub.submit_review(
                pr["id"], "frontend", "approve",
                inline_comments=_inline, considered_alternatives=_alts,
            )
            # orchestrator is auto-injected as reviewer; all reviewers must approve
            hubs.codehub.submit_review(
                pr["id"], "orchestrator", "approve",
                inline_comments=_inline, considered_alternatives=_alts,
            )
            ready_pr = hubs.codehub.snapshot()["pull_requests"][pr["id"]]
            self.assertEqual(ready_pr["merge_state"], "ready")
            merged = hubs.codehub.merge_pull_request(pr["id"], agent="orchestrator")
            self.assertEqual(merged["status"], "merged")
            release = hubs.codehub.create_release("v0.1.0", notes="Initial multi-hub release", agent="orchestrator")
            self.assertEqual(release["tag"], "v0.1.0")
            self.assertIn(commit["id"], hubs.codehub.snapshot()["commits"])


if __name__ == "__main__":
    unittest.main()
