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
from multi_agent.agents.runtime.hub_pulse import (  # noqa: E402
    collect_hub_pulse,
    build_hub_pulse_prompt,
    should_render,
)


class HubPulseCollectTests(unittest.TestCase):
    def test_collect_empty_state_returns_dict_with_4_hubs(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertIn("codehub", pulse)
            self.assertIn("registryhub", pulse)
            self.assertIn("workhub", pulse)
            self.assertIn("eventhub", pulse)

    def test_collect_codehub_my_open_prs(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertGreaterEqual(len(pulse["codehub"]["my_open_prs"]), 1)

    def test_collect_codehub_branch_status_present(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertIn("branch_status", pulse["codehub"])
            self.assertIn("clean", pulse["codehub"]["branch_status"])

    def test_collect_registryhub_my_endpoints_failed_tests(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.registryhub.register_endpoint("POST", "/api/posts", schema={},
                                          provider="backend", agent="backend")
            hubs.registryhub.record_api_test("POST /api/posts",
                                        {"passed": False},
                                        evidence={"status": 422}, agent="verifier")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            failed = pulse["registryhub"]["my_endpoints_with_failed_tests"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["id"], "POST /api/posts")

    def test_collect_registryhub_breaking_changes_for_my_consumed_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.registryhub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend",
            )
            hubs.registryhub.register_consumer("GET /api/feed", "src/Feed.jsx", "frontend")
            hubs.registryhub.update_schema("GET /api/feed",
                                     response={"items": []}, agent="backend")
            pulse = collect_hub_pulse(hubs, agent_id="frontend", step_num=1)
            breaking = pulse["registryhub"]["my_consumed_endpoints_with_breaking_changes"]
            self.assertGreaterEqual(len(breaking), 1)
            self.assertEqual(breaking[0]["endpoint_id"], "GET /api/feed")

    def test_collect_workhub_tasks_assigned_to_me(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.workhub.create_task(title="task1", assignee="backend",
                                     agent="orchestrator")
            hubs.workhub.create_task(title="task2", assignee="frontend",
                                     agent="orchestrator")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            pending = pulse["workhub"]["tasks_assigned_to_me_pending"]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["title"], "task1")

    def test_collect_eventhub_unread_count(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.eventhub.publish_event(
                source_hub="registryhub", event_type="x", payload={},
                recipients=["backend"], priority="urgent",
            )
            hubs.eventhub.publish_event(
                source_hub="registryhub", event_type="y", payload={},
                recipients=["backend"], priority="normal",
            )
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            counts = pulse["eventhub"]["unread_count_by_priority"]
            self.assertEqual(counts.get("urgent", 0), 1)
            self.assertEqual(counts.get("normal", 0), 1)


class HubPulseBuildPromptTests(unittest.TestCase):
    def test_build_prompt_renders_codehub_section_when_dirty(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": False, "dirty_files": ["x.py"],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "registryhub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        prompt = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(prompt)
        self.assertIn("CodeHub", prompt)
        self.assertIn("dirty", prompt.lower())
        self.assertIn("x.py", prompt)

    def test_build_prompt_omits_registryhub_when_empty(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": False, "dirty_files": ["x.py"],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "registryhub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        prompt = build_hub_pulse_prompt(pulse)
        # RegistryHub section should not be rendered because all fields empty
        self.assertNotIn("RegistryHub", prompt)

    def test_should_render_returns_false_when_all_empty(self):
        empty = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": True, "dirty_files": [],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "registryhub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        self.assertFalse(should_render(empty))

    def test_should_render_returns_true_with_any_content(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": True, "dirty_files": [],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "registryhub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [
                            {"id": "t1", "title": "x", "priority": "normal"}],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        self.assertTrue(should_render(pulse))


class HubPulseSelfAuditTests(unittest.TestCase):
    """Long-context recovery: pulse must surface 'wrote code but didn't
    register' drift so the agent self-corrects mid-step, not only when
    finish() blocks it."""

    def test_self_audit_flags_api_drift_when_backend_files_written_and_no_endpoints(self):
        pulse = {
            "self_audit": {
                "api_drift": {
                    "code_paths_sample": ["app/backend/routes/auth.js"],
                    "code_paths_count": 1,
                    "owned_endpoints": 0,
                },
            },
        }
        self.assertTrue(should_render(pulse))
        prompt = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(prompt)
        self.assertIn("registryhub_register_endpoint", prompt)
        self.assertIn("SELF-AUDIT", prompt)

    def test_self_audit_flags_ui_drift_when_pages_written_and_no_workhub_pages(self):
        pulse = {
            "self_audit": {
                "ui_drift": {
                    "code_paths_sample": ["app/frontend/src/pages/Login.jsx"],
                    "code_paths_count": 2,
                    "owned_pages": 0,
                },
            },
        }
        self.assertTrue(should_render(pulse))
        prompt = build_hub_pulse_prompt(pulse)
        self.assertIn("workhub_update_page", prompt)

    def test_self_audit_silent_when_no_drift(self):
        pulse = {"self_audit": {}}
        # No render trigger from self_audit, and the renderer skips it.
        self.assertFalse(should_render(pulse))


if __name__ == "__main__":
    unittest.main()
