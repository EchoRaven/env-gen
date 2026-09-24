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

# Cutover 13: substantive approve requires inline_comments + considered_alternatives
_SUBST_INLINE = [{"file": "x.py", "line": 1, "body": "ok"}]
_SUBST_ALTS = ["considered alt approach; not needed here"]


class ForceMergeTests(unittest.TestCase):
    def _setup_failing_pr(self, td):
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.register_agent_repo("backend", str(Path(td) / "backend"))
        ch.ensure_branch("backend", "agent/backend")
        hubs.registryhub.register_endpoint("GET", "/api/feed", schema={},
                                       provider="backend", agent="backend")
        hubs.registryhub.record_api_test("GET /api/feed", {"passed": False},
                                     evidence={"trace": "fail"}, agent="verifier")
        task = hubs.workhub.create_task(title="x", assignee="backend",
                                        agent="orchestrator")
        hubs.workhub.claim_task(task["id"], "backend")
        hubs.workhub.complete_task(task["id"], "backend", result={"ok": True})
        pr = ch.open_pull_request(
            branch="agent/backend",
            reviewers=["frontend", "orchestrator"],
            linked_tasks=[task["id"]],
            linked_apis=["GET /api/feed"],
            title="x", author="backend",
        )
        ch.submit_review(pr["id"], "frontend", "approve",
                         inline_comments=_SUBST_INLINE,
                         considered_alternatives=_SUBST_ALTS)
        ch.submit_review(pr["id"], "orchestrator", "approve",
                         inline_comments=_SUBST_INLINE,
                         considered_alternatives=_SUBST_ALTS)
        return hubs, ch, pr

    def test_force_merge_rejected_for_non_orchestrator(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"], reason="long enough reason xxxxxxx", agent="backend")
            self.assertEqual(result.get("error"), "force_merge_orchestrator_only")

    def test_force_merge_rejected_for_short_reason(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"], reason="short", agent="orchestrator")
            self.assertEqual(result.get("error"), "force_merge_reason_too_short")

    def test_force_merge_orchestrator_with_valid_reason_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_failing_pr(td)
            result = ch.force_merge_pull_request(
                pr["id"],
                reason="Emergency hotfix: contract tests broken in CI, manually verified locally",
                agent="orchestrator",
            )
            self.assertNotIn("error", result)
            updated = ch.stores.pull_requests.get(pr["id"])
            self.assertTrue(updated.get("force_merged"))
            self.assertEqual(updated.get("force_by"), "orchestrator")

    def test_force_merge_emits_urgent_eventhub_event(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch, pr = self._setup_failing_pr(td)
            ch.force_merge_pull_request(
                pr["id"],
                reason="Emergency hotfix needed for production outage debugging",
                agent="orchestrator",
            )
            events = list(hubs.eventhub.snapshot()["events"].values())
            force_events = [e for e in events if e.get("event_type") == "pr_force_merged"]
            self.assertGreaterEqual(len(force_events), 1)
            self.assertEqual(force_events[-1]["priority"], "urgent")


if __name__ == "__main__":
    unittest.main()
