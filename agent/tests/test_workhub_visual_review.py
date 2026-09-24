"""Tests for WorkHub visual_review helpers (Cutover 20)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEVIATIONS = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8 (indigo-700)",
     "actual": "#2563eb (blue-600)", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px gap between logo and nav",
     "actual": "8px gap", "severity": "medium"},
    {"aspect": "feed card border radius",
     "expected": "12px rounded corners",
     "actual": "4px rounded corners", "severity": "low"},
]


class WorkHubVisualReviewLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_vis_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_creates_pending_task(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed",
            screenshot_path="/tmp/feed.png",
            reference_path="/tmp/ref-feed.png",
            critical=True, agent="frontend")
        self.assertEqual(page["kind"], "visual_review")
        self.assertEqual(page["status"], "pending")
        self.assertEqual(page["metadata"]["route"], "/feed")
        self.assertTrue(page["metadata"]["critical"])

    def test_list_pending_returns_only_pending(self) -> None:
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.gate_registry.register_visual_review_task(
            route="/about", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        pending = self.reg.gate_registry.list_pending_visual_reviews()
        self.assertEqual(len(pending), 2)

    def test_list_critical_returns_only_critical(self) -> None:
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.gate_registry.register_visual_review_task(
            route="/about", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        critical = self.reg.gate_registry.list_critical_visual_reviews()
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0]["metadata"]["route"], "/feed")

    def test_get_visual_review_returns_match(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        got = self.reg.gate_registry.get_visual_review(page["id"])
        self.assertEqual(got["id"], page["id"])

    def test_get_visual_review_returns_none_for_non_visual_kind(self) -> None:
        other = self.reg.workhub.create_document(title="x", agent="o", kind="design")
        self.assertIsNone(self.reg.gate_registry.get_visual_review(other["id"]))


class WorkHubVisualReviewSubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_vis_submit_"))
        self.reg = HubRegistry(self.tmp)
        self.page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_approve_with_3_deviations_and_high_similarity_succeeds(self) -> None:
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS,
            summary="Layout matches; minor color drift on accents")
        self.assertEqual(result["status"], "approved")
        # PR 3 removed the WorkHub.is_visual_approved predicate
        # (re-audit §7.3 dead). Production code reads page status
        # directly via ``GateRegistry.get_visual_review``.
        page = self.reg.gate_registry.get_visual_review(self.page["id"])
        self.assertEqual(page["status"], "approved")

    def test_approve_with_2_deviations_rejected(self) -> None:
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS[:2],
            summary="...........................")
        self.assertIn("error", result)
        self.assertIn("deviations", result["error"].lower())

    def test_approve_with_low_similarity_on_critical_rejected(self) -> None:
        # Critical task with similarity 0.5 -> rejected
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=0.50,
            deviations=_GOOD_DEVIATIONS,
            summary="Many large deviations; should not approve")
        self.assertIn("error", result)
        self.assertIn("similarity", result["error"].lower())

    def test_approve_short_summary_rejected(self) -> None:
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=0.80,
            deviations=_GOOD_DEVIATIONS, summary="LGTM")
        self.assertIn("error", result)
        self.assertIn("summary", result["error"].lower())

    def test_approve_similarity_out_of_range_rejected(self) -> None:
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=1.5,
            deviations=_GOOD_DEVIATIONS, summary="................")
        self.assertIn("error", result)

    def test_needs_revision_with_1_deviation_accepted(self) -> None:
        result = self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="needs_revision", similarity_score=0.30,
            deviations=[_GOOD_DEVIATIONS[0]],
            summary="Layout completely off")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "needs_revision")

    def test_non_critical_low_similarity_approve_allowed(self) -> None:
        # Non-critical task with similarity 0.4 -> allowed (no critical floor)
        non_critical = self.reg.gate_registry.register_visual_review_task(
            route="/admin", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        result = self.reg.gate_registry.submit_visual_review(
            non_critical["id"], reviewer="verifier",
            state="approve", similarity_score=0.40,
            deviations=_GOOD_DEVIATIONS,
            summary="Admin page is internal; not held to brand standards")
        self.assertNotIn("error", result)

    def test_review_history_appended(self) -> None:
        self.reg.gate_registry.submit_visual_review(
            self.page["id"], reviewer="verifier",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS,
            summary="Layout matches; minor drift on accents")
        page = self.reg.gate_registry.get_visual_review(self.page["id"])
        hist = (page.get("metadata") or {}).get("review_history") or []
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["state"], "approve")
        self.assertEqual(hist[0]["similarity_score"], 0.82)
        self.assertEqual(len(hist[0]["deviations"]), 3)


if __name__ == "__main__":
    unittest.main()
