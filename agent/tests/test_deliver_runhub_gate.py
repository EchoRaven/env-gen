"""DeliverProjectTool happy-path smoke (RunHub variant).

This file's original RunHub-since-session enforcement tests (refuses
without runhub run, refuses with run before session, force_deliver
bypasses) were deleted in commit 0a785334 because the in-tool RunHub
gate was removed in commit dbbd38ea — live owner is now
compute_deliverability at runtime/deliverability.py:107. The lone
remaining test was originally a "deliver succeeds when a passing run
exists" assertion, but with the gate gone, the run setup no longer
drives the assertion — deliver succeeds regardless. Per reviewer
follow-up #1 (Phase 0.1 sign-off, 2026-05-30), the test is rescoped
to a plain happy-path smoke so it doesn't masquerade as a gate test.

Filename retained for git history; consider consolidating with
test_deliver_retro_gate.py's rescoped sibling in a future cleanup.
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


def _agent(reg, gen_id=8000.0):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = "orchestrator"
    # GUARD 2c reads agent._visual_defer_check and calls it. On a MagicMock that
    # attribute is auto-created, callable, and returns a truthy Mock — so the
    # guard read "the final milestone's visual gate is still converging" and
    # deferred every delivery here. Production fails OPEN on a missing check;
    # a mock is not missing, so say so explicitly.
    a._visual_defer_check = None
    return a


class DeliverProjectRunhubHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        # In-tool happy path only; the live deliverability gate (DeliverProjectTool GUARD 2,
        # default-on since fix #20) is exercised in test_deliver_project_live_gate.py. The agent
        # is a MagicMock here, so disable the live gate to test this suite's narrow concern.
        os.environ["ENVGEN_DELIVER_GATE"] = "0"
        self.addCleanup(os.environ.pop, "ENVGEN_DELIVER_GATE", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="deliver_runhub_happy_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deliver_succeeds_on_valid_checklist(self) -> None:
        """A valid checklist + CONFIRMED returns success.

        RunHub-since-session enforcement now lives in
        compute_deliverability (runtime/deliverability.py:107), not in
        DeliverProjectTool itself; this test only exercises the
        in-tool happy path."""
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        result = tool.execute(
            confirmation="CONFIRMED",
            delivery_summary="d",
            checklist={"no_bugs": True, "requirements_met": True,
                       "fully_functional": True, "docker_ok": True},
        )
        self.assertTrue(result.success, f"failed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
