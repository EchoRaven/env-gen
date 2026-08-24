"""End-to-end retro flow (Cutover 16).

Exercises the full retro -> deliver_project gate flow without any LLM:
- SubmitRetroTool.execute is async (uses BaseTool async convention).
- DeliverProjectTool.execute is SYNCHRONOUS — call directly, no _run_async.
- DeliverProjectTool checklist keys are the canonical booleans:
  no_bugs / requirements_met / fully_functional / docker_ok.
"""

import asyncio
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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_PVR = [
    {"plan_item": "p1", "actual_outcome": "a1", "drift_reason": "d1"},
    {"plan_item": "p2", "actual_outcome": "a2", "drift_reason": "d2"},
]
_LESSONS = ["l1", "l2"]
_PROMPT_CHANGES = [{"agent_profile": "design", "change_description": "x"}]

_OK_CHECKLIST = {
    "no_bugs": True,
    "requirements_met": True,
    "fully_functional": True,
    "docker_ok": True,
}


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


class RetroE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        # This e2e exercises the retro submit→deliver flow with a MagicMock agent; the live
        # deliverability gate (DeliverProjectTool GUARD 2, default-on since fix #20) is covered
        # separately in test_deliver_project_live_gate.py — disable it here so the mock hub
        # doesn't false-block the deliver step.
        os.environ["ENVGEN_DELIVER_GATE"] = "0"
        self.addCleanup(os.environ.pop, "ENVGEN_DELIVER_GATE", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_e2e_"))
        self.reg = HubRegistry(self.tmp)
        # Cutover 24: satisfy RunHub-since-session gate for both gen_ids
        _insert_passing_run(self.reg, started_at=2001.0)
        _insert_passing_run(self.reg, started_at=3001.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _agent(self, gen_id=2000.0):
        a = MagicMock()
        a.hub_registry = self.reg
        a._session_start_ts = gen_id
        a.workspace_path = "/tmp/x"
        # Same class as the _project_delivered_event line above: GUARD 2c calls
        # agent._visual_defer_check, and an auto-created Mock returns truthy, so
        # every delivery here deferred on "the visual gate is still converging".
        a._visual_defer_check = None
        if hasattr(a, "_project_delivered_event"):
            del a._project_delivered_event
        return a

    def test_full_flow_submit_then_deliver(self) -> None:
        from tools.retro_tools import SubmitRetroTool
        from tools.agent_interaction_tools import DeliverProjectTool

        # Step 1: agent submits retro for gen 2000.0 (async tool)
        rt = SubmitRetroTool(hub_registry=self.reg, generation_id=2000.0)
        r1 = _run_async(rt.execute(
            title="retro-gen-2000",
            plan_vs_reality=_PVR, systematic_failures=[],
            lessons=_LESSONS, proposed_prompt_changes=_PROMPT_CHANGES))
        self.assertTrue(r1.success, f"retro submit failed: {r1.error_message}")

        # Step 2: deliver_project succeeds (sync tool)
        dt = DeliverProjectTool(agent=self._agent(2000.0))
        r2 = dt.execute(
            confirmation="CONFIRMED",
            delivery_summary="done",
            checklist=dict(_OK_CHECKLIST),
        )
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

if __name__ == "__main__":
    unittest.main()
