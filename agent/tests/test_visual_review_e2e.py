"""E2E: critical route blocks deliver; substantive review unblocks; force-deliver audits."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEV = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8", "actual": "#2563eb", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px", "actual": "8px", "severity": "medium"},
    {"aspect": "card border radius",
     "expected": "12px", "actual": "4px", "severity": "low"},
]


def _agent(reg, gen_id=4000.0, agent_type="orchestrator"):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


def _insert_passing_run(reg, started_at):
    """Satisfy the Cutover 24 RunHub-since-session gate."""
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class VisualReviewE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_e2e_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 4000.0)
        # Cutover 24: satisfy RunHub-since-session gate (gen_id=4000.0)
        _insert_passing_run(self.reg, started_at=4001.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_full_flow_register_review_approve_transitions_status(self) -> None:
        """Full register → review → approve cycle, asserted via the
        page status. The original test asserted the same flow via
        ``DeliverProjectTool.execute`` refusing then succeeding, but
        that gate was dead-on-production (the 2026-05-30 review-
        cleanup commit deleted it). The page state machine itself
        IS live — pin it directly."""
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        # Pre-approval: page is pending and the visual gate
        # aggregator surfaces it as unapproved.
        from multi_agent.runtime.visual_review_gate import list_unapproved_critical
        self.assertEqual(self.reg.gate_registry.get_visual_review(page["id"])["status"], "pending")
        self.assertEqual(
            [p["id"] for p in list_unapproved_critical(self.reg.gate_registry)],
            [page["id"]],
        )
        # Visual reviewer approves with substantive deviations.
        self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches reference; minor color drift on accents")
        # Post-approval: page status flips and the aggregator drops it.
        self.assertEqual(self.reg.gate_registry.get_visual_review(page["id"])["status"], "approved")
        self.assertEqual(list_unapproved_critical(self.reg.gate_registry), [])

    def test_rubber_stamp_approve_blocked_at_submit(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        result = self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV[:2],  # only 2 deviations
            summary="..............................")
        self.assertIn("error", result)
        # Status stays pending
        latest = self.reg.gate_registry.get_visual_review(page["id"])
        self.assertEqual(latest["status"], "pending")

    def test_low_similarity_on_critical_forces_needs_revision(self) -> None:
        page = self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        # Try to approve with similarity=0.5
        r = self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="approve", similarity_score=0.50,
            deviations=_GOOD_DEV,
            summary="Layout off; should not approve")
        self.assertIn("error", r)
        # needs_revision with same low score is accepted
        r2 = self.reg.gate_registry.submit_visual_review(
            page["id"], reviewer="verifier",
            state="needs_revision", similarity_score=0.50,
            deviations=[_GOOD_DEV[0]],
            summary="Layout off")
        self.assertNotIn("error", r2)


if __name__ == "__main__":
    unittest.main()
