"""Tests for visual_review_gate after PR 3 (rank 3).

The single-page ``assert_visual_approved`` and the multi-page
``assert_critical_visuals_approved`` exception wrappers were
removed in PR 3 (re-audit §7.3 confirmed dead). The production
gate is ``list_unapproved_critical`` — which the
``DeliverProjectTool`` consumes directly. These tests pin the
behaviour through that one live aggregator.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.visual_review_gate import (  # noqa: E402
    VisualReviewNotApprovedError, list_unapproved_critical,
)


_GOOD_DEV = [
    {"aspect": "a", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "b", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "c", "expected": "e", "actual": "a2", "severity": "low"},
]


class VisualReviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_gate_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_when_no_visual_reviews(self) -> None:
        self.assertEqual(list_unapproved_critical(self.reg.gate_registry), [])

    def test_empty_when_only_non_critical_unapproved(self) -> None:
        self.reg.gate_registry.register_visual_review_task(
            route="/admin", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        self.assertEqual(list_unapproved_critical(self.reg.gate_registry), [])

    def test_lists_pending_critical_routes(self) -> None:
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        unapproved = list_unapproved_critical(self.reg.gate_registry)
        self.assertEqual(len(unapproved), 1)
        self.assertEqual(unapproved[0]["metadata"]["route"], "/feed")

    def test_empty_when_critical_approved(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches; minor color drift on accents")
        self.assertEqual(list_unapproved_critical(self.reg.gate_registry), [])

    def test_critical_needs_revision_still_unapproved(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="needs_revision", similarity_score=0.30,
            deviations=[_GOOD_DEV[0]], summary="Layout off")
        unapproved = list_unapproved_critical(self.reg.gate_registry)
        self.assertEqual(len(unapproved), 1)

    def test_lists_multiple_unapproved_critical_routes(self) -> None:
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.gate_registry.register_visual_review_task(
            route="/profile", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        unapproved = list_unapproved_critical(self.reg.gate_registry)
        routes = {p["metadata"]["route"] for p in unapproved}
        self.assertEqual(routes, {"/feed", "/profile"})


class ErrorClassRemains(unittest.TestCase):
    """``DeliverProjectTool`` still raises ``VisualReviewNotApprovedError``
    when delivery is refused due to unapproved critical routes. Pin
    that the export survives the PR 3 cleanup."""

    def test_error_class_is_runtime_error_subclass(self):
        self.assertTrue(issubclass(VisualReviewNotApprovedError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
