"""DeliverProjectTool happy-path smoke.

This file's original retro-gate enforcement tests (refuses_without_retro
and refuses_with_retro_for_different_generation) were deleted in
commit 0a785334 because the in-tool retro gate was removed in commit
dbbd38ea — live owner is now RetroBeforeDeliverPolicy at
workflow_policies.py:1309. The lone remaining test was originally a
"deliver succeeds when retro exists" assertion, but with the gate
gone, the retro/run setup no longer drives the assertion — deliver
succeeds regardless. Per reviewer follow-up #1 (Phase 0.1 sign-off,
2026-05-30), the test is rescoped to a plain happy-path smoke so it
doesn't masquerade as a gate test.

Filename retained for git history; consider consolidating with
test_deliver_runhub_gate.py's rescoped sibling in a future cleanup.
"""

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


_OK_CHECKLIST = {
    "no_bugs": True,
    "requirements_met": True,
    "fully_functional": True,
    "docker_ok": True,
}


def _make_agent(reg, gen_id=1000.0):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.workspace_path = "/tmp/fake"
    if hasattr(a, "_project_delivered_event"):
        del a._project_delivered_event
    return a


class DeliverProjectHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliver_happy_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deliver_succeeds_on_valid_checklist(self) -> None:
        """A valid checklist + CONFIRMED returns success.

        Retro/run-since-session enforcement lives in
        RetroBeforeDeliverPolicy + compute_deliverability, not in
        DeliverProjectTool itself; this test only exercises the
        in-tool happy path. Tests for the live retro/run gates
        belong in their respective policy/aggregator suites."""
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_make_agent(self.reg))
        result = tool.execute(
            confirmation="CONFIRMED",
            delivery_summary="all done",
            checklist=dict(_OK_CHECKLIST),
        )
        self.assertTrue(result.success, f"failed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
